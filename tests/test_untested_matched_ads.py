"""The Untested Assets popup must include every existing asset-to-ad match."""

from datetime import date
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


@pytest.fixture(autouse=True)
def clear_cache():
    cache = analytics.get_creative_testing_ads.analytics_cache
    cache.entries.clear()
    yield
    cache.entries.clear()


@pytest.fixture
def session():
    return SimpleNamespace(execute=AsyncMock())


@pytest.fixture
async def client(session):
    app = FastAPI()
    app.include_router(analytics.router)

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def results(media="video", *, count=125, ad_prefix="ad"):
    rows = []
    for index in range(count):
        row = {field: None for field in analytics.CreativeTestingAdRow.model_fields}
        row.update(
            ad_id=f"{ad_prefix}-{index}", ad_name=f"CPL_Test_Asset {index}",
            is_copy=index > 0, iteration_index=index,
            ad_created_date=date(2026, 9, 19), spend=Decimal("125.50"),
        )
        # A missing lifecycle/preview join must retain the matched ad.
        if index == 0:
            row.update(ad_status="ACTIVE", category="Winner", impressions=1000,
                       ad_preview_url="https://www.facebook.com/123/posts/456",
                       destination_url="https://example.test/products/asset?utm_content=123")
        rows.append(SimpleNamespace(_mapping=row))
    media_result = MagicMock()
    media_result.scalar.return_value = media if count else None
    return [rows, media_result]


@pytest.mark.parametrize("media", ["video", "graphic", "influencer"])
async def test_popup_returns_all_mapped_ads_including_missing_detail_rows(client, session, media):
    session.execute.side_effect = results(media)
    response = await client.get("/admin/analytics/creative-testing/asset-123/ads")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["asset_id"] == "asset-123"
    assert payload["media"] == media
    # The parent table displays 100 rows per page; the popup must not
    # inherit that cap and hide a matched asset's remaining ads.
    assert len(payload["ads"]) == 125
    assert payload["ads"][-1]["ad_id"] == "ad-124"
    assert payload["ads"][-1]["ad_name"] == "CPL_Test_Asset 124"
    assert payload["ads"][-1]["ad_status"] is None
    assert payload["ads"][-1]["ad_preview_url"] is None
    assert payload["ads"][-1]["spend"] == 125.5
    assert payload["ads"][0]["ad_created_date"] == "2026-09-19"
    assert payload["ads"][0]["destination_url"].endswith("utm_content=123")
    again = await client.get("/admin/analytics/creative-testing/asset-123/ads")
    assert again.json() == payload
    assert session.execute.await_count == 2


async def test_each_asset_has_an_independent_popup_cache(client, session):
    session.execute.side_effect = (
        results(count=2, ad_prefix="first") + results(count=1, ad_prefix="second")
    )
    first = await client.get("/admin/analytics/creative-testing/asset-1/ads")
    second = await client.get("/admin/analytics/creative-testing/asset-2/ads")
    assert first.json()["ads"][0]["ad_id"] == "first-0"
    assert second.json()["asset_id"] == "asset-2"
    assert second.json()["ads"][0]["ad_id"] == "second-0"
    again = await client.get("/admin/analytics/creative-testing/asset-1/ads")
    assert again.json() == first.json()
    assert session.execute.await_count == 4


async def test_empty_mapping_and_failed_read_do_not_leave_popup_loading(client, session):
    session.execute.side_effect = [RuntimeError("temporary database failure"), *results(count=0)]
    failed = await client.get("/admin/analytics/creative-testing/asset-empty/ads")
    assert failed.status_code == 500
    retry = await client.get("/admin/analytics/creative-testing/asset-empty/ads")
    assert retry.status_code == 200
    assert retry.json() == {"asset_id": "asset-empty", "media": None, "ads": []}
    cached = await client.get("/admin/analytics/creative-testing/asset-empty/ads")
    assert cached.json() == retry.json()
    assert session.execute.await_count == 3


def test_popup_uses_the_same_mapping_population_as_the_parent_count():
    """Missing ad metadata must never remove a match or introduce a date filter."""
    pglast = pytest.importorskip("pglast")
    from pglast import ast, enums
    from pglast.stream import RawStream

    query = text(analytics._CT_ADS_SQL).compile(dialect=asyncpg.dialect())
    statement = pglast.parse_sql(str(query))[0].stmt
    assert RawStream()(statement.whereClause) == "m.asset_id = $1"
    assert query.positiontup == ["asset_id"]
    assert statement.limitCount is None
    assert statement.limitOffset is None
    source = statement.fromClause[0]
    while isinstance(source, ast.JoinExpr):
        assert source.jointype == enums.JoinType.JOIN_LEFT
        source = source.larg
    assert source.schemaname == "public"
    assert source.relname == "ad_asset_map"
