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
WHERE object_type = 'campaign'{extra}
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
WHERE a.object_type = 'adset'{extra}
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
WHERE a.object_type = 'ad'{extra}
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
    await session.execute(text(_INSERT_CAMPAIGNS.format(extra="")))
    await session.commit()

    await session.execute(text(_TRUNCATE_ADSETS))
    await session.execute(text(_INSERT_ADSETS.format(extra="")))
    await session.commit()

    await session.execute(text(_TRUNCATE_ADS))
    await session.execute(text(_INSERT_ADS.format(extra="")))
    await session.commit()

    counts: dict[str, int] = {}
    for table in ("meta_campaigns", "meta_adsets", "meta_ads"):
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        counts[table] = result.scalar_one()

    logger.info("meta_entity_tables_refreshed", **counts)
    return counts


#: Per level: the Silver table, its primary key, the Bronze
#: ``object_type``, the alias the templated INSERT uses for
#: ``raw_dump_meta``, and the INSERT template itself.
_LEVELS = {
    "campaign": ("meta_campaigns", "campaign_id", "", _INSERT_CAMPAIGNS),
    "adset": ("meta_adsets", "adset_id", "a.", _INSERT_ADSETS),
    "ad": ("meta_ads", "ad_id", "a.", _INSERT_ADS),
}

#: Campaign before adset before ad: the adset INSERT joins
#: ``campaign_name`` out of ``meta_campaigns`` and the ad INSERT joins
#: ``adset_name``/``campaign_name`` out of both, so a child flattened
#: before its parent lands with a null parent name.
_LEVEL_ORDER = ("campaign", "adset", "ad")


async def refresh_entities_for_ids(
    session: AsyncSession, ids_by_level: dict[str, list[str]]
) -> dict[str, int]:
    """Re-flatten only the named entities, leaving the rest of the Silver
    tables untouched.

    ``refresh_entity_tables`` TRUNCATEs and rebuilds all three tables from
    1.7M Bronze rows, which is the right thing after a full sync and far
    too much after a webhook about one ad. This does the same work scoped
    to a handful of ids: delete those rows, re-select them from Bronze.

    It reuses the very same INSERT templates as the full rebuild, with a
    `meta_id = ANY(...)` predicate spliced into the existing WHERE — so a
    column added to the full rebuild cannot silently go missing here, and
    `DELETE`-then-`INSERT` reproduces `TRUNCATE`-then-`INSERT` row for row.
    That matters because the two must agree: Bronze is append-only and the
    newest `extracted_at` wins, so a scoped refresh of a just-inserted row
    yields exactly what tonight's full rebuild will.

    Returns the number of rows written per table.
    """
    await ensure_entity_tables(session)

    written: dict[str, int] = {}
    for level in _LEVEL_ORDER:
        ids = [str(i) for i in ids_by_level.get(level) or [] if i]
        if not ids:
            continue
        table, primary_key, alias, insert_template = _LEVELS[level]
        await session.execute(
            text(f"DELETE FROM {table} WHERE {primary_key} = ANY(:ids)"), {"ids": ids}
        )
        result = await session.execute(
            text(insert_template.format(extra=f" AND {alias}meta_id = ANY(:ids)")),
            {"ids": ids},
        )
        written[table] = result.rowcount
        # Committed per level so the next level's name join reads the rows
        # this one just wrote.
        await session.commit()

    if written:
        logger.info("meta_entities_refreshed_for_ids", **written)
    return written
