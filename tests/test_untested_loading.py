"""Untested Assets responses and cache isolation, without a live database."""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import get_session
from app.api.routers import analytics


@pytest.fixture(autouse=True)
def clear_cache():
    cache = analytics.get_untested_assets.analytics_cache
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


def results(media="video", match_state="all"):
    rows = [SimpleNamespace(
        id=f"asset-{index}", title="Asset", nomenclature="CPL_Test", kind="New",
        sub_kind=None, link="https://example.test/asset", thumbnail=None,
        date_produced=date(2026, 9, 19), created_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
        candidate_master_sku="CPL" if media != "influencer" else None,
        origin="database" if index == 0 else "historical", source_system="Register",
        links=[{"label": "Asset", "url": "https://example.test/asset"}],
        matched_ads=index * 2,
        matched_master_sku="CPL" if index == 0 and media != "influencer" else None,
        sku_attributed_orders=Decimal("12") if index == 0 else None,
        sku_ad_spend=Decimal("100.50") if index == 0 else None,
        sku_cost_per_order=Decimal("8.375") if index == 0 else None,
    ) for index in range(2)]
    if match_state == "untested":
        rows = [row for row in rows if row.matched_ads == 0]
    elif match_state == "matched":
        rows = [row for row in rows if row.matched_ads > 0]
    coverage = MagicMock()
    # Coverage and the DAM split come back on ONE row, in one round
    # trip -- see the CROSS JOIN in the endpoint. Both fixture rows carry
    # a link and row 1 is the one with matched_ads > 0.
    coverage.one.return_value = SimpleNamespace(
        register_total=2, matched_assets=1, matched_ads=2,
        dam_total=2, dam_tested=1, dam_untested=1, without_link=0)
    return [rows, coverage]


@pytest.mark.parametrize("media", ["video", "graphic", "influencer"])
@pytest.mark.parametrize("match_state", ["untested", "matched", "all"])
async def test_media_populations_serialize_and_reuse_successful_response(client, session, media, match_state):
    session.execute.side_effect = results(media, match_state)
    params = {"media": media, "match_state": match_state}
    first = await client.get("/admin/analytics/untested", params=params)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["media"] == media
    assert data["total_rows"] == (2 if match_state == "all" else 1)
    assert data["register_total"] == 2  # Register coverage ignores the population filter.
    assert data["matched_assets"] == 1
    assert data["matched_ads"] == 2
    # Counted over the whole register, like register_total -- so they do
    # not move when match_state narrows the rows.
    assert data["dam_total"] == 2
    assert data["dam_tested"] + data["dam_untested"] == data["dam_total"]
    assert data["without_link"] == 0
    assert data["from_database"] + data["from_historical"] == data["total_rows"]
    assert data["with_sku_match"] + data["without_sku_match"] == data["total_rows"]
    assert all(row["media"] == media for row in data["rows"])
    assert data["rows"][0]["date_produced"] == "2026-09-19"
    if match_state == "untested":
        assert all(row["matched_ads"] == 0 for row in data["rows"])
    elif match_state == "matched":
        assert all(row["matched_ads"] > 0 for row in data["rows"])
    again = await client.get("/admin/analytics/untested", params=params)
    assert again.status_code == 200
    assert again.json() == data
    assert session.execute.await_count == 2


async def test_media_and_population_have_independent_cache_entries(client, session):
    session.execute.side_effect = (
        results("video", "untested") + results("graphic", "untested") + results("video", "all")
    )
    default = await client.get("/admin/analytics/untested")
    graphic = await client.get("/admin/analytics/untested", params={"media": "graphic"})
    all_video = await client.get("/admin/analytics/untested", params={"match_state": "all"})
    assert default.status_code == graphic.status_code == all_video.status_code == 200
    assert default.json()["media"] == "video"
    assert graphic.json()["media"] == "graphic"
    assert default.json()["total_rows"] == 1
    assert all_video.json()["total_rows"] == 2
    again = await client.get("/admin/analytics/untested")
    assert again.json() == default.json()
    assert session.execute.await_count == 6


async def test_failed_load_can_retry_without_caching_the_error(client, session):
    session.execute.side_effect = [RuntimeError("temporary database failure"), *results("video", "untested")]
    failed = await client.get("/admin/analytics/untested")
    assert failed.status_code == 500
    retry = await client.get("/admin/analytics/untested")
    assert retry.status_code == 200
    again = await client.get("/admin/analytics/untested")
    assert again.json() == retry.json()
    assert session.execute.await_count == 3
