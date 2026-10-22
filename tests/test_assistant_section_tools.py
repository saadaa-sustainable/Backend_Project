"""The section tools an MCP client sees, and the rules that keep them honest.

Each tool wraps the SAME analytics function the dashboard calls, so a client
gets the dashboard's numbers rather than raw SQL over Supabase. What these
tests pin is the part a schema cannot express: the input combinations that
must be refused, and the basis string that says which measurement a number
came from.
"""
import json

import pytest

from app.services import assistant_analytics as tools

NEW_TOOLS = {
    "get_sku_economics",
    "get_first_click_attribution",
    "get_last_click_attribution",
    "get_blended_mer",
}


def spec(name):
    return tools._TOOL_SPECS[name]


def test_every_section_tool_is_declared_to_clients():
    declared = {t["function"]["name"] for t in tools.ANALYTICS_TOOLS}
    assert NEW_TOOLS <= declared


@pytest.mark.parametrize("name", sorted(NEW_TOOLS))
def test_schema_forbids_unknown_arguments(name):
    """extra='forbid' is what stops a model inventing a filter and being ignored."""
    model = spec(name)[0]
    with pytest.raises(Exception):
        model.model_validate({"definitely_not_a_field": 1})


@pytest.mark.parametrize("name", sorted(NEW_TOOLS))
def test_description_is_substantial(name):
    """These descriptions carry the traps; a one-liner would strand the model."""
    assert len(spec(name)[1]) > 300


# ── the refusals ──────────────────────────────────────────────────────

@pytest.mark.parametrize("args", [
    {"date_from": "2026-10-01"},                      # half a range
    {"date_to": "2026-10-01"},
    {"date_from": "2026-10-21", "date_to": "2026-10-01"},  # reversed
])
def test_sku_economics_rejects_broken_ranges(args):
    with pytest.raises(Exception):
        spec("get_sku_economics")[0].model_validate(args)


@pytest.mark.parametrize("sort", ["spend", "first_click_roas", "last_click_roas"])
def test_first_click_source_grain_refuses_spend_sorts(sort):
    """Source grain has no Meta spend, so those columns are all NULL there.

    Sorting on them would order every row by null and look like a broken
    control rather than an absent measurement.
    """
    with pytest.raises(Exception):
        spec("get_first_click_attribution")[0].model_validate(
            {"grain": "source", "sort": sort})


@pytest.mark.parametrize("grain", ["ad", "adset"])
def test_first_click_id_grains_allow_spend_sorts(grain):
    spec("get_first_click_attribution")[0].model_validate(
        {"grain": grain, "sort": "first_click_roas"})


def test_last_click_matched_flags_are_exclusive():
    with pytest.raises(Exception):
        spec("get_last_click_attribution")[0].model_validate(
            {"only_matched": True, "only_unmatched": True})


def test_blended_mer_bounds_periods():
    model = spec("get_blended_mer")[0]
    model.model_validate({"periods": 60})
    for bad in ({"periods": 0}, {"periods": 61}):
        with pytest.raises(Exception):
            model.model_validate(bad)


# ── the caveats that must reach the model ─────────────────────────────

def test_cpis_description_states_the_margin_is_a_constant():
    """Without this the model reads a flat 55% as a per-SKU measurement."""
    text = spec("get_sku_economics")[1]
    assert "0.55" in text and "CONSTANT" in text.upper()


def test_cpis_description_warns_the_two_windows_differ():
    text = spec("get_sku_economics")[1].lower()
    assert "preset" in text and "custom" in text and "32%" in text


def test_first_click_description_forbids_adding_the_revenue_pair():
    """The two columns each carry the order's FULL value and overlap."""
    text = spec("get_first_click_attribution")[1].lower()
    assert "never add" in text and "full" in text


def test_blended_mer_description_separates_blended_from_platform_claims():
    text = spec("get_blended_mer")[1].lower()
    assert "claimed" in text and "will not agree" in text


def test_unknown_tool_is_refused_not_guessed():
    out, failed = __import__("asyncio").run(
        tools.execute_analytics_tool("get_everything", {}, read_only=True))
    assert failed and "Unknown analytics tool" in out


def test_validation_errors_come_back_structured():
    out, failed = __import__("asyncio").run(
        tools.execute_analytics_tool("get_blended_mer", {"periods": 999}, read_only=True))
    assert failed
    assert json.loads(out)["validation_errors"][0]["field"] == ["periods"]
