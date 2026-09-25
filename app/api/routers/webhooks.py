"""Inbound webhooks. Currently EasyEcom.

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

import json
import secrets
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import text

from app.api.deps import SessionDep
from app.config import get_settings
from app.logging.setup import get_logger

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
    VALUES ('easyecom', :event, CAST(:payload AS jsonb), CAST(:headers AS jsonb))
    RETURNING id
""")


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

    # Only the headers worth keeping. Access-Token is deliberately NOT
    # among them -- storing the shared secret next to the data it
    # protects would undo the point of having one.
    keep = {"content-type", "user-agent", "x-forwarded-for"}
    headers = {k: v for k, v in request.headers.items() if k.lower() in keep}

    row = await session.execute(_INSERT, {
        "event": event,
        "payload": json.dumps(payload),
        "headers": json.dumps(headers),
    })
    event_id = row.scalar_one()
    await session.commit()

    logger.info("easyecom webhook stored", extra={"event": event, "id": event_id})
    return {"received": True, "event": event, "id": event_id}
