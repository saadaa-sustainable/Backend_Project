"""Last-click evidence extraction: fallback, URL encoding and source conflicts."""

from __future__ import annotations

import pytest

from app.services.silver.shopify_utm import UTM_FIELDS, extract_order_utm


def _attrs(**values: str) -> list[dict[str, str]]:
    return [{"key": key, "value": value} for key, value in values.items()]


def _journey(**values: str) -> dict:
    return {"lastVisit": {"utmParameters": values}}


def test_checkout_values_remain_primary_and_keep_literal_plus() -> None:
    result = extract_order_utm({
        "utm_content": " SDCP+FBP_Hook ", "utm_campaign": " Summer ",
        "custom_attributes": _attrs(full_url=(
            "https://example.test/?utm_content=SDCP%2BFBP_Hook"
            "&utm_campaign=Summer&utm_source=facebook"
        )),
    })
    assert result.utm_content == "SDCP+FBP_Hook"
    assert result.utm_campaign == "Summer"
    assert result.utm_source == "facebook"
    assert result.sources == ("checkout", "checkout_url")
    assert result.conflicts == ()


def test_url_decodes_exactly_once() -> None:
    result = extract_order_utm({"custom_attributes": _attrs(
        full_url="https://example.test/?utm_content=summer+%252B+launch%2B&UTM_TERM=123",
    )})
    assert result.utm_content == "summer %2B launch+"
    assert result.utm_term == "123"
    assert result.sources == ("checkout_url",)


def test_blank_checkout_fields_permit_last_visit_fallback() -> None:
    result = extract_order_utm({
        "utm_content": "  ", "utm_campaign": "",
        "customer_journey": _journey(content="known ad", campaign="summer"),
    })
    assert result.utm_content == "known ad"
    assert result.utm_campaign == "summer"
    assert result.sources == ("last_visit",)


def test_last_visit_cannot_mix_conflicting_campaign_with_checkout_ad() -> None:
    result = extract_order_utm({
        "utm_campaign": "A", "utm_source": "facebook",
        "customer_journey": _journey(campaign="B", source="facebook", content="other ad"),
    })
    assert result.utm_campaign == "A"
    assert result.utm_content is None
    assert result.sources == ("checkout",)
    assert result.conflicts == ("last_visit:conflicting:utm_campaign",)


def test_disjoint_tuples_are_not_assumed_to_describe_same_click() -> None:
    result = extract_order_utm({
        "utm_term": "checkout adset",
        "customer_journey": _journey(content="journey ad"),
    })
    assert result.utm_content is None
    assert result.conflicts == ("last_visit:unlinked",)


def test_compatible_last_visit_may_fill_missing_fields() -> None:
    result = extract_order_utm({
        "utm_campaign": "same campaign",
        "customer_journey": _journey(campaign="same campaign", content="ad"),
    })
    assert result.utm_content == "ad"
    assert result.sources == ("checkout", "last_visit")


def test_url_cannot_override_conflicting_checkout_tuple() -> None:
    result = extract_order_utm({
        "utm_campaign": "A",
        "custom_attributes": _attrs(full_url="https://example.test/?utm_campaign=B&utm_content=ad"),
    })
    assert result.utm_campaign == "A"
    assert result.utm_content is None
    assert result.conflicts == ("checkout_url:conflicting:utm_campaign",)


def test_url_can_compare_encoded_checkout_value_without_rewriting_it() -> None:
    result = extract_order_utm({
        "utm_content": "summer%20launch",
        "custom_attributes": _attrs(
            full_url="https://example.test/?utm_content=summer%20launch&utm_term=123",
        ),
    })
    assert result.utm_content == "summer%20launch"
    assert result.utm_term == "123"


def test_first_visit_is_never_used_for_last_click() -> None:
    result = extract_order_utm({"customer_journey": {
        "firstVisit": {"utmParameters": {"content": "first ad"},
                       "landingPage": "https://example.test/?utm_content=first+ad"},
    }})
    assert result.as_dict() == dict.fromkeys(UTM_FIELDS)
    assert result.sources == ()


def test_last_visit_landing_url_fallback() -> None:
    result = extract_order_utm({"customer_journey": {"lastVisit": {
        "landingPage": "https://example.test/?utm_content=last+ad&utm_term=123",
    }}})
    assert result.utm_content == "last ad"
    assert result.utm_term == "123"
    assert result.sources == ("last_visit_url",)


def test_conflicting_last_visit_url_does_not_fill_structured_tuple() -> None:
    result = extract_order_utm({"customer_journey": {"lastVisit": {
        "utmParameters": {"campaign": "A"},
        "landingPage": "https://example.test/?utm_campaign=B&utm_content=ad",
    }}})
    assert result.utm_content is None
    assert result.conflicts == ("last_visit_url:conflicting:utm_campaign",)


def test_last_visit_url_cannot_bypass_its_conflicting_structured_visit() -> None:
    result = extract_order_utm({
        "utm_campaign": "checkout",
        "customer_journey": {"lastVisit": {
            "utmParameters": {"campaign": "different visit"},
            "landingPage": "https://example.test/?utm_campaign=checkout&utm_content=ad",
        }},
    })
    assert result.utm_content is None
    assert result.sources == ("checkout",)
    assert result.conflicts == (
        "last_visit_url:conflicting:utm_campaign", "last_visit:conflicting:utm_campaign",
    )


def test_duplicate_conflicting_url_parameters_reject_entire_url() -> None:
    result = extract_order_utm({"custom_attributes": _attrs(
        full_url="https://example.test/?utm_content=A&utm_content=B&utm_campaign=C",
    )})
    assert result.as_dict() == dict.fromkeys(UTM_FIELDS)
    assert result.conflicts == ("checkout_url:duplicate:utm_content",)


def test_duplicate_identical_url_parameters_are_usable() -> None:
    result = extract_order_utm({"custom_attributes": _attrs(
        full_url="https://example.test/?utm_content=A&utm_content=A",
    )})
    assert result.utm_content == "A"
    assert result.conflicts == ()


def test_duplicate_attribute_values_do_not_choose_arbitrary_identity() -> None:
    result = extract_order_utm({"utm_content": "A", "custom_attributes": [
        {"key": "utm_content", "value": "A"},
        {"key": "utm_content", "value": "B"},
        {"key": "utm_campaign", "value": "C"},
    ]})
    assert result.utm_content is None
    assert result.utm_campaign == "C"
    assert result.conflicts == ("checkout:duplicate:utm_content",)


def test_blank_and_case_variant_attributes_recover_missing_columns() -> None:
    result = extract_order_utm({"utm_content": "", "custom_attributes": [
        {"key": "utm_content", "value": "  "},
        {"key": "UTM_CONTENT", "value": " ad "},
        {"key": "UTM_TERM", "value": " 123 "},
    ]})
    assert result.utm_content == "ad"
    assert result.utm_term == "123"


@pytest.mark.parametrize("value", [None, "", [], 123, {"lastVisit": None}])
def test_malformed_or_absent_journey_does_not_fail(value: object) -> None:
    result = extract_order_utm({"customer_journey": value})
    assert result.as_dict() == dict.fromkeys(UTM_FIELDS)


@pytest.mark.parametrize("value", [None, "[]", {}, [None, 123, {"key": []}]])
def test_malformed_attributes_do_not_fail(value: object) -> None:
    result = extract_order_utm({"custom_attributes": value, "utm_content": "ad"})
    assert result.utm_content == "ad"


@pytest.mark.parametrize("url", [
    "http://[broken", "https://example.test/?" + "x=1&" * 257, "x" * 65_537,
])
def test_invalid_or_unbounded_urls_are_ignored(url: str) -> None:
    result = extract_order_utm({"custom_attributes": _attrs(full_url=url)})
    assert result.as_dict() == dict.fromkeys(UTM_FIELDS)
    assert result.conflicts == ("checkout_url:invalid_url",)


def test_extraction_does_not_modify_input() -> None:
    order = {"utm_campaign": "A", "custom_attributes": _attrs(
        full_url="https://example.test/?utm_campaign=A&utm_content=ad",
    )}
    before = repr(order)
    extract_order_utm(order)
    assert repr(order) == before
