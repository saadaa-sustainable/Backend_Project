"""Rebuild ad_insights / adset_insights / campaign_insights from Bronze.

app/services/silver/insights_flatten.py flattens raw_dump_meta's
`object_type='insights'` rows into one table per level, selecting each
level with `WHERE parent_ids ->> 'level' = :level`.

Like ad_lifecycle before it, this was registered as a FlattenJob in
app/services/silver/registry.py and NOTHING ELSE -- so the only thing
that ever ran it was the in-process scheduler, which is off in
production (SCHEDULER_ENABLED=false on Render; GitHub Actions runs
scripts, not the app). The tables went stale and stayed tiny.

Measured 2026-09-15, against 19,056 ads / 3,126 adsets / 523 campaigns
in the roster tables beside them:

    ad_insights          14,866 rows
    adset_insights        1,171 rows     37% of adsets
    campaign_insights       488 rows

Two separate causes, both now fixed in scripts/ingest_last_15_days.py:

  1. The nightly ingest only ever requested `level=ad` (hardcoded).
     Campaign and adset insights were never fetched at all, so those two
     tables could only ever hold whatever a one-off historical run left
     behind. Fixed by `--levels`.

  2. The nightly ingest never wrote `level` into parent_ids, which is
     the exact key this flatten filters on -- so even the ad-level rows
     it did write were invisible here. Fixed by tagging parent_ids.

Run this AFTER an ingest that requested the levels you want:

    python scripts/ingest_last_15_days.py --levels campaign,adset,ad
    python scripts/refresh_insights_tables.py

Usage:
    ./.venv/bin/python scripts/refresh_insights_tables.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.silver.insights_flatten import refresh_insights_tables  # noqa: E402


async def main() -> None:
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] insights flatten: start", flush=True)
    async with session_scope() as session:
        counts = await refresh_insights_tables(session)
    for k, v in counts.items():
        print(f"        {k:35s} {v:,} rows", flush=True)
    print(f"\n[OK] insights flatten complete in "
          f"{(datetime.utcnow() - t0).total_seconds():.1f}s", flush=True)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
