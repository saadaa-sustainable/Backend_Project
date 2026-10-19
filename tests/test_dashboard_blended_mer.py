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


def _session(rows):
    """rows: (day, revenue, meta_spend, google_spend)."""
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
    db.executescript("""
        CREATE TABLE shopify_sales_daily(day TEXT, total_sales NUMERIC, gross_sales NUMERIC);
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend NUMERIC);
        CREATE TABLE google_ads_spend_daily(day TEXT, campaign_id TEXT, spend NUMERIC);
    """)
    for day, rev, meta, goog in rows:
        # gross_sales deliberately inflated, so a regression that reads
        # the wrong column fails loudly instead of plausibly.
        db.execute("INSERT INTO shopify_sales_daily VALUES (?,?,?)", (day, rev, rev * 1.21))
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
