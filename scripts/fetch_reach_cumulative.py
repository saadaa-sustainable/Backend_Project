"""Fetch de-duplicated unique reach from Meta into ``ad_reach_cumulative``.

WHY THIS EXISTS
---------------
Reach is the one Meta metric that must never be summed. It counts
*people*, not events, and Meta de-duplicates it across the requested
window -- so a person who saw an ad on five days contributes 1 to a
5-day reach figure and 5 to the sum of the five daily figures.

Measured live on this account, 2026-09-01..2026-09-15:

    Meta's reach for the range (one call)   5,481,912
    SUM of the 15 daily reach rows         13,995,699   <- 2.55x too big

Everything downstream of that sum inherits the error, in the direction
that flatters: frequency (impressions/reach) reads far too low, cost per
1000 reach reads far too cheap. Over the last 30 days the stored daily
sums give a fleet frequency of 1.17, which is not a number a real
account produces.

The five Ads Analyse columns this feeds -- Reach Weight %, Prev Reach,
Latest Reach, Incr. Reach, Cost / 1k Incr. -- were left as explicit
placeholders in the UI precisely because no honest source existed for
them yet. This script is that source.

HOW
---
Imitates the Apps Script that fed the old sheet (`getAdsetReach`): hit
/insights with an explicit ``time_range`` and read ``reach`` straight
off the response. Two deliberate differences:

  * The call is made at ACCOUNT level with ``level=ad`` (or adset /
    campaign) rather than once per entity id. One paginated call
    returns every entity for the window, which is the same arithmetic
    Meta performs per-entity but costs ~27 requests instead of ~6,800.
  * ``time_increment`` is omitted entirely. That is the whole trick:
    with no increment Meta returns ONE row per entity for the whole
    range, de-duplicated. Asking for ``time_increment=1`` and adding
    the rows up is exactly the bug above.

The window is *growing*: ``[epoch, as_of_date]``. Storing cumulative
reach per as-of date turns incremental reach into a pure subtraction
downstream, with no further API calls:

    incr_reach = MAX(0, cum_at_window_end - cum_just_before_window_start)

which is the same formula the legacy `get_ireach_incremental_analysis`
RPC used, and the reason that RPC needed `ireach_cumulative_daily`.

WHAT IT IS NOT
--------------
`cumulative_reach` is cumulative since the EPOCH, not since the ad was
born. An ad that ran before the epoch has earlier reach that is not
counted here. The epoch is stored on every row so a reader can tell.

COST
----
One paginated pass per (as-of date x level). At ad level that is ~27
requests for ~6,800 ads. The token is on `development_access`, whose
per-hour budget is small, so `--anchors` exists: it fetches only the
dates the UI's date presets can actually ask for (~14 of them) instead
of a dense daily series. Re-running is cheap -- rows already present
are skipped unless `--refetch` is passed.

Usage:
    # the ~14 as-of dates every date preset needs -- start here
    ./.venv/bin/python scripts/fetch_reach_cumulative.py --anchors

    # keep it current (put this in the nightly chain)
    ./.venv/bin/python scripts/fetch_reach_cumulative.py --as-of yesterday

    # densify history so custom ranges land on an exact date
    ./.venv/bin/python scripts/fetch_reach_cumulative.py --from 2026-06-23 --to 2026-09-20

    # adset / campaign grain for the Ads Analyse rollup views
    ./.venv/bin/python scripts/fetch_reach_cumulative.py --anchors --levels ad,adset,campaign
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import httpx
except ImportError:  # pragma: no cover - dependency guard
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - dependency guard
    print("Missing dependency: pip install psycopg2-binary", file=sys.stderr)
    raise SystemExit(1)

from scripts.ingest_last_15_days import (  # noqa: E402
    AccountConfig,
    PAGE_SIZE,
    REQUEST_TIMEOUT_SECONDS,
    _connect_with_retry,
    _discover_accounts,
    _paginate,
    _to_psycopg2_dsn,
)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


#: Meta insights in this project's Bronze begin 2026-01-01. Reaching
#: further back would be fetching a window whose ad roster we cannot
#: reconcile against anything stored.
DEFAULT_EPOCH = date(2026, 1, 1)

#: Identity columns per level. Meta rejects an id below the requested
#: level (ad_id at level=campaign is an error, not a null), so each
#: level gets exactly the columns it owns.
_ID_FIELD = {"ad": "ad_id", "adset": "adset_id", "campaign": "campaign_id"}
_NAME_FIELD = {"ad": "ad_name", "adset": "adset_name", "campaign": "campaign_name"}

LEVELS = ("ad", "adset", "campaign")

DDL = """
CREATE TABLE IF NOT EXISTS public.ad_reach_cumulative (
    level                  TEXT        NOT NULL,
    entity_id              TEXT        NOT NULL,
    as_of_date             DATE        NOT NULL,
    epoch_date             DATE        NOT NULL,
    entity_name            TEXT,
    account_id             TEXT,
    cumulative_reach       BIGINT      NOT NULL,
    cumulative_impressions BIGINT,
    cumulative_spend       NUMERIC(18, 4),
    fetched_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- epoch_date is part of the key, not just a stamp. A row is the
    -- answer to "reach over [epoch_date, as_of_date]", and two rows
    -- with the same `until` but different `since` are different
    -- questions, not a conflict. Keying on it also leaves room for
    -- window-reach rows (a moving `since`) in the same table without a
    -- migration.
    PRIMARY KEY (level, entity_id, epoch_date, as_of_date)
);
"""

#: Repairs the first shipped shape of the table, whose primary key was
#: (level, entity_id, as_of_date) -- it could not hold two different
#: window starts for the same end date. Idempotent, and a no-op on a
#: table created by the DDL above.
DDL_MIGRATIONS = ["""
DO $$
DECLARE
    cols text;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY k.ord)
      INTO cols
      FROM pg_constraint c
      JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
     WHERE c.conrelid = 'public.ad_reach_cumulative'::regclass
       AND c.contype = 'p';

    IF cols = 'level,entity_id,as_of_date' THEN
        ALTER TABLE public.ad_reach_cumulative
            DROP CONSTRAINT ad_reach_cumulative_pkey,
            ADD PRIMARY KEY (level, entity_id, epoch_date, as_of_date);
    END IF;
END $$;
"""]

DDL_INDEXES = [
    # The read path asks "newest snapshot at or before this anchor date,
    # for every entity at this level" -- one index serves both anchors.
    "CREATE INDEX IF NOT EXISTS ix_arc_level_asof "
    "ON public.ad_reach_cumulative (level, as_of_date DESC)",
    "CREATE INDEX IF NOT EXISTS ix_arc_entity "
    "ON public.ad_reach_cumulative (entity_id, as_of_date DESC)",
]


# ----------------------------------------------------------------------
# As-of date selection
# ----------------------------------------------------------------------


def preset_anchor_dates(today: date) -> list[date]:
    """The as-of dates the UI's date presets can ask for.

    Every window needs two snapshots: one at ``to_date`` (latest) and one
    at ``from_date - 1`` (previous). Enumerating the presets rather than
    fetching a dense daily series is what keeps the first run inside the
    development-tier rate budget.

    Mirrors ``resolvePreset`` in admin/src/components/DateRangePicker.tsx.
    "Lifetime" is absent on purpose: an unbounded window has no previous
    anchor, so incremental reach is undefined for it.
    """
    first_of_this = today.replace(day=1)
    last_of_prev = first_of_this - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)

    windows = [
        (today, today),                                  # Today
        (today - timedelta(days=1), today - timedelta(days=1)),   # Yesterday
        (today - timedelta(days=6), today),              # Last 7 Days
        (today - timedelta(days=29), today),             # Last 30 Days
        (today - timedelta(days=89), today),             # Last 90 Days
        (first_of_this, today),                          # This Month
        (first_of_prev, last_of_prev),                   # Last Month
    ]
    anchors: set[date] = set()
    for frm, to in windows:
        anchors.add(to)
        anchors.add(frm - timedelta(days=1))
    return sorted(a for a in anchors if a >= DEFAULT_EPOCH)


def preset_windows(today: date) -> list[tuple[date, date]]:
    """(since, until) for every window the UI can ask for.

    This is the Apps Script's `getAdsetReach(adsetId, start, end)` shape:
    one /insights call with an explicit time_range, reading `reach`
    straight off the response. Meta de-duplicates over exactly that
    range, so the answer is the true unique reach for the window --
    not a difference between two cumulative snapshots, which measures
    people NEW since the epoch and is a different quantity.

    Stored with epoch_date = since, so a row answers "reach over
    [since, until]" and the read path can look one up exactly.
    """
    first_of_this = today.replace(day=1)
    last_of_prev = first_of_this - timedelta(days=1)
    yesterday = today - timedelta(days=1)
    windows = [
        (today, today),
        (yesterday, yesterday),
        (today - timedelta(days=6), today),
        (today - timedelta(days=29), today),
        (today - timedelta(days=89), today),
        (first_of_this, today),
        (last_of_prev.replace(day=1), last_of_prev),
        (DEFAULT_EPOCH, today),          # "Lifetime", now bounded
        (DEFAULT_EPOCH, yesterday),      # ... and its data-last-date twin
        # Same windows ending yesterday -- Meta's daily insights land a
        # day late, so the dashboard's own last date is usually
        # yesterday and those are the ranges it actually requests.
        (yesterday - timedelta(days=6), yesterday),
        (yesterday - timedelta(days=29), yesterday),
        (yesterday - timedelta(days=89), yesterday),
    ]
    return sorted({(f, t) for f, t in windows if f >= DEFAULT_EPOCH and f <= t})


def date_series(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ----------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------


async def _fetch_cumulative(
    client: httpx.AsyncClient,
    base_url: str,
    account: AccountConfig,
    access_token: str,
    *,
    level: str,
    epoch: date,
    as_of: date,
) -> list[dict[str, Any]]:
    """One growing-window pass for one account at one level.

    No ``time_increment``: that is what makes Meta return a single
    de-duplicated row per entity for [epoch, as_of] instead of one row
    per day for us to (wrongly) add up.
    """
    params = {
        "access_token": access_token,
        "level": level,
        "fields": ",".join([
            _ID_FIELD[level], _NAME_FIELD[level],
            "account_id", "reach", "impressions", "spend",
        ]),
        "time_range": json.dumps({"since": epoch.isoformat(), "until": as_of.isoformat()}),
    }
    return await _paginate(client, f"{base_url}/act_{account.account_id}/insights", params)


def _to_rows(items: list[dict[str, Any]], *, level: str, epoch: date, as_of: date,
             fallback_account_id: str) -> list[tuple]:
    id_field, name_field = _ID_FIELD[level], _NAME_FIELD[level]
    rows: list[tuple] = []
    for it in items:
        entity_id = it.get(id_field)
        if not entity_id:
            continue
        rows.append((
            level,
            str(entity_id),
            as_of,
            epoch,
            it.get(name_field),
            str(it.get("account_id") or fallback_account_id),
            int(float(it.get("reach") or 0)),
            int(float(it.get("impressions") or 0)),
            float(it.get("spend") or 0.0),
        ))
    return rows


# ----------------------------------------------------------------------
# Write
# ----------------------------------------------------------------------


UPSERT = """
INSERT INTO public.ad_reach_cumulative
    (level, entity_id, as_of_date, epoch_date, entity_name, account_id,
     cumulative_reach, cumulative_impressions, cumulative_spend, fetched_at)
VALUES %s
ON CONFLICT (level, entity_id, epoch_date, as_of_date) DO UPDATE SET
    entity_name            = EXCLUDED.entity_name,
    account_id             = EXCLUDED.account_id,
    cumulative_reach       = EXCLUDED.cumulative_reach,
    cumulative_impressions = EXCLUDED.cumulative_impressions,
    cumulative_spend       = EXCLUDED.cumulative_spend,
    fetched_at             = EXCLUDED.fetched_at
"""


class _Db:
    """A Postgres handle that reconnects instead of assuming it survived.

    This job spends 90-170 seconds per anchor talking to Meta and
    nothing at all to Postgres. Supabase's pooler closes an idle
    connection well inside that gap, so holding one connection open for
    the whole run fails at a random write -- it did, on the sixth
    anchor, *after* that anchor's 170 seconds of rate-limited API budget
    had already been spent fetching data that was then thrown away.

    Every statement therefore goes through `run`, which reconnects and
    retries on the two errors that mean "this handle is dead"
    (OperationalError / InterfaceError) rather than "this statement is
    wrong".
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn = None

    def _fresh(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 - a dead handle may throw on close
                pass
        self._conn = _connect_with_retry(self._dsn)
        return self._conn

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            return self._fresh()
        return self._conn

    def run(self, fn, *, attempts: int = 4):
        last: Exception | None = None
        for i in range(attempts):
            conn = self.conn
            try:
                out = fn(conn)
                conn.commit()
                return out
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                last = exc
                print(f"    db connection lost ({exc.__class__.__name__}); "
                      f"reconnecting (attempt {i + 1}/{attempts})", flush=True)
                self._fresh()
                time.sleep(2 ** i)
        assert last is not None
        raise last

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass


def _ensure_schema(db: _Db) -> None:
    def _go(conn):
        with conn.cursor() as cur:
            cur.execute(DDL)
            for stmt in DDL_MIGRATIONS + DDL_INDEXES:
                cur.execute(stmt)
    db.run(_go)


def _existing_pairs(db: _Db, level: str, epoch: date) -> set[date]:
    """As-of dates already stored for this level at this epoch.

    A row fetched against a different epoch is not interchangeable with
    one fetched against this epoch -- the number means something else --
    so the epoch is part of the match.
    """
    def _go(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT as_of_date FROM public.ad_reach_cumulative "
                "WHERE level = %s AND epoch_date = %s",
                (level, epoch),
            )
            return {r[0] for r in cur.fetchall()}
    return db.run(_go)


#: The Supabase pooler drops a single oversized statement, and an
#: ad-level snapshot is ~6,800 rows. Each chunk is also its own
#: transaction (see _write), so a connection lost mid-snapshot costs one
#: chunk to redo, not the whole 170-second fetch.
_WRITE_CHUNK = 500


def _existing_windows(db: _Db, level: str) -> set[tuple[date, date]]:
    """(since, until) pairs already stored for this level."""
    def _go(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT epoch_date, as_of_date FROM public.ad_reach_cumulative "
                "WHERE level = %s", (level,))
            return {(r[0], r[1]) for r in cur.fetchall()}
    return db.run(_go)


def _write(db: _Db, rows: list[tuple]) -> int:
    if not rows:
        return 0
    now = datetime.now()
    payload = [r + (now,) for r in rows]
    written = 0
    for i in range(0, len(payload), _WRITE_CHUNK):
        chunk = payload[i:i + _WRITE_CHUNK]

        def _go(conn, chunk=chunk):
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, UPSERT, chunk, page_size=_WRITE_CHUNK)

        db.run(_go)
        written += len(chunk)
    return written


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------


async def _run(
    accounts: list[AccountConfig],
    *,
    base_url: str,
    access_token: str,
    levels: list[str],
    epoch: date,
    as_of_dates: list[date] | None,
    windows: list[tuple[date, date]] | None,
    db: _Db,
    refetch: bool,
) -> tuple[int, int]:
    total_rows = 0
    total_calls = 0
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for level in levels:
            pairs = windows if windows is not None else [(epoch, d) for d in as_of_dates]
            if refetch:
                todo_pairs = pairs
            else:
                have = _existing_windows(db, level)
                todo_pairs = [p for p in pairs if p not in have]
            skipped = len(pairs) - len(todo_pairs)
            todo = [u for _s, u in todo_pairs]
            print(f"\n=== level={level}  {len(todo)} as-of dates to fetch"
                  f"{f' ({skipped} already stored)' if skipped else ''}", flush=True)
            for since, as_of in todo_pairs:
                t0 = time.monotonic()
                # Accounts in parallel, as-of dates strictly in series:
                # each call's cost grows with the window, and the token's
                # hourly budget is the binding constraint, not latency.
                results = await asyncio.gather(*[
                    _fetch_cumulative(client, base_url, acct, access_token,
                                      level=level, epoch=since, as_of=as_of)
                    for acct in accounts
                ], return_exceptions=True)
                rows: list[tuple] = []
                failed = []
                for acct, res in zip(accounts, results):
                    if isinstance(res, BaseException):
                        failed.append(f"{acct.name or acct.account_id}: {res}")
                        continue
                    total_calls += 1
                    rows.extend(_to_rows(res, level=level, epoch=since, as_of=as_of,
                                         fallback_account_id=acct.account_id))
                if failed:
                    # Loudly, and without writing a partial snapshot: a
                    # snapshot missing one account's ads is not a smaller
                    # snapshot, it is a wrong one, and the subtraction
                    # downstream would read the gap as lost reach.
                    print(f"  {since}..{as_of}  FAILED -- {'; '.join(failed)}", flush=True)
                    continue
                n = _write(db, rows)
                total_rows += n
                reach = sum(r[6] for r in rows)
                print(f"  {since}..{as_of}  {n:>6,} rows  reach={reach:>12,}  "
                      f"{time.monotonic() - t0:5.1f}s", flush=True)
    return total_rows, total_calls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preset-windows", action="store_true",
                        help="Fetch TRUE window reach for every range the UI "
                             "presets can ask for (since..until per call).")
    parser.add_argument("--anchors", action="store_true",
                        help="Fetch only the as-of dates the UI date presets need (~14).")
    parser.add_argument("--as-of", help="A single as-of date (YYYY-MM-DD, or 'today'/'yesterday').")
    parser.add_argument("--from", dest="from_date", help="Start of a dense as-of range.")
    parser.add_argument("--to", dest="to_date", help="End of a dense as-of range.")
    parser.add_argument("--epoch", default=DEFAULT_EPOCH.isoformat(),
                        help=f"Fixed window start for every snapshot (default {DEFAULT_EPOCH}).")
    parser.add_argument("--levels", default="ad",
                        help="Comma-separated: ad,adset,campaign (default: ad).")
    parser.add_argument("--account", help="Limit to one configured account key.")
    parser.add_argument("--refetch", action="store_true",
                        help="Re-fetch as-of dates already stored instead of skipping them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan and exit without calling Meta.")
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    epoch = date.fromisoformat(args.epoch)
    today = date.today()

    levels = [lv.strip() for lv in args.levels.split(",") if lv.strip()]
    bad = [lv for lv in levels if lv not in LEVELS]
    if bad:
        print(f"Unknown level(s): {', '.join(bad)}. Valid: {', '.join(LEVELS)}", file=sys.stderr)
        return 2

    windows: list[tuple[date, date]] | None = None
    as_of_dates: list[date] = []
    if args.preset_windows:
        windows = preset_windows(today)
    elif args.anchors:
        as_of_dates = preset_anchor_dates(today)
    elif args.as_of:
        token = args.as_of.strip().lower()
        one = (today if token == "today"
               else today - timedelta(days=1) if token == "yesterday"
               else date.fromisoformat(args.as_of))
        as_of_dates = [one]
    elif args.from_date and args.to_date:
        as_of_dates = date_series(date.fromisoformat(args.from_date),
                                  date.fromisoformat(args.to_date))
    else:
        print("Pick one of --preset-windows / --anchors / --as-of / (--from and --to).",
              file=sys.stderr)
        return 2

    if windows is None:
        as_of_dates = [d for d in as_of_dates if epoch <= d <= today]
    if windows is None and not as_of_dates:
        print("No as-of dates in range after clamping to [epoch, today].", file=sys.stderr)
        return 2

    access_token = os.getenv("META_ACCESS_TOKEN")
    if not access_token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 2
    api_version = os.getenv("META_API_VERSION", "v21.0")
    base_url = os.getenv("META_GRAPH_API_BASE_URL", f"https://graph.facebook.com/{api_version}")

    configured = _discover_accounts()
    if args.account:
        configured = {k: v for k, v in configured.items() if k == args.account}
    accounts = list(configured.values())
    if not accounts:
        print("No Meta ad accounts configured -- set META_ACCOUNT_1_ID in .env.", file=sys.stderr)
        return 2

    print(f"Epoch:      {epoch}  (every snapshot is cumulative from this date)")
    print(f"Levels:     {', '.join(levels)}")
    print(f"Accounts:   {', '.join(a.name or a.account_id for a in accounts)}")
    if windows is not None:
        print(f"Windows ({len(windows)}):")
        for f, t in windows:
            print(f"   {f} .. {t}")
    else:
        print(f"As-of dates ({len(as_of_dates)}): "
              f"{', '.join(d.isoformat() for d in as_of_dates)}")
    print(f"Page size:  {PAGE_SIZE}")
    if args.dry_run:
        print("\n--dry-run: nothing fetched.")
        return 0

    dsn_raw = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL")
    if not dsn_raw:
        print("DATABASE_URL_SYNC / DATABASE_URL is not set.", file=sys.stderr)
        return 2
    db = _Db(_to_psycopg2_dsn(dsn_raw))
    try:
        _ensure_schema(db)
        t0 = time.monotonic()
        rows, calls = asyncio.run(_run(
            accounts, base_url=base_url, access_token=access_token,
            levels=levels, epoch=epoch, as_of_dates=as_of_dates, windows=windows,
            db=db, refetch=args.refetch,
        ))
        print(f"\n[OK] {rows:,} rows written from {calls} account-level passes "
              f"in {time.monotonic() - t0:.1f}s", flush=True)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
