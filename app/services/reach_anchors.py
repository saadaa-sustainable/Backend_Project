"""Exact cumulative-reach anchors, so a CUSTOM date range is not a lie.

THE PROBLEM
-----------
Incremental reach is a subtraction of two cumulative snapshots:

    incr = cum[epoch, to_date] - cum[epoch, from_date - 1]

`scripts/fetch_reach_cumulative.py --anchors` stores only the ~8 as-of
dates the UI's date PRESETS can ask for. A preset therefore lands on an
exact pair and the subtraction is honest. A custom range does not, and
`_REACH_ANCHOR_SQL`'s `DISTINCT ON ... as_of_date <= :anchor` quietly
substitutes the nearest EARLIER snapshot instead of refusing.

That is not a rounding error, it is a different question. Measured
2026-10-21 for a 1 Oct..10 Oct range: both anchors resolve to the
30 Sep snapshot, so the subtraction is cum(09-30) - cum(09-30) = 0 and
the column reads zero new people for a campaign that reached 158,263.
A 14-day custom range resolved 20 days wide and read 13.1% high.

THE FIX
-------
Fetch the two anchors the range actually needs, from Meta, scoped to the
entities on the page, and store them so the next reader is free. Three
things make that cheap enough to do inside a request:

  * `filtering` on <level>.id. Verified 2026-10-21 that scoping the call
    does NOT change Meta's number -- reach is already de-duplicated per
    entity, so a filtered call returns the identical figure (SMCP
    5,620,833 either way). Filtered calls ran 0.7-1.0s against 1.3-2.2s
    account-wide, and the response is a page instead of 27.
  * The roster tables carry `account_id`, so only the accounts that own
    these entities are called, not all of them.
  * Rows persist into `ad_reach_cumulative` under the same primary key
    the nightly uses, so a custom range anyone has already looked at
    costs nothing, and the nightly's `--refetch` keeps it current.

ONLY A CLOSED WINDOW IS FINAL
-----------------------------
Meta revises a cumulative window's de-duplicated reach -- but measured
2026-10-21 against Meta, it revises it for exactly as long as the
window's LAST DAY is still accruing, and not a day longer:

    measured      as-of        campaigns   exact   worst error
    same day      2026-10-04          62      46        24.19%
    same day      2026-10-12          63      52        13.58%
    +1 day        2026-09-20          52      52         0.00%
    +2 days       2026-09-19          50      50         0.00%
    +7 days       2026-09-14          50      50         0.00%
    +30 days      2026-09-10          47      47         0.00%
    +90 days      2026-07-15          32      32         0.00%

So the rule is not "both anchors must share a vintage" -- it is that an
anchor measured on its own as-of date is PROVISIONAL and one measured
any time after it is FINAL. Two final anchors are comparable however
far apart they were measured, which is what makes serving a custom
range from stored rows possible at all.

A provisional anchor is re-measured when its day has since closed. When
its day has NOT closed -- an anchor on today -- no measurement can fix
it, so this declines to answer and the caller falls back. The clamp in
`_reach_spend_bound` normally keeps the latest anchor off today anyway.

FAILURE
-------
Every path degrades to the caller's existing nearest-snapshot lookup
rather than failing the page: reach is five columns of a wide table, and
a Meta outage must not take Ads Analyse down with it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.session import session_scope
from app.services.meta.client import MetaAPIClient

logger = logging.getLogger(__name__)

Level = Literal["ad", "adset", "campaign"]

#: Graph API `level`, the id field it returns, its name field, the
#: `filtering` field used to scope the call, and the roster table that
#: maps the entity to an ad account.
_LEVEL: dict[str, dict[str, str]] = {
    "ad": {"id": "ad_id", "name": "ad_name",
           "filter": "ad.id", "roster": "meta_ads"},
    "adset": {"id": "adset_id", "name": "adset_name",
              "filter": "adset.id", "roster": "meta_adsets"},
    "campaign": {"id": "campaign_id", "name": "campaign_name",
                 "filter": "campaign.id", "roster": "meta_campaigns"},
}

#: Meta rejects an over-long `filtering` value, and a shorter list also
#: keeps one failure from costing the whole page. 50 keeps the URL well
#: inside limits while still being one call for a typical page.
_ID_CHUNK = 50

#: Never fan out further than this from one request. A page of Ads
#: Analyse is bounded well below it; anything larger is a sign the caller
#: is asking for the whole fleet, which is the nightly's job.
MAX_ENTITIES = 600

#: An anchor is FINAL once measured strictly after its own as-of date;
#: see the table above. Measured on that date it is provisional, because
#: the window's last day was still accruing when Meta answered.
def _is_final(as_of: date, fetched_at: datetime | None) -> bool:
    return fetched_at is not None and fetched_at.date() > as_of

#: A request must not hang on Meta. Past this the caller falls back, and
#: whatever did arrive is still written (see _measure), so successive
#: readers converge instead of each paying the same cost.
FETCH_TIMEOUT_SECONDS = 12.0

#: How long to stop calling an account after it fails or runs out of
#: time. The token is on `development_access`, and when an account is
#: over its hourly budget MetaAPIClient does the right thing for a batch
#: job and the wrong thing for a web request: it waits. Observed
#: 2026-10-21 at usage_pct=382, it elected to sleep 3,065s. Cancelling
#: that is what the deadline is for, but without a cooldown EVERY
#: request would pay the deadline again to rediscover the same wall.
ACCOUNT_COOLDOWN_SECONDS = 300.0

#: {account_id: monotonic deadline}. Process-local and best-effort --
#: this is a politeness valve, not a correctness mechanism.
_cooldown: dict[str, float] = {}


def _cooling(account_id: str) -> bool:
    until = _cooldown.get(account_id)
    if until is None:
        return False
    if time.monotonic() >= until:
        del _cooldown[account_id]
        return False
    return True


def _cool_off(account_id: str) -> None:
    _cooldown[account_id] = time.monotonic() + ACCOUNT_COOLDOWN_SECONDS

_STORED_SQL = """
SELECT entity_id, as_of_date, cumulative_reach, fetched_at
  FROM public.ad_reach_cumulative
 WHERE level = :level
   AND epoch_date = :epoch
   AND as_of_date = ANY(:days)
   AND entity_id = ANY(:entity_ids)
"""

_UPSERT_SQL = """
INSERT INTO public.ad_reach_cumulative
    (level, entity_id, as_of_date, epoch_date, entity_name, account_id,
     cumulative_reach, cumulative_impressions, cumulative_spend, fetched_at)
VALUES (:level, :entity_id, :as_of_date, :epoch_date, :entity_name, :account_id,
        :reach, :impressions, :spend, now())
ON CONFLICT (level, entity_id, epoch_date, as_of_date) DO UPDATE SET
    entity_name            = EXCLUDED.entity_name,
    account_id             = EXCLUDED.account_id,
    cumulative_reach       = EXCLUDED.cumulative_reach,
    cumulative_impressions = EXCLUDED.cumulative_impressions,
    cumulative_spend       = EXCLUDED.cumulative_spend,
    fetched_at             = EXCLUDED.fetched_at
"""


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


async def _stored(
    session: AsyncSession, *, level: str, entity_ids: list[str],
    days: list[date], epoch: date,
) -> dict[tuple[str, date], tuple[int, datetime]]:
    """{(entity_id, as_of_date): (reach, fetched_at)} for EXACT day hits."""
    result = await session.execute(text(_STORED_SQL), {
        "level": level, "epoch": epoch, "days": days, "entity_ids": entity_ids,
    })
    return {(r[0], r[1]): (int(r[2] or 0), r[3]) for r in result}


async def _accounts_for(
    session: AsyncSession, *, level: str, entity_ids: list[str],
) -> dict[str, list[str]]:
    """{account_id: [entity_id, ...]}, so only the owning accounts are called.

    Entities the roster does not know are returned under the key ``""``
    and asked of every configured account -- a filtered call that matches
    nothing is cheap, and silently dropping the entity would leave its
    reach column blank with no explanation.
    """
    meta = _LEVEL[level]
    result = await session.execute(
        text(f"SELECT {meta['id']}, account_id FROM public.{meta['roster']} "
             f" WHERE {meta['id']} = ANY(:ids)"),
        {"ids": entity_ids},
    )
    by_account: dict[str, list[str]] = {}
    seen: set[str] = set()
    for entity_id, account_id in result:
        seen.add(entity_id)
        by_account.setdefault(account_id or "", []).append(entity_id)
    unknown = [e for e in entity_ids if e not in seen]
    if unknown:
        by_account.setdefault("", []).extend(unknown)
    return by_account


async def _fetch(
    client: MetaAPIClient, *, account_id: str, level: str, entity_ids: list[str],
    epoch: date, as_of: date,
) -> list[dict[str, Any]]:
    """One filtered, de-duplicated cumulative window for one account.

    `time_increment` is omitted deliberately -- that is what makes Meta
    return ONE de-duplicated row per entity for [epoch, as_of] rather
    than one row per day for the caller to wrongly add up.
    """
    meta = _LEVEL[level]
    params = {
        "level": level,
        "fields": f"{meta['id']},{meta['name']},account_id,reach,impressions,spend",
        "time_range": {"since": epoch.isoformat(), "until": as_of.isoformat()},
        "filtering": [
            {"field": meta["filter"], "operator": "IN", "value": entity_ids},
        ],
    }
    return [
        item async for item in
        client.paginate(f"act_{account_id}/insights", params=params)
    ]


async def _persist(rows: list[dict[str, Any]]) -> None:
    """Write through a session of our own.

    Not the request's session: a cache fill must not be able to poison
    the transaction the page is being read in, and its failure must not
    roll the read back.
    """
    if not rows:
        return
    async with session_scope() as write_session:
        for row in rows:
            await write_session.execute(text(_UPSERT_SQL), row)


async def _measure(
    session: AsyncSession, *, level: str, entity_ids: list[str],
    days: list[date], epoch: date,
) -> dict[tuple[str, date], int]:
    """Fetch `days` for `entity_ids` from Meta, store them, return them."""
    meta = _LEVEL[level]
    settings = get_settings().meta
    by_account = await _accounts_for(session, level=level, entity_ids=entity_ids)
    configured = [a.account_id for a in settings.accounts]

    jobs: list[tuple[str, list[str], date]] = []
    for account_id, ids in by_account.items():
        targets = configured if account_id == "" else [account_id]
        for target in targets:
            if _cooling(target):
                continue
            for chunk in _chunks(sorted(set(ids)), _ID_CHUNK):
                for day in days:
                    jobs.append((target, chunk, day))
    if not jobs:
        return {}

    out: dict[tuple[str, date], int] = {}
    pending: list[dict[str, Any]] = []
    async with MetaAPIClient() as client:
        # Concurrently: an ad-level page is a dozen (chunk x day) jobs and
        # running them in series put the cold path over the timeout. The
        # client's own semaphore (META_MAX_CONCURRENT_REQUESTS) still caps
        # how many actually reach Meta at once, so this does not stampede
        # a token whose hourly budget is the binding constraint.
        tasks = {
            asyncio.ensure_future(
                _fetch(client, account_id=account_id, level=level,
                       entity_ids=chunk, epoch=epoch, as_of=day)
            ): (account_id, chunk, day)
            for account_id, chunk, day in jobs
        }
        # The deadline lives HERE, not around the whole call, so whatever
        # did come back is still written. Timing out used to discard every
        # completed job, which meant a slow page never warmed its own
        # cache and the next reader paid the same cost again -- the fetch
        # made no progress no matter how many times it ran.
        done, unfinished = await asyncio.wait(
            tasks.keys(), timeout=FETCH_TIMEOUT_SECONDS)
        for task in unfinished:
            task.cancel()
            _cool_off(tasks[task][0])
        if unfinished:
            logger.info("reach_anchor_partial level=%s done=%d of %d",
                        level, len(done), len(tasks))

        for task in done:
            account_id, chunk, day = tasks[task]
            error = task.exception()
            if error is not None:
                _cool_off(account_id)
                logger.warning(
                    "reach_anchor_fetch_failed level=%s account=%s as_of=%s n=%d: %s",
                    level, account_id, day, len(chunk), error)
                continue
            for item in task.result():
                entity_id = item.get(meta["id"])
                if not entity_id:
                    continue
                reach = int(item.get("reach") or 0)
                out[(entity_id, day)] = reach
                pending.append({
                    "level": level, "entity_id": entity_id, "as_of_date": day,
                    "epoch_date": epoch, "entity_name": item.get(meta["name"]),
                    "account_id": item.get("account_id") or account_id,
                    "reach": reach,
                    "impressions": int(item.get("impressions") or 0),
                    "spend": float(item.get("spend") or 0.0),
                })
    await _persist(pending)
    return out


async def window_anchors(
    session: AsyncSession, *, level: Level, entity_ids: list[str],
    prev_day: date, latest_day: date, epoch: date,
) -> dict[str, tuple[int, int]] | None:
    """{entity_id: (prev_reach, latest_reach)} on ONE shared vintage.

    Returns ``None`` when it cannot answer -- no entities, too many of
    them, or Meta unreachable -- and the caller falls back to its
    existing nearest-snapshot lookup rather than showing a blank column.

    Entities that resolve on only one of the two days are omitted: half
    a subtraction is not a smaller answer, it is a wrong one.
    """
    if not entity_ids or prev_day >= latest_day:
        return None
    if len(entity_ids) > MAX_ENTITIES:
        logger.info("reach_anchor_fanout_skipped level=%s n=%d", level, len(entity_ids))
        return None

    days = [prev_day, latest_day]
    stored = await _stored(session, level=level, entity_ids=entity_ids,
                           days=days, epoch=epoch)

    # Who needs re-measuring: anyone missing a day, and anyone whose two
    # days were measured too far apart to be subtracted from each other.
    today = date.today()
    needs: list[str] = []
    for entity_id in entity_ids:
        for day in days:
            got = stored.get((entity_id, day))
            if got is None or not _is_final(day, got[1]):
                # An anchor on a day that has not closed cannot be made
                # final by re-measuring it, so do not spend a call on it.
                if day < today:
                    needs.append(entity_id)
                break

    if needs:
        try:
            fresh = await _measure(session, level=level, entity_ids=needs,
                                   days=days, epoch=epoch)
        except Exception:
            logger.warning("reach_anchor_measure_failed level=%s n=%d",
                           level, len(needs), exc_info=True)
            fresh = {}
        now = datetime.now().astimezone()
        for key, reach in fresh.items():
            stored[key] = (reach, now)

    out: dict[str, tuple[int, int]] = {}
    for entity_id in entity_ids:
        lo = stored.get((entity_id, prev_day))
        hi = stored.get((entity_id, latest_day))
        if lo is None or hi is None:
            continue
        # Both ends must be final. A provisional anchor would hand back a
        # number that moves on its own overnight, which is worse than
        # falling back to a nearest-snapshot value the cell labels.
        if not (_is_final(prev_day, lo[1]) and _is_final(latest_day, hi[1])):
            continue
        out[entity_id] = (lo[0], hi[0])
    return out or None
