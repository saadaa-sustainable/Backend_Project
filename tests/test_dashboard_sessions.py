"""Session totals keep date scopes, missing data and cached reads distinct."""

from datetime import date
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.exc import DBAPIError

from app.api.deps import get_session
from app.api.routers import analytics
from app.services.dashboard_sessions import _CREATE, _INSERT


@pytest.fixture(autouse=True)
def clear_cache():
    analytics.get_dashboard_sessions.analytics_cache.entries.clear()
    yield
    analytics.get_dashboard_sessions.analytics_cache.entries.clear()


@pytest.fixture
def session():
    connection = sqlite3.connect(":memory:")
    # Built through the production _INSERT, so the Meta rule under test
    # is the one that actually ships. 225 sessions of which 75 are Meta:
    # the 150 kwikengage sessions are WhatsApp tooling and must not count.
    connection.executescript("""
        CREATE TABLE shopify_sessions (day TEXT, sessions NUMERIC, utm_source TEXT);
        INSERT INTO shopify_sessions VALUES
            ('2026-01-01',50,'META'), ('2026-01-01',150,'kwikengage'),
            ('2026-01-02',0,'facebook'), ('2026-01-03',25,'ig'),
            ('2026-01-04',NULL,'META'), (NULL,1000,'META');
    """)
    connection.execute(_CREATE.replace("public.", ""))
    # btrim is Postgres' name for the standard no-argument trim.
    connection.execute(_INSERT.replace("public.", "").replace("btrim(", "trim("))

    async def execute(query, params):
        # A cache miss must never regress to the multi-million-row source.
        assert "FROM public.shopify_sessions " not in str(query)
        sql = str(query).replace("public.", "")
        row = connection.execute(sql, {key: str(value) for key, value in params.items()}).fetchone()
        return SimpleNamespace(one=lambda: row)

    fake = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    yield fake
    connection.close()


# `expected` is the META total, `expected_all` the all-traffic total --
# they differ on every populated range, so reading the wrong column
# cannot pass.
@pytest.mark.parametrize(("start", "end", "expected", "expected_all", "days"), [
    (None, None, 75, 225, 3),
    (date(2026, 1, 1), date(2026, 1, 1), 50, 200, 1),
    (date(2026, 1, 2), date(2026, 1, 2), 0, 0, 1),
    (date(2026, 1, 4), date(2026, 1, 4), None, None, 0),
    (date(2026, 1, 5), date(2026, 1, 6), None, None, 0),
])
async def test_additive_sessions_date_bounds_and_missing_values(
    session, start, end, expected, expected_all, days,
):
    response = await analytics.get_dashboard_sessions(session, date_from=start, date_to=end)
    assert response.total_sessions == expected
    assert response.all_sessions == expected_all
    assert response.available_days == days
    if days == 0:
        assert response.session_data_from is response.session_data_to is None
    else:
        assert response.session_data_from == (start or date(2026, 1, 1))
        assert response.session_data_to == (end or date(2026, 1, 3))
    session.execute.assert_awaited_once()


async def test_cache_reuses_same_range_and_separates_changed_dates(session):
    first = await analytics.get_dashboard_sessions(session)
    assert await analytics.get_dashboard_sessions(session) == first
    assert session.execute.await_count == 1
    filtered = await analytics.get_dashboard_sessions(
        session, date_from=date(2026, 1, 1), date_to=date(2026, 1, 1),
    )
    assert (first.total_sessions, first.all_sessions) == (75, 225)
    assert (filtered.total_sessions, filtered.all_sessions) == (50, 200)
    assert session.execute.await_count == 2


async def test_http_response_contract_reads_summary(session):
    app = FastAPI()
    app.include_router(analytics.router)

    async def dependency():
        yield session

    app.dependency_overrides[get_session] = dependency
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/admin/analytics/dashboard/sessions?date_from=2026-01-01&date_to=2026-01-02"
        )
    assert response.status_code == 200
    assert response.json() == {
        "total_sessions": 50, "all_sessions": 200,
        "session_data_from": "2026-01-01",
        "session_data_to": "2026-01-02", "available_days": 2,
    }


@pytest.mark.parametrize("query", [
    "date_from=2026-01-01", "date_to=2026-01-01",
    "date_from=2026-01-03&date_to=2026-01-01",
    "date_from=invalid&date_to=2026-01-01",
])
async def test_invalid_ranges_are_rejected_without_database_work(session, query):
    app = FastAPI()
    app.include_router(analytics.router)

    async def dependency():
        yield session

    app.dependency_overrides[get_session] = dependency
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/admin/analytics/dashboard/sessions?{query}")
    assert response.status_code == 422
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("sqlstate,expected_status", [("42P01", 503), ("57014", None), ("08006", None)])
async def test_uninitialized_summary_is_explicit_and_errors_never_fallback(sqlstate, expected_status):
    original = RuntimeError("database failure")
    original.sqlstate = sqlstate
    failure = DBAPIError("SELECT summary", {}, original)
    session = SimpleNamespace(execute=AsyncMock(side_effect=failure))
    if expected_status:
        with pytest.raises(analytics.HTTPException) as caught:
            await analytics.get_dashboard_sessions(session)
        assert caught.value.status_code == expected_status
        assert "refresh_dashboard_sessions.py" in caught.value.detail
    else:
        with pytest.raises(DBAPIError) as caught:
            await analytics.get_dashboard_sessions(session)
        assert caught.value is failure
    session.execute.assert_awaited_once()
    assert not analytics.get_dashboard_sessions.analytics_cache.entries
