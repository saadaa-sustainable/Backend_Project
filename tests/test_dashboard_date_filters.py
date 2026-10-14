"""Dashboard range regression tests execute the actual SQL on isolated fixtures."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routers import analytics


ENDPOINTS = (
    analytics.get_dashboard_kpis,
    analytics.get_dashboard_category_breakdown,
    analytics.get_dashboard_channel_breakdown,
    analytics.get_dashboard_top_landing_pages,
    analytics.get_dashboard_top_cpis_skus,
)


@pytest.fixture(autouse=True)
def reset_cache():
    for endpoint in ENDPOINTS:
        endpoint.analytics_cache.entries.clear()
    yield
    for endpoint in ENDPOINTS:
        endpoint.analytics_cache.entries.clear()


@pytest.fixture
def session():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE insights_daily_by_ad(ad_id TEXT, day TEXT, spend NUMERIC, ncp_count NUMERIC);
        INSERT INTO insights_daily_by_ad VALUES
            ('a','2026-09-30',9000,90), ('a','2026-10-01',100,2),
            ('a','2026-10-14',200,3), ('a','2026-10-15',9000,90),
            ('b','2026-10-02',50,0), ('c','2026-09-30',8000,8),
            ('d','2026-10-01',30,1);
        CREATE TABLE ad_lifecycle(ad_id TEXT PRIMARY KEY, ad_name TEXT);
        INSERT INTO ad_lifecycle VALUES
            ('a','Launch sdcp blue'), ('b','SDLT new'), ('c','SDTS historical'),
            ('d','SDCP and SDLT bundle');
        CREATE TABLE cpis_by_sku(master_sku TEXT, window_key TEXT,
            matched_ad_count INTEGER, ad_spend NUMERIC, cost_per_ncp NUMERIC);
        INSERT INTO cpis_by_sku VALUES
            ('SDCP','7d',2,9999,99), ('SDCP','30d',2,9999,99),
            ('SDLT','7d',2,8888,88), ('SDTS','7d',1,7777,77),
            ('SD','7d',0,0,NULL);
        CREATE TABLE shopify_landing_page_analysis(day TEXT, landing_page_path TEXT, sessions INTEGER);
        INSERT INTO shopify_landing_page_analysis VALUES
            ('2026-09-30','/old',9000), ('2026-10-01','/new',10),
            ('2026-10-14','/new',20), ('2026-10-14','/second',5),
            ('2026-10-15','/future',9000), ('2026-10-01',NULL,9000);
    """)

    async def execute(query, params=None):
        rows = db.execute(str(query), {k: str(v) for k, v in (params or {}).items()}).fetchall()
        return SimpleNamespace(all=lambda: rows)

    fake = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    yield fake
    db.close()


async def test_sku_exact_range_preserves_name_matching_and_cost_per_ncp(session):
    rows = await analytics.get_dashboard_top_cpis_skus(
        session, date_from="2026-10-01", date_to="2026-10-14")
    assert [r.master_sku for r in rows] == ["SDCP", "SDLT"]
    # Shared bundle matches both SKUs, exactly as in the original matching rule.
    assert [(r.ad_spend, r.cost_per_ncp) for r in rows] == [(330, 55), (80, 80)]
    assert session.execute.await_count == 2
    cached = await analytics.get_dashboard_top_cpis_skus(
        session, date_from="2026-10-01", date_to="2026-10-14")
    assert cached == rows
    assert session.execute.await_count == 2
    # Same duration in September must not return the October data.
    historical = await analytics.get_dashboard_top_cpis_skus(
        session, date_from="2026-09-17", date_to="2026-09-30")
    assert [r.ad_spend for r in historical] == [9000, 8000]


async def test_sku_single_day_zero_denominator_empty_and_lifetime(session):
    rows = await analytics.get_dashboard_top_cpis_skus(
        session, date_from="2026-10-02", date_to="2026-10-02")
    assert len(rows) == 1
    assert rows[0].ad_spend == 50
    assert rows[0].cost_per_ncp is None
    assert await analytics.get_dashboard_top_cpis_skus(
        session, date_from="2026-11-01", date_to="2026-11-14") == []
    lifetime = await analytics.get_dashboard_top_cpis_skus(session)
    assert [r.ad_spend for r in lifetime] == [9999, 8888, 7777]


async def test_landing_pages_use_inclusive_dates_and_lifetime(session):
    rows = await analytics.get_dashboard_top_landing_pages(
        session, date_from="2026-10-01", date_to="2026-10-14")
    assert [(r.landing_page_path, r.sessions) for r in rows] == [("/new", 30), ("/second", 5)]
    lifetime = await analytics.get_dashboard_top_landing_pages(session)
    assert sum(r.sessions for r in lifetime) == 18035
    assert await analytics.get_dashboard_top_landing_pages(
        session, date_from="2026-11-01", date_to="2026-11-14") == []


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("bounds,status", [
    ({"date_from": "2026-10-01"}, 422),
    ({"date_to": "2026-10-01"}, 422),
    ({"date_from": "2026-10-14", "date_to": "2026-10-01"}, 422),
    ({"date_from": "2026-02-30", "date_to": "2026-10-01"}, 400),
])
async def test_invalid_range_never_falls_back_to_lifetime(session, endpoint, bounds, status):
    with pytest.raises(HTTPException) as exc:
        await endpoint(session, **bounds)
    assert exc.value.status_code == status
    session.execute.assert_not_awaited()
