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
    # ARPU's source. The `(all)` rows are the ones the endpoint reads;
    # the mobile row must be ignored, or a person on two devices in one
    # day would be counted twice.
    connection.executescript("""
        CREATE TABLE ga4_arpu_daily (
            day TEXT, device_category TEXT, active_users INTEGER, total_revenue NUMERIC,
            sessions INTEGER, purchases INTEGER);
        INSERT INTO ga4_arpu_daily VALUES
            ('2026-01-01','(all)',   100, 2000, 200,  4),
            ('2026-01-01','mobile',   90, 1800, 180,  3),
            ('2026-01-02','(all)',   150, 3000, 300,  6),
            ('2026-01-02','mobile',  140, 2900, 280,  5),
            ('2026-01-03','(all)',    50, 1000, 100,  2);
    """)
    connection.execute(_CREATE.replace("public.", ""))
    # btrim is Postgres' name for the standard no-argument trim.
    connection.execute(_INSERT.replace("public.", "").replace("btrim(", "trim("))

    async def execute(query, params):
        # A cache miss must never regress to the multi-million-row source.
        assert "FROM public.shopify_sessions " not in str(query)
        sql = str(query).replace("public.", "")
        row = connection.execute(sql, {key: str(value) for key, value in params.items()}).fetchone()
        # `.one()` for the session summary, `.first()` for the ARPU read.
        return SimpleNamespace(one=lambda: row, first=lambda: row)

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
    # Two: the session summary, then ARPU. ARPU is a separate read
    # because it comes from a different table at a different grain --
    # joining them would make the session figures depend on a table
    # that was added later and can be absent.
    assert session.execute.await_count == 2


async def test_cache_reuses_same_range_and_separates_changed_dates(session):
    first = await analytics.get_dashboard_sessions(session)
    assert await analytics.get_dashboard_sessions(session) == first
    # 2 per uncached call (summary + ARPU); the repeat is served from
    # the cache and costs none.
    assert session.execute.await_count == 2
    filtered = await analytics.get_dashboard_sessions(
        session, date_from=date(2026, 1, 1), date_to=date(2026, 1, 1),
    )
    assert (first.total_sessions, first.all_sessions) == (75, 225)
    assert (filtered.total_sessions, filtered.all_sessions) == (50, 200)
    assert session.execute.await_count == 4


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
        # A 2-day range matches no stored ARPU window, and the fixture
        # has no ga4_arpu_window table at all. Both paths must yield
        # null rather than a figure: GA4 deduplicates active users per
        # window, so anything derived from a different window is wrong.
        # 1-2 Jan: 250 active user-days, Rs 5,000 -> 20.00. The mobile
        # rows (230 users, Rs 4,700) are excluded, which is the whole
        # point of reading only `(all)`.
        "ga4_arpu": 20.0, "ga4_active_users": 250, "ga4_revenue": 5000.0,
        # GA4's own session and purchase counts, for the Google tab:
        # 1-2 Jan `(all)` rows are 200 + 300 sessions and 4 + 6
        # purchases. The mobile rows are excluded here too, so the
        # Google tab divides the same population it counts.
        "ga4_sessions": 500, "ga4_purchases": 10,
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
    # Still one: the summary read raised, so the ARPU read below it was
    # never reached and nothing was cached.
    session.execute.assert_awaited_once()
    assert not analytics.get_dashboard_sessions.analytics_cache.entries


async def test_ga4_session_counts_exclude_the_per_device_rows(session):
    """The Google tab's denominator must read `(all)` only.

    The per-device rows sit beside it in the same table and summing
    them in would count anyone who used two devices in a day twice --
    the same trap the ARPU numerator already avoids.
    """
    result = await analytics.get_dashboard_sessions(
        session=session, date_from=date(2026, 1, 1), date_to=date(2026, 1, 3))
    # `(all)`: 200 + 300 + 100 sessions, 4 + 6 + 2 purchases. With the
    # mobile rows it would be 980 and 18.
    assert result.ga4_sessions == 600
    assert result.ga4_purchases == 12


async def test_ga4_session_counts_follow_the_date_range(session):
    """A narrower window must not quietly return the whole table."""
    result = await analytics.get_dashboard_sessions(
        session=session, date_from=date(2026, 1, 3), date_to=date(2026, 1, 3))
    assert result.ga4_sessions == 100
    assert result.ga4_purchases == 2
