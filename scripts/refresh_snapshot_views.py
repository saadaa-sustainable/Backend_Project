"""Rebuild the founder-facing meta_direct_* snapshots.

These are MATERIALIZED views, so unlike a plain view they do not
recompute on read -- which is the point. meta_direct_daily_90d is
~100k rows and takes about 9 seconds to build; a Google Sheet pulling
it a thousand rows at a time would pay that on every page. Materialised
and indexed, the same read is under 0.2s.

The cost is that they are only as fresh as the last refresh, so this
runs at the END of the nightly pipeline, after Meta insights, Shopify
and the attribution rebuild have all landed. Run it earlier and the
snapshot shows yesterday's numbers under today's window.

CONCURRENTLY on purpose: a plain REFRESH takes an ACCESS EXCLUSIVE lock
and any sheet pulling at that moment blocks until it finishes. The
concurrent form needs the unique index each view carries (see
sql/snapshot_views.sql) and leaves readers untouched.

Usage:
    ./.venv/bin/python scripts/refresh_snapshot_views.py
    ./.venv/bin/python scripts/refresh_snapshot_views.py --no-concurrent
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402

DSN = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")

VIEWS = (
    "meta_direct_active_30d",
    "meta_direct_active_90d",
    "meta_direct_daily_30d",
    "meta_direct_daily_90d",
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-concurrent", action="store_true",
                    help="Plain REFRESH. Faster, but locks readers out for its "
                         "duration. Only for a first build or a repair.")
    args = ap.parse_args()
    mode = "" if args.no_concurrent else "CONCURRENTLY "

    t0 = time.time()
    failed: list[str] = []
    conn = psycopg2.connect(DSN)
    conn.autocommit = True          # REFRESH CONCURRENTLY cannot run in a txn block
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '3600s'")
            for v in VIEWS:
                t = time.time()
                try:
                    cur.execute(f"REFRESH MATERIALIZED VIEW {mode}public.{v}")
                    cur.execute(f"SELECT COUNT(*) FROM public.{v}")
                    n = cur.fetchone()[0]
                    print(f"[ok]   {v:<24}{n:>8,} rows   {time.time() - t:>6.1f}s", flush=True)
                except Exception as exc:                      # noqa: BLE001
                    # One bad view must not cost the other three.
                    failed.append(v)
                    print(f"[FAIL] {v:<24}{str(exc)[:90]}", flush=True)
            cur.execute("SELECT data_through FROM public.meta_direct_data_through")
            through = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"\n[{'OK' if not failed else 'PARTIAL'}] snapshots refreshed in "
          f"{time.time() - t0:.1f}s, data through {through}")
    if failed:
        print(f"    failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
