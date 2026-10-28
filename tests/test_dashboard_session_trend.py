"""Daily trend ratios must retain the cards' sources and never join raw grains."""

from datetime import date
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.exc import DBAPIError

from app.api.deps import get_session
from app.api.routers import analytics


@pytest.fixture(autouse=True)
def reset_cache():
    analytics.get_dashboard_session_trend.analytics_cache.entries.clear()
    yield
    analytics.get_dashboard_session_trend.analytics_cache.entries.clear()


@pytest.fixture
def session():
    db = sqlite3.connect(":memory:")
    # btrim is Postgres' name for the standard no-argument trim, and the
    # Meta source rule shared with the session rollup uses it.
    db.create_function("btrim", 1, lambda v: v.strip() if v is not None else None)
    db.executescript("""
        -- The trend reads meta_sessions, not sessions. `sessions` is
        -- deliberately larger on every row so a regression that reads
        -- the all-traffic column again fails loudly on the ratios
        -- rather than quietly returning a plausible smaller number.
        CREATE TABLE shopify_sessions_daily(
            day TEXT PRIMARY KEY, sessions NUMERIC, meta_sessions NUMERIC);
        INSERT INTO shopify_sessions_daily VALUES
            ('2026-09-30',900,100), ('2026-10-01',900,100), ('2026-10-02',900,0),
            ('2026-10-03',900,200), ('2026-10-05',900,100), ('2026-10-06',900,100),
            ('2026-10-07',900,100);
        -- Daily ARPU. The mobile row must never reach the line: a
        -- person on two devices in one day would be counted twice.
        -- 2 Oct is deliberately absent, so the series has a real gap.
        CREATE TABLE ga4_arpu_daily(
            day TEXT, device_category TEXT, active_users INTEGER, total_revenue NUMERIC,
            sessions INTEGER, purchases INTEGER);
        INSERT INTO ga4_arpu_daily VALUES
            ('2026-10-01','(all)',  100, 2500, 250, 5),
            ('2026-10-01','mobile',  90, 2300, 220, 4),
            ('2026-10-03','(all)',   50, 2000, 125, 2);
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend NUMERIC);
        INSERT INTO insights_daily_by_ad VALUES
            ('a','2026-10-01',100), ('b','2026-10-01',50),
            ('a','2026-10-02',200), ('a','2026-10-06',100);
        CREATE TABLE shopify_order_attribution(
            order_id TEXT, created_at TEXT, total_price NUMERIC, utm_source TEXT);
        -- 'f' is the guard on the Meta filter: a 500-rupee Google order
        -- on a day the assertions below pin at 100. Drop the filter and
        -- 1 Oct reads 600 over 3 orders instead of 100 over 2, so the
        -- numerator and the meta_sessions denominator part company.
        INSERT INTO shopify_order_attribution VALUES
            ('a','2026-10-01 00:00:00',25,'meta'),
            ('b','2026-10-01 23:59:59.999999',75,'facebook'),
            ('f','2026-10-01 12:00:00',500,'google'),
            ('c','2026-10-03 23:59:59.999999',100,'instagram'),
            ('d','2026-10-04 00:00:00',800,'meta'),
            ('e','2026-10-06 12:00:00',-20,'ig');
    """)

    async def execute(query, params):
        sql = str(query).replace("public.", "")
        assert "FROM public.shopify_sessions " not in str(query)
        sql = sql.replace("CAST(:df AS date)", ":df").replace("CAST(:dt AS date)", ":dt")
        sql = sql.replace("CAST(o.created_at AS date)", "date(o.created_at)")
        sql = sql.replace("(b.hi + 1)", "datetime(b.hi, '+1 day')")
        raw = db.execute(sql, {k: str(v) if v is not None else None for k, v in params.items()}).fetchall()
        rows = [tuple(date.fromisoformat(v) if i in (0, 5, 6) and v else v for i, v in enumerate(r)) for r in raw]  # noqa: E501
        return SimpleNamespace(all=lambda: rows)

    fake = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    yield fake
    db.close()


async def test_exact_days_source_totals_and_ratios_without_join_multiplication(session):
    result = await analytics.get_dashboard_session_trend(session, date(2026, 10, 1), date(2026, 10, 3))
    first, zero, last = result.points
    assert (first.sessions, first.ad_spend, first.attributed_revenue, first.attributed_orders) == (100, 150, 100, 2)
    assert (first.cost_per_session, first.revenue_per_session, first.conversion_rate) == (1.5, 1, 0.02)
    assert zero.sessions == 0
    assert zero.cost_per_session is zero.revenue_per_session is zero.conversion_rate is None
    assert (last.ad_spend, last.attributed_revenue, last.attributed_orders) == (0, 100, 1)
    assert last.conversion_rate == 0.005
    assert sum(p.attributed_revenue for p in result.points) == 200  # Next midnight excluded.
    session.execute.assert_awaited_once()


async def test_lifetime_missing_days_source_coverage_and_negative_revenue(session):
    result = await analytics.get_dashboard_session_trend(session)
    assert [p.day.day for p in result.points] == [30, 1, 2, 3, 4, 5, 6, 7]
    assert result.points[0].cost_per_session is None  # Before spend coverage.
    assert result.points[-1].cost_per_session is None  # After spend coverage.
    missing = result.points[4]
    assert missing.sessions is missing.cost_per_session is missing.revenue_per_session is None
    assert missing.attributed_revenue == 800  # Missing session denominator does not erase orders.
    no_orders = result.points[5]
    assert (no_orders.revenue_per_session, no_orders.conversion_rate) == (0, 0)
    assert result.points[6].revenue_per_session == -0.2


async def test_cache_changes_with_range_and_single_day_supported(session):
    first = await analytics.get_dashboard_session_trend(session, date(2026, 10, 1), date(2026, 10, 1))
    assert len(first.points) == 1
    assert await analytics.get_dashboard_session_trend(session, date(2026, 10, 1), date(2026, 10, 1)) == first
    session.execute.assert_awaited_once()
    empty = await analytics.get_dashboard_session_trend(session, date(2026, 11, 1), date(2026, 11, 2))
    assert empty.points == []
    assert session.execute.await_count == 2


@pytest.mark.parametrize("bounds", [
    {"date_from": date(2026, 10, 1)}, {"date_to": date(2026, 10, 1)},
    {"date_from": date(2026, 10, 3), "date_to": date(2026, 10, 1)},
    {"date_from": date(1900, 1, 1), "date_to": date(2026, 10, 1)},
])
async def test_invalid_ranges_do_no_database_work(session, bounds):
    with pytest.raises(HTTPException) as exc:
        await analytics.get_dashboard_session_trend(session, **bounds)
    assert exc.value.status_code == 422
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("sqlstate", ["42P01", "57014", "08006"])
async def test_database_failure_stops_without_fallback_or_retry(sqlstate):
    original = RuntimeError("database failure")
    original.sqlstate = sqlstate
    session = SimpleNamespace(execute=AsyncMock(side_effect=DBAPIError("SELECT trend", {}, original)))
    with pytest.raises(HTTPException if sqlstate == "42P01" else DBAPIError):
        await analytics.get_dashboard_session_trend(session)
    session.execute.assert_awaited_once()


async def test_http_response_serializes_dates_and_fractional_rate(session):
    app = FastAPI()
    app.include_router(analytics.router)

    async def dependency():
        yield session

    app.dependency_overrides[get_session] = dependency
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/analytics/dashboard/session-trend?date_from=2026-10-01&date_to=2026-10-01")
    assert response.status_code == 200
    assert response.json()["points"][0]["conversion_rate"] == 0.02
    assert response.json()["points"][0]["day"] == "2026-10-01"


async def test_daily_arpu_is_exact_per_day_and_gaps_where_ga4_has_no_row(session):
    """Day grain is the one grain where ARPU needs no caveat: GA4
    deduplicates active users per query, and one day is one
    deduplication window. So 2,500 / 100 is simply 25.0.

    2 Oct has no GA4 row and must come back null, not 0 -- the ARPU
    table starts later than the session history, and a zero would read
    as "nobody spent anything" rather than "not measured here"."""
    result = await analytics.get_dashboard_session_trend(
        session, date(2026, 10, 1), date(2026, 10, 3))
    by_day = {p.day: p for p in result.points}

    assert by_day[date(2026, 10, 1)].ga4_arpu == 25.0
    assert by_day[date(2026, 10, 1)].ga4_active_users == 100
    # The mobile row (90 users, 2,300) is excluded, which is the point
    # of reading only `(all)`.
    assert by_day[date(2026, 10, 3)].ga4_arpu == 40.0

    assert by_day[date(2026, 10, 2)].ga4_arpu is None
    assert by_day[date(2026, 10, 2)].ga4_active_users is None


async def test_ga4_daily_ratios_divide_ga4_by_ga4(session):
    """The Google tab's chart lines, on GA4's own numbers.

    Its denominator is `(all)` GA4 sessions, never the Meta-driven
    Shopify count the lines beside them use -- that mismatch is exactly
    what made the Shopify ratios read 97 per cent high.
    """
    result = await analytics.get_dashboard_session_trend(
        session, date(2026, 10, 1), date(2026, 10, 3))
    first, gap, last = result.points

    # 1 Oct: 250 `(all)` sessions, Rs 2,500, 5 purchases. The mobile row
    # beside it (220 sessions) is excluded, as it is for ARPU.
    assert first.ga4_sessions == 250
    assert first.ga4_revenue_per_session == 10
    assert first.ga4_conversion_rate == 0.02
    assert first.ga4_cost_per_session == 150 / 250

    # Shopify's lines for the same day divide Meta's orders by Meta's
    # 100 sessions, so the two sources genuinely disagree here.
    assert first.revenue_per_session == 1
    assert first.conversion_rate == 0.02

    # 2 Oct has no GA4 row at all: a gap, not a zero.
    assert gap.ga4_sessions is None
    assert gap.ga4_revenue_per_session is None
    assert gap.ga4_conversion_rate is None
    assert gap.ga4_cost_per_session is None

    # 3 Oct: 125 sessions, Rs 2,000, 2 purchases, and no spend that day.
    assert last.ga4_revenue_per_session == 16
    assert last.ga4_conversion_rate == 0.016
    assert last.ga4_cost_per_session == 0


async def test_all_traffic_ratios_use_the_whole_shop(session):
    """The Shopify tab's lines: every order over every session.

    Meta is a SUBSET of this, not an alternative to it, so both must be
    carried per day -- the fixture's 1 Oct has a 500-rupee Google order
    that belongs here and not in the Meta figures beside it.
    """
    result = await analytics.get_dashboard_session_trend(
        session, date(2026, 10, 1), date(2026, 10, 3))
    first, _gap, last = result.points

    # 1 Oct: meta 25 + 75 = 100 over 2 orders; all adds the Google 500,
    # so 600 over 3. Sessions 100 Meta of 900 all -- the Shopify
    # rollup's own counts, NOT the 250 GA4 reports for the same day.
    assert (first.attributed_revenue, first.attributed_orders) == (100, 2)
    assert (first.all_revenue, first.all_orders) == (600, 3)
    assert first.all_sessions == 900
    assert first.ga4_sessions == 250
    assert first.all_revenue_per_session == 600 / 900
    assert first.all_conversion_rate == 3 / 900
    assert first.all_cost_per_session == 150 / 900

    # The Meta ratios on the same day divide by the 100-session subset,
    # so the two tabs genuinely differ.
    assert first.revenue_per_session == 1

    # 3 Oct has one order, Meta's, so the two agree there.
    assert (last.attributed_revenue, last.all_revenue) == (100, 100)


async def test_all_traffic_sessions_gap_where_the_rollup_has_no_row(session):
    """A missing session row is unknown, not zero -- for both counts."""
    result = await analytics.get_dashboard_session_trend(session)
    missing = result.points[4]
    assert missing.sessions is None
    assert missing.all_sessions is None
    assert missing.all_revenue_per_session is None
    # The orders are still reported; only the denominator is absent.
    assert missing.all_revenue == 800
