"""Silver-layer flatten step for Meta campaign/adset/ad entities.

Bronze (``raw_dump_meta``) accumulates one row per fetch — the same
campaign/adset/ad reappears every time the hourly/daily sync refreshes it.
This module rebuilds three current-state Silver tables (``meta_campaigns``,
``meta_adsets``, ``meta_ads``), one row per entity, keeping only each
entity's most recently fetched snapshot.

Column names deliberately mirror the existing ``primary_table`` (the
production Meta_ads_data dashboard's daily-insights table) — ``ad_name``,
``ad_id``, ``ad_status``, ``campaign_name``, ``campaign_id``, ``adset_name``,
``adset_id``, ``account_name`` — rather than raw Meta API field names, so the
same naming convention reads consistently whether a table/RPC/chatbot is
looking at insights or entities, and campaign/adset names are joined in
directly (Meta's API only gives each level its own parent *ids*, not
parent *names*) so no caller needs a join to get a human-readable row.

Called after every sync (see ``app/scheduler/jobs.py``) so these tables
never drift stale relative to Bronze.

Each statement below is executed individually (never semicolon-joined into
one call) — asyncpg's extended query protocol rejects multiple commands in
a single prepared statement.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS meta_campaigns (
        campaign_id text PRIMARY KEY,
        campaign_name text,
        campaign_status text,
        campaign_effective_status text,
        account_id text,
        account_name text,
        objective text,
        buying_type text,
        smart_promotion_type text,
        daily_budget numeric,
        lifetime_budget numeric,
        budget_remaining numeric,
        spend_cap numeric,
        bid_strategy text,
        start_time timestamptz,
        stop_time timestamptz,
        created_time timestamptz,
        updated_time timestamptz,
        updated_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_meta_campaigns_account_name ON meta_campaigns (account_name)",
    "CREATE INDEX IF NOT EXISTS ix_meta_campaigns_status ON meta_campaigns (campaign_status)",
    """
    CREATE TABLE IF NOT EXISTS meta_adsets (
        adset_id text PRIMARY KEY,
        adset_name text,
        adset_status text,
        adset_effective_status text,
        campaign_id text,
        campaign_name text,
        account_id text,
        account_name text,
        billing_event text,
        optimization_goal text,
        destination_type text,
        daily_budget numeric,
        lifetime_budget numeric,
        budget_remaining numeric,
        bid_amount numeric,
        bid_strategy text,
        start_time timestamptz,
        end_time timestamptz,
        created_time timestamptz,
        updated_time timestamptz,
        updated_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_meta_adsets_account_name ON meta_adsets (account_name)",
    "CREATE INDEX IF NOT EXISTS ix_meta_adsets_campaign_id ON meta_adsets (campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_meta_adsets_status ON meta_adsets (adset_status)",
    """
    CREATE TABLE IF NOT EXISTS meta_ads (
        ad_id text PRIMARY KEY,
        ad_name text,
        ad_status text,
        ad_effective_status text,
        adset_id text,
        adset_name text,
        campaign_id text,
        campaign_name text,
        account_id text,
        account_name text,
        conversion_domain text,
        bid_amount numeric,
        created_time timestamptz,
        updated_time timestamptz,
        updated_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_meta_ads_account_name ON meta_ads (account_name)",
    "CREATE INDEX IF NOT EXISTS ix_meta_ads_campaign_id ON meta_ads (campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_meta_ads_adset_id ON meta_ads (adset_id)",
    "CREATE INDEX IF NOT EXISTS ix_meta_ads_status ON meta_ads (ad_status)",
]

_TRUNCATE_CAMPAIGNS = "TRUNCATE meta_campaigns"
_INSERT_CAMPAIGNS = """
INSERT INTO meta_campaigns
SELECT DISTINCT ON (meta_id)
    meta_id AS campaign_id,
    raw_payload ->> 'name' AS campaign_name,
    raw_payload ->> 'status' AS campaign_status,
    raw_payload ->> 'effective_status' AS campaign_effective_status,
    parent_ids ->> 'account_id' AS account_id,
    parent_ids ->> 'account_name' AS account_name,
    raw_payload ->> 'objective' AS objective,
    raw_payload ->> 'buying_type' AS buying_type,
    raw_payload ->> 'smart_promotion_type' AS smart_promotion_type,
    NULLIF(raw_payload ->> 'daily_budget', '')::numeric AS daily_budget,
    NULLIF(raw_payload ->> 'lifetime_budget', '')::numeric AS lifetime_budget,
    NULLIF(raw_payload ->> 'budget_remaining', '')::numeric AS budget_remaining,
    NULLIF(raw_payload ->> 'spend_cap', '')::numeric AS spend_cap,
    raw_payload ->> 'bid_strategy' AS bid_strategy,
    NULLIF(raw_payload ->> 'start_time', '')::timestamptz AS start_time,
    NULLIF(raw_payload ->> 'stop_time', '')::timestamptz AS stop_time,
    NULLIF(raw_payload ->> 'created_time', '')::timestamptz AS created_time,
    NULLIF(raw_payload ->> 'updated_time', '')::timestamptz AS updated_time,
    extracted_at AS updated_at
FROM raw_dump_meta
WHERE object_type = 'campaign'
ORDER BY meta_id, extracted_at DESC
"""

_TRUNCATE_ADSETS = "TRUNCATE meta_adsets"
_INSERT_ADSETS = """
INSERT INTO meta_adsets
SELECT DISTINCT ON (a.meta_id)
    a.meta_id AS adset_id,
    a.raw_payload ->> 'name' AS adset_name,
    a.raw_payload ->> 'status' AS adset_status,
    a.raw_payload ->> 'effective_status' AS adset_effective_status,
    a.parent_ids ->> 'campaign_id' AS campaign_id,
    c.campaign_name,
    a.parent_ids ->> 'account_id' AS account_id,
    a.parent_ids ->> 'account_name' AS account_name,
    a.raw_payload ->> 'billing_event' AS billing_event,
    a.raw_payload ->> 'optimization_goal' AS optimization_goal,
    a.raw_payload ->> 'destination_type' AS destination_type,
    NULLIF(a.raw_payload ->> 'daily_budget', '')::numeric AS daily_budget,
    NULLIF(a.raw_payload ->> 'lifetime_budget', '')::numeric AS lifetime_budget,
    NULLIF(a.raw_payload ->> 'budget_remaining', '')::numeric AS budget_remaining,
    (a.raw_payload ->> 'bid_amount')::numeric AS bid_amount,
    a.raw_payload ->> 'bid_strategy' AS bid_strategy,
    NULLIF(a.raw_payload ->> 'start_time', '')::timestamptz AS start_time,
    NULLIF(a.raw_payload ->> 'end_time', '')::timestamptz AS end_time,
    NULLIF(a.raw_payload ->> 'created_time', '')::timestamptz AS created_time,
    NULLIF(a.raw_payload ->> 'updated_time', '')::timestamptz AS updated_time,
    a.extracted_at AS updated_at
FROM raw_dump_meta a
LEFT JOIN meta_campaigns c ON c.campaign_id = a.parent_ids ->> 'campaign_id'
WHERE a.object_type = 'adset'
ORDER BY a.meta_id, a.extracted_at DESC
"""

_TRUNCATE_ADS = "TRUNCATE meta_ads"
_INSERT_ADS = """
INSERT INTO meta_ads
SELECT DISTINCT ON (a.meta_id)
    a.meta_id AS ad_id,
    a.raw_payload ->> 'name' AS ad_name,
    a.raw_payload ->> 'status' AS ad_status,
    a.raw_payload ->> 'effective_status' AS ad_effective_status,
    a.parent_ids ->> 'adset_id' AS adset_id,
    ads.adset_name,
    a.parent_ids ->> 'campaign_id' AS campaign_id,
    c.campaign_name,
    a.parent_ids ->> 'account_id' AS account_id,
    a.parent_ids ->> 'account_name' AS account_name,
    a.raw_payload ->> 'conversion_domain' AS conversion_domain,
    (a.raw_payload ->> 'bid_amount')::numeric AS bid_amount,
    NULLIF(a.raw_payload ->> 'created_time', '')::timestamptz AS created_time,
    NULLIF(a.raw_payload ->> 'updated_time', '')::timestamptz AS updated_time,
    a.extracted_at AS updated_at
FROM raw_dump_meta a
LEFT JOIN meta_adsets ads ON ads.adset_id = a.parent_ids ->> 'adset_id'
LEFT JOIN meta_campaigns c ON c.campaign_id = a.parent_ids ->> 'campaign_id'
WHERE a.object_type = 'ad'
ORDER BY a.meta_id, a.extracted_at DESC
"""


async def ensure_entity_tables(session: AsyncSession) -> None:
    """Create meta_campaigns/meta_adsets/meta_ads if they don't exist yet. Safe to call every time."""
    for statement in _DDL_STATEMENTS:
        await session.execute(text(statement))
    await session.commit()


async def refresh_entity_tables(session: AsyncSession) -> dict[str, int]:
    """Rebuild meta_campaigns/meta_adsets/meta_ads from the latest raw_dump_meta
    snapshot of each entity. Order matters: adsets/ads join campaign_name/adset_name
    from the tables refreshed just before them."""
    await ensure_entity_tables(session)

    await session.execute(text(_TRUNCATE_CAMPAIGNS))
    await session.execute(text(_INSERT_CAMPAIGNS))
    await session.commit()

    await session.execute(text(_TRUNCATE_ADSETS))
    await session.execute(text(_INSERT_ADSETS))
    await session.commit()

    await session.execute(text(_TRUNCATE_ADS))
    await session.execute(text(_INSERT_ADS))
    await session.commit()

    counts: dict[str, int] = {}
    for table in ("meta_campaigns", "meta_adsets", "meta_ads"):
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        counts[table] = result.scalar_one()

    logger.info("meta_entity_tables_refreshed", **counts)
    return counts
