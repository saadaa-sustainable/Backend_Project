"""Build dashboard session totals without re-ingesting Shopify data.

Run once before deploying the dashboard summary reader:
    .venv/bin/python scripts/refresh_dashboard_sessions.py

Subsequent Shopify silver refreshes maintain the totals automatically.
Failure rolls back the replacement, exits nonzero, and is not retried.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from time import monotonic

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import dispose_engine, session_scope  # noqa: E402
from app.services.dashboard_sessions import refresh_dashboard_sessions  # noqa: E402


async def main() -> None:
    started = monotonic()
    try:
        async with session_scope() as session:
            await session.execute(text("SET LOCAL statement_timeout = '300s'"))
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            await refresh_dashboard_sessions(session)
            days, first, last = (await session.execute(text(
                "SELECT COUNT(*), MIN(day), MAX(day) FROM public.shopify_sessions_daily"
            ))).one()
        print(f"Session summary ready: {days} days, {first} to {last}; {monotonic() - started:.1f}s")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
