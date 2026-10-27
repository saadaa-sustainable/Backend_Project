"""Bring a named handful of Meta entities current, Bronze first.

Two callers need the same thing and must not grow two copies of it:

* the Meta webhook processor (``app/api/routers/webhooks.py``), which is
  handed the ids of objects Meta says just changed, and
* the delta poll (``app/scheduler/jobs.py``), which asks Meta which
  objects changed since we last looked.

Both end in the same place: fetch those objects from the Graph API, write
them to Bronze, re-flatten them into ``meta_campaigns`` / ``meta_adsets``
/ ``meta_ads``.

Bronze first is not optional. ``meta_ads`` is not a table anyone writes
to -- it is rebuilt by ``DISTINCT ON (meta_id) ORDER BY extracted_at
DESC`` over ``raw_dump_meta``. An UPDATE straight into ``meta_ads`` would
show up on the dashboard and then be silently reverted by the next full
rebuild, which is a far worse failure than being an hour stale: the
dashboard would be right, then wrong, with nothing in between to explain
it. Appending a Bronze row with a fresh ``extracted_at`` instead makes
the change the newest snapshot, so every later rebuild agrees with what
we just showed.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_meta_credentials
from app.logging.setup import get_logger
from app.services.meta.ads import AdSyncService
from app.services.meta.adsets import AdSetSyncService
from app.services.meta.campaigns import CampaignSyncService
from app.services.meta.client import MetaAPIClient
from app.services.meta.entity_flatten import refresh_entities_for_ids

logger = get_logger(__name__)

#: Meta's own names for the levels, as they arrive in webhook payloads
#: (``value.level``), mapped to ours. ``CREATIVE`` also appears there; we
#: have no Silver creative table, so it is deliberately absent and such
#: events are stored and skipped rather than guessed at.
WEBHOOK_LEVELS = {
    "CAMPAIGN": "campaign",
    "AD_SET": "adset",
    "ADSET": "adset",
    "AD": "ad",
}

_SERVICES = {
    "campaign": CampaignSyncService,
    "adset": AdSetSyncService,
    "ad": AdSyncService,
}

#: Graph's filter field for each level's last-modified timestamp.
_UPDATED_TIME_FIELD = {
    "campaign": "campaign.updated_time",
    "adset": "adset.updated_time",
    "ad": "ad.updated_time",
}

_IDS_IN_BATCH = text("""
    SELECT DISTINCT meta_id
    FROM raw_dump_meta
    WHERE batch_id = :batch_id AND meta_id IS NOT NULL
""")

#: Parent ids of the Bronze rows a batch just wrote, so an ad whose ad set
#: we have never seen can pull that ad set (and its campaign) in too --
#: otherwise the ad lands in ``meta_ads`` with a null ``adset_name``.
_PARENTS_IN_BATCH = text("""
    SELECT DISTINCT
        parent_ids ->> 'campaign_id' AS campaign_id,
        parent_ids ->> 'adset_id'    AS adset_id
    FROM raw_dump_meta
    WHERE batch_id = :batch_id
""")

_MISSING_CAMPAIGNS = text(
    "SELECT u.id FROM unnest(CAST(:ids AS text[])) AS u(id)"
    " LEFT JOIN meta_campaigns c ON c.campaign_id = u.id WHERE c.campaign_id IS NULL"
)
_MISSING_ADSETS = text(
    "SELECT u.id FROM unnest(CAST(:ids AS text[])) AS u(id)"
    " LEFT JOIN meta_adsets a ON a.adset_id = u.id WHERE a.adset_id IS NULL"
)


async def _sync(
    session: AsyncSession,
    level: str,
    account_key: str,
    request_params: dict[str, Any],
    triggered_by: str,
) -> tuple[uuid.UUID, list[str]]:
    """Run one level's Bronze sync and return its batch id and the
    meta_ids it wrote."""
    credentials = get_meta_credentials(account_key)
    async with MetaAPIClient(credentials=credentials) as client:
        service = _SERVICES[level](session, client)
        batch = await service.sync(
            request_params=request_params,
            sync_type="incremental",
            triggered_by=triggered_by,
        )
    rows = await session.execute(_IDS_IN_BATCH, {"batch_id": batch.id})
    return batch.id, [r[0] for r in rows]


async def _pull_missing_parents(
    session: AsyncSession,
    batch_ids: list[uuid.UUID],
    fetched: dict[str, list[str]],
    *,
    account_key: str,
    triggered_by: str,
) -> None:
    """Fetch any campaign or ad set a just-fetched child refers to but
    Silver has never seen, so the child does not land with a null parent
    name.

    The ad INSERT joins ``adset_name`` and ``campaign_name`` out of
    ``meta_adsets``/``meta_campaigns``. A webhook about a brand-new ad
    arrives before any sync has seen its ad set, so without this the ad
    shows up on the dashboard with blank parent names.

    Ad sets before campaigns, and the parent ids are re-read from Bronze
    each pass: pulling an ad set reveals the campaign id it belongs to,
    which the campaign pass then picks up. Only ever one extra level per
    pass, so this cannot walk away from us.
    """
    for level, statement, column in (
        ("adset", _MISSING_ADSETS, "adset_id"),
        ("campaign", _MISSING_CAMPAIGNS, "campaign_id"),
    ):
        candidates: set[str] = set()
        for batch_id in batch_ids:
            for row in await session.execute(_PARENTS_IN_BATCH, {"batch_id": batch_id}):
                if row._mapping[column]:
                    candidates.add(str(row._mapping[column]))
        candidates -= set(fetched.get(level) or [])
        if not candidates:
            continue

        rows = await session.execute(statement, {"ids": sorted(candidates)})
        missing = [r[0] for r in rows]
        if not missing:
            continue

        logger.info("meta_live_refresh_pulling_parents", level=level, count=len(missing))
        batch_id, got = await _sync(
            session, level, account_key, {"object_ids": missing}, triggered_by
        )
        batch_ids.append(batch_id)
        if got:
            fetched.setdefault(level, []).extend(got)


async def refresh_objects(
    session: AsyncSession,
    ids_by_level: dict[str, list[str]],
    *,
    account_key: str,
    triggered_by: str = "webhook",
) -> dict[str, int]:
    """Re-read the named objects from Meta and re-flatten just those rows.

    ``ids_by_level`` maps ``"campaign"`` / ``"adset"`` / ``"ad"`` to the
    ids that changed. Unknown levels are ignored. Returns the rows written
    per Silver table.
    """
    wanted = {
        level: sorted({str(i) for i in (ids_by_level.get(level) or []) if i})
        for level in ("campaign", "adset", "ad")
    }
    if not any(wanted.values()):
        return {}

    fetched: dict[str, list[str]] = {}
    batch_ids: list[uuid.UUID] = []
    for level, ids in wanted.items():
        if not ids:
            continue
        batch_id, got = await _sync(
            session, level, account_key, {"object_ids": ids}, triggered_by
        )
        batch_ids.append(batch_id)
        if got:
            fetched[level] = got
        logger.info(
            "meta_live_refresh_fetched",
            level=level,
            requested=len(ids),
            fetched=len(got),
        )

    # A requested id that came back with nothing is an object we can no
    # longer read -- deleted, or moved out of this account. Its Silver row
    # is now wrong either way, but we have no replacement snapshot, so the
    # scoped re-flatten below would delete the row and re-insert the same
    # stale Bronze. Leaving it alone and saying so is the honest option;
    # the nightly full sync is what reconciles deletions.
    for level, ids in wanted.items():
        unreadable = sorted(set(ids) - set(fetched.get(level) or []))
        if unreadable:
            logger.warning(
                "meta_live_refresh_unreadable_objects",
                level=level,
                object_ids=unreadable[:20],
                count=len(unreadable),
            )

    if not fetched:
        return {}

    await _pull_missing_parents(
        session, batch_ids, fetched, account_key=account_key, triggered_by=triggered_by
    )
    return await refresh_entities_for_ids(session, fetched)


async def refresh_changed_since(
    session: AsyncSession,
    *,
    account_key: str,
    since_epoch: int,
    triggered_by: str = "scheduler_delta",
) -> dict[str, int]:
    """Ask Meta which campaigns/ad sets/ads changed since ``since_epoch``
    and re-flatten exactly those.

    This, not the webhook, is what carries an ordinary status flip or edit:
    Meta's ``ad_account`` webhook topic has six fields and none of them
    fires on ACTIVE/PAUSED or on an edit (see ``docs/meta-webhooks.md``).
    Filtering the account edge on ``updated_time`` is the only way to learn
    about those. It is cheap in *requests* -- three pages per account, and
    a quiet interval returns three empty ones -- but not in Meta's CPU
    budget: Meta still scans every ad in the account to apply the filter,
    and these accounts are on ``development_access``, where that budget is
    small and is the binding limit (measured live: ``call=1%`` while
    ``total_cputime=108%``). Hence a 15-minute default interval rather
    than a 1-minute one, and hence the client's own proactive wait at 90%
    usage, which turns an over-eager interval into a skipped run instead
    of a throttled account.
    """
    fetched: dict[str, list[str]] = {}
    batch_ids: list[uuid.UUID] = []
    for level in ("campaign", "adset", "ad"):
        request_params = {
            "filtering": [
                {
                    "field": _UPDATED_TIME_FIELD[level],
                    "operator": "GREATER_THAN",
                    "value": since_epoch,
                }
            ]
        }
        try:
            batch_id, got = await _sync(
                session, level, account_key, request_params, triggered_by
            )
        except Exception as exc:  # noqa: BLE001 - one level must not sink the others
            # Usually Meta rate-limiting one edge. The levels are
            # independent, and ads are what the dashboard mostly shows, so
            # a throttled /campaigns call must not cost us the ad refresh.
            # The watermark is derived from Bronze, so whatever this level
            # missed is simply still pending at the next interval.
            logger.warning(
                "meta_delta_level_failed",
                account_key=account_key,
                level=level,
                error=str(exc),
            )
            continue
        batch_ids.append(batch_id)
        if got:
            fetched[level] = got

    logger.info(
        "meta_delta_fetched",
        account_key=account_key,
        since_epoch=since_epoch,
        **{level: len(ids) for level, ids in fetched.items()},
    )
    if not fetched:
        return {}

    await _pull_missing_parents(
        session, batch_ids, fetched, account_key=account_key, triggered_by=triggered_by
    )
    return await refresh_entities_for_ids(session, fetched)


#: When this account's entities were last surveyed in full.
#:
#: Read from `sync_batches`, not from `max(extracted_at)` on Bronze: the
#: Bronze version has no index for `parent_ids ->> 'account_key'`, so it
#: walks back along `ix_raw_dump_meta_extracted_at` for 21,542 blocks and
#: 2.1s per account -- absurd for a watermark the poll reads every few
#: minutes. `sync_batches` is small and indexed on `account_key`.
#:
#: `started_at`, not `finished_at`, because every row a batch wrote has an
#: `extracted_at` at or after the batch began; starting there cannot leave
#: a gap. Only completed batches count, so a failed run does not advance
#: the watermark past data it never read.
#:
#: Batches that fetched specific ids (the webhook path, and the parent
#: pulls) are excluded: they looked at a handful of objects, not at the
#: account, so they are no evidence about anything else that changed.
_WATERMARK = text("""
    SELECT max(started_at)
    FROM sync_batches
    WHERE account_key = :account_key
      AND endpoint IN ('campaigns', 'adsets', 'ads')
      AND status IN ('success', 'partial_failure')
      AND NOT coalesce(request_params ? 'object_ids', false)
""")


async def last_fetch_epoch(
    session: AsyncSession, *, account_key: str, overlap_seconds: int, max_lookback_days: int
) -> int:
    """When this account's entities were last surveyed in full, as a unix
    timestamp, less ``overlap_seconds``.

    Derived from the sync log rather than kept as a stored cursor, which
    makes it self-healing: if the poller is down for a day, the next run
    asks for a day of changes and catches up on its own, and a nightly full
    sync moves the watermark forward for free. The overlap re-reads a few
    minutes we have already seen, because Bronze is append-only and
    re-reading an unchanged object is harmless, while missing one is not.

    ``max_lookback_days`` caps a cold start (or a long outage) so the first
    run cannot ask Meta for every edit in the account's history.
    """
    newest = (await session.execute(_WATERMARK, {"account_key": account_key})).scalar()
    floor = int(time.time()) - max_lookback_days * 86400
    if newest is None:
        return floor
    return max(floor, int(newest.timestamp()) - overlap_seconds)
