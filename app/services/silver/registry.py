"""Registry of known Bronze -> Silver flatten jobs.

Each entry names a *known* raw table this project actually builds a
flatten table from today — this is deliberately not "flatten any table
the user points at," since that requires column-mapping knowledge only a
human (or a lot more inference) has. Adding a new source (e.g. Shopify,
once it has a flatten target) means adding one entry here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.gold.ad_performance import refresh_ad_performance_summary
from app.services.gold.cpis import refresh_cpis_by_sku
from app.services.gold.cpis_utm import refresh_cpis_by_sku_utm
from app.services.gold.landing_page import refresh_landing_page_tables
from app.services.meta.entity_flatten import refresh_entity_tables
from app.services.silver.ad_lifecycle import refresh_ad_lifecycle
from app.services.silver.insights_flatten import refresh_insights_tables
from app.services.silver.instagram_flatten import refresh_insta_data
from app.services.silver.shopify_ad_attribution import refresh_attribution_tables
from app.services.silver.shopify_flatten import refresh_shopify_tables


@dataclass(frozen=True)
class FlattenJob:
    key: str
    label: str
    source_table: str
    target_tables: tuple[str, ...]
    refresh: Callable[[AsyncSession], Awaitable[dict[str, int]]]


FLATTEN_REGISTRY: dict[str, FlattenJob] = {
    "meta_entities": FlattenJob(
        key="meta_entities",
        label="Meta campaigns / adsets / ads",
        source_table="raw_dump_meta",
        target_tables=("meta_campaigns", "meta_adsets", "meta_ads"),
        refresh=refresh_entity_tables,
    ),
    "insta_data": FlattenJob(
        key="insta_data",
        label="Instagram media / account",
        source_table="dump_instagram",
        target_tables=("insta_data",),
        refresh=refresh_insta_data,
    ),
    "meta_insights": FlattenJob(
        key="meta_insights",
        label="Meta campaign / adset / ad Insights",
        source_table="raw_dump_meta",
        target_tables=("campaign_insights", "adset_insights", "ad_insights"),
        refresh=refresh_insights_tables,
    ),
    "ad_lifecycle": FlattenJob(
        key="ad_lifecycle",
        label="Ad performance + Winner/Loser category (ae_raw_view/summary_table equivalent)",
        # ad_insights is the primary driver (performance metrics change far more
        # often than ad_status) -- staleness checking only watches this one source,
        # so a meta_ads-only change (e.g. an ad getting paused) won't mark this job
        # stale on its own. Known simplification: FlattenJob only supports one
        # source_table today.
        source_table="ad_insights",
        target_tables=("ad_lifecycle",),
        refresh=refresh_ad_lifecycle,
    ),
    "shopify_data": FlattenJob(
        key="shopify_data",
        label="Shopify orders / customers / sessions",
        source_table="raw_dump_shopify",
        target_tables=(
            "shopify_orders", "shopify_customers", "shopify_sessions", "shopify_fulfillments",
            "shopify_customer_analytics", "shopify_sales", "shopify_discounts", "shopify_inventory",
        ),
        refresh=refresh_shopify_tables,
    ),
    "shopify_ad_attribution": FlattenJob(
        key="shopify_ad_attribution",
        label="Shopify order attribution + landing page analysis (mapped to Meta ads)",
        # Depends on shopify_orders/shopify_sessions (Silver, not Bronze) --
        # same "source_table is itself a Silver table" pattern as
        # ad_lifecycle's source_table="ad_insights". Known simplification:
        # FlattenJob only supports one source_table, so staleness checking
        # only watches shopify_orders -- a shopify_sessions-only update
        # (sessions refreshed, orders untouched) won't mark this stale on
        # its own. Same simplification ad_lifecycle already accepts.
        source_table="shopify_orders",
        target_tables=("shopify_order_attribution", "shopify_landing_page_analysis"),
        refresh=refresh_attribution_tables,
    ),
    "ad_performance_summary": FlattenJob(
        key="ad_performance_summary",
        label="Gold: Ad performance summary (Meta metrics + Shopify-attributed revenue, per ad)",
        # Depends on ad_lifecycle AND shopify_order_attribution (both Silver) --
        # same one-source_table simplification as shopify_ad_attribution's own
        # entry above. ad_lifecycle is the primary driver since every ad has a
        # lifecycle row but not every ad has Shopify-attributed orders.
        source_table="ad_lifecycle",
        target_tables=("ad_performance_summary",),
        refresh=refresh_ad_performance_summary,
    ),
    "landing_page_gold": FlattenJob(
        key="landing_page_gold",
        label="Gold: Landing-page performance (legacy landing_page_analysis_30d/ad_breakdown_30d/sessions_daily, ported from live legacy DB)",
        # Depends on shopify_sessions (Silver), ad_performance_summary (Gold),
        # raw_dump_meta ad-creative rows (Bronze), and shopify_order_attribution
        # (Silver) -- shopify_sessions picked as the primary driver since it's
        # the highest-frequency-changing of the four. Same one-source_table
        # simplification as every other multi-source job in this registry.
        source_table="shopify_sessions",
        target_tables=(
            "landing_page_sessions_daily", "landing_page_analysis_30d", "landing_page_ad_breakdown_30d",
        ),
        refresh=refresh_landing_page_tables,
    ),
    "cpis_by_sku": FlattenJob(
        key="cpis_by_sku",
        label="Gold: CPIS by master SKU (cost per NCP / cost per item sold, 1d/7d/30d windows)",
        # Depends on shopify_inventory (daily per-SKU units, the real
        # window source) and ad_lifecycle (spend/ncp, lifetime-only --
        # see cpis.py's module docstring). shopify_inventory picked as the
        # primary driver since its daily grain is what actually makes the
        # window recompute meaningfully.
        source_table="shopify_inventory",
        target_tables=("cpis_by_sku",),
        refresh=refresh_cpis_by_sku,
    ),
    "cpis_by_sku_utm": FlattenJob(
        key="cpis_by_sku_utm",
        label="Gold: CPIS by master SKU via UTM attribution (order.utm_content -> ad_id, line_items.sku, 7d/30d/90d)",
        source_table="shopify_orders",
        target_tables=("cpis_by_sku_utm",),
        refresh=refresh_cpis_by_sku_utm,
    ),
}


def jobs_for_table(table_name: str) -> list[FlattenJob]:
    """Every job where `table_name` is either the source or one of the targets --
    used by the Schema Browser to decide which Flatten panel(s) to show for whatever
    table is open. A source table (e.g. raw_dump_meta) can back more than one job."""
    return [job for job in FLATTEN_REGISTRY.values() if table_name == job.source_table or table_name in job.target_tables]
