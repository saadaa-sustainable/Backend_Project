"""The `basis` toggle: what the selected window MEANS for each side.

The last touch IS the session that converted, so it sits on the order's
own day -- windowing it by order date and by last-touch date are the same
thing. The first touch can sit weeks earlier. Measured over 26 Sep to
25 Oct 2026 at ad grain, 30.4% of orders (Rs 85.2L, 31.2% of first-click
revenue) were opened BEFORE the window, average 14.9 days to convert and
up to 89. On the default basis that revenue is divided by spend from a
window which did not contain the click that earned it, so first-click
ROAS read 2.98 against 2.03 on one real ad and 2.05 against 1.54 on
another, while an ad whose whole life sat inside the window was
unchanged.

What must hold:

  * The last-click side is byte-identical under both bases. Anything
    else means the toggle leaked across the UNION.
  * Spend is unchanged too -- `basis` moves the revenue window, never
    the billing window.
  * On the default, the two sides still share one predicate, so the
    section keeps reconciling against the last-click table.
"""
import pytest

from app.api.routers import analytics

GRAINS = ("ad", "adset", "source")


@pytest.mark.parametrize("grain", GRAINS)
def test_order_basis_windows_both_sides_on_the_order_date(grain):
    sql = analytics._first_click_sql(grain, "order")
    assert "first_seen_at" not in sql
    assert sql.count("order_at >=") == 2, "both sides must share the order predicate"


@pytest.mark.parametrize("grain", GRAINS)
def test_first_touch_basis_moves_only_the_first_side(grain):
    sql = analytics._first_click_sql(grain, "first_touch")
    # Exactly one side switched columns: first on first_seen_at, last
    # still on order_at.
    assert sql.count("first_seen_at >=") == 1
    assert sql.count("order_at >=") == 1


@pytest.mark.parametrize("grain", GRAINS)
def test_last_click_side_is_identical_under_both_bases(grain):
    """The clause that builds the last-click rows must not move."""
    marker = "'last'::text"
    a = analytics._first_click_sql(grain, "order")
    b = analytics._first_click_sql(grain, "first_touch")
    assert a[a.index(marker):] == b[b.index(marker):]


@pytest.mark.parametrize("grain", ("ad", "adset"))
def test_spend_window_is_untouched_by_basis(grain):
    """basis moves the revenue window, never the billing window."""
    for b in ("order", "first_touch"):
        sql = analytics._first_click_sql(grain, b)
        assert "day BETWEEN CAST(:from_date AS date) AND CAST(:to_date AS date)" in sql


def test_basis_defaults_to_order():
    import inspect
    sig = inspect.signature(analytics._first_click_sql)
    assert sig.parameters["basis"].default == "order"
    assert analytics._first_click_sql("ad") == analytics._first_click_sql("ad", "order")


@pytest.mark.parametrize("grain", GRAINS)
def test_every_sortable_column_survives_both_bases(grain):
    """The guard in test_first_click_roas, re-asserted per basis."""
    for b in ("order", "first_touch"):
        sql = analytics._first_click_sql(grain, b)
        for key in analytics._FIRST_CLICK_SORTS.values():
            assert key in sql, f"{key} missing from {grain}/{b} SQL"
