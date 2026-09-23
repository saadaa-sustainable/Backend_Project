"""The startup fill must match the request sent when Ads Analyse opens."""

from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock

from app.api.routers import analytics
from app.services.analytics_cache import cached_analytics


async def test_warmup_is_reused_by_the_first_browser_page(monkeypatch):
    calls = []

    @cached_analytics(ttl=300)
    async def read(session, limit=50, from_date=None, to_date=None, date_field="created"):
        calls.append((limit, from_date, to_date, date_field))
        return {"total": 5976}

    @asynccontextmanager
    async def session_scope():
        yield object()

    monkeypatch.setattr("app.database.session.session_scope", session_scope)
    monkeypatch.setattr(analytics, "get_ads_analyse", read)
    for name in ("get_creative_testing", "get_last_click_utm", "get_landing_pages"):
        monkeypatch.setattr(analytics, name, AsyncMock())

    await analytics.warm_ads_analyse_cache()
    browser_response = await read(
        session=object(), limit=100, from_date=date(2026, 1, 1),
        to_date=date.today(), date_field="delivery",
    )
    assert browser_response == {"total": 5976}
    assert len(calls) == 1, "Opening the page should reuse the warm response."
