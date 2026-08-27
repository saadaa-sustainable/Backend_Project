"""Configurable registries of Meta Marketing API fields, breakdowns,
attribution windows, date presets, and object-level field sets.

This module is the single source of truth for "what do we ask Meta for."
Ingestion services never hardcode field lists inline — they read from the
registries here. Adding a newly released metric/breakdown/field is a
one-line change to a list in this file; no service logic changes.

References: Meta Marketing API "Insights" and per-object field references
(Graph API v21.0+).
"""

from __future__ import annotations

from enum import StrEnum


# ==========================================================================
# Insights: levels, date presets, time increments
# ==========================================================================


class InsightsLevel(StrEnum):
    ACCOUNT = "account"
    CAMPAIGN = "campaign"
    ADSET = "adset"
    AD = "ad"


class DatePreset(StrEnum):
    """All ``date_preset`` values accepted by the Insights endpoint, per
    Meta's Ad Campaign Group Insights "Reading" reference
    (developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/insights/)."""

    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    THIS_QUARTER = "this_quarter"
    LAST_3D = "last_3d"
    LAST_7D = "last_7d"
    LAST_14D = "last_14d"
    LAST_28D = "last_28d"
    LAST_30D = "last_30d"
    LAST_90D = "last_90d"
    LAST_WEEK_MON_SUN = "last_week_mon_sun"
    LAST_WEEK_SUN_SAT = "last_week_sun_sat"
    LAST_QUARTER = "last_quarter"
    LAST_YEAR = "last_year"
    THIS_YEAR = "this_year"
    THIS_WEEK_MON_TODAY = "this_week_mon_today"
    THIS_WEEK_SUN_TODAY = "this_week_sun_today"
    MAXIMUM = "maximum"  # entire available history
    DATA_MAXIMUM = "data_maximum"  # entire history Meta has data for, which
    # can differ from `maximum` (the account's own reporting-availability window)


class TimeIncrement(StrEnum):
    """The two non-numeric ``time_increment`` values. ``ALL_DAYS`` aggregates
    the whole range into a single row; ``MONTHLY`` buckets by calendar
    month. Meta additionally accepts any **integer 1-90** (days per bucket)
    directly in the request — that's not representable as a fixed enum
    member, so callers pass a plain ``int`` instead of this enum for that
    case; see :func:`resolve_time_increment`, which every request builder
    goes through."""

    ALL_DAYS = "all_days"
    MONTHLY = "monthly"
    #: Convenience aliases for the two integer values used most often
    #: elsewhere in this codebase — still just "an int 1-90" to Meta.
    DAILY = "1"
    WEEKLY = "7"


#: Bounds Meta documents for the integer form of `time_increment`.
TIME_INCREMENT_MIN_DAYS = 1
TIME_INCREMENT_MAX_DAYS = 90


def resolve_time_increment(value: "TimeIncrement | int | str") -> str:
    """Normalize a ``time_increment`` value to the exact string Meta
    expects, validating the integer-days form's documented 1-90 range."""
    if isinstance(value, TimeIncrement):
        return value.value
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        raise ValueError(f"Invalid time_increment: {value!r}")
    if isinstance(value, int):
        if not (TIME_INCREMENT_MIN_DAYS <= value <= TIME_INCREMENT_MAX_DAYS):
            raise ValueError(
                f"time_increment integer must be between {TIME_INCREMENT_MIN_DAYS} and "
                f"{TIME_INCREMENT_MAX_DAYS} days, got {value}."
            )
        return str(value)
    if isinstance(value, str):
        if value in ("all_days", "monthly"):
            return value
        try:
            return resolve_time_increment(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid time_increment: {value!r}") from exc
    raise ValueError(f"Invalid time_increment: {value!r}")


class ActionReportTime(StrEnum):
    """``action_report_time`` — when an action is counted against a date
    bucket: at impression time, at conversion time, Meta's blended
    ``mixed`` (impression-time for paid actions, conversion-time for
    organic), or ``lifetime`` (report time equals the report's own
    date range regardless of when the impression/conversion happened)."""

    IMPRESSION = "impression"
    CONVERSION = "conversion"
    MIXED = "mixed"
    LIFETIME = "lifetime"


class FilterOperator(StrEnum):
    """Every operator accepted by the Insights ``filtering`` parameter, per
    Meta's Ad Campaign Group Insights "Reading" reference."""

    EQUAL = "EQUAL"
    NOT_EQUAL = "NOT_EQUAL"
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    IN_RANGE = "IN_RANGE"
    NOT_IN_RANGE = "NOT_IN_RANGE"
    CONTAIN = "CONTAIN"
    NOT_CONTAIN = "NOT_CONTAIN"
    CONTAINS_ANY = "CONTAINS_ANY"
    CONTAINS_ALL = "CONTAINS_ALL"
    NOT_CONTAINS_ANY = "NOT_CONTAINS_ANY"
    STEM_MATCH = "STEM_MATCH"
    IN = "IN"
    NOT_IN = "NOT_IN"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"
    ANY = "ANY"
    ALL = "ALL"
    NONE = "NONE"
    AFTER = "AFTER"
    BEFORE = "BEFORE"
    ON_OR_AFTER = "ON_OR_AFTER"
    ON_OR_BEFORE = "ON_OR_BEFORE"
    TOP = "TOP"


#: Reading-reference parameters deliberately NOT implemented, and why —
#: listed here (rather than silently omitted) for the same reason as
#: ATTRIBUTION_SENTINELS's "incrementality": a caller hitting a missing
#: feature should get an explicit, actionable reason, not silent absence.
#: ``export_columns`` / ``export_format`` / ``export_name`` drive Meta's
#: asynchronous CSV/XLS export flow (the response is a downloadable file,
#: not JSON rows) — incompatible with this service's JSON-row Bronze
#: storage model (`raw_dump_meta`). Use the standard `fields` parameter and
#: the async report-run flow (`use_async=True`) instead; both return the
#: same underlying data as structured JSON.
UNSUPPORTED_READING_PARAMS: frozenset[str] = frozenset(
    {"export_columns", "export_format", "export_name"}
)


# ==========================================================================
# Attribution windows
# ==========================================================================

#: Maps a friendly name to the literal token Meta expects in the
#: ``action_attribution_windows`` Insights request parameter.
ATTRIBUTION_WINDOWS: dict[str, str] = {
    "1d_click": "1d_click",
    "7d_click": "7d_click",
    "28d_click": "28d_click",
    "1d_view": "1d_view",
    "7d_view": "7d_view",
    "28d_view": "28d_view",
    "1d_ev": "1d_ev",  # engaged-view
    "7d_view_first_conversion": "7d_view_first_conversion",
    "28d_view_first_conversion": "28d_view_first_conversion",
    "7d_view_all_conversions": "7d_view_all_conversions",
    "28d_view_all_conversions": "28d_view_all_conversions",
    "skan_click": "skan_click",
    "skan_view": "skan_view",
    "skan_click_second_postback": "skan_click_second_postback",
    "skan_view_second_postback": "skan_view_second_postback",
    "skan_click_third_postback": "skan_click_third_postback",
    "skan_view_third_postback": "skan_view_third_postback",
    #: The literal Meta enum value meaning "use the ad account's configured
    #: attribution setting" — distinct from the "dda" sentinel below, which
    #: achieves the same outcome by *omitting* the parameter entirely rather
    #: than sending this literal token.
    "default": "default",
}

#: Sentinel names that do NOT map to an ``action_attribution_windows`` token:
#: * "dda" (data-driven attribution) is requested by *omitting*
#:   ``action_attribution_windows`` entirely so Meta applies the ad
#:   account's configured attribution setting/model.
#: * "incrementality" is not retrievable via the Insights endpoint at all —
#:   it requires Meta's separate (invite-only) Conversion Lift / Lift Study
#:   API. It is listed here only so callers get a clear, actionable error
#:   instead of silently receiving standard (non-incremental) numbers.
ATTRIBUTION_SENTINELS: frozenset[str] = frozenset({"dda", "incrementality"})

#: Standard combinations commonly requested together; services default to
#: this set but callers can pass any subset/superset of ATTRIBUTION_WINDOWS.
DEFAULT_ATTRIBUTION_WINDOWS: list[str] = [
    "1d_click",
    "7d_click",
    "28d_click",
    "1d_view",
    "7d_view",
]


def resolve_attribution_windows(names: list[str] | None) -> list[str]:
    """Validate and resolve friendly attribution window names to the token
    list Meta expects in the ``action_attribution_windows`` request
    parameter. An empty return value means "omit the parameter" (i.e. use
    the ad account's default/DDA attribution model).
    """
    if not names:
        names = DEFAULT_ATTRIBUTION_WINDOWS

    if "incrementality" in names:
        raise ValueError(
            "'incrementality' attribution is not available through the Insights "
            "endpoint — it requires Meta's Conversion Lift (Lift Study) API, "
            "which is a separate, invite-only product. Remove it from "
            "`attribution_windows` or integrate the Lift Study API separately."
        )
    if "dda" in names:
        if len(names) > 1:
            raise ValueError(
                "'dda' (data-driven attribution / account default) cannot be "
                "combined with explicit attribution windows in the same "
                "request — request it alone to omit action_attribution_windows."
            )
        return []

    unknown = set(names) - set(ATTRIBUTION_WINDOWS)
    if unknown:
        raise ValueError(f"Unknown attribution window(s): {sorted(unknown)}")
    return [ATTRIBUTION_WINDOWS[n] for n in names]


# ==========================================================================
# Breakdowns
# ==========================================================================

#: Every breakdown value supported by the Insights endpoint, grouped by
#: category purely for documentation/UX — Meta itself only restricts which
#: breakdowns may be *combined* (see BREAKDOWN_COMBINATION_NOTES).
BREAKDOWN_GROUPS: dict[str, list[str]] = {
    "demographic": ["age", "gender"],
    "geographic": ["country", "region", "dma", "zip", "comscore_market"],
    "platform": [
        "publisher_platform",
        "platform_position",
        "placement",  # combined publisher_platform + platform_position shorthand
        "impression_device",
        "device_platform",
    ],
    "time": [
        "hourly_stats_aggregated_by_advertiser_time_zone",
        "hourly_stats_aggregated_by_audience_time_zone",
        "impression_view_time_advertiser_hour_v2",
    ],
    "product_catalog": [
        "product_id",
        "product_brand_breakdown",
        "product_category_breakdown",
        "product_custom_label_0_breakdown",
        "product_custom_label_1_breakdown",
        "product_custom_label_2_breakdown",
        "product_custom_label_3_breakdown",
        "product_custom_label_4_breakdown",
        "product_group_content_id_breakdown",
    ],
    "delivery_and_signal": [
        "frequency_value",
        "coarse_conversion_value",
        "place_page_id",
        "standard_event_content_type",
        "conversion_destination",
        "signal_source_bucket",
        "mmm",
        "overlap_segment",
        "hsid",
    ],
    "dynamic_creative": [
        "body_asset",
        "image_asset",
        "video_asset",
        "title_asset",
        "description_asset",
        "call_to_action_asset",
        "link_url_asset",
        "ad_format_asset",
        "media_type",
        "flexible_format_asset_type",
        "gen_ai_asset_type",
        "creative_automation_asset_id",
        "creative_relaxation_asset_type",
    ],
    "skan": ["skan_conversion_id", "skan_campaign_id", "skan_version"],
    "ad_extension": ["ad_extension_domain", "ad_extension_url"],
    "attribution_and_measurement": [
        "fidelity_type",
        "is_conversion_id_modeled",
        "sot_attribution_model_type",
        "sot_attribution_window",
        "sot_channel",
        "sot_event_type",
        "sot_source",
    ],
    "media_and_instagram": [
        "app_id",
        "instagram_ads_follow_type",
        "instagram_ads_instagram_media_product_type",
        "instagram_ads_time_since_creation_bucket",
        "is_auto_advance",
        "is_rendered_as_delayed_skip_ad",
        "landing_destination",
        "mdsa_landing_destination",
        "media_asset_url",
        "media_creator",
        "media_destination_url",
        "media_format",
        "media_origin_url",
        "media_text_content",
        "pa_creator_ig_handle",
        "postback_sequence_index",
        "redownload",
        "reels_trending_topic",
        "rta_ugc_topic",
        "marketing_messages_btn_name",
    ],
    "campaign_meta": [
        "internal_campaign_id",
        "breakdown_ad_objective",
        "breakdown_reporting_ad_id",
        "rule_set_id",
        "rule_set_name",
    ],
    "crm_and_persona": [
        "crm_advertiser_l12_territory_ids",
        "crm_advertiser_subvertical_id",
        "crm_advertiser_vertical_id",
        "crm_ult_advertiser_id",
        "user_persona_id",
        "user_persona_name",
    ],
}

#: The pre-refactor "action" group (``action_type``, ``action_target_id``,
#: ``action_destination``, ``action_device``) has been removed from
#: BREAKDOWN_GROUPS: Meta's official Ad Campaign Group Insights "Reading"
#: reference does not list any of these in the top-level ``breakdowns``
#: enum — they only exist as ``action_breakdowns`` values (see
#: ACTION_BREAKDOWNS below), which is a separate request parameter entirely.

ALL_BREAKDOWNS: list[str] = sorted({b for group in BREAKDOWN_GROUPS.values() for b in group})

#: Values for the ``action_breakdowns`` parameter — a separate axis from
#: ``breakdowns`` that slices the nested ``actions``/``action_values``/
#: ``cost_per_action_type`` arrays rather than splitting top-level rows.
#: Meta defaults to ``["action_type"]`` when the parameter is omitted.
ACTION_BREAKDOWNS: list[str] = [
    "action_type",
    "action_target_id",
    "action_destination",
    "action_device",
    "action_reaction",
    "action_video_type",
    "action_video_sound",
    "action_carousel_card_id",
    "action_carousel_card_name",
    "action_canvas_component_name",
    "conversion_destination",
    "matched_persona_id",
    "matched_persona_name",
    "signal_source_bucket",
    "standard_event_content_type",
    "is_business_ai_assisted",
]

DEFAULT_ACTION_BREAKDOWNS: list[str] = ["action_type"]


def resolve_action_breakdowns(names: list[str] | None) -> list[str]:
    """Validate ``action_breakdowns`` selections against the registry."""
    if not names:
        return DEFAULT_ACTION_BREAKDOWNS
    unknown = set(names) - set(ACTION_BREAKDOWNS)
    if unknown:
        raise ValueError(f"Unknown action_breakdown(s): {sorted(unknown)}")
    return names


#: "placement" is a legacy shorthand for the combination of
#: publisher_platform + platform_position and cannot be requested alongside
#: either of them in the same call. Documented here so the service layer
#: can fail fast instead of letting Meta reject the request after a round
#: trip. Extend this list if Meta introduces new mutually exclusive
#: breakdown families in future API versions.
MUTUALLY_EXCLUSIVE_BREAKDOWN_FAMILIES: list[list[str]] = [
    ["placement", "publisher_platform", "platform_position"],
]

#: Breakdowns Meta's Reading reference documents as unable to be requested
#: on their own — they must be combined with at least one other breakdown.
BREAKDOWNS_REQUIRING_COMPANION: frozenset[str] = frozenset({"impression_device"})

#: Breakdowns only meaningful/available at specific Insights `level`
#: values. Dynamic Creative asset breakdowns require ad-level, per-ad
#: creative data — Meta does not expose them at account/campaign/adset
#: aggregation.
LEVEL_RESTRICTED_BREAKDOWNS: dict[str, tuple[str, ...]] = {
    breakdown: ("ad",) for breakdown in BREAKDOWN_GROUPS["dynamic_creative"]
}

#: Metrics only meaningful (or only returned) at specific Insights `level`
#: values, per the Ads Insights reference. Requesting them at other levels
#: does not error, but returns nulls/zeroes — logged as a warning rather
#: than rejected outright, since Meta itself doesn't hard-block it.
LEVEL_RESTRICTED_METRICS: dict[str, tuple[str, ...]] = {
    "quality_ranking": ("ad",),
    "engagement_rate_ranking": ("ad",),
    "conversion_rate_ranking": ("ad",),
    "auction_bid": ("ad", "adset"),
    "auction_competitiveness": ("ad", "adset"),
    "auction_max_competitor_bid": ("ad", "adset"),
}

#: Fields that must be DROPPED from the request at a given `level` --
#: unlike LEVEL_RESTRICTED_METRICS above, these aren't a soft
#: null-at-the-wrong-level case: including them gets the WHOLE request
#: hard-rejected (confirmed live 2026-08-21, isolated per level against a
#: real account, full default field set): `interactive_component_tap`
#: fails at account level ("error_subcode": 1504041 / "Invalid
#: breakdowns", masked by a generic top-level "Service temporarily
#: unavailable" message) but succeeds combined with everything else at
#: ad/adset/campaign level. get_insights_fields_for_level() below
#: consults this so each level's actual request only ever contains
#: fields Meta will accept from it.
LEVEL_EXCLUDED_FIELDS: dict[str, frozenset[str]] = {
    "account": frozenset({"interactive_component_tap"}),
}

#: Hard, documented field/breakdown incompatibilities that Meta rejects
#: outright — checked up front so bad requests fail fast instead of
#: burning API quota on a round trip that was always going to 400.
_HOURLY_BREAKDOWNS: frozenset[str] = frozenset(
    {"hourly_stats_aggregated_by_advertiser_time_zone", "hourly_stats_aggregated_by_audience_time_zone"}
)


def validate_breakdown_combination(breakdowns: list[str]) -> None:
    """Raise ``ValueError`` if ``breakdowns`` mixes values Meta disallows
    combining in a single request."""
    unknown = set(breakdowns) - set(ALL_BREAKDOWNS)
    if unknown:
        raise ValueError(f"Unknown breakdown(s): {sorted(unknown)}")
    for family in MUTUALLY_EXCLUSIVE_BREAKDOWN_FAMILIES:
        used = [b for b in breakdowns if b in family]
        if len(used) > 1:
            raise ValueError(
                f"{used} cannot be combined in the same request; 'placement' is "
                "a shorthand for publisher_platform + platform_position — use "
                "either 'placement' alone or the two granular breakdowns."
            )
    if len(breakdowns) == 1 and breakdowns[0] in BREAKDOWNS_REQUIRING_COMPANION:
        raise ValueError(
            f"Breakdown '{breakdowns[0]}' cannot be requested by itself — Meta "
            "requires it be combined with at least one other breakdown."
        )


def validate_breakdown_level_compatibility(breakdowns: list[str], level: str) -> None:
    """Raise ``ValueError`` for breakdowns Meta only supports at a specific
    Insights ``level`` (e.g. Dynamic Creative asset breakdowns require
    ``level=ad``)."""
    for breakdown in breakdowns:
        allowed_levels = LEVEL_RESTRICTED_BREAKDOWNS.get(breakdown)
        if allowed_levels and level not in allowed_levels:
            raise ValueError(
                f"Breakdown '{breakdown}' is only available at level(s) "
                f"{allowed_levels}, not '{level}'."
            )


def validate_field_breakdown_compatibility(fields: list[str], breakdowns: list[str]) -> None:
    """Raise ``ValueError`` for the documented hard incompatibilities
    between specific fields and specific breakdowns."""
    video_fields = [f for f in fields if f.startswith("video_")]
    if video_fields and any(b in _HOURLY_BREAKDOWNS for b in breakdowns):
        raise ValueError(
            f"video_* fields ({video_fields}) cannot be combined with an hourly "
            f"breakdown ({[b for b in breakdowns if b in _HOURLY_BREAKDOWNS]})."
        )
    if "video_avg_time_watched_actions" in fields and "region" in breakdowns:
        raise ValueError(
            "'video_avg_time_watched_actions' cannot be combined with the "
            "'region' breakdown."
        )


#: Pre-defined, VALIDATED breakdown combos for the most common audience-
#: segment analyses -- each key is meant to become its own Silver table
#: (e.g. insights_ad_breakdown_demographic) once wired into a sync call, the
#: same pattern app/services/silver/insights_flatten.py already uses for the
#: unbroken-down levels. Every combo here has been checked against this
#: module's OWN validate_breakdown_combination/validate_breakdown_level_compatibility
#: (2026-08-25) -- not copied from an external source's assumptions, which
#: got the platform combo wrong (publisher_platform + platform_position
#: together is actually one of MUTUALLY_EXCLUSIVE_BREAKDOWN_FAMILIES's
#: exclusive trios, not a valid pairing -- 'placement' is the correct
#: shorthand to combine with impression_device instead).
#:
#: NOT yet wired into any scheduler job or sync call -- adding real
#: breakdown-fetching to the daily/hourly cron is a bigger decision (new
#: Bronze row volume per combo, new Silver tables, real API-quota cost) than
#: "the combo definitions are structurally valid," and this project's Meta
#: API access is on Development Access tier with a demonstrated low
#: request-volume ceiling (see DATE_CHUNK_DAYS / _should_use_async in
#: app/services/meta/insights.py) -- revisit this constant when there's a
#: concrete need for one of these breakdowns' data before turning any of
#: them on by default.
RECOMMENDED_BREAKDOWN_COMBOS: dict[str, list[list[str]]] = {
    "demographic": [["age", "gender"]],
    "geographic": [["country"], ["region"], ["dma"]],
    "platform": [["placement", "impression_device"]],
    "product": [["product_id"]],
    "hourly": [["hourly_stats_aggregated_by_advertiser_time_zone"]],
}


# ==========================================================================
# Insights fields — the exhaustive metric registry
# ==========================================================================

INSIGHTS_FIELD_GROUPS: dict[str, list[str]] = {
    "identity": [
        "account_id",
        "account_name",
        "account_currency",
        "campaign_id",
        "campaign_name",
        "adset_id",
        "adset_name",
        "ad_id",
        "ad_name",
        "date_start",
        "date_stop",
        "objective",
        "buying_type",
        "optimization_goal",
        "created_time",
        "updated_time",
        "adset_end",
        "adset_start",
        "anchor_event_attribution_setting",
        "anchor_events_performance_indicator",
        "multi_event_conversion_attribution_setting",
        "result_values_performance_indicator",
    ],
    "delivery": [
        # NOTE: "unique_impressions" deliberately excluded — despite being
        # documented, Meta rejects it live ("not valid for fields param",
        # error code 100) on the API version this codebase targets.
        "impressions",
        "reach",
        "frequency",
        "full_view_impressions",
        "full_view_reach",
    ],
    "spend": [
        "spend",
        "social_spend",
    ],
    "clicks": [
        "clicks",
        "unique_clicks",
        "inline_link_clicks",
        "unique_inline_link_clicks",
        "inline_link_click_ctr",
        "unique_inline_link_click_ctr",
        "outbound_clicks",
        "unique_outbound_clicks",
        "outbound_clicks_ctr",
        "unique_outbound_clicks_ctr",
        "unique_link_clicks_ctr",
        "website_ctr",
        "inline_post_engagement",
    ],
    "rate_and_cost": [
        "ctr",
        "unique_ctr",
        "cpc",
        "cost_per_unique_click",
        "cost_per_inline_link_click",
        "cost_per_unique_inline_link_click",
        "cost_per_outbound_click",
        "cost_per_unique_outbound_click",
        "cost_per_inline_post_engagement",
        "cost_per_one_thousand_ad_impression",
        "cpm",
        "cpp",
    ],
    "conversions": [
        "actions",
        "unique_actions",
        "conversions",
        "conversion_values",
        "cost_per_conversion",
        "cost_per_action_type",
        "cost_per_unique_action_type",
        "converted_product_quantity",
        "converted_product_value",
        "converted_promoted_product_quantity",
        "converted_promoted_product_value",
        "conversion_lead_rate",
        "cost_per_conversion_lead",
        "qualifying_question_qualify_answer_rate",
        "shops_assisted_purchases",
        "dda_results",
        "ad_click_actions",
        "ad_impression_actions",
        "cost_per_ad_click",
        "cost_per_unique_conversion",
        "dda_countby_convs",
        "cost_per_dda_countby_convs",
    ],
    "revenue_and_roas": [
        "action_values",
        "purchase_roas",
        "website_purchase_roas",
        "mobile_app_purchase_roas",
        "conversion_rate_ranking",
    ],
    "catalog_segment": [
        "catalog_segment_actions",
        "catalog_segment_value",
        "catalog_segment_value_website_purchase_roas",
        "catalog_segment_value_mobile_purchase_roas",
        "catalog_segment_value_omni_purchase_roas",
    ],
    "skadnetwork": [
        "total_postbacks",
        "total_postbacks_detailed",
        "total_postbacks_detailed_v4",
    ],
    "auction_diagnostics": [
        # ad/adset level only — see LEVEL_RESTRICTED_METRICS.
        "auction_bid",
        "auction_competitiveness",
        "auction_max_competitor_bid",
    ],
    "video": [
        "video_play_actions",
        "video_play_curve_actions",
        "video_p25_watched_actions",
        "video_p50_watched_actions",
        "video_p75_watched_actions",
        "video_p95_watched_actions",
        "video_p100_watched_actions",
        "video_avg_time_watched_actions",
        "video_time_watched_actions",
        "video_thruplay_watched_actions",
        "cost_per_thruplay",
        "video_30_sec_watched_actions",
        "video_continuous_2_sec_watched_actions",
        "cost_per_2_sec_continuous_video_view",
        "cost_per_15_sec_video_view",
        "video_play_retention_0_to_15s_actions",
        "video_play_retention_20_to_60s_actions",
        "video_play_retention_graph_actions",
        "video_6_sec_watched_actions",
    ],
    "engagement": [
        # NOTE: "post_reactions"/"post_comments"/"post_shares"/"post_saves"
        # deliberately excluded — Meta rejects them outright ("not valid
        # for fields param", error code 100). Confirmed live; no per-type
        # breakdown of post_engagement is exposed via the Insights fields
        # param today (see the `action_breakdowns` "action_reaction" value
        # for reaction-level detail on the nested `actions` array instead).
        "post_engagement",
        "page_engagement",
    ],
    # NOTE: no "messaging" group here — "onsite_conversion.messaging_*"
    # are `action_type` values (see ACTION_TYPES below), not top-level
    # Insights fields. Meta's field parser rejects them in `fields=`
    # outright ("Expected '(' instead of ','" — the dot is parsed as a
    # method-call modifier). Confirmed live; previously a real bug here.
    "marketing_messages": [
        # NOTE: "marketing_messages_blocked",
        # "marketing_messages_click_rate",
        # "marketing_messages_website_purchase_values",
        # "marketing_messages_website_add_to_cart", and
        # "marketing_messages_website_initiate_checkout" deliberately
        # excluded — Meta rejects them outright ("not valid for fields
        # param", error code 100). Confirmed live.
        "marketing_messages_sent",
        "marketing_messages_delivered",
        "marketing_messages_delivery_rate",
        "marketing_messages_cost_per_delivered",
        "marketing_messages_read",
        "marketing_messages_read_rate",
        "marketing_messages_read_rate_benchmark",
        "marketing_messages_link_btn_click",
        "marketing_messages_cost_per_link_btn_click",
        "marketing_messages_phone_call_btn_click_rate",
        "marketing_messages_quick_reply_btn_click_rate",
        "marketing_messages_media_view_rate",
        "marketing_messages_spend",
    ],
    "estimated": [
        # NOTE: `estimated_ad_recallers_lower_bound`,
        # `estimated_ad_recallers_upper_bound`,
        # `estimated_ad_recall_rate_lower_bound`, and
        # `estimated_ad_recall_rate_upper_bound` deliberately excluded —
        # Meta rejects them outright ("not valid for fields param after
        # V19.0", error code 100) on v19.0+, which is every API version
        # this codebase targets. Confirmed live.
        "estimated_ad_recallers",
        "estimated_ad_recall_rate",
        "cost_per_estimated_ad_recallers",
    ],
    "quality_and_relevance": [
        # ad level only — see LEVEL_RESTRICTED_METRICS.
        "quality_ranking",
        "engagement_rate_ranking",
        "conversion_rate_ranking",
    ],
    "canvas_and_instant_experience": [
        "canvas_avg_view_time",
        "canvas_avg_view_percent",
        "instant_experience_clicks_to_open",
        "instant_experience_clicks_to_start",
        "instant_experience_outbound_clicks",
        # `interactive_component_tap` re-included 2026-08-21 -- the
        # 2026-08-20 finding that it broke "the WHOLE request" turned out
        # to be account-level-only, not universal (re-verified live:
        # succeeds combined with the full default field set at ad/adset/
        # campaign level; still hard-fails at account level with the same
        # "error_subcode": 1504041 / "Invalid breakdowns" masked behind a
        # generic "Service temporarily unavailable" message). See
        # LEVEL_EXCLUDED_FIELDS, which drops it only for account-level
        # requests instead of excluding it everywhere.
        "interactive_component_tap",
    ],
    "attribution_meta": [
        "attribution_setting",
    ],
    # NOTE: no "creative_assets" group -- every candidate field
    # (body_asset, image_asset, video_asset, title_asset, description_asset,
    # media_asset, rule_asset, creative_automation_asset_id,
    # creative_relaxation_asset_type, flexible_format_asset_type,
    # gen_ai_asset_type, ad_format_asset) was rejected live ("not valid for
    # fields param", error code 100), despite being documented. These
    # names remain valid as `breakdowns` values (see BREAKDOWN_GROUPS'
    # dynamic_creative group) -- just not as standalone `fields`.
    "results_framework": [
        "results",
        "result_rate",
        "cost_per_result",
        "objective_results",
        "objective_result_rate",
        "cost_per_objective_result",
    ],
    # NOTE: no "dwell_and_attention" group -- every candidate field
    # (dwell_3_sec/5_sec/7_sec, cost_per_dwell*, dwell_rate, thumb_stops,
    # attention_events_per_impression, attention_events_unq_per_reach) was
    # rejected live ("not valid for fields param", error code 100),
    # despite being documented. Likely display-ad-specific and gated off
    # this API version/permission level.
    "product_catalog_fields": [
        "product_group_retailer_id",
        "product_retailer_id",
        "product_views",
    ],
    "configurable_reach_and_attribution": [
        "configurable_attribution_action",
        "configurable_attribution_actionvalue",
        "configurable_audience_overlap_reach",
        "configurable_reachbyfrequency_action",
        "configurable_reachbyfrequency_converters_count",
        "configurable_reachbyfrequency_impressions_cost",
        "configurable_reachbyfrequency_impressions_count",
        "configurable_reachbyfrequency_reach",
    ],
    "creative_diagnostics": [
        "creative_diversity_data",
        "creative_diversity_label",
        "creative_diversity_score",
        "creative_fatigue_summary",
        "creative_fatigued_ads",
    ],
    "converted_product_variants": [
        "converted_product_app_custom_event_fb_mobile_purchase",
        "converted_product_app_custom_event_fb_mobile_purchase_value",
        "converted_product_offline_purchase",
        "converted_product_offline_purchase_value",
        "converted_product_omni_purchase",
        "converted_product_omni_purchase_values",
        "converted_product_website_pixel_purchase",
        "converted_product_website_pixel_purchase_value",
        "converted_promoted_product_app_custom_event_fb_mobile_purchase",
        "converted_promoted_product_app_custom_event_fb_mobile_purchase_value",
        "converted_promoted_product_offline_purchase",
        "converted_promoted_product_offline_purchase_value",
        "converted_promoted_product_omni_purchase",
        "converted_promoted_product_omni_purchase_values",
        "converted_promoted_product_website_pixel_purchase",
        "converted_promoted_product_website_pixel_purchase_value",
    ],
    "legacy_and_misc": [
        # NOTE: "opportunity_score_l4" and "total_card_view" deliberately
        # excluded — Meta doesn't cleanly reject either, they trigger a
        # genuine backend error ("Service temporarily unavailable", code 2
        # / subcode 1504044) reproducible on every request that includes
        # them. Confirmed live via bisection.
        "wish_bid",
        "instagram_upcoming_event_reminders_set",
        "landing_page_view_per_link_click",
        "purchase_per_landing_page_view",
    ],
    # NOTE: no "breakdown_dimensions_as_fields" group -- despite Meta's own
    # docs listing dimension names (country, device_platform, dma,
    # fidelity_type, hourly_stats_aggregated_by_*, hsid, impression_device,
    # is_auto_advance, platform_position, postback_sequence_index,
    # publisher_platform, redownload, reels_trending_topic, rta_ugc_topic,
    # rule_set_id, rule_set_name, skan_version, zip, comscore_market) as
    # also being directly-requestable top-level `fields` values, every one
    # was rejected live ("not valid for fields param", error code 100).
    # These remain valid and unaffected as `breakdowns` values (see
    # BREAKDOWN_GROUPS) -- just not as standalone Insights `fields`.
}

#: Field groups excluded from the "everything" default
#: (:data:`ALL_INSIGHTS_FIELDS` / ``get_insights_fields()`` with no
#: ``include_groups``) because Meta imposes an extra precondition on them
#: that a blanket "fetch every field" request can't satisfy generically.
#: Still fetchable via ``get_insights_fields(include_groups=["<group>"])``
#: once the caller has met the precondition. Two distinct reasons, both
#: confirmed live:
#: * ``skadnetwork`` — must be queried completely **alone**; combining
#:   with fields from any other group fails outright ("`total_postbacks`
#:   should not be queried with other field values.", error code 100).
#: * ``configurable_reach_and_attribution`` — requires a
#:   ``filtering=[{"field":"customization_name","operator":"EQUAL",
#:   "value":"<name>"}]`` param naming a custom attribution/reach config
#:   the ad account has set up in Ads Manager ("The customization_name
#:   filter is required when requesting ... metrics", error code 100) —
#:   not something a generic fetch can supply without account-specific
#:   configuration.
FIELD_GROUPS_REQUIRING_ISOLATION: frozenset[str] = frozenset(
    {"skadnetwork", "configurable_reach_and_attribution"}
)

ALL_INSIGHTS_FIELDS: list[str] = sorted(
    {
        f
        for group_name, group in INSIGHTS_FIELD_GROUPS.items()
        if group_name not in FIELD_GROUPS_REQUIRING_ISOLATION
        for f in group
    }
)

#: Common ``action_type`` values nested inside the ``actions`` /
#: ``action_values`` / ``cost_per_action_type`` arrays. Not exhaustive (Meta
#: adds custom-event and app-event action types dynamically per
#: advertiser), but covers every standard event/conversion type — useful
#: for downstream (Silver-layer) code that needs to recognize known types
#: without round-tripping to Meta.
ACTION_TYPES: list[str] = [
    "purchase",
    "omni_purchase",
    "offsite_conversion.fb_pixel_purchase",
    "add_to_cart",
    "omni_add_to_cart",
    "initiate_checkout",
    "add_payment_info",
    "view_content",
    "omni_view_content",
    "search",
    "lead",
    "complete_registration",
    "landing_page_view",
    "link_click",
    "post_engagement",
    "page_engagement",
    "post_reaction",
    "comment",
    "post",
    "like",
    "video_view",
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.messaging_first_reply",
    "onsite_conversion.total_messaging_connection",
    "onsite_conversion.purchase",
    "mobile_app_install",
    "app_custom_event.*",
    "subscribe",
    "start_trial",
]


def get_insights_fields(
    *,
    include_groups: list[str] | None = None,
    exclude_fields: list[str] | None = None,
    extra_fields: list[str] | None = None,
) -> list[str]:
    """Build the field list for an Insights request.

    Defaults to every field in every group (the "fetch everything"
    requirement). Callers may narrow to specific groups, drop specific
    fields, or append fields not yet in the registry (e.g. a brand-new
    metric Meta shipped) without touching ingestion code.
    """
    if include_groups:
        unknown_groups = set(include_groups) - set(INSIGHTS_FIELD_GROUPS)
        if unknown_groups:
            raise ValueError(f"Unknown insights field group(s): {sorted(unknown_groups)}")
        isolation_groups = set(include_groups) & FIELD_GROUPS_REQUIRING_ISOLATION
        if isolation_groups and len(include_groups) > 1:
            raise ValueError(
                f"Group(s) {sorted(isolation_groups)} must be requested alone — Meta "
                "rejects them combined with any other field group in the same request."
            )
        fields = {f for g in include_groups for f in INSIGHTS_FIELD_GROUPS[g]}
    else:
        fields = set(ALL_INSIGHTS_FIELDS)

    if exclude_fields:
        fields -= set(exclude_fields)
    if extra_fields:
        fields |= set(extra_fields)

    return sorted(fields)


# ==========================================================================
# Object-level field registries (non-insights entities)
# ==========================================================================

ACCOUNT_FIELDS: list[str] = [
    "id",
    "account_id",
    "name",
    "account_status",
    "age",
    "amount_spent",
    "balance",
    "business",
    "business_city",
    "business_country_code",
    "currency",
    "disable_reason",
    "end_advertiser",
    "funding_source",
    "funding_source_details",
    "is_prepay_account",
    "min_daily_budget",
    "owner",
    "spend_cap",
    "timezone_id",
    "timezone_name",
    "timezone_offset_hours_utc",
    "capabilities",
    "tax_id_status",
    "attribution_spec",
]

CAMPAIGN_FIELDS: list[str] = [
    "id",
    "account_id",
    "name",
    "objective",
    "status",
    "effective_status",
    "buying_type",
    "budget_remaining",
    "daily_budget",
    "lifetime_budget",
    "bid_strategy",
    "spend_cap",
    "start_time",
    "stop_time",
    "created_time",
    "updated_time",
    "special_ad_categories",
    "smart_promotion_type",
    "source_campaign_id",
    "promoted_object",
    "pacing_type",
    "issues_info",
]

ADSET_FIELDS: list[str] = [
    "id",
    "account_id",
    "campaign_id",
    "name",
    "status",
    "effective_status",
    "billing_event",
    "optimization_goal",
    "bid_amount",
    "bid_strategy",
    "budget_remaining",
    "daily_budget",
    "lifetime_budget",
    "start_time",
    "end_time",
    "created_time",
    "updated_time",
    "targeting",
    "promoted_object",
    "attribution_spec",
    "destination_type",
    "learning_stage_info",
    "frequency_control_specs",
    "pacing_type",
    "issues_info",
    "dsa_beneficiary",
    "dsa_payor",
]

AD_FIELDS: list[str] = [
    "id",
    "account_id",
    "campaign_id",
    "adset_id",
    "name",
    "status",
    "effective_status",
    "creative",
    "created_time",
    "updated_time",
    "bid_amount",
    "conversion_domain",
    "tracking_specs",
    "issues_info",
    "recommendations",
]

#: Nested-expansion field spec implementing the Ads Insights reference's
#: "Bulk pull (recommended)" query for URL/UTM tracking data (§8) — fetches
#: the ad plus every creative field needed to resolve destination URLs and
#: UTM tags in a single call, instead of joining separate ads/adcreatives
#: Bronze syncs downstream. Pass this to :class:`AdSyncService` via
#: ``request_params={"fields": AD_URL_TRACKING_FIELDS}``. Deliberately kept
#: as a raw Graph API field-expansion string (not a list) since it encodes
#: nested sub-field selections that a flat ``list[str]`` can't represent.
AD_URL_TRACKING_FIELDS: str = (
    "id,name,status,effective_status,adset_id,campaign_id,updated_time,"
    "creative{id,name,url_tags,link_url,"
    "object_story_spec{link_data{link,message,name,call_to_action},"
    "video_data{call_to_action}},"
    "asset_feed_spec{link_urls},"
    "template_url,template_url_spec,object_url,effective_object_story_id},"
    "tracking_specs,conversion_domain"
)

#: Dynamic macros Meta substitutes into `url_tags` at click time. They
#: return *literally* (unresolved) in API responses — the Bronze layer
#: stores them verbatim; resolving them against the ad/adset/campaign
#: id/name fields to build a UTM -> ad mapping table is downstream
#: (Silver-layer) business logic, not an ingestion concern.
URL_MACROS: list[str] = [
    "{{campaign.id}}",
    "{{campaign.name}}",
    "{{adset.id}}",
    "{{adset.name}}",
    "{{ad.id}}",
    "{{ad.name}}",
    "{{site_source_name}}",
    "{{placement}}",
]

CREATIVE_FIELDS: list[str] = [
    "id",
    "account_id",
    "name",
    "status",
    "object_story_spec",
    "object_story_id",
    "asset_feed_spec",
    "image_hash",
    "image_url",
    "video_id",
    "thumbnail_url",
    "body",
    "title",
    "call_to_action_type",
    "effective_object_story_id",
    "instagram_permalink_url",
    "url_tags",
    "link_url",
    "object_url",
    "template_url",
    "template_url_spec",
    "degrees_of_freedom_spec",
]

AD_IMAGE_FIELDS: list[str] = [
    "id",
    "account_id",
    "hash",
    "name",
    "url",
    "url_128",
    "width",
    "height",
    "status",
    "created_time",
    "updated_time",
]

AD_VIDEO_FIELDS: list[str] = [
    "id",
    "account_id",
    "title",
    "description",
    "source",
    "length",
    "picture",
    "status",
    "created_time",
    "updated_time",
]

AUDIENCE_FIELDS: list[str] = [
    "id",
    "account_id",
    "business_id",
    "name",
    "subtype",
    "approximate_count_lower_bound",
    "approximate_count_upper_bound",
    "data_source",
    "delivery_status",
    "operation_status",
    "lookalike_spec",
    "rule",
    "retention_days",
    "time_created",
    "time_updated",
]

PIXEL_FIELDS: list[str] = [
    "id",
    "business_id",
    "name",
    "code",
    "creation_time",
    "last_fired_time",
    "is_created_by_business",
    "data_use_setting",
    "enable_automatic_matching",
]

CUSTOM_CONVERSION_FIELDS: list[str] = [
    "id",
    "account_id",
    "name",
    "custom_event_type",
    "rule",
    "aggregation_rule",
    "pixel",
    "default_conversion_value",
    "creation_time",
    "is_archived",
]

OFFLINE_EVENT_FIELDS: list[str] = [
    "id",
    "event_name",
    "event_time",
    "currency",
    "value",
    "order_id",
    "match_keys",
]

ACTIVITY_FIELDS: list[str] = [
    "account_id",
    "actor_id",
    "actor_name",
    "application_id",
    "application_name",
    "date_time_in_timezone",
    "event_time",
    "event_type",
    "extra_data",
    "object_id",
    "object_name",
    "object_type",
    "translated_event_type",
]

BUSINESS_ASSET_FIELDS: list[str] = [
    "id",
    "name",
    "business",
    "permitted_tasks",
    "permitted_roles",
]

CATALOG_FIELDS: list[str] = [
    "id",
    "business",
    "name",
    "product_count",
    "vertical",
    "feed_count",
]

PRODUCT_FIELDS: list[str] = [
    "id",
    "retailer_id",
    "name",
    "description",
    "availability",
    "condition",
    "price",
    "currency",
    "brand",
    "category",
    "image_url",
    "url",
    "inventory",
]

LABEL_FIELDS: list[str] = [
    "id",
    "account_id",
    "name",
    "created_time",
]
