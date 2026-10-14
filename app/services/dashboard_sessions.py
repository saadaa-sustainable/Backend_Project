"""Daily session totals, built by ingestion rather than dashboard requests."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_EXISTS = "SELECT to_regclass('public.shopify_sessions_daily') IS NOT NULL"
_CREATE = """
CREATE TABLE public.shopify_sessions_daily (
    day date PRIMARY KEY,
    sessions numeric NOT NULL,
    flattened_at timestamptz NOT NULL
)
"""
_INSERT = """
INSERT INTO public.shopify_sessions_daily (day, sessions, flattened_at)
SELECT day, SUM(sessions), CURRENT_TIMESTAMP
FROM public.shopify_sessions
WHERE day IS NOT NULL AND sessions IS NOT NULL
GROUP BY day
"""


async def refresh_dashboard_sessions(
    session: AsyncSession, *, only_if_missing: bool = False,
) -> bool:
    """Publish a full daily snapshot in the caller's transaction.

    Called before committing a sessions flatten so both snapshots advance
    together. DELETE preserves the previous committed summary for readers
    while a replacement is computed; failure rolls back the entire change.
    No commit, retries, or request-time backfill here.
    """
    if only_if_missing and await session.scalar(text(_EXISTS)):
        return False

    # Always take the source lock before the writer lock, including for the
    # standalone backfill. This matches the flatten's TRUNCATE lock order.
    await session.execute(text("LOCK TABLE public.shopify_sessions IN ACCESS SHARE MODE"))
    await session.execute(text(
        "SELECT pg_advisory_xact_lock(hashtext('dashboard_sessions_daily_refresh'))"
    ))
    exists = await session.scalar(text(_EXISTS))
    if exists and only_if_missing:
        return False
    if not exists:
        await session.execute(text(_CREATE))
        # Internal analytics data: only the backend/ETL role should read it.
        await session.execute(text("ALTER TABLE public.shopify_sessions_daily ENABLE ROW LEVEL SECURITY"))
        await session.execute(text(
            "REVOKE ALL ON public.shopify_sessions_daily FROM PUBLIC, anon, authenticated"
        ))

    await session.execute(text("DELETE FROM public.shopify_sessions_daily"))
    await session.execute(text(_INSERT))
    await session.execute(text("ANALYZE public.shopify_sessions_daily"))
    return True
