"""The hourly tracker's day-level rollups: source ranking and AOV.

Both share one trap. A figure summed over a day is not the average of
the hourly figures, and neither would raise if it were -- the page
would just quietly show a number nobody could reconcile against the
table under it.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.api.routers.analytics import (
    _EXCLUDED_ORDER_SQL,
    _TOP_SOURCES,
    HourlyRow,
    _derive_hourly,
    _rank_sources,
    _totals,
)
from scripts.fetch_hourly_tracker import (
    distribute_daily,
    is_excluded_order,
    is_pnl_excluded,
    is_unsettled,
)
from scripts.import_kwikchat_spend import parse_amount, parse_day


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
    # Return Prime: the order IS the return leg, not an order that was
    # later returned, so no tag rescues it.
    (None, ["Return_Prime"], True, "a return flowing back is not revenue"),
    (None, ["return_prime"], True, "typed by hand, so never case-stable"),
    (None, [" RETURN_PRIME "], True, "nor whitespace-stable"),
    (None, ["Return_Prime", "Exchange"], True,
     "Exchange rescues a plain Return, NOT a Return Prime leg"),
    # `inf` stays IN the tracker on purpose, though the P&L drops it.
    (None, ["inf"], False, "a report order is still something the hour produced"),
    (None, ["influencer-order"], False, "same, under its other spelling"),
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


# --- settling a closed day --------------------------------------------
# The hour a run writes is the hour in progress, so it is partial by
# construction. Fine while the day is live; not fine at midnight, when
# the date rolls over and nothing goes back for the rest of it.

def _ist(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_a_day_last_written_before_its_midnight_is_unsettled():
    """The bug this exists for: 30 Oct frozen at 23:16 IST, missing the
    last forty-four minutes of orders permanently."""
    assert is_unsettled(date(2026, 10, 30), _ist(2026, 10, 30, 23, 16), 23) is True


def test_a_day_rewritten_after_its_midnight_is_settled():
    assert is_unsettled(date(2026, 10, 30), _ist(2026, 10, 31, 0, 20), 23) is False


def test_a_day_missing_its_final_hours_is_unsettled():
    """Written after midnight but short of hour 23 -- a run that died
    partway, or a day whose late hours never arrived."""
    assert is_unsettled(date(2026, 10, 30), _ist(2026, 10, 31, 3, 0), 19) is True


def test_a_day_never_ingested_is_not_settled_but_left_alone():
    """Absent is a backfill, not a settle. Tidying the edge of yesterday
    must never silently fill a hole in history."""
    assert is_unsettled(date(2026, 1, 1), None, None) is False


def test_the_boundary_is_the_day_s_own_midnight():
    midnight = _ist(2026, 10, 31, 0, 0)
    assert is_unsettled(date(2026, 10, 30), midnight - timedelta(seconds=1), 23) is True
    assert is_unsettled(date(2026, 10, 30), midnight, 23) is False


# --- the P&L population is not the revenue population -----------------
# The tracker drops a cancelled order outright. The P&L keeps it, counts
# it, and deducts it on its own line -- so the deduction can be read
# instead of assumed. These two rules must not collapse into one.

def test_pnl_keeps_the_orders_the_tracker_drops():
    """A cancelled, untagged order: out of revenue, in the P&L basis."""
    assert is_excluded_order("2026-10-30T10:00:00Z", []) is True
    assert is_pnl_excluded([]) is False


def test_pnl_drops_the_report_and_return_prime_tags():
    assert is_pnl_excluded(["inf"]) is True
    assert is_pnl_excluded(["influencer-order"]) is True
    assert is_pnl_excluded(["Return_Prime"]) is True
    # Typed by hand, so never case- or whitespace-stable.
    assert is_pnl_excluded([" RETURN_PRIME "]) is True
    assert is_pnl_excluded(["Exchange", "Prepaid"]) is False
    assert is_pnl_excluded(None) is False


def test_a_cancelled_report_order_is_out_of_both():
    """The two rules overlap rather than partition, and that is fine --
    what must not happen is one of them quietly deciding the other."""
    assert is_excluded_order("2026-10-30T10:00:00Z", ["inf"]) is True
    assert is_pnl_excluded(["inf"]) is True


# --- the Kwikchat export ----------------------------------------------
# A manual CSV download, so its two fragile fields are parsed here
# rather than trusted: Indian digit grouping, and a day/month order that
# the American reading would silently swap.

@pytest.mark.parametrize("raw, want, why", [
    ("\u20b90", 0.0, "a day with no spend"),
    ("\u20b966.7", 66.7, "no grouping needed"),
    ("\u20b94,921.42", 4921.42, "thousands separator"),
    ("\u20b980,717.01", 80717.01, "the blast days are five figures"),
    ("\u20b91,00,000.50", 100000.5, "Indian grouping is not every three digits"),
    ("  \u20b9 1,234  ", 1234.0, "padded by the export"),
    ("", 0.0, "an empty cell is no spend, not a crash"),
    ("-", 0.0, "a dash is how the console writes nothing"),
])
def test_parse_amount(raw, want, why):
    assert parse_amount(raw) == pytest.approx(want), why


def test_dates_are_read_day_first():
    """03-10-2026 is the third of October. Read the American way it is
    the tenth of March, and a month of spend lands in the wrong month
    without anything failing."""
    assert parse_day("03-10-2026") == date(2026, 10, 3)
    assert parse_day("31-10-2026") == date(2026, 10, 31)


def test_an_impossible_date_is_refused_rather_than_rolled():
    with pytest.raises(ValueError):
        parse_day("32-10-2026")
    with pytest.raises(ValueError):
        parse_day("2026-10-03")


# --- the two rules overlap on Return_Prime and disagree on inf --------

def test_both_rules_drop_return_prime():
    """It is a return flowing backwards. Neither question it is not a
    sale, so neither population counts it."""
    assert is_excluded_order(None, ["Return_Prime"]) is True
    assert is_pnl_excluded(["Return_Prime"]) is True


def test_only_the_pnl_drops_report_orders():
    """The one tag the two rules deliberately disagree about.

    The P&L asks what the day EARNED, and goods that went out with no
    sale behind them earned nothing. The tracker asks what the hour
    PRODUCED, and a report order is still something it produced.

    Asserted rather than assumed: if someone ever makes these agree it
    should be a decision, not a quiet edit.
    """
    assert is_excluded_order(None, ["inf"]) is False
    assert is_pnl_excluded(["inf"]) is True


def test_exchange_rescues_a_return_but_not_a_return_prime():
    """An Exchange tag means the money stayed, which is true of a swap
    and not of a return leg."""
    assert is_excluded_order(None, ["Return", "Exchange"]) is False
    assert is_excluded_order(None, ["Return_Prime", "Exchange"]) is True
