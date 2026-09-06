"""One-shot ad_performance_summary rebuild.

app/services/gold/ad_performance.py builds the Gold table the Ads
Analyse dashboard actually SELECTs from -- /admin/analytics/ads-analyse
starts `FROM ad_performance_summary aps` and joins ad_lifecycle beside
it, so whatever this table says is what a merchant sees.

It had the same defect ad_lifecycle had: registered only as a FlattenJob
in app/services/silver/registry.py, so the in-process scheduler was the
only thing that ever refreshed it -- and that scheduler does not run in
production (SCHEDULER_ENABLED is off on Render, and the GitHub Actions
path runs scripts, not the app).

Measured 2026-09-06, right after the metric overlay finally landed:

    ad_id 120210879750940422   source 5,684,807   ad_lifecycle 5,684,807
                                                  ad_performance_summary
                                                    635,741
    ad_id 120215851600420422   source 5,435,814   ad_lifecycle 5,435,814
                                                  gold 0, and categorised
                                                    "Discarded" against
                                                    "P1 analysis"

gold_refreshed_at on every row read 2026-08-28 -- nine days stale. The
overlay had worked perfectly into ad_lifecycle and stopped one table
short of the dashboard, which is the only table the dashboard reads.

Fixing ad_lifecycle's copy of this bug (scripts/refresh_ad_lifecycle.py)
did not fix this one, because the two are separate registry entries. If
another Gold table is ever added the same way, it will need its own
runner too -- being in the registry is not the same as being in a
pipeline.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_ad_performance_summary.py
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


async def main() -> None:
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] ad_performance_summary refresh: start",
          flush=True)
    async with session_scope() as session:
        counts = await refresh_ad_performance_summary(session)
    for k, v in counts.items():
        print(f"        {k:35s} {v:,} rows", flush=True)
    print(f"\n[OK] ad_performance_summary refresh complete in "
          f"{(datetime.utcnow() - t0).total_seconds():.1f}s", flush=True)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
