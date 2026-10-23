"""Rebuild cpis_by_sku -- the table behind /cpis.

WHY THIS SCRIPT HAD TO EXIST
----------------------------
`refresh_cpis_by_sku` was registered as a FlattenJob in
app/services/silver/registry.py and NOTHING ELSE -- no script, no
pipeline step. The only things that could run it were the in-process
scheduler, which is off in production (SCHEDULER_ENABLED=false on
Render; GitHub Actions runs scripts, not the app), and a manual
`POST /admin/flatten/jobs/cpis_by_sku/run`.

So it did not run. Measured 2026-10-22: `cpis_by_sku.computed_at` was
**2026-08-28 02:14**, 55 days stale, while both of its inputs were
current -- `ad_lifecycle` refreshed 2026-10-21 03:30 and
`shopify_inventory` held data through 2026-10-20. Nothing was wrong with
the data; nothing was running the job. Every figure /cpis served was an
August snapshot.

Fourth instance of this exact bug in this codebase, after
`meta_entities`, `ad_lifecycle` and `refresh_insights_tables`. The
lesson each time is the same: a registry entry is not a schedule.

ORDERING
--------
Reads `ad_lifecycle` (ad_id, ad_name, spend, ncp_count) and
`shopify_inventory` (daily units sold / ending units / sell-through), so
it must run after both. In scripts/refresh_all_daily.py it is the last
CPIS step, which puts it after `ad_lifecycle` and after the Shopify
silver that feeds `shopify_inventory`.

WHAT IT COMPUTES, AND THE CAVEAT THAT COMES WITH IT
---------------------------------------------------
See app/services/gold/cpis.py and docs/cpis-attribution.md section D.
In short, this table CORRELATES ads to master SKUs by case-insensitive
substring match on the ad NAME -- it never looks at an order, so it is
not attribution. `units_sold` is genuinely windowed; `ad_spend` and
`ncp_count` are LIFETIME totals, so `cost_per_unit_sold` divides a
lifetime numerator by a windowed denominator.

The substring matcher also over-counts: measured 2026-10-22, 3,046 ads
match more than one master SKU and each one's full spend is charged to
every SKU it matched, Rs 4,98,35,906 in total, of which Rs 4,36,06,585
is a nested-substring collision (`SDFS` matching an ad named for
`SDFSK`). Refreshing this table makes those numbers CURRENT rather than
stale; it does not make them right. The attribution-based tables
(`cpis_by_sku_utm`, `cpis_by_sku_daily`) are the ones to trust.

Usage:
    ./.venv/bin/python scripts/refresh_cpis_by_sku.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.gold.cpis import refresh_cpis_by_sku  # noqa: E402


async def main() -> None:
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] cpis_by_sku: start", flush=True)
    async with session_scope() as session:
        counts = await refresh_cpis_by_sku(session)
    for key, value in counts.items():
        print(f"        {key:35s} {value:,} rows", flush=True)
    print(f"\n[OK] cpis_by_sku complete in "
          f"{(datetime.utcnow() - t0).total_seconds():.1f}s", flush=True)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
