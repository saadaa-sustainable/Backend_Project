"""One-shot Shopify silver-layer refresh.

After ingest_shopify.py lands fresh rows in raw_dump_shopify, this
script rebuilds the two silver tables the CPIS + Landing Page views
read from:

  1. refresh_shopify_tables()
       -> shopify_orders, shopify_customers, shopify_sessions
     (structural flatten of the latest raw_dump_shopify snapshot per
     entity id -- see app/services/silver/shopify_flatten.py)

  2. refresh_attribution_tables()
       -> shopify_order_attribution, shopify_landing_page_analysis
     (Python-side matching engine that resolves each order's utm_content
     back to a Meta ad_id -- see app/services/silver/shopify_ad_attribution.py)

The scheduler runs both automatically on the flatten-poll interval, but
this script lets a merchant/admin trigger them explicitly right after a
manual Shopify fetch without waiting for the next poll (or on Render
where SCHEDULER_ENABLED is off).

Step 1 only rebuilds a table whose BRONZE has moved since that table was
last built -- a normal run fetches products/inventory/orders, so the five
other tables would otherwise be re-flattened into byte-identical rows.
That check reads raw_dump_shopify, so it cannot see a change to the
FLATTEN SQL itself; pass --force after editing shopify_flatten.py.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_shopify_silver.py
    ./.venv/Scripts/python.exe scripts/refresh_shopify_silver.py --force
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

# Make sure the app package is importable from the repo root.
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.silver.shopify_flatten import refresh_shopify_tables  # noqa: E402
from app.services.silver.shopify_ad_attribution import refresh_attribution_tables  # noqa: E402


async def main(force: bool) -> None:
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] Shopify silver refresh: start", flush=True)

    mode = "rebuilding EVERY table (--force)" if force else "rebuilding only tables whose bronze moved"
    print(f"  [1/2] refresh_shopify_tables -- {mode}...", flush=True)
    async with session_scope() as session:
        counts_a = await refresh_shopify_tables(session, force=force)
    for k, v in counts_a.items():
        print(f"        {k:35s} {v:,} rows", flush=True)

    print("  [2/2] refresh_attribution_tables (order_attribution + landing_page)...", flush=True)
    async with session_scope() as session:
        counts_b = await refresh_attribution_tables(session)
    for k, v in counts_b.items():
        print(f"        {k:35s} {v:,} rows", flush=True)

    dt = (datetime.utcnow() - t0).total_seconds()
    print(f"\n[OK] Shopify silver refresh complete in {dt:.1f}s", flush=True)
    await dispose_engine()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true",
                    help="Rebuild every silver table even if its bronze is unchanged. "
                         "Use after editing the flatten SQL -- the freshness check "
                         "watches bronze, so a code change alone never triggers it.")
    asyncio.run(main(ap.parse_args().force))
