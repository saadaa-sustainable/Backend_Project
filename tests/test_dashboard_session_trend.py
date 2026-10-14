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
    db.executescript("""
        CREATE TABLE shopify_sessions_daily(day TEXT PRIMARY KEY, sessions NUMERIC);
        INSERT INTO shopify_sessions_daily VALUES
            ('2026-09-30',100), ('2026-10-01',100), ('2026-10-02',0),
            ('2026-10-03',200), ('2026-10-05',100), ('2026-10-06',100), ('2026-10-07',100);
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend NUMERIC);
        INSERT INTO insights_daily_by_ad VALUES
            ('a','2026-10-01',100), ('b','2026-10-01',50),
            ('a','2026-10-02',200), ('a','2026-10-06',100);
        CREATE TABLE shopify_order_attribution(order_id TEXT, created_at TEXT, total_price NUMERIC);
        INSERT INTO shopify_order_attribution VALUES
            ('a','2026-10-01 00:00:00',25), ('b','2026-10-01 23:59:59.999999',75),
            ('c','2026-10-03 23:59:59.999999',100), ('d','2026-10-04 00:00:00',800),
            ('e','2026-10-06 12:00:00',-20);
    """)

    async def execute(query, params):
        sql = str(query).replace("public.", "")
        assert "FROM public.shopify_sessions " not in str(query)
        sql = sql.replace("CAST(:df AS date)", ":df").replace("CAST(:dt AS date)", ":dt")
        sql = sql.replace("CAST(o.created_at AS date)", "date(o.created_at)")
        sql = sql.replace("(b.hi + 1)", "datetime(b.hi, '+1 day')")
        raw = db.execute(sql, {k: str(v) if v is not None else None for k, v in params.items()}).fetchall()
        rows = [tuple(date.fromisoformat(v) if i in (0, 5, 6) and v else v for i, v in enumerate(r)) for r in raw]
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
