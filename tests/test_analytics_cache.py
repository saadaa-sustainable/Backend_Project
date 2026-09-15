"""Response-cache behavior without the production app or a database connection."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, Query
from pydantic import BaseModel, Field

from app.services.analytics_cache import AnalyticsCache, cached_analytics


async def test_concurrent_identical_requests_share_one_successful_fill() -> None:
    cache = AnalyticsCache()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def load() -> dict[str, int]:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"rows": 42}

    owner = asyncio.create_task(cache.get("same", load))
    await entered.wait()
    waiters = [asyncio.create_task(cache.get("same", load)) for _ in range(8)]
    await asyncio.sleep(0)
    assert calls == 1
    release.set()
    assert await asyncio.gather(owner, *waiters) == [{"rows": 42}] * 9
    assert calls == 1
    assert cache.fills == {}


async def test_slow_key_does_not_block_another_filter_set() -> None:
    cache = AnalyticsCache()
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow() -> str:
        entered.set()
        await release.wait()
        return "slow"

    owner = asyncio.create_task(cache.get("30d", slow))
    await entered.wait()
    try:
        assert await asyncio.wait_for(cache.get("7d", AsyncMock(return_value="fast")), 1) == "fast"
        assert not owner.done()
    finally:
        release.set()
        await owner
    assert cache.fills == {}


async def test_ttl_begins_after_fill_and_expires_at_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("app.services.analytics_cache.monotonic", lambda: clock[0])
    cache = AnalyticsCache(ttl=60)

    async def slow_fill() -> str:
        clock[0] = 100.0
        return "first"

    assert await cache.get("sku", slow_fill) == "first"
    replacement = AsyncMock(return_value="second")
    clock[0] = 159.99
    assert await cache.get("sku", replacement) == "first"
    replacement.assert_not_awaited()
    clock[0] = 160.0
    assert await cache.get("sku", replacement) == "second"
    replacement.assert_awaited_once()
    assert cache.fills == {}


async def test_capacity_evicts_least_recently_used_result() -> None:
    cache = AnalyticsCache(max_entries=2)
    await cache.get("a", AsyncMock(return_value="A"))
    await cache.get("b", AsyncMock(return_value="B"))
    should_not_run = AsyncMock()
    assert await cache.get("a", should_not_run) == "A"
    await cache.get("c", AsyncMock(return_value="C"))
    should_not_run.assert_not_awaited()
    assert list(cache.entries) == ["a", "c"]
    reload_b = AsyncMock(return_value="B2")
    assert await cache.get("b", reload_b) == "B2"
    reload_b.assert_awaited_once()
    assert len(cache.entries) == 2


@pytest.mark.parametrize("value", [None, False, 0, [], {}])
async def test_falsy_results_are_cached(value: object) -> None:
    cache = AnalyticsCache()
    load = AsyncMock(return_value=value)
    assert await cache.get("key", load) == value
    assert await cache.get("key", load) == value
    load.assert_awaited_once()


async def test_failed_fill_is_not_cached_and_waiter_retries_its_own_loader() -> None:
    cache = AnalyticsCache()
    entered, release = asyncio.Event(), asyncio.Event()

    async def failure() -> str:
        entered.set()
        await release.wait()
        raise RuntimeError("temporary query error")

    owner = asyncio.create_task(cache.get("key", failure))
    await entered.wait()
    retry = AsyncMock(return_value="fresh result")
    waiter = asyncio.create_task(cache.get("key", retry))
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(RuntimeError, match="temporary query error"):
        await owner
    assert await waiter == "fresh result"
    assert await cache.get("key", retry) == "fresh result"
    retry.assert_awaited_once()
    assert cache.fills == {}


async def test_cancelled_owner_releases_fill_and_waiter_uses_its_own_request_session() -> None:
    cache = AnalyticsCache()
    entered, finalized = asyncio.Event(), asyncio.Event()
    owner_session, waiter_session = object(), object()
    sessions_used: list[object] = []

    async def owner_load() -> str:
        sessions_used.append(owner_session)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()
        return "unreachable"

    async def waiter_load() -> str:
        assert finalized.is_set()
        sessions_used.append(waiter_session)
        return "retried"

    owner = asyncio.create_task(cache.get("key", owner_load))
    await entered.wait()
    waiter = asyncio.create_task(cache.get("key", waiter_load))
    await asyncio.sleep(0)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert await asyncio.wait_for(waiter, 1) == "retried"
    assert sessions_used == [owner_session, waiter_session]
    assert cache.fills == {}


async def test_cancelled_waiter_does_not_cancel_owner_or_leak_fill() -> None:
    cache = AnalyticsCache()
    entered, release = asyncio.Event(), asyncio.Event()

    async def owner_load() -> str:
        entered.set()
        await release.wait()
        return "owner result"

    owner = asyncio.create_task(cache.get("key", owner_load))
    await entered.wait()
    waiter_load = AsyncMock()
    waiter = asyncio.create_task(cache.get("key", waiter_load))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not owner.done()
    release.set()
    assert await owner == "owner result"
    assert await cache.get("key", waiter_load) == "owner result"
    waiter_load.assert_not_awaited()
    assert cache.fills == {}


async def test_last_cancelled_owner_leaves_no_cached_value_or_lock() -> None:
    cache = AnalyticsCache()
    entered = asyncio.Event()

    async def load() -> None:
        entered.set()
        await asyncio.Event().wait()

    owner = asyncio.create_task(cache.get("key", load))
    await entered.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert cache.entries == {}
    assert cache.fills == {}
    assert await cache.get("key", AsyncMock(return_value="retry")) == "retry"


async def test_decorator_normalizes_direct_query_defaults_and_ignores_session() -> None:
    observed = []

    @cached_analytics()
    async def endpoint(
        session: object,
        limit: int = Query(default=10, ge=1),
        from_date: date | None = Query(default=None),
    ) -> dict[str, object]:
        observed.append((session, limit, from_date))
        return {"limit": limit, "from_date": from_date}

    first_session = object()
    assert await endpoint(first_session) == {"limit": 10, "from_date": None}
    assert await endpoint(session=object(), from_date=None, limit=10) == {
        "limit": 10, "from_date": None,
    }
    assert observed == [(first_session, 10, None)]
    await endpoint(object(), limit=20)
    assert len(observed) == 2


class CacheProbeRequest(BaseModel):
    master_skus: list[str] = Field(min_length=1)
    window: str = "30d"
    from_date: date | None = None


class CacheProbeResponse(BaseModel):
    generation: int
    master_skus: list[str]
    limit: int
    from_date: date | None


async def test_fastapi_keeps_future_annotations_body_validation_and_dependency_lifecycle() -> None:
    """Exercise real FastAPI routing/serialization with an in-process transport."""
    router = APIRouter()
    generations = 0
    opened, closed = [], []

    async def request_session() -> AsyncIterator[object]:
        session = object()
        opened.append(session)
        try:
            yield session
        finally:
            closed.append(session)

    @router.post("/probe", response_model=CacheProbeResponse)
    @cached_analytics()
    async def probe(
        body: CacheProbeRequest,
        session: object = Depends(request_session),
        limit: int = Query(default=10, ge=1),
    ) -> CacheProbeResponse:
        nonlocal generations
        assert isinstance(body, CacheProbeRequest)
        assert session in opened and session not in closed
        generations += 1
        return CacheProbeResponse(
            generation=generations, master_skus=body.master_skus,
            limit=limit, from_date=body.from_date,
        )

    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        first = await client.post("/probe", json={
            "master_skus": ["SDCP"], "from_date": "2026-09-01",
        })
        equivalent = await client.post("/probe?limit=10", json={
            "from_date": "2026-09-01", "window": "30d", "master_skus": ["SDCP"],
        })
        different_query = await client.post("/probe?limit=20", json={
            "master_skus": ["SDCP"], "from_date": "2026-09-01",
        })
        different_body = await client.post("/probe", json={"master_skus": ["SMCP"]})
        invalid_body = await client.post("/probe", json={"master_skus": []})
        invalid_query = await client.post("/probe?limit=0", json={"master_skus": ["SDCP"]})
        schema = (await client.get("/openapi.json")).json()

    assert first.status_code == equivalent.status_code == 200
    assert first.json() == equivalent.json() == {
        "generation": 1, "master_skus": ["SDCP"], "limit": 10, "from_date": "2026-09-01",
    }
    assert different_query.json()["generation"] == 2
    assert different_body.json()["generation"] == 3
    assert invalid_body.status_code == invalid_query.status_code == 422
    assert generations == 3
    assert len(opened) == len(closed) == 6
    assert set(opened) == set(closed)
    request_schema = schema["paths"]["/probe"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/CacheProbeRequest")
