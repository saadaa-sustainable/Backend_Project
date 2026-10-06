"""refresh_landing_page_gold.py -- populate landing_page_sessions_daily,
landing_page_analysis_30d, and landing_page_ad_breakdown_30d.

The actual logic lives in app/services/gold/landing_page.refresh_landing_page_tables()
(pure async function against an AsyncSession). This script is the
subprocess-friendly wrapper that the daily orchestrator + the
/admin/refresh/silver-all endpoint call. Keeps the gold module usable
from the in-process scheduler AND from GitHub Actions with no
duplicated SQL.

Root cause of this file: the FlattenJob registered in
app/services/silver/registry.py was only fired by the in-process
scheduler, which is disabled on Render (SCHEDULER_ENABLED=false). So
the three tables had not been refreshed since 2026-08-28 -- the
Landing Page Analysis tab was serving a fixed 30-day window that
ended two-plus weeks ago, and it looked like most rows had zero
ad_spend (they did -- for the OLD window, before the ads that spent
went live).

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_landing_page_gold.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.services.gold.landing_page import refresh_landing_page_tables  # noqa: E402


def _async_dsn() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_SYNC")
    if not url:
        raise RuntimeError(
            "Set DATABASE_URL (asyncpg) or DATABASE_URL_SYNC in the env."
        )
    # asyncpg does not accept sslmode; drop it if present (Supabase adds
    # it to the connection string). The pooler already forces TLS.
    dsn = (
        url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
           .replace("postgres+psycopg2://",   "postgresql+asyncpg://")
           .split("?")[0]
    )
    # 2026-09-14: swap pgbouncer transaction-mode port (:6543) to the
    # session-mode pooler (:5432). refresh_landing_page_tables streams
    # ~1.4M shopify_sessions rows into pandas and then flushes 800
    # aggregated rows back -- transaction pool times the connection out
    # mid-scan (ConnectionDoesNotExistError). Session pool has no such
    # cap. Same DB, different pool, no schema change.
    return dsn.replace(":6543/", ":5432/")


async def _main() -> None:
    # 10-min statement_timeout, applied with an explicit SET.
    #
    # It used to be passed as an asyncpg `server_settings` startup
    # parameter, and Supabase's pooler SILENTLY IGNORED it: the
    # connection still reported `2min`, so this job was killed at ~127
    # seconds on every run and both gold tables stayed EMPTY -- which is
    # why the Landing Page Analysis tab had nothing to show. Measured
    # 2026-10-05 on the same DSN:
    #
    #     server_settings={"statement_timeout": "600000"}  ->  2min
    #     SET statement_timeout = '600s'                   -> 10min
    #
    # The SET runs inside the session below, so it applies to the
    # connection that actually executes the scan rather than relying on
    # a startup parameter the pooler may drop.
    from sqlalchemy import text  # noqa: E402
    engine = create_async_engine(_async_dsn(), pool_pre_ping=True)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await session.execute(text("SET statement_timeout = '600s'"))
        counts = await refresh_landing_page_tables(session)
        await session.commit()
    for name, n in counts.items():
        print(f"  {name:<32} {n:>7,}")


if __name__ == "__main__":
    asyncio.run(_main())
