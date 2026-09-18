"""Rebuild meta_campaigns / meta_adsets / meta_ads from Bronze.

app/services/meta/entity_flatten.py collapses raw_dump_meta's
`object_type` in ('campaign','adset','ad') rows down to one current-state
row per entity (newest snapshot wins).

Third instance of the same bug, and the most expensive one so far.
`meta_entities` was registered as a FlattenJob in
app/services/silver/registry.py:39 and NOTHING ELSE -- no script, no
pipeline step -- so the only thing that could run it was the in-process
scheduler, which is off in production (SCHEDULER_ENABLED=false on
Render; GitHub Actions runs scripts, not the app). Same shape as
`ad_lifecycle` and `refresh_insights_tables` before it.

What it cost, measured 2026-09-16 against the legacy dashboard on an
identical window (2026-08-16..09-15):

    meta_ads newest ad          2026-08-24   (23 days stale)
    ad_lifecycle newest ad      2026-09-10
    ads in ad_lifecycle only           944

    orders matched to an ad     CTD 21,458   BP 17,531   -18.3%
    attributed sales            CTD 23.0L    BP 19.5L    -34,98,720

2,797 of those missing orders (Rs 33,31,217) had a utm_content that is a
numeric ad_id present in ad_lifecycle RIGHT NOW -- the cascade simply
could not see the ad, because `_load_ad_universe` reads meta_ads. Zero
orders whose ad WAS in meta_ads went unmatched, which is what proves the
matching logic itself was never the problem.

Note the ordering constraint this creates. shopify_ad_attribution
TRUNCATEs and re-derives every order each run, so it always attributes
against whatever the universe looks like at that moment. Run this BEFORE
silver_shopify or the nightly attribution rebuild spends its run on a
universe one day older than it needed to be.

This flatten only ever sees what Bronze holds, so it is the second half
of a pair -- `ingest_last_15_days.py --roster-only` fills Bronze,
this promotes it to Silver:

    python scripts/ingest_last_15_days.py --roster-only
    python scripts/refresh_meta_entities.py

Usage:
    ./.venv/bin/python scripts/refresh_meta_entities.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.meta.entity_flatten import refresh_entity_tables  # noqa: E402


async def main() -> None:
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] meta entity flatten: start", flush=True)
    async with session_scope() as session:
        counts = await refresh_entity_tables(session)
    for k, v in counts.items():
        print(f"        {k:35s} {v:,} rows", flush=True)
    print(f"\n[OK] meta entity flatten complete in "
          f"{(datetime.utcnow() - t0).total_seconds():.1f}s", flush=True)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
