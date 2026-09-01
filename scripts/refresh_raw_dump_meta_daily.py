"""refresh_raw_dump_meta_daily.py — Bronze → Silver day-wise flatten.

Reads `public.raw_dump_meta` rows where `object_type='insights'` AND
`request_params->>'time_increment' = '1'` (true per-day rows only, not
the time_increment=all_days summaries that inflate spend 3-10× when
summed), and upserts them into `public.raw_dump_meta_daily` on the
partial unique index `ux_meta_daily_ad_date` — keyed on
`(raw_payload->>'ad_id', raw_payload->>'date_start')`.

The Silver table has the same shape as Bronze (id, meta_id, raw_payload,
api_endpoint, ..., parent_ids, is_nested), just with the guarantee that
there is at most one row per (ad, day). On conflict the existing row is
overwritten with the newest Bronze row for that key — `ingested_at DESC`
tie-break — so any re-fetch of a day (fixing a gap, refreshing counts)
propagates through.

Runs against DATABASE_URL_SYNC (psycopg2) so it stays independent of the
FastAPI async engine and can be launched by cron, by `/admin/flatten`,
or by hand.

Usage:
    python scripts/refresh_raw_dump_meta_daily.py
    python scripts/refresh_raw_dump_meta_daily.py --since 2026-08-01
    python scripts/refresh_raw_dump_meta_daily.py --account 1 --since 2026-08-20
    python scripts/refresh_raw_dump_meta_daily.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("psycopg2 not installed. `pip install psycopg2-binary`.", file=sys.stderr)
    sys.exit(1)

# Load .env from the project root, not from wherever the script was launched.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env", override=True)


def _get_db_url() -> str:
    """Return a libpq-compatible URL routed through Supabase's
    transaction-mode pooler (:6543).

    We DON'T prefer DATABASE_URL_SYNC anymore -- that .env line is
    typically on :5432 (session mode), which caps at 15 clients per
    project and gets exhausted the moment uvicorn + a sync script run
    together. DATABASE_URL is guaranteed to be transaction-mode
    (:6543) after 2026-08-29's pool fix, so we build the psycopg2 URL
    from it by stripping asyncpg's driver prefix and its
    ?prepared_statement_cache_size query param."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL required in .env")
    # SQLAlchemy dialect prefixes psycopg2.connect can't parse.
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    # asyncpg's ?prepared_statement_cache_size=0 query param isn't a
    # valid libpq option -- drop the whole query string (nothing else
    # in there we need).
    if "?" in url:
        url = url.split("?", 1)[0]
    return url


# The upsert SQL. Column list is verbatim from raw_dump_meta so any
# addition to Bronze surfaces here too -- keep in sync when adding new
# tracked columns.
UPSERT_SQL = """
INSERT INTO public.raw_dump_meta_daily (
    id, meta_id, raw_payload, api_endpoint, api_version,
    batch_id, request_params, extracted_at, ingested_at,
    sync_type, payload_hash, processing_status,
    object_type, parent_ids, is_nested
)
SELECT
    r.id, r.meta_id, r.raw_payload, r.api_endpoint, r.api_version,
    r.batch_id, r.request_params, r.extracted_at, r.ingested_at,
    r.sync_type, r.payload_hash, r.processing_status,
    r.object_type, r.parent_ids, r.is_nested
FROM public.raw_dump_meta r
WHERE r.object_type = 'insights'
  AND r.request_params->>'time_increment' = '1'
  AND r.raw_payload->>'ad_id' IS NOT NULL
  AND r.raw_payload->>'date_start' IS NOT NULL
  {extra_where}
ON CONFLICT ((raw_payload->>'ad_id'), (raw_payload->>'date_start'))
  WHERE raw_payload->>'ad_id' IS NOT NULL
    AND raw_payload->>'date_start' IS NOT NULL
DO UPDATE SET
    raw_payload       = EXCLUDED.raw_payload,
    api_endpoint      = EXCLUDED.api_endpoint,
    api_version       = EXCLUDED.api_version,
    batch_id          = EXCLUDED.batch_id,
    request_params    = EXCLUDED.request_params,
    extracted_at      = EXCLUDED.extracted_at,
    ingested_at       = EXCLUDED.ingested_at,
    sync_type         = EXCLUDED.sync_type,
    payload_hash      = EXCLUDED.payload_hash,
    processing_status = EXCLUDED.processing_status,
    parent_ids        = EXCLUDED.parent_ids,
    meta_id           = EXCLUDED.meta_id
WHERE
    -- Only overwrite when the incoming row is newer than the one in
    -- Silver -- guards against reprocessing a stale run clobbering a
    -- fresh one.
    EXCLUDED.ingested_at >= public.raw_dump_meta_daily.ingested_at
"""

COUNT_SQL = """
SELECT count(*) AS bronze_rows,
       count(*) FILTER (WHERE raw_payload->>'ad_id' IS NOT NULL
                          AND raw_payload->>'date_start' IS NOT NULL) AS valid_keys
FROM public.raw_dump_meta
WHERE object_type = 'insights'
  AND request_params->>'time_increment' = '1'
  {extra_where}
"""

SILVER_STATS_SQL = """
SELECT count(*) AS silver_rows,
       min((raw_payload->>'date_start')) AS min_d,
       max((raw_payload->>'date_start')) AS max_d,
       count(DISTINCT (raw_payload->>'ad_id')) AS unique_ads
FROM public.raw_dump_meta_daily
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", type=str, help="Only include Bronze rows with date_start >= this (YYYY-MM-DD).")
    ap.add_argument("--account", type=str, help="Filter to one account_key ('1', '2', or '3').")
    ap.add_argument("--dry-run", action="store_true", help="Report what would be flattened without writing.")
    args = ap.parse_args()

    extra_where_parts = []
    query_params: dict[str, object] = {}
    if args.since:
        # ISO text comparison works for YYYY-MM-DD; no ::date cast needed.
        extra_where_parts.append("AND (raw_payload->>'date_start') >= %(since)s")
        query_params["since"] = args.since
    if args.account:
        extra_where_parts.append("AND (parent_ids->>'account_key') = %(account)s")
        query_params["account"] = args.account
    extra_where = "\n  ".join(extra_where_parts)

    url = _get_db_url()
    conn = psycopg2.connect(url, connect_timeout=30)
    conn.autocommit = False
    cur = conn.cursor()

    # Pre-flight report
    cur.execute(COUNT_SQL.format(extra_where=extra_where), query_params)
    bronze_rows, valid_keys = cur.fetchone()
    print(f"[bronze] {bronze_rows:,} matching rows; {valid_keys:,} have both ad_id and date_start")

    if args.dry_run:
        print("[dry-run] not writing")
        conn.close()
        return 0

    t0 = time.monotonic()
    cur.execute(UPSERT_SQL.format(extra_where=extra_where), query_params)
    upserted = cur.rowcount
    conn.commit()
    dt = time.monotonic() - t0
    print(f"[silver] upserted {upserted:,} rows in {dt:.1f}s")

    # Post-flatten stats
    cur.execute(SILVER_STATS_SQL)
    silver_rows, min_d, max_d, unique_ads = cur.fetchone()
    print(f"[silver] table now has {silver_rows:,} rows, "
          f"{unique_ads:,} unique ads, date_start {min_d}..{max_d}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
