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

REBINDING, and why this script checks before it refreshes: Postgres
stores a view's dependencies by table OID, not by name. The silver
builders rebuild into `<table>_new` and rename-swap, which means the old
table keeps the OID these views were compiled against. A REFRESH then
re-executes the stored definition perfectly faithfully -- against
`insights_daily_by_ad_old`. Nothing errors. The sheets just quietly show
whatever the table held before the last swap, and did for weeks. So
`_verify_bindings` resolves each view's real dependencies and re-applies
sql/snapshot_views.sql when any of them has drifted off the live table.

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


#: Every view below must depend on this table, not on a swapped-out
#: predecessor of it.
LIVE_SOURCE = "insights_daily_by_ad"

DDL_PATH = Path(__file__).resolve().parents[1] / "sql" / "snapshot_views.sql"


def _verify_bindings(cur) -> list[str]:
    """Names of meta_direct_* views bound to something other than LIVE_SOURCE.

    Reads pg_depend, so it reports where the view will ACTUALLY read on
    its next refresh rather than what its printed definition says -- the
    two diverge after a rename-swap, which is the whole point.
    """
    cur.execute("""
        SELECT DISTINCT v.relname, src.relname
          FROM pg_class v
          JOIN pg_namespace n   ON n.oid = v.relnamespace
          JOIN pg_rewrite r     ON r.ev_class = v.oid
          JOIN pg_depend d      ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass
          JOIN pg_class src     ON src.oid = d.refobjid
         WHERE n.nspname = 'public'
           AND v.relname LIKE %s
           AND src.relkind IN ('r', 'p')
           AND src.relname LIKE %s
           AND src.relname <> %s
    """, ("meta_direct%", LIVE_SOURCE + "%", LIVE_SOURCE))
    drifted = cur.fetchall()
    for view, src in drifted:
        print(f"[drift] {view} reads public.{src}, not public.{LIVE_SOURCE}", flush=True)
    return sorted({v for v, _ in drifted})


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
            # A refresh of a view bound to a stale table succeeds and
            # publishes stale numbers, so rebind first.
            if _verify_bindings(cur):
                print(f"[fix]  re-applying {DDL_PATH.name} to rebind", flush=True)
                cur.execute(DDL_PATH.read_text())
                still = _verify_bindings(cur)
                print("[fix]  rebound" if not still
                      else f"[FAIL] still drifted: {', '.join(still)}", flush=True)
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
