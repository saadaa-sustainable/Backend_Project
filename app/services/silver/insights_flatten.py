"""Silver-layer flatten step for Meta Insights (performance data) --
ad_insights / adset_insights / campaign_insights, one row per entity.

Sources from raw_dump_meta WHERE object_type='insights', filtered further
by parent_ids->>'level'. Column coverage matches the full ~169-field
Insights registry (app.core.meta_registry.ALL_INSIGHTS_FIELDS) rather than
just whatever fields a given account/date-range happens to populate --
confirmed live 2026-08-21 that a field being absent from one response
doesn't mean it's invalid, just that nothing matched it for that entity/
window (e.g. no video creative -> no video_* fields in the payload).

Types come from a live scan across real Insights rows (both a dedicated
test fetch and the existing production data), not guessed -- FIELD_TYPES
below. The ~66 registry fields never observed in any real row yet default
to jsonb (never fails a cast; re-type to numeric/text once real data shows
up for them). Nested "actions"-shaped fields (actions, action_values,
conversions, cost_per_*, video_*_watched_actions, purchase_roas, etc.) stay
jsonb regardless -- they're genuinely arrays of {action_type, value, ...}
breakdowns, not flat scalars, matching this project's convention elsewhere
(meta_ads/meta_adsets/meta_campaigns keep nested Meta objects as JSONB too).

IMPORTANT caveat this table does NOT resolve: Meta Insights rows are
date-range facts, not a single "current state" the way an entity is.
DISTINCT ON (meta_id) ORDER BY extracted_at DESC below picks each entity's
MOST RECENTLY FETCHED sync -- if two syncs used different date windows
(e.g. one pulled last_7d, another pulled last_30d), this table reflects
whichever happened to run last, not a consistent reporting window across
every row. Fine for "what does this entity look like as of the latest
sync" -- not a substitute for a proper per-day time series if that's ever
needed (a structurally different table, out of scope here).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

FIELD_TYPES: dict[str, str] = {
    "account_currency": "text",
    "account_id": "text",
    "account_name": "text",
    "action_values": "jsonb",
    "actions": "jsonb",
    "ad_click_actions": "jsonb",
    "ad_id": "text",
    "ad_impression_actions": "jsonb",
    "ad_name": "text",
    "adset_end": "jsonb",
    "adset_id": "text",
    "adset_name": "text",
    "adset_start": "jsonb",
    "anchor_event_attribution_setting": "text",
    "anchor_events_performance_indicator": "jsonb",
    "attribution_setting": "text",
    "auction_bid": "jsonb",
    "auction_competitiveness": "jsonb",
    "auction_max_competitor_bid": "jsonb",
    "buying_type": "text",
    "campaign_id": "text",
    "campaign_name": "text",
    "canvas_avg_view_percent": "numeric",
    "canvas_avg_view_time": "numeric",
    "catalog_segment_actions": "jsonb",
    "catalog_segment_value": "jsonb",
    "catalog_segment_value_mobile_purchase_roas": "jsonb",
    "catalog_segment_value_omni_purchase_roas": "jsonb",
    "catalog_segment_value_website_purchase_roas": "jsonb",
    "clicks": "numeric",
    "conversion_lead_rate": "jsonb",
    "conversion_rate_ranking": "text",
    "conversion_values": "jsonb",
    "conversions": "jsonb",
    "converted_product_app_custom_event_fb_mobile_purchase": "jsonb",
    "converted_product_app_custom_event_fb_mobile_purchase_value": "jsonb",
    "converted_product_offline_purchase": "jsonb",
    "converted_product_offline_purchase_value": "jsonb",
    "converted_product_omni_purchase": "jsonb",
    "converted_product_omni_purchase_values": "jsonb",
    "converted_product_quantity": "jsonb",
    "converted_product_value": "jsonb",
    "converted_product_website_pixel_purchase": "jsonb",
    "converted_product_website_pixel_purchase_value": "jsonb",
    "converted_promoted_product_app_custom_event_fb_mobile_purchase": "jsonb",
    "converted_promoted_product_app_custom_event_fb_mobile_purchase_value": "jsonb",
    "converted_promoted_product_offline_purchase": "jsonb",
    "converted_promoted_product_offline_purchase_value": "jsonb",
    "converted_promoted_product_omni_purchase": "jsonb",
    "converted_promoted_product_omni_purchase_values": "jsonb",
    "converted_promoted_product_quantity": "jsonb",
    "converted_promoted_product_value": "jsonb",
    "converted_promoted_product_website_pixel_purchase": "jsonb",
    "converted_promoted_product_website_pixel_purchase_value": "jsonb",
    "cost_per_15_sec_video_view": "jsonb",
    "cost_per_2_sec_continuous_video_view": "jsonb",
    "cost_per_action_type": "jsonb",
    "cost_per_ad_click": "jsonb",
    "cost_per_conversion": "jsonb",
    "cost_per_conversion_lead": "jsonb",
    "cost_per_dda_countby_convs": "jsonb",
    "cost_per_estimated_ad_recallers": "jsonb",
    "cost_per_inline_link_click": "numeric",
    "cost_per_inline_post_engagement": "numeric",
    "cost_per_objective_result": "jsonb",
    "cost_per_one_thousand_ad_impression": "jsonb",
    "cost_per_outbound_click": "jsonb",
    "cost_per_result": "jsonb",
    "cost_per_thruplay": "jsonb",
    "cost_per_unique_action_type": "jsonb",
    "cost_per_unique_click": "numeric",
    "cost_per_unique_conversion": "jsonb",
    "cost_per_unique_inline_link_click": "numeric",
    "cost_per_unique_outbound_click": "jsonb",
    "cpc": "numeric",
    "cpm": "numeric",
    "cpp": "numeric",
    "created_time": "timestamptz",
    "creative_diversity_data": "jsonb",
    "creative_diversity_label": "text",
    "creative_diversity_score": "text",
    "creative_fatigue_summary": "jsonb",
    "creative_fatigued_ads": "jsonb",
    "ctr": "numeric",
    "date_start": "date",
    "date_stop": "date",
    "dda_countby_convs": "jsonb",
    "dda_results": "jsonb",
    "engagement_rate_ranking": "text",
    "estimated_ad_recall_rate": "jsonb",
    "estimated_ad_recallers": "jsonb",
    "frequency": "numeric",
    "full_view_impressions": "numeric",
    "full_view_reach": "numeric",
    "impressions": "numeric",
    "inline_link_click_ctr": "numeric",
    "inline_link_clicks": "numeric",
    "inline_post_engagement": "numeric",
    "instagram_upcoming_event_reminders_set": "numeric",
    "instant_experience_clicks_to_open": "jsonb",
    "instant_experience_clicks_to_start": "jsonb",
    "instant_experience_outbound_clicks": "jsonb",
    "interactive_component_tap": "jsonb",
    "landing_page_view_per_link_click": "numeric",
    "marketing_messages_cost_per_delivered": "numeric",
    "marketing_messages_cost_per_link_btn_click": "numeric",
    "marketing_messages_delivered": "numeric",
    "marketing_messages_delivery_rate": "numeric",
    "marketing_messages_link_btn_click": "numeric",
    "marketing_messages_media_view_rate": "jsonb",
    "marketing_messages_phone_call_btn_click_rate": "jsonb",
    "marketing_messages_quick_reply_btn_click_rate": "numeric",
    "marketing_messages_read": "numeric",
    "marketing_messages_read_rate": "numeric",
    "marketing_messages_read_rate_benchmark": "numeric",
    "marketing_messages_sent": "numeric",
    "marketing_messages_spend": "numeric",
    "mobile_app_purchase_roas": "jsonb",
    "multi_event_conversion_attribution_setting": "text",
    "objective": "text",
    "objective_result_rate": "jsonb",
    "objective_results": "jsonb",
    "optimization_goal": "text",
    "outbound_clicks": "jsonb",
    "outbound_clicks_ctr": "jsonb",
    "page_engagement": "jsonb",
    "post_engagement": "jsonb",
    "product_group_retailer_id": "jsonb",
    "product_retailer_id": "jsonb",
    "product_views": "jsonb",
    "purchase_per_landing_page_view": "numeric",
    "purchase_roas": "jsonb",
    "qualifying_question_qualify_answer_rate": "jsonb",
    "quality_ranking": "text",
    "reach": "numeric",
    "result_rate": "jsonb",
    "result_values_performance_indicator": "text",
    "results": "jsonb",
    "shops_assisted_purchases": "numeric",
    "social_spend": "numeric",
    "spend": "numeric",
    "unique_actions": "jsonb",
    "unique_clicks": "numeric",
    "unique_ctr": "numeric",
    "unique_inline_link_click_ctr": "numeric",
    "unique_inline_link_clicks": "numeric",
    "unique_link_clicks_ctr": "numeric",
    "unique_outbound_clicks": "jsonb",
    "unique_outbound_clicks_ctr": "jsonb",
    "updated_time": "timestamptz",
    "video_30_sec_watched_actions": "jsonb",
    "video_6_sec_watched_actions": "jsonb",
    "video_avg_time_watched_actions": "jsonb",
    "video_continuous_2_sec_watched_actions": "jsonb",
    "video_p100_watched_actions": "jsonb",
    "video_p25_watched_actions": "jsonb",
    "video_p50_watched_actions": "jsonb",
    "video_p75_watched_actions": "jsonb",
    "video_p95_watched_actions": "jsonb",
    "video_play_actions": "jsonb",
    "video_play_curve_actions": "jsonb",
    "video_play_retention_0_to_15s_actions": "jsonb",
    "video_play_retention_20_to_60s_actions": "jsonb",
    "video_play_retention_graph_actions": "jsonb",
    "video_thruplay_watched_actions": "jsonb",
    "video_time_watched_actions": "jsonb",
    "website_ctr": "jsonb",
    "website_purchase_roas": "jsonb",
    "wish_bid": "numeric",
}

ENVELOPE_BY_LEVEL: dict[str, list[str]] = {
    "ad": ["ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name", "account_id", "account_name"],
    "adset": ["adset_id", "adset_name", "campaign_id", "campaign_name", "account_id", "account_name"],
    "campaign": ["campaign_id", "campaign_name", "account_id", "account_name"],
}
PK_BY_LEVEL: dict[str, str] = {"ad": "ad_id", "adset": "adset_id", "campaign": "campaign_id"}
TARGET_TABLE_BY_LEVEL: dict[str, str] = {"ad": "ad_insights", "adset": "adset_insights", "campaign": "campaign_insights"}

_ENVELOPE_NAMES = {"account_id", "account_name", "ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name"}
_METRIC_FIELDS = ["date_start", "date_stop"] + sorted(set(FIELD_TYPES) - _ENVELOPE_NAMES - {"date_start", "date_stop"})


def _cast_expr(field: str, sql_type: str, *, prefix: str = "") -> str:
    col = f"{prefix}raw_payload ->> '{field}'"
    if sql_type == "numeric":
        return f"NULLIF({col}, '')::numeric AS {field}"
    if sql_type in ("timestamptz", "date"):
        return f"NULLIF({col}, '')::{sql_type} AS {field}"
    if sql_type == "boolean":
        return f"({col})::boolean AS {field}"
    if sql_type == "jsonb":
        return f"({prefix}raw_payload -> '{field}') AS {field}"
    return f"{col} AS {field}"


def _ddl_statements(level: str) -> list[str]:
    envelope = ENVELOPE_BY_LEVEL[level]
    pk = PK_BY_LEVEL[level]
    target = TARGET_TABLE_BY_LEVEL[level]
    metric_fields = [f for f in _METRIC_FIELDS if f not in envelope]

    cols = [f"{pk} text PRIMARY KEY"]
    cols += [f"{c} text" for c in envelope if c != pk]
    cols += [f"{f} {FIELD_TYPES.get(f, 'jsonb')}" for f in metric_fields]
    cols += ["extracted_at timestamptz", "updated_at timestamptz"]

    statements = [f"CREATE TABLE IF NOT EXISTS {target} (\n  " + ",\n  ".join(cols) + "\n)"]
    statements.append(f"CREATE INDEX IF NOT EXISTS ix_{target}_account_name ON {target} (account_name)")
    if level != "campaign":
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{target}_campaign_id ON {target} (campaign_id)")
    if level == "ad":
        statements.append(f"CREATE INDEX IF NOT EXISTS ix_{target}_adset_id ON {target} (adset_id)")
    return statements


def _insert_sql(level: str) -> str:
    envelope = ENVELOPE_BY_LEVEL[level]
    pk = PK_BY_LEVEL[level]
    target = TARGET_TABLE_BY_LEVEL[level]
    metric_fields = [f for f in _METRIC_FIELDS if f not in envelope]

    select_cols = [f"a.meta_id AS {pk}"]
    select_cols += [f"a.raw_payload ->> '{c}' AS {c}" for c in envelope if c != pk]
    select_cols += [_cast_expr(f, FIELD_TYPES.get(f, "jsonb"), prefix="a.") for f in metric_fields]
    select_cols += ["a.extracted_at", "a.extracted_at AS updated_at"]

    # Two-stage instead of a plain `DISTINCT ON (meta_id) ... ORDER BY
    # meta_id, extracted_at DESC` over the raw scan: that form forces
    # Postgres to evaluate every one of this level's ~170 JSONB field
    # extractions for EVERY matching row (not just the surviving latest-per-
    # entity one) before it can dedup, since DISTINCT ON needs the full
    # target list already projected to compare/discard adjacent rows.
    # `latest` below touches only meta_id/extracted_at (both plain columns,
    # covered by the partial index in ensure_insights_tables) to find the
    # winning row per entity first, so the expensive JSONB projection only
    # ever runs for the rows that actually survive into the target table --
    # confirmed live 2026-08-25 this was required, not just an index, once
    # raw_dump_meta passed ~300K insights rows (the DISTINCT ON form alone
    # still blew the 2-minute statement_timeout at the ad level).
    return (
        "WITH latest AS (\n"
        "  SELECT meta_id, MAX(extracted_at) AS extracted_at\n"
        "  FROM raw_dump_meta\n"
        "  WHERE object_type = 'insights' AND parent_ids ->> 'level' = :level\n"
        "  GROUP BY meta_id\n"
        ")\n"
        f"INSERT INTO {target}\n"
        f"SELECT\n  " + ",\n  ".join(select_cols) + "\n"
        "FROM raw_dump_meta a\n"
        "JOIN latest ON latest.meta_id = a.meta_id AND latest.extracted_at = a.extracted_at\n"
        "WHERE a.object_type = 'insights' AND a.parent_ids ->> 'level' = :level"
    )


# Supports the WHERE/ORDER BY in _insert_sql() below -- without it, every
# level's INSERT has to filter raw_dump_meta's full insights set (300K+ rows
# and growing) by the unindexed `parent_ids ->> 'level'` expression, then
# sort for DISTINCT ON, which blew the pooler's 2-minute statement_timeout
# once raw_dump_meta reached ~314K insights rows (confirmed live 2026-08-25 --
# every level failed identically, not just the largest one, since the scan
# cost is paid before level-specific result size matters).
_BRONZE_INSIGHTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_insights_level_meta_extracted "
    "ON raw_dump_meta ((parent_ids ->> 'level'), meta_id, extracted_at DESC) "
    "WHERE object_type = 'insights'"
)


async def ensure_insights_tables(session: AsyncSession) -> None:
    await session.execute(text(_BRONZE_INSIGHTS_INDEX))
    await session.commit()
    for level in ("campaign", "adset", "ad"):
        for statement in _ddl_statements(level):
            await session.execute(text(statement))
    await session.commit()


async def refresh_insights_tables(session: AsyncSession) -> dict[str, int]:
    """Rebuild ad_insights/adset_insights/campaign_insights from the latest
    raw_dump_meta insights snapshot of each entity. No cross-level dependency
    (unlike entity_flatten.py, Insights rows already carry denormalized
    campaign_name/account_name etc. from Meta directly -- no join needed),
    so order between levels doesn't matter here."""
    await ensure_insights_tables(session)

    counts: dict[str, int] = {}
    for level in ("campaign", "adset", "ad"):
        target = TARGET_TABLE_BY_LEVEL[level]
        await session.execute(text(f"TRUNCATE {target}"))
        await session.execute(text(_insert_sql(level)), {"level": level})
        await session.commit()
        result = await session.execute(text(f"SELECT COUNT(*) FROM {target}"))
        counts[target] = result.scalar_one()

    logger.info("meta_insights_tables_refreshed", **counts)
    return counts
