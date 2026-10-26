"""Turn a stored Meta webhook event into a Silver-table update.

Runs after the response, off the request, reading the row the receiver
already committed to ``webhook_events``. That ordering is the point: if
anything here is wrong -- a payload shape that differs from the docs, an
id we cannot resolve, a Graph call that fails -- the event is still on
disk to re-read, and Meta has already had its 200 and will not disable
the subscription.

What this can actually act on is narrow, and worth stating plainly rather
than discovering later. Meta's ``ad_account`` topic carries six fields;
only ``in_process_ad_objects``, ``with_issues_ad_objects``,
``ad_recommendations`` and ``creative_fatigue`` name an object we hold,
and none of the six fires on an ordinary status flip or edit. Those reach
the dashboard through the delta poll instead. See
``docs/meta-webhooks.md``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.config import get_settings
from app.database.session import session_scope
from app.logging.setup import get_logger
from app.services.meta.live_refresh import WEBHOOK_LEVELS, refresh_objects

logger = get_logger(__name__)

_SELECT_EVENT = text(
    "SELECT payload FROM public.webhook_events WHERE id = :id AND source = 'meta'"
)
_MARK_DONE = text("""
    UPDATE public.webhook_events
    SET processed_at = now(), process_error = :error
    WHERE id = :id
""")

#: Events stored but never processed. A FastAPI background task lives in
#: the serving process, so a restart or a crash between the 200 and the
#: refresh loses the task -- but not the row, which is the reason custody
#: comes first. The delta job sweeps these up.
#:
#: The age floor keeps the sweep off events whose background task is still
#: in flight, so the same event is not refreshed twice concurrently.
_UNPROCESSED = text("""
    SELECT id
    FROM public.webhook_events
    WHERE source = 'meta'
      AND processed_at IS NULL
      AND received_at < now() - make_interval(secs => :min_age_seconds)
    ORDER BY received_at
    LIMIT :limit
""")


def extract_targets(payload: dict) -> tuple[dict[str, list[str]], set[str]]:
    """Pull the changed object ids, by level, out of one notification.

    Returns the ids keyed by our level names, plus the ad account ids the
    notification was about. Tolerant on purpose -- ``changes`` vs
    ``changed_fields``, ``act_`` prefixed or not, a ``level`` Meta spells
    ``AD_SET`` -- because a payload that drifts from the docs should cost
    us one unrecognised event, not an exception in a background task.
    """
    ids_by_level: dict[str, list[str]] = {}
    accounts: set[str] = set()

    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        account_id = str(entry.get("id") or "").removeprefix("act_")
        if account_id:
            accounts.add(account_id)

        for change in entry.get("changes") or entry.get("changed_fields") or []:
            if not isinstance(change, dict):
                continue
            field = change.get("field")
            value = change.get("value")
            if not isinstance(value, dict):
                continue

            # Four of the six fields name the account in the value too.
            if value.get("ad_account_id"):
                accounts.add(str(value["ad_account_id"]).removeprefix("act_"))

            # Only two fields say which level their id is at; the other two
            # are defined at a fixed level, so they do not need to.
            if field in ("in_process_ad_objects", "with_issues_ad_objects"):
                level = WEBHOOK_LEVELS.get(str(value.get("level") or "").upper())
                raw_ids = [value.get("id")]
            elif field == "ad_recommendations":
                # `ad_object_ids` is a list and carries no level. Meta names
                # these recommendations at ad level.
                level = "ad"
                raw_ids = value.get("ad_object_ids") or []
            elif field == "creative_fatigue":
                # `adgroup_id` is Meta's older name for an ad set id.
                level = "adset"
                raw_ids = [value.get("adgroup_id")]
            else:
                continue

            if not level:
                continue
            for object_id in raw_ids if isinstance(raw_ids, list) else [raw_ids]:
                if object_id:
                    ids_by_level.setdefault(level, []).append(str(object_id))

    return ids_by_level, accounts


def _account_keys_for(account_ids: set[str]) -> list[str]:
    """Map the ad account ids in a notification to our configured account
    keys. An id we are not configured for is skipped, not guessed at --
    Meta can deliver for any account the app is subscribed to, including
    one nobody here has credentials or a name for."""
    configured = {a.account_id: a.key for a in get_settings().meta.accounts}
    keys = [configured[a] for a in sorted(account_ids) if a in configured]
    unknown = sorted(account_ids - set(configured))
    if unknown:
        logger.warning("meta webhook for unconfigured accounts", account_ids=unknown)
    return keys


async def process_meta_event(event_id: int | uuid.UUID) -> None:
    """Re-read whatever the stored event says changed, and re-flatten it.

    Never raises: this runs as a FastAPI background task, where an
    exception would be logged somewhere nobody looks. The failure is
    written onto the event row's ``process_error`` instead, where the
    unprocessed events are already visible.
    """
    error: str | None = None
    try:
        async with session_scope() as session:
            payload = (
                await session.execute(_SELECT_EVENT, {"id": event_id})
            ).scalar_one_or_none()
            if payload is None:
                logger.warning("meta webhook event vanished", event_id=str(event_id))
                return

            ids_by_level, account_ids = extract_targets(payload)
            if not ids_by_level:
                # Expected for four of the six fields, and for any field
                # Meta adds later. Marked processed so it does not sit in
                # the backlog looking like a failure.
                logger.info("meta webhook had nothing to refresh", event_id=str(event_id))
            else:
                keys = _account_keys_for(account_ids)
                if not keys:
                    # Deliberately not defaulting to the first configured
                    # account. Every Bronze row this writes is stamped with
                    # the account it came from; guessing that stamp would
                    # put one account's ads under another account's name in
                    # Silver, which is harder to notice and harder to undo
                    # than an event left unprocessed.
                    raise ValueError(
                        f"no configured Meta account for {sorted(account_ids) or 'unknown'}"
                    )
                for account_key in keys:
                    written = await refresh_objects(
                        session,
                        ids_by_level,
                        account_key=account_key,
                        triggered_by="webhook",
                    )
                    logger.info(
                        "meta webhook processed",
                        event_id=str(event_id),
                        account_key=account_key,
                        **written,
                    )
    except Exception as exc:  # noqa: BLE001 - a background task must not die silently
        error = f"{type(exc).__name__}: {exc}"[:2000]
        logger.error("meta webhook processing failed", event_id=str(event_id), error=error)

    try:
        async with session_scope() as session:
            await session.execute(_MARK_DONE, {"id": event_id, "error": error})
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("meta webhook stamp failed", event_id=str(event_id), error=str(exc))


async def process_pending_meta_events(*, min_age_seconds: int = 120, limit: int = 200) -> int:
    """Process Meta events that were stored but never refreshed, and
    return how many were attempted.

    Called by the delta job rather than on a timer of its own: the two do
    the same work, and a pending event that the delta poll would have
    picked up anyway costs nothing extra to retry here.
    """
    async with session_scope() as session:
        rows = await session.execute(
            _UNPROCESSED, {"min_age_seconds": min_age_seconds, "limit": limit}
        )
        pending = [r[0] for r in rows]

    if pending:
        logger.info("meta webhook backlog found", count=len(pending))
    for event_id in pending:
        await process_meta_event(event_id)
    return len(pending)
