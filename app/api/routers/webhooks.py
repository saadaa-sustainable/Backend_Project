"""Inbound webhooks: EasyEcom delivery events and Meta ad-object events.

A webhook receiver has one job at the moment of the call: take custody
of the payload and say 200. Everything else -- parsing, mapping to an
order, deriving delivery state -- happens later, off the request, and
must not be able to lose the event if it goes wrong.

So the body is written verbatim to `webhook_events` as JSONB before
anything looks at it. If a field is renamed upstream, or a payload
shape turns out to differ from the docs, the rows are still there to
re-read. EasyEcom shows delivery attempts in its own Webhook Trigger
History, so a 500 from us is visible to whoever set it up -- but a
silently dropped event is not.

Auth is the shared secret EasyEcom echoes back as `Access-Token`. That
is all the authentication this endpoint has: the URL is public by
necessity, so without the secret anyone who learned the path could post
fabricated delivery events straight into the warehouse. Compared with
`secrets.compare_digest`, not `==`, so the check cannot be probed a
character at a time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.api.deps import SessionDep
from app.config import get_settings
from app.logging.setup import get_logger
from app.services.meta.webhook_processor import process_meta_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = get_logger(__name__)

#: The 12 events EasyEcom can send, as named in its Webhook Settings
#: screen, normalised to slugs. Accepting only these means a typo in the
#: configured URL fails loudly at setup rather than silently collecting
#: rows nobody reads.
#:
#: `tracking`, `mark_return`, `manifested` and `rtd` are the ones that
#: carry delivery state -- i.e. whether revenue actually landed. The
#: rest describe order and inventory movements we already receive from
#: Shopify and GoKwik.
EasyEcomEvent = Literal[
    "create_order", "confirm_order", "update_inventory", "manifested",
    "mark_return", "grn_details", "complete_grn", "rtd", "tracking",
    "confirm_order_start", "fetch_order", "cancel_order",
]

_INSERT = text("""
    INSERT INTO public.webhook_events (source, event, payload, headers)
    VALUES (:source, :event, CAST(:payload AS jsonb), CAST(:headers AS jsonb))
    RETURNING id
""")

#: Headers worth keeping on a stored event. Neither EasyEcom's
#: ``Access-Token`` nor Meta's ``X-Hub-Signature-256`` is among them --
#: storing the credential next to the data it protects would undo the
#: point of having one.
_KEEP_HEADERS = {"content-type", "user-agent", "x-forwarded-for"}


def _authorise(supplied: str | None) -> None:
    expected = get_settings().easyecom_webhook_token
    if not expected:
        # Refusing is the safe default. A public URL with the check
        # disabled is an open write path into the warehouse.
        logger.error("easyecom webhook received but EASYECOM_WEBHOOK_TOKEN is unset")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook receiver is not configured.",
        )
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bad or missing Access-Token.",
        )


@router.post("/easyecom/{event}", status_code=status.HTTP_200_OK)
async def easyecom_webhook(
    event: EasyEcomEvent,
    request: Request,
    session: SessionDep,
    access_token: Annotated[str | None, Header(alias="Access-Token")] = None,
) -> dict[str, Any]:
    """Receive one EasyEcom webhook and store it verbatim.

    Configure one URL per event in EasyEcom:
        https://<host>/webhooks/easyecom/tracking
        https://<host>/webhooks/easyecom/mark_return
        ...

    Returns 200 with the stored row id. Anything else tells EasyEcom to
    consider the delivery failed, which is what we want for a genuine
    auth or storage failure and never for a payload we simply do not
    understand yet.
    """
    _authorise(access_token)

    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty body.")
    try:
        payload = json.loads(raw)
    except ValueError:
        # Keep it anyway, as a string. A body we cannot parse is still
        # evidence, and throwing it away makes the bug unfindable.
        payload = {"_unparsed": raw.decode("utf-8", "replace")}
        logger.warning("easyecom webhook %s: body was not JSON", event)

    headers = {
        k: v for k, v in request.headers.items() if k.lower() in _KEEP_HEADERS
    }

    row = await session.execute(_INSERT, {
        "source": "easyecom",
        "event": event,
        "payload": json.dumps(payload),
        "headers": json.dumps(headers),
    })
    event_id = row.scalar_one()
    await session.commit()

    logger.info("easyecom webhook stored", extra={"event": event, "id": event_id})
    return {"received": True, "event": event, "id": event_id}


# ----------------------------------------------------------------------
# Meta
# ----------------------------------------------------------------------

#: The six fields the `ad_account` webhook topic can carry, per
#: https://developers.facebook.com/docs/graph-api/webhooks/reference/ad-account.
#:
#: Worth being blunt about what is NOT here, because it is the whole shape
#: of this feature: there is no `effective_status` field and no `ad` field.
#: Meta does not send a webhook when an ad is paused, resumed, renamed,
#: re-budgeted or re-creatived. The two status-ish fields below are narrow:
#: `in_process_ad_objects` fires when an object leaves review, and
#: `with_issues_ad_objects` when one is flagged WITH_ISSUES. Ordinary edits
#: and ACTIVE/PAUSED flips reach the dashboard through the delta poll
#: instead (`run_meta_delta_sync`), which asks Meta what changed.
META_FIELDS = frozenset({
    "ads_async_creation_request",
    "creative_fatigue",
    "ad_recommendations",
    "in_process_ad_objects",
    "product_set_issue",
    "with_issues_ad_objects",
})

#: Fields whose `value` names an ad object we hold in Silver, and the keys
#: that carry its id. Everything else is stored and not acted on.
_META_OBJECT_KEYS = {
    "in_process_ad_objects": ("id",),
    "with_issues_ad_objects": ("id",),
    "ad_recommendations": ("ad_object_ids",),
    "creative_fatigue": ("adgroup_id",),
}


def _verify_meta_signature(raw: bytes, supplied: str | None) -> None:
    """Check Meta's `X-Hub-Signature-256` over the exact bytes received.

    Over `raw`, never over a re-serialised parse of it: `json.dumps` of a
    parsed body differs from Meta's bytes in key order and whitespace, and
    every event would be rejected for no visible reason.
    """
    secret = get_settings().meta.app_secret
    if not secret:
        logger.error("meta webhook received but META_APP_SECRET is unset")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook receiver is not configured.",
        )
    if not supplied or not supplied.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed X-Hub-Signature-256.",
        )
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied[len("sha256="):], expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bad X-Hub-Signature-256.",
        )


@router.get("/meta", response_class=PlainTextResponse)
async def meta_webhook_verify(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> str:
    """Meta's one-time verification handshake, run when the callback URL is
    registered on the app.

    Meta requires the body to be `hub.challenge` and nothing else -- not
    JSON, not a wrapper object -- or it refuses to register the URL, which
    is why this returns a bare `PlainTextResponse`.
    """
    expected = get_settings().meta_webhook_verify_token
    if not expected:
        logger.error("meta webhook verify attempted but META_WEBHOOK_VERIFY_TOKEN is unset")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook receiver is not configured.",
        )
    if hub_mode != "subscribe" or not hub_verify_token or not hub_challenge:
        raise HTTPException(status_code=400, detail="Not a subscribe handshake.")
    if not secrets.compare_digest(hub_verify_token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bad verify token.")

    logger.info("meta webhook verified")
    return hub_challenge


@router.post("/meta", status_code=status.HTTP_200_OK)
async def meta_webhook(
    request: Request,
    session: SessionDep,
    background: BackgroundTasks,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, Any]:
    """Receive one Meta `ad_account` notification, store it verbatim, and
    queue the affected objects for a Bronze re-read.

    Same custody rule as EasyEcom: the body is in `webhook_events` before
    anything interprets it. Meta retries a non-200 for a while and then
    disables the subscription outright, so interpretation happens after the
    response, never in front of it -- a payload shape we do not recognise
    must not be able to cost us the subscription.
    """
    raw = await request.body()
    _verify_meta_signature(raw, signature)
    if not raw:
        raise HTTPException(status_code=400, detail="Empty body.")
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {"_unparsed": raw.decode("utf-8", "replace")}
        logger.warning("meta webhook: body was not JSON")

    headers = {
        k: v for k, v in request.headers.items() if k.lower() in _KEEP_HEADERS
    }
    row = await session.execute(_INSERT, {
        "source": "meta",
        "event": str(payload.get("object") or "unknown")[:64],
        "payload": json.dumps(payload),
        "headers": json.dumps(headers),
    })
    event_id = row.scalar_one()
    await session.commit()

    background.add_task(process_meta_event, event_id)
    logger.info("meta webhook stored", extra={"id": event_id})
    return {"received": True, "id": event_id}
