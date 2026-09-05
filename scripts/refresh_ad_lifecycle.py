"""One-shot ad_lifecycle rebuild.

app/services/silver/ad_lifecycle.py builds the per-ad table the Ads
Analyse dashboard reads -- every ad_insights metric, the F1-F4 pass
flags, and the Winner / Incremental Winner / P0 / P1 / P2 / Discarded
category. It was registered as a FlattenJob in
app/services/silver/registry.py and nothing else, which means the ONLY
thing that ever refreshed it was the in-process scheduler.

That scheduler does not run in production (SCHEDULER_ENABLED is off on
Render, and the GitHub Actions path runs scripts, not the app). So the
table simply stopped updating: measured 2026-09-05, ad_lifecycle's
newest lifecycle_refreshed_at was 2026-08-25 -- eleven days stale, while
insights_daily_by_ad beside it was six hours old. Every category on the
dashboard was a verdict on eleven-day-old metrics, and no ad created in
that window had a row at all.

This script exists so scripts/refresh_all_daily.py can refresh it like
everything else. Same shape as refresh_shopify_silver.py: import the
service function, run it, print the count.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_ad_lifecycle.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.silver.ad_lifecycle import refresh_ad_lifecycle  # noqa: E402


async def main() -> None:
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] ad_lifecycle refresh: start", flush=True)
    async with session_scope() as session:
        counts = await refresh_ad_lifecycle(session)
    for k, v in counts.items():
        print(f"        {k:35s} {v:,} rows", flush=True)
    print(f"\n[OK] ad_lifecycle refresh complete in "
          f"{(datetime.utcnow() - t0).total_seconds():.1f}s", flush=True)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
