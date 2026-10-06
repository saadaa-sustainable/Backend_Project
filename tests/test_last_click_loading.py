"""Exercise analytics HTTP routes with fake queries and their real response caches."""

from __future__ import annotations

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
def clear_caches():
    caches = [
        analytics.get_last_click_utm.analytics_cache,
        analytics.get_landing_pages.analytics_cache,
    ]
    for cache in caches:
        cache.entries.clear()
    yield
    for cache in caches:
        cache.entries.clear()


@pytest.fixture
def session():
    return SimpleNamespace(execute=AsyncMock())


@pytest.fixture
async def client(session):
    # Mount the actual router without the production startup warmers or DB.
    app = FastAPI()
    app.include_router(analytics.router)

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def last_click_results(*, total: int = 2):
    summary = MagicMock()
    summary.all.return_value = [
        ("fb", "ad_direct", False, 1, Decimal("1999.50")),
        ("ig", "unmatched", True, 1, Decimal("100.00")),
    ]
    row = {
        "order_id": "gid://shopify/Order/123",
        "name": "#123",
        "total_price": Decimal("1999.50"),
        "created_at": datetime(2026, 9, 18, 12, tzinfo=timezone.utc),
        "customer_id": "gid://shopify/Customer/456",
        "utm_source": "fb",
        "utm_medium": "paid",
        "utm_campaign": "Autumn",
        "utm_content": "789",
        "utm_term": "adset-1",
        "tier": "ad_direct",
        "matched_ad_id": "789",
        "matched_ad_name": "Autumn creative",
        "matched_adset_id": "adset-1",
        "matched_campaign_id": "campaign-1",
        "matched_campaign_name": "Autumn",
        "matched_value": "789",
        "contact_email": "customer@example.test",
        "customer_num_orders": Decimal("3"),
    }
    count = MagicMock()
    count.scalar_one.return_value = total
    return [summary, [SimpleNamespace(_mapping=row)], count]


def landing_page_results():
    """One result set, not two.

    The endpoint carries its total in the rows via COUNT(*) OVER ()
    rather than running the whole FULL OUTER JOIN a second time, so the
    mock supplies a single execute() result and every row carries
    `_total`. A fixture shaped like the old two-query form would pass a
    count object the endpoint never asks for, and the second request in
    these tests would consume it as if it were rows.
    """
    row = {
        "landing_page_path": "/collections/autumn",
        # Shopify: the top of the funnel, where it is reliable.
        "shopify_sessions": 100,
        "shopify_atc_rate": Decimal("20.00"),
        "shopify_bounce_rate": Decimal("25.00"),
        # GA4: deliberately disagreeing with Shopify on the same page,
        # which is the condition the section exists to show.
        "ga4_sessions": 85,
        "ga4_pdp_views": 60,
        "ga4_add_to_carts": 12,
        "ga4_checkouts": 6,
        "ga4_purchases": 3,
        "ga4_bounce_rate": Decimal("30.00"),
        # GA4 minus Shopify. Negative is the usual direction.
        "sessions_delta": -15,
        "sessions_delta_pct": Decimal("-15.00"),
        "bounce_rate_delta": Decimal("5.00"),
        # Funnel ratios, all GA4-only.
        "conversion_rate": Decimal("3.53"),
        "pdp_to_atc_rate": Decimal("20.00"),
        "pdp_to_checkout_rate": Decimal("10.00"),
        "atc_to_checkout_rate": Decimal("50.00"),
        "checkout_to_purchase_rate": Decimal("50.00"),
        "pdp_to_purchase_rate": Decimal("5.00"),
        "_total": 1,
    }
    return [[SimpleNamespace(_mapping=row)]]


async def test_last_click_http_response_serializes_rows_summaries_and_reuses_cache(client, session):
    session.execute.side_effect = last_click_results()

    first = await client.get("/admin/analytics/last-click-utm")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["total"] == 2
    assert payload["rows"][0]["order_id"] == "gid://shopify/Order/123"
    assert payload["rows"][0]["created_at"] == "2026-09-18T12:00:00Z"
    assert payload["rows"][0]["total_price"] == 1999.5
    assert payload["rows"][0]["customer_num_orders"] == 3
    assert payload["rows"][0]["channel"] == "Meta"
    assert payload["rows"][0]["has_match"] is True
    assert payload["channel_counts"]["Meta"] == {"count": 1, "sales": 1999.5}
    assert payload["channel_counts"]["Organic (IG)"] == {"count": 1, "sales": 100.0}
    assert payload["tier_summary"]["unmatched"] == {"count": 1, "sales": 100.0}
    assert payload["tier_by_channel"]["Meta"]["ad_direct"]["count"] == 1
    assert payload["channel_sources"]["Meta"] == [
        {"utm_source": "fb", "count": 1, "sales": 1999.5}
    ]
    row_query, row_params = session.execute.await_args_list[1].args
    assert row_params == {"limit": 100, "offset": 0}
    assert "ORDER BY soa.created_at DESC" in str(row_query)

    second = await client.get("/admin/analytics/last-click-utm")
    assert second.status_code == 200
    assert second.json() == payload
    assert session.execute.await_count == 3


@pytest.mark.parametrize("filters", [
    {"from_date": "2026-09-18", "to_date": "2026-09-19"},
    {"channel": "Meta"},
    {"only_matched": "true"},
])
async def test_last_click_filter_changes_have_separate_cache_entries(client, session, filters):
    session.execute.side_effect = last_click_results(total=2) + last_click_results(total=1)

    first = await client.get("/admin/analytics/last-click-utm")
    filtered = await client.get("/admin/analytics/last-click-utm", params=filters)
    assert first.status_code == filtered.status_code == 200
    assert first.json()["total"] == 2
    assert filtered.json()["total"] == 1
    assert session.execute.await_count == 6

    row_query, row_params = session.execute.await_args_list[4].args
    if "from_date" in filters:
        assert row_params["from_date"] == date(2026, 9, 18)
        assert row_params["to_date"] == date(2026, 9, 19)
        assert "soa.created_at >= :from_date" in str(row_query)
    elif "channel" in filters:
        assert "soa.utm_source" in str(row_query)
        assert any(key.startswith("ch_") for key in row_params)
    else:
        assert "soa.matched_ad_id IS NOT NULL" in str(row_query)

    original_again = await client.get("/admin/analytics/last-click-utm")
    assert original_again.json()["total"] == 2
    assert session.execute.await_count == 6


async def test_landing_pages_http_response_and_cache(client, session):
    session.execute.side_effect = landing_page_results()

    first = await client.get("/admin/analytics/landing-pages")
    assert first.status_code == 200, first.text
    payload = first.json()
    # The total comes from COUNT(*) OVER () inside the rows, so it has to
    # survive being stripped off before the row model is built.
    assert payload["total"] == 1
    row = payload["rows"][0]
    assert row["landing_page_path"] == "/collections/autumn"
    assert "_total" not in row, "the window-function column must not leak into the response"
    # Both sources present and NOT merged.
    assert row["shopify_sessions"] == 100
    assert row["ga4_sessions"] == 85
    assert row["sessions_delta"] == -15

    query, params = session.execute.await_args_list[0].args
    # Dates are always sent: every ratio is computed over the requested
    # window, so "which window" is never implicit.
    assert params["limit"] == 50 and params["offset"] == 0
    assert "from_date" in params and "to_date" in params
    assert "ORDER BY ga4_sessions DESC" in str(query)
    assert "COUNT(*) OVER ()" in str(query)

    second = await client.get("/admin/analytics/landing-pages")
    assert second.status_code == 200
    assert second.json() == payload
    # ONE execute, not two: the second request is served from cache and
    # the first no longer runs a separate COUNT(*).
    assert session.execute.await_count == 1


@pytest.mark.parametrize(("path", "results", "successful_query_count"), [
    ("/admin/analytics/last-click-utm", last_click_results, 3),
    # 1, not 2: the landing-pages endpoint no longer runs a separate COUNT(*).
    ("/admin/analytics/landing-pages", landing_page_results, 1),
])
async def test_query_failure_can_retry_then_cache_success(
    client, session, path, results, successful_query_count,
):
    session.execute.side_effect = [RuntimeError("temporary database failure"), *results()]

    failed = await client.get(path)
    assert failed.status_code == 500
    recovered = await client.get(path)
    assert recovered.status_code == 200, recovered.text
    repeated = await client.get(path)
    assert repeated.status_code == 200
    assert repeated.json() == recovered.json()
    assert session.execute.await_count == 1 + successful_query_count
