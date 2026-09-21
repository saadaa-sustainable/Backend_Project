"""Rebuild ad_performance_summary -- the table Ads Analyse reads.

FIFTH INSTANCE OF THE SAME BUG
------------------------------
`ad_performance_summary` was registered as a FlattenJob in
app/services/silver/registry.py and NOTHING ELSE -- no script, no
pipeline step -- so the only thing that could run it was the in-process
scheduler, which is off in production (SCHEDULER_ENABLED=false on
Render; GitHub Actions runs scripts, not the app).

Same shape as `ad_lifecycle`, `refresh_insights_tables`,
`meta_entities` and the Meta activity log before it. Registering a job
is not the same as scheduling one, and nothing in the registry fails
loudly when a job never runs -- the table simply stops moving.

What it cost, measured 2026-09-21: gold_refreshed_at was 2026-09-11,
ten days stale, while ad_lifecycle beside it was refreshed that
morning. Ads Analyse is built on this table -- every spend, ROAS,
category and F1-F4 verdict in that section was ten days old, and
nothing in the UI said so.

Runs AFTER ad_lifecycle and shopify_ad_attribution: it joins Meta
metrics from the first to Shopify-attributed revenue from the second,
so running it earlier just rebuilds yesterday's answer.

Usage:
    ./.venv/bin/python scripts/refresh_ad_performance_summary.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.gold.ad_performance import (  # noqa: E402
    refresh_ad_performance_summary,
)


async def main() -> int:
    t0 = datetime.now()
    print(f"[{t0:%Y-%m-%dT%H:%M:%SZ}] ad_performance_summary refresh: start", flush=True)
    async with session_scope() as session:
        counts = await refresh_ad_performance_summary(session)
    for table, n in sorted(counts.items()):
        print(f"        {table:36}{n:>12,} rows", flush=True)
    await dispose_engine()
    print(f"\n[OK] ad_performance_summary refresh complete in "
          f"{(datetime.now() - t0).total_seconds():.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
