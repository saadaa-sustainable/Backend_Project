"""Regression examples for the legacy Ads Analyse efficiency formulas.

Expected values come from the SQL view recovered from CTD commit 0232121,
not from a second implementation of the calculation under test.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.ad_efficiency import EfficiencyAnchors, calculate_efficiency_scores


@pytest.fixture
def anchors():
    return EfficiencyAnchors(
        g_spend=Decimal("1000"),
        g_reach=Decimal("10000"),
        g_ftewv=Decimal("1000"),
        g_ncp=Decimal("100"),
        g_conv=Decimal("5000"),
        med_ftewv=Decimal("100"),
        med_profit=Decimal("200"),
    )


@pytest.fixture
def row():
    return {
        "spend": 200.0,
        "reach": 1000.0,
        "conv_value": 600.0,
        "ftewv_count": 200.0,
        "cpr_1000": 200.0,
        "cost_per_ncp": 25.0,
        "cost_per_ftewv": 1.0,
        "roas": 3.0,
    }


def test_all_nine_scores_match_known_legacy_example(row, anchors):
    assert calculate_efficiency_scores(row, anchors) == {
        "cpr_eff": 0.5,
        "ftv_contrib_eff": 2.0,
        "ftev_volume": 2.0,
        "ncp_cost_eff": 0.4,
        "roas_eff": 0.6,
        "profit_vol_eff": 2.0,
        "delivery_eff": 3.5,
        "sales_spend_eff": 1.0,
        "blended_eff": 1.25,
    }


def test_cpr_uses_stored_reach_cost_not_impression_cost(row, anchors):
    # Stored ratios can be rounded independently of the displayed totals.
    # The legacy view explicitly consumes that stored reach-cost ratio.
    row["cpr_1000"] = 250.0
    row["cost_per_1000"] = 50.0
    assert calculate_efficiency_scores(row, anchors)["cpr_eff"] == 0.4


def test_composites_use_unrounded_components_and_are_sums():
    thirds = EfficiencyAnchors(
        g_spend=Decimal("1"),
        g_reach=Decimal("1000"),
        g_ftewv=Decimal("3"),
        g_ncp=Decimal("1"),
        g_conv=Decimal("6"),
        med_ftewv=Decimal("3"),
        med_profit=Decimal("599"),
    )
    scores = calculate_efficiency_scores(
        {
            "spend": 3.0,
            "reach": 1000.0,
            "conv_value": 6.0,
            "ftewv_count": 1.0,
            "cpr_1000": 3.0,
            "cost_per_ncp": 3.0,
            "cost_per_ftewv": 3.0,
            "roas": 2.0,
        },
        thirds,
    )
    assert scores["cpr_eff"] == 0.333
    assert scores["ftv_contrib_eff"] == 0.333
    assert scores["ncp_cost_eff"] == 0.333
    assert scores["roas_eff"] == 0.333
    # Rounding the components first would produce .777, .666 and .300.
    assert scores["delivery_eff"] == 0.778
    assert scores["sales_spend_eff"] == 0.667
    assert scores["blended_eff"] == 0.301


def test_zero_delivery_has_zero_scores(anchors):
    no_delivery = {
        "spend": 0.0,
        "reach": 0.0,
        "conv_value": 0.0,
        "ftewv_count": 0.0,
        "cpr_1000": None,
        "cost_per_ncp": None,
        "cost_per_ftewv": None,
        "roas": None,
    }
    scores = calculate_efficiency_scores(no_delivery, anchors)
    assert len(scores) == 9
    assert set(scores.values()) == {0.0}


def test_unavailable_fleet_denominators_return_guarded_zeros(row):
    # SQL NULLIF converts zero global sums to None before constructing the
    # anchors; zero medians remain zero and are covered separately below.
    empty = EfficiencyAnchors(
        g_spend=None,
        g_reach=None,
        g_ftewv=None,
        g_ncp=None,
        g_conv=None,
        med_ftewv=None,
        med_profit=None,
    )
    assert set(calculate_efficiency_scores(row, empty).values()) == {0.0}


def test_missing_row_data_is_not_reported_as_zero_observations(anchors):
    assert calculate_efficiency_scores({}, anchors) == {
        "cpr_eff": 0.0,
        "ftv_contrib_eff": 0.0,
        "ftev_volume": None,
        "ncp_cost_eff": 0.0,
        "roas_eff": 0.0,
        "profit_vol_eff": None,
        "delivery_eff": 0.0,
        "sales_spend_eff": 0.0,
        "blended_eff": None,
    }


def test_missing_video_count_propagates_only_to_dependent_scores(row, anchors):
    row["ftewv_count"] = None
    scores = calculate_efficiency_scores(row, anchors)
    for key in ("ftv_contrib_eff", "ftev_volume", "delivery_eff", "blended_eff"):
        assert scores[key] is None
    assert scores["cpr_eff"] == 0.5
    assert scores["sales_spend_eff"] == 1.0
    assert scores["profit_vol_eff"] == 2.0


@pytest.mark.parametrize("missing_field", ["spend", "conv_value"])
def test_profit_requires_both_row_inputs(row, anchors, missing_field):
    row[missing_field] = None
    scores = calculate_efficiency_scores(row, anchors)
    assert scores["profit_vol_eff"] is None
    assert scores["blended_eff"] is None
    assert scores["delivery_eff"] == 3.5


def test_missing_global_spend_is_null_when_a_guard_already_passed(row, anchors):
    scores = calculate_efficiency_scores(row, replace(anchors, g_spend=None))
    for key in ("cpr_eff", "ncp_cost_eff", "delivery_eff", "sales_spend_eff", "blended_eff"):
        assert scores[key] is None
    # ROAS explicitly guards on global spend, unlike the cost scores.
    assert scores["roas_eff"] == 0.0
    assert scores["ftv_contrib_eff"] == 2.0


@pytest.mark.parametrize("conversion_anchor", [None, Decimal("0")])
def test_missing_conversion_anchor_does_not_fabricate_roas_score(row, anchors, conversion_anchor):
    scores = calculate_efficiency_scores(row, replace(anchors, g_conv=conversion_anchor))
    assert scores["roas_eff"] is None
    assert scores["sales_spend_eff"] is None
    assert scores["blended_eff"] is None
    assert scores["delivery_eff"] == 3.5


def test_zero_medians_use_legacy_zero_fallback(row, anchors):
    scores = calculate_efficiency_scores(
        row,
        replace(anchors, med_ftewv=Decimal("0"), med_profit=Decimal("0")),
    )
    assert scores["ftev_volume"] == 0.0
    assert scores["profit_vol_eff"] == 0.0
    assert scores["blended_eff"] == 0.75


def test_negative_profit_median_preserves_legacy_sign(row, anchors):
    scores = calculate_efficiency_scores(row, replace(anchors, med_profit=Decimal("-200")))
    assert scores["profit_vol_eff"] == -2.0
    assert scores["blended_eff"] == 0.85


def test_rounding_matches_postgres_numeric_for_both_signs(row, anchors):
    row.update(spend=2469.0, conv_value=0.0, ftewv_count=2469.0)
    scores = calculate_efficiency_scores(
        row,
        replace(anchors, med_ftewv=Decimal("2000"), med_profit=Decimal("2000")),
    )
    assert scores["ftev_volume"] == 1.235
    assert scores["profit_vol_eff"] == -1.235
