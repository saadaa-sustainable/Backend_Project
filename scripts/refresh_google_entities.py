"""SILVER: rebuild google_campaigns / google_ad_groups / google_ads from Bronze.

Second half of the pair. app/services/google/entity_flatten.py collapses
`raw_dump_google_ads` down to one current-state row per entity, newest
snapshot wins, and derives `google_ads.ad_label` for the 11% of ads
Google gave no name.

    python scripts/fetch_google_ads_entities.py   # API  -> raw_dump_google_ads
    python scripts/refresh_google_entities.py     # that -> google_* (Silver)

ORDERING CONSTRAINT -- this is the part that bites
--------------------------------------------------
`shopify_ad_attribution` TRUNCATEs and re-derives every order on every
run, attributing against whatever the universe looks like at that
moment, and its Google pass reads `google_ads` / `google_campaigns`.
Run this BEFORE silver_shopify_attribution or the nightly spends its
rebuild on a roster one day older than it needed to be.

That is the same trap meta_entities fell into three times -- registered
as a FlattenJob and nothing else, so only the in-process scheduler could
run it, and the scheduler is off in production. Hence this script AND the
`silver_google_entities` step in scripts/refresh_all_daily.py, not just
the registry entry.

Usage:
    ./.venv/bin/python scripts/refresh_google_entities.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import session_scope, dispose_engine  # noqa: E402
from app.services.google.entity_flatten import (  # noqa: E402
    refresh_google_entity_tables,
)


async def main() -> None:
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] google entity flatten: start",
          flush=True)
    async with session_scope() as session:
        counts = await refresh_google_entity_tables(session)
    for key, value in counts.items():
        print(f"        {key:35s} {value:,} rows", flush=True)
    print(f"\n[OK] google entity flatten complete in "
          f"{(datetime.utcnow() - t0).total_seconds():.1f}s", flush=True)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
