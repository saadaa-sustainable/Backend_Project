"""Backfill Meta's account activity log -- the ad RENAME history.

WHY THIS EXISTS
---------------
Meta bakes an ad's name into the UTM tag AT CLICK TIME. Rename the ad
afterwards and every older order still carries the OLD name, while our
ad universe only knows the new one, so the order stops matching. The
attribution cascade lands it in `adset_name_miss`: we know which ad set
the click came from, but nothing in that ad set is called what the order
says it was called.

app/services/meta/activities.py already described this exact failure in
its docstring -- and was never wired to anything. It is registered
nowhere, no script drives it, and no Silver table consumes it. The 46,955
activity rows in Bronze today are a single accidental window
(2026-08-14 .. 2026-09-02, fetched 2026-09-04), which is presumably what
the in-process scheduler managed before it was turned off. Same shape as
`ad_lifecycle`, `refresh_insights_tables` and `meta_entities` before it:
the code was written, the runner never was.

WHAT IT RECOVERS
----------------
`update_ad_friendly_name` events carry object_id plus an extra_data blob
holding old_value and new_value, e.g.

    object_id  120251448926970431
    old_value  CTP-SMCFP+MU+NA+IHP+NO-ID-14/08/26
    new_value  CTP-SMCFP+MU+NA+IHP+CPL010-0783-14/08/26

Every old_value is an alias for that ad_id, which is exactly what an
order's utm_content holds. `refresh_ad_name_aliases.py` promotes these
into `ad_name_alias`, and the attribution cascade resolves through it.

RANGE, AND WHY IT IS CHUNKED
----------------------------
Meta refuses an over-long activities window, and a single unbounded call
would also be one enormous response. The range is cut into
--chunk-days slices, each fetched and written on its own, so a failure
part-way keeps everything already collected.

Rows are de-duplicated against Bronze on payload_hash before writing --
raw_dump_meta has no unique constraint on it, so re-running an
overlapping range would otherwise pile up copies of the same event.

Usage:
    # everything since the first ad this account ever ran
    ./.venv/bin/python scripts/ingest_meta_activities.py --since 2025-01-01

    # nightly top-up (the default window)
    ./.venv/bin/python scripts/ingest_meta_activities.py --days 7
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

# ingest_last_15_days only loads .env inside its own main(), so importing
# it is not enough -- do it here before any env is read.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from ingest_last_15_days import (  # noqa: E402
    AccountConfig,
    FetchResult,
    _build_rows,
    _connect_with_retry,
    _describe_dsn_safely,
    _discover_accounts,
    _ensure_schema,
    _bulk_insert_rows,
    _hash_payload,
    _paginate,
    _to_psycopg2_dsn,
)

#: app/core/meta_registry.py's ACTIVITY_FIELDS. Duplicated rather than
#: imported because this script deliberately does not pull in the app
#: package -- same standalone stance as ingest_last_15_days.py.
ACTIVITY_FIELDS = [
    "account_id", "actor_id", "actor_name", "application_id", "application_name",
    "date_time_in_timezone", "event_time", "event_type", "extra_data",
    "object_id", "object_name", "object_type", "translated_event_type",
]

DEFAULT_CHUNK_DAYS = 30


def _chunks(since: date, until: date, chunk_days: int) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    cur = since
    while cur <= until:
        end = min(cur + timedelta(days=chunk_days - 1), until)
        out.append((cur, end))
        cur = end + timedelta(days=1)
    return out


async def _fetch_activities(
    client: httpx.AsyncClient, base_url: str, account: AccountConfig,
    access_token: str, since: date, until: date,
) -> FetchResult:
    params = {
        "access_token": access_token,
        "fields": ",".join(ACTIVITY_FIELDS),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "limit": "500",
    }
    t0 = time.monotonic()
    result = FetchResult(
        account=account, object_type="activity", api_endpoint="activities",
        request_params={k: v for k, v in params.items() if k != "access_token"},
    )
    try:
        result.items = await _paginate(
            client, f"{base_url}/act_{account.account_id}/activities", params
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


def _existing_hashes(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '600s'")
        cur.execute(
            "SELECT payload_hash FROM raw_dump_meta "
            " WHERE object_type = 'activity' AND payload_hash IS NOT NULL"
        )
        return {r[0] for r in cur}


async def _run(args) -> int:
    import os

    accounts = list(_discover_accounts().values())
    if args.account:
        accounts = [a for a in accounts if a.key == args.account]
    if not accounts:
        print("No Meta accounts configured (META_ACCOUNT_<n>_ID).", file=sys.stderr)
        return 2
    access_token = os.environ.get("META_ACCESS_TOKEN")
    if not access_token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 2

    base_url = f"https://graph.facebook.com/{args.api_version}"
    until = date.fromisoformat(args.until) if args.until else date.today()
    since = (date.fromisoformat(args.since) if args.since
             else until - timedelta(days=args.days - 1))
    if since > until:
        print(f"--since {since} is after --until {until}.", file=sys.stderr)
        return 2

    windows = _chunks(since, until, args.chunk_days)
    print(f"Accounts: {len(accounts)}  ({', '.join(a.key for a in accounts)})")
    print(f"Range: {since} .. {until}  in {len(windows)} chunk(s) of {args.chunk_days}d")

    dsn = _to_psycopg2_dsn(args.database_url or os.environ["DATABASE_URL_SYNC"])
    print(f"Target: {_describe_dsn_safely(dsn)}")

    conn = _connect_with_retry(dsn)
    try:
        _ensure_schema(conn)
        seen = _existing_hashes(conn)
        print(f"Bronze already holds {len(seen):,} distinct activity payloads\n")

        total_fetched = total_new = 0
        renames = 0
        limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
        async with httpx.AsyncClient(limits=limits, timeout=180) as client:
            for account in accounts:
                for w_since, w_until in windows:
                    res = await _fetch_activities(
                        client, base_url, account, access_token, w_since, w_until)
                    if res.error:
                        # A failed chunk is reported and skipped, not fatal:
                        # the remaining chunks are still worth collecting.
                        print(f"  [{account.key}] {w_since}..{w_until}  ERROR {res.error}")
                        continue
                    total_fetched += len(res.items)
                    rows = _build_rows(
                        res, batch_id=uuid.uuid4(), api_version=args.api_version,
                        extracted_at=datetime.now(timezone.utc),
                    )
                    fresh = [r for r in rows if r["payload_hash"] not in seen]
                    seen.update(r["payload_hash"] for r in fresh)
                    n_ren = sum(
                        1 for it in res.items
                        if it.get("event_type") == "update_ad_friendly_name")
                    renames += n_ren
                    if fresh and not args.no_insert:
                        _bulk_insert_rows(conn, fresh)
                    total_new += len(fresh)
                    print(f"  [{account.key}] {w_since}..{w_until}  "
                          f"{len(res.items):>6,} events  {len(fresh):>6,} new  "
                          f"{n_ren:>4} renames  {res.duration_seconds:>5.1f}s", flush=True)

        print(f"\nfetched {total_fetched:,} events, wrote {total_new:,} new, "
              f"{renames:,} of them ad renames")
        if args.no_insert:
            print("(--no-insert: nothing was written)")
    finally:
        conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=None, help="Start date (YYYY-MM-DD).")
    ap.add_argument("--until", default=None, help="End date (YYYY-MM-DD). Default: today.")
    ap.add_argument("--days", type=int, default=7,
                    help="Trailing window when --since is omitted (default 7).")
    ap.add_argument("--chunk-days", type=int, default=DEFAULT_CHUNK_DAYS,
                    help=f"Days per request (default {DEFAULT_CHUNK_DAYS}).")
    ap.add_argument("--account", default=None, help="Restrict to one account key.")
    ap.add_argument("--api-version", default="v21.0")
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--no-insert", action="store_true",
                    help="Fetch and report only -- skip every DB write.")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
