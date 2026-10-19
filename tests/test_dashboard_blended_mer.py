"""MER divides two totals, so the only ways it goes wrong are quiet ones.

  * A day with revenue and no spend yet makes the ratio enormous, not
    absent. Meta reports a day behind, so this happens every morning.
  * total_sales is the column the media plan's own "Shopify Gross
    Sales" row holds; this warehouse's gross_sales is a different,
    larger figure and using it inflates every reading by ~21%.
  * Google is ~9% of spend. Dropping it lifts the ratio about 10%,
    always in the flattering direction -- the mistake this endpoint
    exists to stop.
"""

from datetime import date
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routers import analytics as A


@pytest.fixture(autouse=True)
def reset_cache():
    A.get_dashboard_blended_mer.analytics_cache.entries.clear()
    yield
    A.get_dashboard_blended_mer.analytics_cache.entries.clear()


def _session(rows, kwik_default=None):
    """rows: (day, revenue, meta_spend, google_spend[, new, ret, s_first, s_ret]).

    kwik_default seeds the Kwikchat placeholder at that daily amount on
    every day carrying spend; None leaves the table empty, which is how
    most of these tests isolate the Meta/Google arithmetic."""
    db = sqlite3.connect(":memory:")
    # Postgres GREATEST/LEAST SKIP nulls; sqlite's max()/min() return
    # NULL if any argument is. The window clamp leans on the Postgres
    # behaviour -- a source with no rows must widen the window, not
    # annihilate it -- so the shim reproduces it rather than the SQL
    # being written down to sqlite's weaker version.
    db.create_function("greatest", -1,
                       lambda *a: max([x for x in a if x is not None], default=None))
    db.create_function("least", -1,
                       lambda *a: min([x for x in a if x is not None], default=None))

    # Postgres bool_or; sqlite has no equivalent aggregate. Used to ask
    # whether ANY day in a group still carries the Kwikchat estimate.
    class _BoolOr:
        def __init__(self): self.v = False
        def step(self, value): self.v = self.v or bool(value)
        def finalize(self): return self.v
    db.create_aggregate("bool_or", 1, _BoolOr)
    db.executescript("""
        CREATE TABLE shopify_sales_daily(day TEXT, total_sales NUMERIC, gross_sales NUMERIC,
            new_customers INTEGER, returning_customers INTEGER,
            total_sales_first_time NUMERIC, total_sales_returning NUMERIC);
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend NUMERIC);
        CREATE TABLE google_ads_spend_daily(day TEXT, campaign_id TEXT, spend NUMERIC);
        CREATE TABLE kwikchat_spend_daily(day TEXT, spend NUMERIC, is_estimate INTEGER);
    """)
    for row in rows:
        day, rev, meta, goog = row[:4]
        # Kwikchat is seeded for every day that has any spend at all,
        # as the placeholder script does. `kwik` on the fixture row
        # overrides the amount; None omits the day entirely.
        if kwik_default is not None and (meta is not None or goog is not None):
            db.execute("INSERT INTO kwikchat_spend_daily VALUES (?,?,1)", (day, kwik_default))
        # Customer columns default to a 2:1 new/returning split and a
        # 60/40 revenue split unless a test states its own.
        new_c, ret_c, s_first, s_ret = (row[4:] if len(row) > 4
                                        else (20, 10, rev * 0.6, rev * 0.4))
        # gross_sales deliberately inflated, so a regression that reads
        # the wrong column fails loudly instead of plausibly.
        db.execute("INSERT INTO shopify_sales_daily VALUES (?,?,?,?,?,?,?)",
                   (day, rev, rev * 1.21, new_c, ret_c, s_first, s_ret))
        if meta is not None:
            db.execute("INSERT INTO insights_daily_by_ad VALUES ('a',?,?)", (day, meta))
        if goog is not None:
            db.execute("INSERT INTO google_ads_spend_daily VALUES (?,'c',?)", (day, goog))

    async def execute(query, params=None):
        sql = str(query).replace("public.", "")
        bound = {k: (v.isoformat() if isinstance(v, date) else v)
                 for k, v in (params or {}).items()}
        cur = db.execute(sql, bound)
        cols = [c[0] for c in cur.description]
        dicts = [dict(zip(cols, r)) for r in cur.fetchall()]
        for d in dicts:
            if isinstance(d.get("day"), str):
                d["day"] = date.fromisoformat(d["day"])
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: dicts))

    return SimpleNamespace(execute=AsyncMock(side_effect=execute)), db


async def test_mer_is_revenue_over_both_platforms():
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0),
                      ("2026-09-02", 2000.0, 300.0, 50.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-02")
    assert r.revenue == 3000
    assert r.meta_spend == 500
    assert r.google_spend == 100
    assert r.total_spend == 600
    assert r.mer == 5.0
    db.close()


async def test_dropping_google_would_flatter_the_ratio():
    """The whole reason Google was ingested: same revenue, smaller
    denominator, a number that is wrong in the comfortable direction."""
    s, db = _session([("2026-09-01", 4700.0, 1192.0, 122.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    meta_only = 4700.0 / 1192.0
    assert r.mer < meta_only
    assert round(meta_only / r.mer, 2) == 1.10  # ~10% overstatement
    db.close()


async def test_a_gap_in_the_MIDDLE_yields_no_ratio_for_that_day():
    """The clamp removes the trailing reporting lag, not a day both
    platforms straddle. That day's point must be null, not a vast
    number -- but its revenue still counts toward the window, because
    it happened."""
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0),
                      ("2026-09-02", 2000.0, None, None),
                      ("2026-09-03", 1000.0, 300.0, 50.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-03")
    assert r.points[1].mer is None
    assert r.points[0].mer == 4.0
    assert r.revenue == 4000
    assert r.days_missing_meta == 1
    db.close()


async def test_missing_spend_days_INSIDE_the_window_are_counted_not_hidden():
    """Both gaps have to be straddled by reporting days, or the clamp
    simply cuts them off the end -- which is what it is for."""
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0),
                      ("2026-09-02", 2000.0, None, 50.0),
                      ("2026-09-03", 1500.0, 100.0, None),
                      ("2026-09-04", 1000.0, 200.0, 50.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-04")
    assert (r.window_from, r.window_to) == (date(2026, 9, 1), date(2026, 9, 4))
    assert r.days_missing_meta == 1
    assert r.days_missing_google == 1
    db.close()


async def test_a_day_with_no_revenue_is_not_counted_as_a_gap():
    """A day the store took nothing is not a reporting lag."""
    s, db = _session([("2026-09-01", 0.0, None, None)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.days_missing_meta == 0
    assert r.days_missing_google == 0
    db.close()


async def test_google_share_of_spend_is_reported():
    s, db = _session([("2026-09-01", 4700.0, 1192.0, 122.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.google_share_of_spend == round(100 * 122 / (1192 + 122), 1)
    db.close()


async def test_no_spend_at_all_yields_no_ratio_rather_than_zero():
    s, db = _session([("2026-09-01", 1000.0, None, None)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.mer is None
    assert r.google_share_of_spend is None
    db.close()


async def test_the_window_clamps_to_the_days_both_platforms_cover():
    """Meta reports a day behind Google. Without the clamp the last day
    contributes revenue and Google spend against no Meta spend, and the
    ratio reads high."""
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0),
                      ("2026-09-02", 1000.0, 200.0, 50.0),
                      ("2026-09-03", 9000.0, None, 50.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-03")
    assert r.window_from == date(2026, 9, 1)
    assert r.window_to == date(2026, 9, 2)
    assert r.window_clamped is True
    # The third day is outside the window entirely: its revenue is not
    # counted against a denominator that cannot cover it.
    assert r.revenue == 2000
    assert r.mer == 4.0
    assert r.days_missing_meta == 0
    db.close()


async def test_revenue_is_cut_to_the_same_window_as_spend():
    """A numerator covering more days than its denominator is the same
    error in the other direction."""
    s, db = _session([("2026-09-01", 5000.0, None, None),
                      ("2026-09-02", 1000.0, 200.0, 50.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-02")
    assert r.window_from == date(2026, 9, 2)
    assert r.revenue == 1000
    assert r.mer == 4.0
    db.close()


async def test_a_fully_covered_range_is_not_clamped():
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0),
                      ("2026-09-02", 2000.0, 300.0, 50.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-02")
    assert r.window_clamped is False
    assert (r.window_from, r.window_to) == (date(2026, 9, 1), date(2026, 9, 2))
    db.close()


async def test_returning_revenue_pct_matches_the_media_plan():
    """returning / (first-time + returning) -- the one D2C ratio whose
    formula the plan and this endpoint agree on exactly."""
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0, 20, 10, 600.0, 400.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.returning_revenue_pct == 40.0
    assert r.sales_first_time == 600
    assert r.sales_returning == 400
    db.close()


async def test_returning_customer_pct_does_not_double_count_the_new_cohort():
    """The plan's cell is W31/SUM(W29:W31), spanning NEW CUSTOMERS, the
    RTO-adjusted repeat of that same cohort, and RETURNING -- so the new
    customers land in the denominator twice and the figure comes out
    near half. This divides by new + returning only."""
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0, 30, 10, 600.0, 400.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.returning_customer_pct == 25.0           # 10 / (30 + 10)
    doubled = round(100 * 10 / (30 + 30 + 10), 2)     # the plan's shape
    assert doubled == 14.29
    assert r.returning_customer_pct != doubled
    db.close()


async def test_blended_cac_is_spend_over_new_customers():
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0, 25, 10, 600.0, 400.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.blended_cac == 10.0      # (200 + 50) / 25
    assert r.new_customers == 25
    assert r.returning_customers == 10
    db.close()


async def test_customer_metrics_respect_the_clamped_window():
    """They are summed from the same rows the ratio uses, so a day cut
    off the end must not contribute customers either."""
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0, 20, 10, 600.0, 400.0),
                      ("2026-09-02", 9000.0, None, 50.0, 999, 999, 5000.0, 4000.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-02")
    assert r.window_to == date(2026, 9, 1)
    assert r.new_customers == 20
    assert r.returning_customers == 10
    db.close()


async def test_no_customers_yields_no_cac_rather_than_a_division_error():
    s, db = _session([("2026-09-01", 1000.0, 200.0, 50.0, 0, 0, 0.0, 0.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.blended_cac is None
    assert r.returning_customer_pct is None
    assert r.returning_revenue_pct is None
    db.close()


async def test_kwikchat_joins_the_denominator_and_lowers_the_ratio():
    """Omitting it was not neutral -- every spend-divided figure read
    high. Sep 2026 measured 3.58x without and 3.35x with."""
    s, db = _session([("2026-09-01", 1000.0, 150.0, 50.0)], kwik_default=50.0)
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.kwikchat_spend == 50
    assert r.total_spend == 250
    assert r.mer == 4.0                      # 1000 / 250, not 1000 / 200
    db.close()


async def test_estimated_kwikchat_days_are_counted_so_the_card_can_say_so():
    s, db = _session([("2026-09-01", 1000.0, 150.0, 50.0),
                      ("2026-09-02", 1000.0, 150.0, 50.0)], kwik_default=30.0)
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-02")
    assert r.kwikchat_estimated_days == 2
    assert r.kwikchat_spend == 60
    db.close()


async def test_kwikchat_absent_leaves_the_ratio_on_meta_and_google():
    """The table may simply not be seeded for a range; that must not
    error, and must not silently count zero as a measured figure."""
    s, db = _session([("2026-09-01", 1000.0, 150.0, 50.0)])
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-01")
    assert r.kwikchat_spend == 0
    assert r.kwikchat_estimated_days == 0
    assert r.mer == 5.0
    db.close()


async def test_kwikchat_does_not_widen_or_narrow_the_window():
    """The clamp is the days Meta and Google both report. A flat
    placeholder must not get a vote on the range it is measured over."""
    s, db = _session([("2026-09-01", 1000.0, 150.0, 50.0),
                      ("2026-09-02", 9000.0, None, 50.0)], kwik_default=50.0)
    r = await A.get_dashboard_blended_mer(s, "2026-09-01", "2026-09-02")
    assert r.window_to == date(2026, 9, 1)
    assert r.kwikchat_spend == 50
    db.close()


def test_the_numerator_is_total_sales_not_gross_sales():
    """The media plan's "Shopify Gross Sales" row is this warehouse's
    total_sales column -- verified to the rupee for Aug and Sep 2026.
    gross_sales is a larger, different figure living in the same table,
    so the column name alone invites exactly the wrong pick."""
    assert "SUM(s.total_sales)" in A._BLENDED_MER_SQL
    assert "gross_sales" not in A._BLENDED_MER_SQL


def test_both_spend_sources_are_in_the_denominator():
    assert "insights_daily_by_ad" in A._BLENDED_MER_SQL
    assert "google_ads_spend_daily" in A._BLENDED_MER_SQL


def test_spend_is_summed_per_day_before_joining():
    """insights_daily_by_ad is one row per AD per day. Joining it
    unaggregated would multiply revenue by the number of ads running
    that day -- hundreds of them."""
    assert re.search(r"SELECT i\.day, SUM\(i\.spend\).*FROM public\.insights_daily_by_ad",
                     A._BLENDED_MER_SQL, re.S)
