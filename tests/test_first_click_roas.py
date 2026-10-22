"""First/last-click ROAS: guarded by a minimum spend, absent at source grain.

The two columns divide each side's revenue by the ENTITY's window spend.
Two things must hold and neither is obvious from the column name:

  * Below `_ROAS_MIN_SPEND` the quotient is noise, not a rate. Measured
    2026-10-22 at ad grain over the 30 days to 2026-10-21, median
    first-click ROAS ran 812x in the Rs 1-100 spend band and 20.6x in
    Rs 100-1k, against 2.3x at Rs 1k-10k and 1.6x above Rs 10k. Only 17
    of 316 rows sat under the line, but sorted by ROAS they filled the
    first page -- the top row was an ad with Rs 1.48 of window spend
    reading 46,672x.

  * Source grain has no Meta spend at all, so both columns must come
    back NULL rather than 0 there.
"""
import pytest

from app.api.routers import analytics


def test_threshold_is_the_measured_one():
    assert analytics._ROAS_MIN_SPEND == 1000


@pytest.mark.parametrize("grain", ["ad", "adset"])
def test_id_grains_guard_the_denominator(grain):
    sql = analytics._first_click_sql(grain)
    assert "first_click_roas" in sql and "last_click_roas" in sql
    # The guard is >= the threshold, never a bare > 0: a few hundred
    # rupees of spend is what produced the 812x median.
    assert f"sp.spend >= {analytics._ROAS_MIN_SPEND}" in sql
    assert "sp.spend > 0" not in sql


def test_source_grain_has_no_spend_to_divide_by():
    sql = analytics._first_click_sql("source")
    # NULL::numeric is the spend expression at source grain, so both
    # CASE arms are unsatisfiable and the columns come back NULL.
    assert "NULL::numeric AS spend" in sql
    assert "insights_daily_by_ad" not in sql
    assert "first_click_roas" in sql and "last_click_roas" in sql


def test_both_roas_columns_are_sortable():
    assert "first_click_roas" in analytics._FIRST_CLICK_SORTS
    assert "last_click_roas" in analytics._FIRST_CLICK_SORTS


def test_revenue_pair_is_still_full_credit_on_both_sides():
    """The ROAS pair inherits the revenue pair's overlap, so this must hold."""
    sql = analytics._first_click_sql("ad")
    assert "FILTER (WHERE side = 'first')" in sql
    assert "FILTER (WHERE side = 'last')" in sql
