"""Gold layer: per-ad performance summary -- this project's first Gold
table, and the direct fill for the gap `ad_lifecycle.py`'s own docstring
flagged ("Shopify enrichment... no Shopify Silver layer exists yet"). That
gap is closed now: `shopify_order_attribution` (Silver) pins a subset of
Shopify orders to a `matched_ad_id`. This table joins that onto
`ad_lifecycle` (Silver) so a dashboard can read Meta-reported performance
and real Shopify revenue for the same ad in one row, without recomputing
either upstream table's business logic here -- matches this project's
Gold design principle (Context.md): "pre-aggregated for specific dashboard
queries... every RPC/read the frontend needs should be a thin wrapper over
a gold table."

Deliberately curated, not `ad_lifecycle`'s full ~190-column wide table --
Gold is meant to be dashboard-shaped, not "everything about this ad."
Coverage caveat carried forward from `shopify_ad_attribution.py`: only
orders that resolved to tier IN ('ad_direct', 'ad_name_match') carry a
`matched_ad_id` (campaign_match/unmatched orders don't roll up to a
specific ad here) -- so `shopify_orders`/`shopify_revenue` are a real but
partial slice of an ad's actual Shopify-attributed sales, same caveat that
already applies to `shopify_order_attribution` itself.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

_COLUMNS: list[tuple[str, str]] = [
    ("ad_id", "text"),
    ("ad_name", "text"),
    ("ad_status", "text"),
    ("ad_effective_status", "text"),
    ("adset_id", "text"),
    ("adset_name", "text"),
    ("campaign_id", "text"),
    ("campaign_name", "text"),
    ("account_id", "text"),
    ("account_name", "text"),
    ("category", "text"),
    ("f1_pass", "boolean"),
    ("f2_pass", "boolean"),
    ("f3_pass", "boolean"),
    ("f4_pass", "boolean"),
    ("spend", "numeric"),
    ("impressions", "numeric"),
    ("purchases", "numeric"),
    ("meta_conv_value", "numeric"),
    ("meta_roas", "numeric"),
    ("cost_per_purchase", "numeric"),
    ("ctr_pct", "numeric"),
    ("shopify_orders", "numeric"),
    ("shopify_revenue", "numeric"),
    ("shopify_aov", "numeric"),
    ("shopify_roas", "numeric"),
    ("cost_per_shopify_order", "numeric"),
    ("gold_refreshed_at", "timestamptz"),
]

COLUMN_FORMULAS: dict[str, str] = {
    "ad_status": "ad_lifecycle.ad_status (passthrough)",
    "ad_effective_status": "ad_lifecycle.ad_effective_status (passthrough)",
    "category": "ad_lifecycle.category (passthrough -- Winner/Incremental Winner/P0-P2 analysis/Discarded/Result Awaited)",
    "spend": "ad_lifecycle.spend (passthrough)",
    "meta_conv_value": "ad_lifecycle.conv_value (Meta-pixel-reported conversion value)",
    "meta_roas": "ad_lifecycle.roas (meta_conv_value / spend, as Meta's own pixel reports it)",
    "shopify_orders": "COUNT(shopify_order_attribution rows) WHERE matched_ad_id = this ad -- tier IN ('ad_direct','ad_name_match') only",
    "shopify_revenue": "SUM(shopify_order_attribution.total_price) WHERE matched_ad_id = this ad",
    "shopify_aov": "shopify_revenue / shopify_orders",
    "shopify_roas": "shopify_revenue / spend -- the real-order-backed ROAS, contrast against meta_roas's pixel-reported figure",
    "cost_per_shopify_order": "spend / shopify_orders",
    "gold_refreshed_at": "now() at the time this row was last (re)computed",
}


def _ddl_statements() -> list[str]:
    cols = [f"{name} {sql_type}" for name, sql_type in _COLUMNS]
    cols[0] = cols[0] + " PRIMARY KEY"  # ad_id
    return [
        "CREATE TABLE IF NOT EXISTS ad_performance_summary (\n  " + ",\n  ".join(cols) + "\n)",
        "CREATE INDEX IF NOT EXISTS ix_ad_performance_summary_account_name ON ad_performance_summary (account_name)",
        "CREATE INDEX IF NOT EXISTS ix_ad_performance_summary_campaign_id ON ad_performance_summary (campaign_id)",
        "CREATE INDEX IF NOT EXISTS ix_ad_performance_summary_category ON ad_performance_summary (category)",
    ]


_TRUNCATE = "TRUNCATE ad_performance_summary"

_INSERT_TARGET_COLUMNS = ", ".join(name for name, _ in _COLUMNS)

_INSERT_TEMPLATE = f"""
INSERT INTO ad_performance_summary ({_INSERT_TARGET_COLUMNS})
SELECT
    al.ad_id,
    al.ad_name,
    al.ad_status,
    al.ad_effective_status,
    al.adset_id,
    al.adset_name,
    al.campaign_id,
    al.campaign_name,
    al.account_id,
    al.account_name,
    al.category,
    al.f1_pass,
    al.f2_pass,
    al.f3_pass,
    al.f4_pass,
    al.spend,
    al.impressions,
    al.purchases,
    al.conv_value AS meta_conv_value,
    al.roas AS meta_roas,
    al.cost_per_purchase,
    al.ctr_pct,
    -- Shopify figures prefer public.ad_metrics_external where it has
    -- them, and fall back to this project's own attribution otherwise.
    --
    -- Not a preference for its own sake: this project's shopify_orders
    -- silver holds 2026 only (2025 = 50 orders against 429,669), so its
    -- attributed revenue was 184.4M against the reference system's
    -- 444.0M -- 42%. Overlaying the Meta side alone would have made
    -- things WORSE, not better: meta_shop_diff_pct is
    -- (shopify_revenue - conv_value) / conv_value, so lifting
    -- conv_value while leaving shopify_revenue at 42% swings the ratio
    -- sharply negative, and shopify_roas (revenue / spend) roughly
    -- halves. Both sides move together or neither does.
    COALESCE(ext.shopify_orders, soa.shopify_orders, 0) AS shopify_orders,
    COALESCE(ext.shopify_revenue, soa.shopify_revenue, 0) AS shopify_revenue,
    COALESCE(
        ext.shopify_aov,
        CASE WHEN COALESCE(soa.shopify_orders, 0) > 0
             THEN soa.shopify_revenue / soa.shopify_orders END
    ) AS shopify_aov,
    COALESCE(
        ext.shopify_roas,
        CASE WHEN al.spend > 0 THEN COALESCE(soa.shopify_revenue, 0) / al.spend END
    ) AS shopify_roas,
    -- Derived from whichever pair actually won above, so it can never
    -- divide an overlaid numerator by a local denominator.
    CASE WHEN COALESCE(ext.shopify_orders, soa.shopify_orders, 0) > 0
         THEN al.spend / COALESCE(ext.shopify_orders, soa.shopify_orders)
         END AS cost_per_shopify_order,
    now() AS gold_refreshed_at
FROM ad_lifecycle al
LEFT JOIN (
    SELECT matched_ad_id AS ad_id, COUNT(*) AS shopify_orders, SUM(total_price) AS shopify_revenue
    FROM shopify_order_attribution
    WHERE matched_ad_id IS NOT NULL
    GROUP BY matched_ad_id
) soa ON soa.ad_id = al.ad_id
LEFT JOIN public.ad_metrics_external ext ON ext.ad_id = al.ad_id
"""


#: public.ad_metrics_external is created by
#: scripts/sync_ad_metrics_external.py and is absent on an install that
#: has no source configured. Rather than duplicate that script's DDL
#: here -- two definitions of one table is how columns drift -- the join
#: is simply removed when the table is not there, and every Shopify
#: figure falls back to this project's own attribution.
_EXTERNAL_JOIN = "LEFT JOIN public.ad_metrics_external ext ON ext.ad_id = al.ad_id"

#: With the mirror present: ext wins, local fills the gaps.
_INSERT_WITH_EXTERNAL = _INSERT_TEMPLATE

#: Without it: `ext.x` would not resolve, so every reference collapses to
#: the local branch of its own COALESCE. NULL::numeric keeps each
#: expression's shape and type identical to the overlaid form.
_INSERT_LOCAL_ONLY = (
    _INSERT_TEMPLATE
    .replace(_EXTERNAL_JOIN, "")
    .replace("ext.shopify_orders", "NULL::numeric")
    .replace("ext.shopify_revenue", "NULL::numeric")
    .replace("ext.shopify_aov", "NULL::numeric")
    .replace("ext.shopify_roas", "NULL::numeric")
)

_EXTERNAL_TABLE_EXISTS = """
SELECT 1 FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'ad_metrics_external'
"""


async def ensure_ad_performance_summary_table(session: AsyncSession) -> None:
    for statement in _ddl_statements():
        await session.execute(text(statement))
    await session.commit()


async def refresh_ad_performance_summary(session: AsyncSession) -> dict[str, int]:
    await ensure_ad_performance_summary_table(session)
    await session.execute(text(_TRUNCATE))
    has_external = (
        await session.execute(text(_EXTERNAL_TABLE_EXISTS))
    ).scalar_one_or_none() is not None
    await session.execute(text(_INSERT_WITH_EXTERNAL if has_external else _INSERT_LOCAL_ONLY))
    await session.commit()

    result = await session.execute(text("SELECT COUNT(*) FROM ad_performance_summary"))
    count = result.scalar_one()
    logger.info("ad_performance_summary_refreshed", ad_performance_summary=count)
    return {"ad_performance_summary": count}
