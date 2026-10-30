"""The hourly tracker's day-level rollups: source ranking and AOV.

Both share one trap. A figure summed over a day is not the average of
the hourly figures, and neither would raise if it were -- the page
would just quietly show a number nobody could reconcile against the
table under it.
"""
from datetime import date, datetime, timezone

import pytest

from app.api.routers.analytics import (
    _EXCLUDED_ORDER_SQL,
    _TOP_SOURCES,
    HourlyRow,
    _derive_hourly,
    _rank_sources,
    _totals,
)
from scripts.fetch_hourly_tracker import distribute_daily, is_excluded_order


def row(hour: int, by_source: dict[str, int] | None) -> HourlyRow:
    """An hour carrying nothing but its source split.

    Every other field is filled with None off the model itself rather
    than listed here, so adding a metric to HourlyRow does not break
    this file.
    """
    fields = {k: None for k in HourlyRow.model_fields}
    return HourlyRow(**{
        **fields,
        "hour": f"2026-10-30T{hour:02d}:00:00+00:00",
        "day_ist": "2026-10-30",
        "hour_of_day": hour,
        "sessions": sum((by_source or {}).values()) or None,
        "sessions_by_source": by_source,
    })


def _h(n: int) -> datetime:
    """The UTC instant starting IST hour n, which is how hours are keyed."""
    return datetime(2026, 10, 30, n, tzinfo=timezone.utc)


def _blank() -> dict:
    """The raw mapping _derive_hourly expects: every stored column, none
    of the derived ones (it fills those itself)."""
    derived = {"spend", "cost_per_session", "cost_per_paid_session", "pct_paid",
               "pct_direct", "revenue_per_session", "revenue_per_meta_session",
               "revenue_per_google_session", "revenue_per_paid_session", "aov",
               "conversion_rate", "conversion_rate_paid", "conversion_rate_direct",
               "amer", "ga4_arpu"}
    # `spend` is derived, but its three components are stored columns.
    m = {k: None for k in HourlyRow.model_fields if k not in derived}
    m.update(hour="2026-10-30T01:00:00+00:00", day_ist="2026-10-30", hour_of_day=1)
    return m


def test_sums_across_hours():
    out = _rank_sources([row(1, {"meta": 10, "google": 3}),
                         row(2, {"meta": 5, "google": 1})])
    assert [(s.source, s.sessions) for s in out] == [("meta", 15), ("google", 4)]


def test_folds_case_variants_into_one_slice():
    """META/Meta/meta are one hand-typed tag, not three sources."""
    out = _rank_sources([row(1, {"META": 10, "Meta": 5, "  meta ": 2})])
    assert [(s.source, s.sessions) for s in out] == [("meta", 17)]


def test_blank_source_counts_as_direct():
    out = _rank_sources([row(1, {"": 4, "(direct)": 6})])
    assert [(s.source, s.sessions) for s in out] == [("(direct)", 10)]


def test_tail_folds_into_one_other_slice():
    by_source = {f"src{i}": 100 - i for i in range(12)}
    out = _rank_sources([row(1, by_source)])
    # Six slices at most: five named plus the fold. Any more and the
    # six-colour categorical palette would have to repeat a hue.
    assert len(out) == _TOP_SOURCES + 1
    assert out[-1].source == "other"
    assert out[-1].sessions == sum(sorted(by_source.values())[:-_TOP_SOURCES])


def test_no_other_slice_when_nothing_is_left_over():
    out = _rank_sources([row(1, {"a": 3, "b": 2})])
    assert [s.source for s in out] == ["a", "b"]


def test_shares_are_fractions_of_the_day_and_sum_to_one():
    out = _rank_sources([row(1, {f"src{i}": i + 1 for i in range(9)})])
    assert sum(s.share for s in out) == pytest.approx(1.0)
    total = sum(s.sessions for s in out)
    assert all(s.share == pytest.approx(s.sessions / total) for s in out)


def test_ties_break_by_name_so_colours_do_not_shuffle():
    """Equal sources must rank in a stable order.

    The page assigns colours by position, so an unstable sort would
    repaint a source a different colour between two refreshes that
    found the same numbers.
    """
    first = _rank_sources([row(1, {"zeta": 5, "alpha": 5, "mid": 5})])
    assert [s.source for s in first] == ["alpha", "mid", "zeta"]


def test_hours_without_a_source_map_are_skipped():
    """Rows written before the column existed are null, not empty."""
    out = _rank_sources([row(1, None), row(2, {"meta": 7}), row(3, {})])
    assert [(s.source, s.sessions) for s in out] == [("meta", 7)]


def test_a_day_with_no_sessions_yields_no_slices():
    assert _rank_sources([]) == []
    assert _rank_sources([row(1, {"meta": 0})]) == []


# --- AOV --------------------------------------------------------------
# Revenue over ORDERS. Kept in this file because it shares the fixture,
# and because it is the same trap the rollup has: a ratio summed from
# counts is not the average of the hourly ratios.

def order_row(hour: int, revenue: float | None, orders: int | None) -> HourlyRow:
    r = row(hour, None)
    return r.model_copy(update={
        "revenue": revenue, "orders": orders,
        "aov": (revenue / orders) if (revenue is not None and orders) else None,
    })


def test_hourly_aov_is_revenue_over_orders():
    assert _derive_hourly({**_blank(), "revenue": 5000.0, "orders": 4}).aov == 1250.0


def test_an_hour_with_no_orders_has_no_aov():
    """NULL, not zero: no orders is not a basket worth ₹0."""
    assert _derive_hourly({**_blank(), "revenue": 0.0, "orders": 0}).aov is None


def test_day_aov_is_redivided_not_averaged():
    """The whole point of deriving totals from the summed counts.

    One big-basket hour with a single order must not weigh the same as
    a busy hour with many. Averaging these two gives 1,100; the honest
    figure is 505.
    """
    rows = [order_row(1, 2000.0, 1), order_row(2, 8100.0, 40)]
    t = _totals(date(2026, 10, 30), rows)
    assert t is not None
    assert t.aov == pytest.approx(10100 / 41)
    hourly_mean = sum(r.aov for r in rows) / len(rows)
    assert t.aov != pytest.approx(hourly_mean)


def test_day_with_orders_but_no_revenue_still_has_an_aov():
    t = _totals(date(2026, 10, 30), [order_row(1, 0.0, 3)])
    assert t is not None and t.aov == 0.0


def test_day_with_no_orders_has_no_aov():
    t = _totals(date(2026, 10, 30), [order_row(1, 500.0, 0)])
    assert t is not None and t.aov is None


# --- what the tracker counts as revenue -------------------------------
# Deliberately NOT the dashboard's rule. The tracker asks what a
# campaign hour brought in, so an equal-value exchange still counts;
# the dashboard asks what we ended up keeping, so it does not.

@pytest.mark.parametrize("cancelled, tags, excluded, why", [
    (None, [], False, "a plain order"),
    ("2026-10-30T10:00:00Z", [], True, "cancelled"),
    ("2026-10-30T10:00:00Z", ["Exchange"], True, "cancelled beats every tag"),
    (None, ["Return"], True, "returned -- the money went back"),
    (None, ["Exchange"], False, "swapped for equal value, money stayed"),
    (None, ["Return", "Exchange"], False, "the exchange leg of a swap"),
    (None, ["return"], True, "Shopify tags are not case-stable"),
    (None, ["Prepaid", " RETURN "], True, "tag lists carry unrelated tags"),
    (None, None, False, "an order with no tags at all"),
])
def test_tracker_exclusion_rule(cancelled, tags, excluded, why):
    assert is_excluded_order(cancelled, tags) is excluded, why


def test_tracker_and_dashboard_disagree_on_exchanges_on_purpose():
    """A guard on the one case the two products answer differently.

    If someone ever makes these agree, it should be a decision, not a
    quiet edit -- so the divergence is asserted rather than assumed.
    """
    assert is_excluded_order(None, ["Exchange"]) is False
    assert "jsonb_exists(o.tags, 'Exchange')" in _EXCLUDED_ORDER_SQL


# --- conversion rate --------------------------------------------------

def test_hourly_conversion_rates_use_matching_denominators():
    r = _derive_hourly({**_blank(), "sessions": 1000, "sessions_paid": 800,
                        "sessions_direct": 200, "orders": 20,
                        "orders_paid": 12, "orders_direct": 8})
    assert r.conversion_rate == pytest.approx(0.02)
    assert r.conversion_rate_paid == pytest.approx(12 / 800)
    assert r.conversion_rate_direct == pytest.approx(8 / 200)


def test_an_hour_with_no_sessions_has_no_conversion_rate():
    r = _derive_hourly({**_blank(), "sessions": 0, "orders": 0})
    assert r.conversion_rate is None


def test_day_conversion_rate_is_redivided():
    rows = [_derive_hourly({**_blank(), "sessions": 100, "orders": 10}),
            _derive_hourly({**_blank(), "sessions": 900, "orders": 9})]
    t = _totals(date(2026, 10, 30), rows)
    assert t is not None
    assert t.conversion_rate == pytest.approx(19 / 1000)
    # Averaging the two hourly rates would give 5.5%, nearly triple.
    assert t.conversion_rate != pytest.approx(sum(r.conversion_rate for r in rows) / 2)


def test_a_day_ingested_before_the_split_existed_reports_no_split_cr():
    """Absent is not zero.

    Hours written before orders_paid existed are NULL, and summing
    NULLs gives 0 -- which would render as a confident "0.00%" and look
    like a day that sold nothing to paid traffic.
    """
    rows = [_derive_hourly({**_blank(), "sessions": 1000, "sessions_paid": 800,
                            "sessions_direct": 200, "orders": 20})]
    t = _totals(date(2026, 10, 29), rows)
    assert t is not None
    assert t.conversion_rate == pytest.approx(0.02)
    assert t.conversion_rate_paid is None
    assert t.conversion_rate_direct is None


def test_a_day_that_genuinely_sold_nothing_to_paid_reports_zero():
    """The other side of it: a real 0 must survive."""
    rows = [_derive_hourly({**_blank(), "sessions": 1000, "sessions_paid": 800,
                            "sessions_direct": 200, "orders": 5,
                            "orders_paid": 0, "orders_direct": 5})]
    t = _totals(date(2026, 10, 30), rows)
    assert t is not None and t.conversion_rate_paid == 0.0


# --- spend distribution -----------------------------------------------
# Google and Kwikchat are DAILY totals. Only Meta is measured hourly,
# so the other two are shared out -- and a share-out that does not sum
# back to the total is just a wrong number with extra steps.

def test_distribution_sums_back_to_the_daily_total():
    w = {_h(0): 100.0, _h(1): 300.0, _h(2): 50.0}
    out = distribute_daily(10_932.0, w)
    assert sum(out.values()) == pytest.approx(10_932.0)


def test_distribution_follows_the_weights():
    out = distribute_daily(1000.0, {_h(0): 100.0, _h(1): 300.0})
    assert out[_h(0)] == pytest.approx(250.0)
    assert out[_h(1)] == pytest.approx(750.0)


def test_an_hour_with_no_google_traffic_gets_no_google_spend():
    out = distribute_daily(1000.0, {_h(0): 0.0, _h(1): 1.0})
    assert out[_h(0)] == 0.0
    assert out[_h(1)] == pytest.approx(1000.0)


def test_a_day_with_no_google_traffic_falls_back_to_an_even_split():
    """A worse answer, but the only one left -- and it still totals."""
    out = distribute_daily(900.0, {_h(0): 0.0, _h(1): 0.0, _h(2): 0.0})
    assert set(out.values()) == {300.0}
    assert sum(out.values()) == pytest.approx(900.0)


def test_distributing_over_no_hours_yields_nothing():
    assert distribute_daily(1000.0, {}) == {}


def test_spend_is_all_three_channels():
    r = _derive_hourly({**_blank(), "sessions": 100, "meta_spend": 1000.0,
                        "kwikchat_spend": 1250.0, "google_spend": 450.0})
    assert r.spend == pytest.approx(2700.0)
    assert r.cost_per_session == pytest.approx(27.0)


def test_an_hour_past_the_google_capture_still_has_a_spend():
    """google_spend NULL means 'not told yet', not 'everything is null'.

    The hour still spent on Meta and Kwikchat, and dropping its whole
    spend because one component is unknown would put a hole in the
    middle of the cost curve.
    """
    r = _derive_hourly({**_blank(), "sessions": 100, "meta_spend": 1000.0,
                        "kwikchat_spend": 1250.0, "google_spend": None})
    assert r.spend == pytest.approx(2250.0)
