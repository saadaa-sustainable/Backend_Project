"""Daily session totals, built by ingestion rather than dashboard requests."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_EXISTS = "SELECT to_regclass('public.shopify_sessions_daily') IS NOT NULL"

#: Is this session Meta-driven? Read off `utm_source` alone.
#:
#: Measured over all 20,045,933 sessions on 2026-10-15: utm_source
#: identifies 14,519,759 of them as Meta. Also testing utm_medium for
#: Meta's placement names (Instagram_Reels, Facebook_Mobile_Feed,
#: Facebook_Stories, Threads_Feed and the rest) found 82 more sessions
#: -- 0.0004%. Every Meta placement already carries a Meta utm_source,
#: so the medium test earns nothing and is left out rather than carried
#: as a second rule that has to stay in step with the first.
#:
#: What the data actually holds, by session volume:
#:   META 13.6M · Meta 269k · meta 199k   -> the `meta%` prefix
#:   METALD_1, META-FREETOTE, META-FeaturedOfferings, META-SiteLink,
#:   META-P-H5, METALD_1-FeaturedOfferings  -> same prefix
#:   facebook 363k · ig 57k · fb 9k · IGShopping 611 · instagram 36
#:   Mutm_source=META 3.4k · utm_source=META 474  -> a broken template
#:      wrote the whole parameter into the value; `%=meta%` recovers it
#:   {{site_source_name}} 96  -> Meta's own macro, unexpanded
#:   an 469  -> Audience Network, one of the four values that macro
#:      resolves to (fb / ig / an / msg)
#:
#: Deliberately NOT Meta, though they look adjacent: kwikengage,
#: kwikchat, KwikChatBOT, spur, contlo and `wa` are WhatsApp and chat
#: tooling, not Meta ad delivery, and together they carry 1.37M
#: sessions that would otherwise be counted as paid Meta traffic.
#:
#: Prefix-matched rather than listed exactly, because the `META-<name>`
#: family grows whenever someone adds a campaign suffix, and a new one
#: appearing should not silently fall out of the number.
META_SOURCE_SQL = """(
       lower(btrim(utm_source)) LIKE 'meta%'
    OR lower(btrim(utm_source)) LIKE '%=meta%'
    OR lower(btrim(utm_source)) LIKE 'facebook.%'
    OR lower(btrim(utm_source)) LIKE 'instagram.%'
    OR lower(btrim(utm_source)) LIKE '%.facebook.com'
    OR lower(btrim(utm_source)) LIKE '%.instagram.com'
    OR lower(btrim(utm_source)) IN
         ('facebook', 'fb', 'ig', 'instagram', 'igshopping', 'an',
          'msg', 'messenger', 'fb.me', '{{site_source_name}}')
)"""

#: `sessions` stays the all-traffic total. The Dashboard reads
#: `meta_sessions`, but the total is what tells a reader that 14.5M of
#: 20.0M sessions were Meta -- drop it and the tile cannot say what
#: share of traffic it is describing, and nothing else can check it.
_CREATE = """
CREATE TABLE public.shopify_sessions_daily (
    day date PRIMARY KEY,
    sessions numeric NOT NULL,
    meta_sessions numeric NOT NULL DEFAULT 0,
    flattened_at timestamptz NOT NULL
)
"""

#: Added after the table shipped, so an existing deployment gains the
#: column instead of needing a drop. Cheap and idempotent.
_ADD_META_COLUMN = (
    "ALTER TABLE public.shopify_sessions_daily "
    "ADD COLUMN IF NOT EXISTS meta_sessions numeric NOT NULL DEFAULT 0"
)

_INSERT = f"""
INSERT INTO public.shopify_sessions_daily (day, sessions, meta_sessions, flattened_at)
SELECT day,
       SUM(sessions),
       COALESCE(SUM(sessions) FILTER (WHERE {META_SOURCE_SQL}), 0),
       CURRENT_TIMESTAMP
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
    else:
        # Already deployed without meta_sessions: add it rather than
        # make the caller drop a table other readers are using.
        await session.execute(text(_ADD_META_COLUMN))

    await session.execute(text("DELETE FROM public.shopify_sessions_daily"))
    await session.execute(text(_INSERT))
    await session.execute(text("ANALYZE public.shopify_sessions_daily"))
    return True
