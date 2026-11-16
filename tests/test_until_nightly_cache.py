"""Answers kept until a refresh run ends, and the watcher that ends them."""

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.api.routers import analytics
from app.services import analytics_cache
from app.services.analytics_cache import cached_analytics, invalidate_nightly


async def test_answer_outlives_the_short_ttl_and_ends_with_the_refresh(monkeypatch):
    calls = []

    @cached_analytics(ttl=60.0, until_nightly=True)
    async def read(session, day="x"):
        calls.append(day)
        return len(calls)

    @cached_analytics(ttl=60.0)
    async def hourly(session):
        calls.append("hourly")
        return len(calls)

    clock = [1000.0]
    monkeypatch.setattr(analytics_cache, "monotonic", lambda: clock[0])
    assert await read(session=None) == 1
    await hourly(session=None)
    clock[0] += 6 * 3600          # six hours on: far past the 60s lifetime
    assert await read(session=None) == 1, "still the cached answer"
    assert await hourly(session=None) == 3, "a short-lived cache expired as before"

    invalidate_nightly()           # a refresh run ended
    assert await read(session=None) == 4
    assert await hourly(session=None) == 3, "only until_nightly caches are dropped"

    clock[0] += 25 * 3600          # no run for over a day: the 24h cap applies
    assert await read(session=None) == 5


class _Stop(BaseException):
    """Ends the watcher's endless loop from inside a test."""


async def _run_watcher(monkeypatch, markers, days):
    """Drive watch_refresh_runs through one poll per marker; return (warms, clears)."""
    warm, clear = AsyncMock(), []
    monkeypatch.setattr(analytics, "warm_ads_analyse_cache", warm)
    monkeypatch.setattr(analytics, "invalidate_nightly", lambda: clear.append(1))
    polls = iter(markers)

    class _Result:
        def scalar(self):
            try:
                return next(polls)
            except StopIteration:
                # BaseException: the watcher catches Exception and retries.
                raise _Stop from None

    class _Session:
        async def execute(self, _sql):
            return _Result()

    @asynccontextmanager
    async def session_scope():
        yield _Session()

    monkeypatch.setattr("app.database.session.session_scope", session_scope)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    clock = iter(days)

    class _Datetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, next(clock), 12, tzinfo=tz)

    monkeypatch.setattr(analytics, "datetime", _Datetime)
    with pytest.raises(_Stop):
        await analytics.watch_refresh_runs()
    return warm.await_count, len(clear)


async def test_watcher_clears_and_warms_only_when_a_run_ends(monkeypatch):
    a, b = datetime(2026, 11, 16, 5), datetime(2026, 11, 17, 5)
    # Start-up warm, then three polls: first sighting, no change, a run ended.
    warms, clears = await _run_watcher(
        monkeypatch, markers=[a, a, b], days=[16, 16, 16, 16])
    assert (warms, clears) == (2, 1)


async def test_watcher_warms_again_when_the_day_changes(monkeypatch):
    a = datetime(2026, 11, 16, 5)
    # Start-up, then two polls; the second lands on the next IST day.
    warms, clears = await _run_watcher(
        monkeypatch, markers=[a, a], days=[16, 16, 17])
    assert (warms, clears) == (2, 0)
