"""Asset status qualifies assets; the preview keeps every mapped ad."""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import asyncpg

from app.api.deps import get_session
from app.api.routers import analytics


@pytest.fixture
def session():
    return SimpleNamespace(execute=AsyncMock())


@pytest.fixture
async def client(session):
    caches = [analytics.get_asset_analysis.analytics_cache, analytics.get_asset_iterations.analytics_cache]
    for cache in caches:
        cache.entries.clear()
    app = FastAPI()
    app.include_router(analytics.router)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    for cache in caches:
        cache.entries.clear()


def mapped_result(rows):
    result = MagicMock()
    result.mappings.return_value = rows
    return result


async def test_preview_retains_unrated_ads_null_shopify_values_and_source_roas(client, session):
    rows = []
    for index in range(125):
        row = {key: None for key in analytics.AssetIteration.model_fields}
        row.update(iter_no=index + 1, ad_id=f"ad-{index}", ad_name=f"Ad {index}",
                   ad_created_date=date(2025, 10, 3), spend=Decimal("100"),
                   impressions=1000, conv_value=Decimal("450"), ncp=2, rk=8)
        rows.append(row)
    rows[0].update(ad_effective_status="ACTIVE", category="Winner", rk=2,
                   shopify_orders=3, shopify_revenue=Decimal("205.75"),
                   shopify_roas=Decimal("2.06"), purchases=4, ftewv=20, link_clicks=10,
                   account_name="Account", adset_name="Ad set", campaign_name="Campaign",
                   match_source="nomenclature", name_conflict=False,
                   gold_refreshed_at=datetime(2026, 10, 14, tzinfo=timezone.utc))
    rows[-1].update(ad_effective_status="CAMPAIGN_PAUSED", spend=0, conv_value=0)
    session.execute.return_value = mapped_result(rows)
    response = await client.get("/admin/analytics/asset-analysis/asset-1/iterations")
    assert response.status_code == 200, response.text
    data = response.json()["iterations"]
    assert len(data) == 125
    assert data[0]["ad_created_date"] == "2025-10-03"
    assert data[0]["shopify_roas"] == 2.06  # Retain the established source's value.
    assert data[0]["roas"] == 4.5
    assert data[0]["purchases"] == 4
    assert data[0]["link_clicks"] == 10
    assert data[-1]["category"] is None
    assert data[-1]["shopify_orders"] is None
    assert data[-1]["shopify_roas"] is None
    assert data[-1]["roas"] is None
    assert data[-1]["iter_no"] == 125
    assert (await client.get("/admin/analytics/asset-analysis/asset-1/iterations")).json() == response.json()
    assert session.execute.await_count == 1

    # No status, category, date, or limit may silently remove a mapped ad.
    pglast = pytest.importorskip("pglast")
    from pglast.stream import RawStream
    statement = session.execute.call_args.args[0].compile(dialect=asyncpg.dialect())
    parsed = pglast.parse_sql(str(statement))[0].stmt
    assert RawStream()(parsed.whereClause) == "m.asset_id = $1"
    assert parsed.limitCount is None


def empty_asset_results():
    rows = mapped_result([])
    totals = MagicMock()
    totals.mappings.return_value.all.return_value = []
    accounts = MagicMock()
    accounts.all.return_value = [("Account",)]
    return [rows, totals, mapped_result([]), accounts]


async def test_active_status_is_shared_by_rows_kpis_and_cache_and_supports_pagination(client, session):
    session.execute.side_effect = empty_asset_results() * 3
    active = await client.get("/admin/analytics/asset-analysis", params={"status": "active", "account_name": "Account", "limit": 1000})
    assert active.status_code == 200, active.text
    row_query, row_params = session.execute.call_args_list[0].args
    _, total_params = session.execute.call_args_list[1].args
    assert row_params["status"] == total_params["status"] == "active"
    assert row_params["account_name"] == total_params["account_name"] == "Account"
    assert row_params["from_date"] is None
    assert row_params["limit"] == 1000
    assert row_params["offset"] == 0
    await client.get("/admin/analytics/asset-analysis", params={"status": "active", "account_name": "Account", "limit": 1000})
    assert session.execute.await_count == 4
    await client.get("/admin/analytics/asset-analysis", params={"limit": 1000})
    assert session.execute.call_args_list[4].args[1]["status"] is None
    await client.get("/admin/analytics/asset-analysis", params={"status": "active", "limit": 1000, "offset": 1000})
    assert session.execute.call_args_list[8].args[1]["offset"] == 1000

    # Check the SQL grammar and keep status qualification OUTSIDE iteration
    # numbering so older active ads still qualify an asset whose newest ad paused.
    pglast = pytest.importorskip("pglast")
    from pglast.stream import RawStream
    parsed = pglast.parse_sql(str(row_query.compile(dialect=asyncpg.dialect())))[0].stmt
    outer_where = RawStream()(parsed.whereClause)
    iteration_where = RawStream()(parsed.withClause.ctes[0].ctequery.whereClause)
    assert "active_ad.ad_effective_status = 'ACTIVE'" in outer_where
    assert "active_map.asset_id = laned.asset_id" in outer_where
    assert "active_map.account_name" in outer_where
    assert "ad_effective_status" not in iteration_where
    assert "spend >" not in outer_where
    assert "category IS NOT NULL" not in iteration_where


async def test_invalid_filters_are_rejected_without_querying(client, session):
    for params in ({"status": "anything"}, {"limit": 0}, {"limit": 1001}):
        response = await client.get("/admin/analytics/asset-analysis", params=params)
        assert response.status_code == 422
    session.execute.assert_not_awaited()


async def test_kpi_median_uses_all_assets_without_double_counting_the_total_row(client, session):
    results = empty_asset_results()
    common = dict(spend=100, conv_value=200, ncp=3, ever_won=0, won_fell=0)
    results[1].mappings.return_value.all.return_value = [
        dict(common, lane="Discarded", n=2, med_iter=1),
        dict(common, lane="Result Awaited", n=4, med_iter=9),
        dict(common, lane=None, n=6, med_iter=2),
    ]
    session.execute.side_effect = results
    response = await client.get("/admin/analytics/asset-analysis")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == data["totals"]["assets"] == 6
    assert data["totals"]["median_iterations"] == 2
    assert data["totals"]["spend"] == 200
    assert sum(data["lane_counts"].values()) == 6
