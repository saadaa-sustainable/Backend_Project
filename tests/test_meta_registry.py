"""Unit tests for the configurable field/breakdown/attribution registries."""

from __future__ import annotations

import pytest

from app.core.meta_registry import (
    ALL_INSIGHTS_FIELDS,
    DEFAULT_ACTION_BREAKDOWNS,
    DEFAULT_ATTRIBUTION_WINDOWS,
    TIME_INCREMENT_MAX_DAYS,
    TIME_INCREMENT_MIN_DAYS,
    TimeIncrement,
    get_insights_fields,
    resolve_action_breakdowns,
    resolve_attribution_windows,
    resolve_time_increment,
    validate_breakdown_combination,
    validate_breakdown_level_compatibility,
    validate_field_breakdown_compatibility,
)


def test_get_insights_fields_defaults_to_everything() -> None:
    fields = get_insights_fields()
    assert fields == ALL_INSIGHTS_FIELDS
    assert "spend" in fields
    assert "purchase_roas" in fields
    assert "video_p100_watched_actions" in fields


def test_get_insights_fields_scoped_to_groups() -> None:
    fields = get_insights_fields(include_groups=["spend", "clicks"])
    assert "spend" in fields
    assert "clicks" in fields
    assert "purchase_roas" not in fields


def test_get_insights_fields_unknown_group_raises() -> None:
    with pytest.raises(ValueError, match="Unknown insights field group"):
        get_insights_fields(include_groups=["not_a_real_group"])


def test_get_insights_fields_extra_and_exclude() -> None:
    fields = get_insights_fields(
        include_groups=["spend"], exclude_fields=["spend"], extra_fields=["brand_new_metric"]
    )
    assert fields == ["brand_new_metric"]


def test_resolve_attribution_windows_defaults() -> None:
    resolved = resolve_attribution_windows(None)
    assert resolved == DEFAULT_ATTRIBUTION_WINDOWS


def test_resolve_attribution_windows_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown attribution window"):
        resolve_attribution_windows(["not_a_window"])


def test_resolve_attribution_windows_dda_alone_omits_param() -> None:
    assert resolve_attribution_windows(["dda"]) == []


def test_resolve_attribution_windows_dda_combined_raises() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        resolve_attribution_windows(["dda", "7d_click"])


def test_resolve_attribution_windows_incrementality_raises_actionable_error() -> None:
    with pytest.raises(ValueError, match="Conversion Lift"):
        resolve_attribution_windows(["incrementality"])


def test_validate_breakdown_combination_accepts_valid() -> None:
    validate_breakdown_combination(["age", "gender"])


def test_validate_breakdown_combination_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown breakdown"):
        validate_breakdown_combination(["not_a_breakdown"])


def test_validate_breakdown_combination_rejects_placement_conflict() -> None:
    with pytest.raises(ValueError, match="placement"):
        validate_breakdown_combination(["placement", "publisher_platform"])


def test_resolve_action_breakdowns_defaults() -> None:
    assert resolve_action_breakdowns(None) == DEFAULT_ACTION_BREAKDOWNS


def test_resolve_action_breakdowns_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown action_breakdown"):
        resolve_action_breakdowns(["not_a_real_action_breakdown"])


def test_validate_breakdown_level_compatibility_allows_ad_level_dynamic_creative() -> None:
    validate_breakdown_level_compatibility(["image_asset"], "ad")


def test_validate_breakdown_level_compatibility_rejects_account_level_dynamic_creative() -> None:
    with pytest.raises(ValueError, match="only available at level"):
        validate_breakdown_level_compatibility(["image_asset"], "account")


def test_validate_field_breakdown_compatibility_rejects_video_with_hourly_breakdown() -> None:
    with pytest.raises(ValueError, match="video_\\*"):
        validate_field_breakdown_compatibility(
            ["video_p25_watched_actions"],
            ["hourly_stats_aggregated_by_advertiser_time_zone"],
        )


def test_validate_field_breakdown_compatibility_rejects_avg_watch_time_with_region() -> None:
    with pytest.raises(ValueError, match="region"):
        validate_field_breakdown_compatibility(["video_avg_time_watched_actions"], ["region"])


def test_validate_field_breakdown_compatibility_accepts_valid_combo() -> None:
    validate_field_breakdown_compatibility(["spend", "clicks"], ["age", "gender"])


def test_resolve_attribution_windows_accepts_literal_default_token() -> None:
    assert resolve_attribution_windows(["default"]) == ["default"]


def test_resolve_time_increment_enum_passthrough() -> None:
    assert resolve_time_increment(TimeIncrement.ALL_DAYS) == "all_days"
    assert resolve_time_increment(TimeIncrement.MONTHLY) == "monthly"


def test_resolve_time_increment_accepts_arbitrary_int_in_range() -> None:
    assert resolve_time_increment(1) == "1"
    assert resolve_time_increment(14) == "14"
    assert resolve_time_increment(TIME_INCREMENT_MAX_DAYS) == str(TIME_INCREMENT_MAX_DAYS)


def test_resolve_time_increment_rejects_out_of_range_int() -> None:
    with pytest.raises(ValueError, match="between 1 and 90"):
        resolve_time_increment(TIME_INCREMENT_MAX_DAYS + 1)
    with pytest.raises(ValueError, match="between 1 and 90"):
        resolve_time_increment(TIME_INCREMENT_MIN_DAYS - 1)


def test_validate_breakdown_combination_rejects_impression_device_alone() -> None:
    with pytest.raises(ValueError, match="cannot be requested by itself"):
        validate_breakdown_combination(["impression_device"])


def test_validate_breakdown_combination_allows_impression_device_combined() -> None:
    validate_breakdown_combination(["impression_device", "age"])
