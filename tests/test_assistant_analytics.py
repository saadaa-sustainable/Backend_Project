"""Offline tests: real tool dispatch/provider loops, fake database/provider I/O."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routers import assistant
from app.services import assistant_analytics as tools
from app.services.analytics_cache import cached_analytics


def payload(data):
    return SimpleNamespace(model_dump=lambda **kwargs: data)


@pytest.fixture
def session(monkeypatch):
    session = SimpleNamespace(execute=AsyncMock())

    @asynccontextmanager
    async def session_factory():
        yield session

    monkeypatch.setattr(tools, "get_session_factory", lambda: session_factory)
    return session


def question(**kwargs):
    return assistant.ChatRequest(messages=[{"role": "user", "content": "Show ad spend"}], **kwargs)


@pytest.mark.parametrize("bad", [
    {"date_from": "2026-01-01"}, {"date_to": "2026-01-01"},
    {"date_from": "2026-02-01", "date_to": "2026-01-01"},
    {"date_from": "2020-01-01", "date_to": "2026-01-01"},
    {"date_from": "2026-01-01", "date_to": "2099-01-01"},
    {"lifetime": True, "date_from": "2026-01-01", "date_to": "2026-01-02"},
])
def test_ambiguous_or_unbounded_dates_are_rejected(bad):
    with pytest.raises(ValidationError):
        tools.WindowInput(**bad)


def test_default_window_is_30_completed_days_in_ist():
    params = tools.WindowInput()
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    assert params.date_to == today - timedelta(days=1)
    assert (params.date_to - params.date_from).days == 29
    assert tools.WindowInput(lifetime=True).date_from is None
    with pytest.raises(ValidationError):
        tools.DashboardInput(section="session_trend", lifetime=True)


async def test_invalid_filters_and_sql_never_open_a_database_session(monkeypatch):
    def forbidden():
        pytest.fail("Validation must happen before session creation")
    monkeypatch.setattr(tools, "get_session_factory", forbidden)
    for name, args in [("get_ad_performance", {"limit": 51}),
                       ("get_ad_performance", {"sql": "SELECT 1"}),
                       ("get_asset_performance", {"date_from": "2026-01-01"}),
                       ("query_sql", {"sql": "SELECT 1"})]:
        _, failed = await tools.execute_analytics_tool(name, args)
        assert failed


async def test_ad_queries_use_delivery_dates_and_retained_full_totals(session, monkeypatch):
    handler = AsyncMock(return_value=payload({
        "rows": [{"ad_id": "123", "spend": 10, "shopify_roas": None, "preview_url": "private-url"}],
        "total": 100, "totals": {"spend": 999}, "customer_mix_unavailable": True,
    }))
    monkeypatch.setattr(tools.analytics, "get_ads_analyse", handler)
    content, failed = await tools.execute_analytics_tool("get_ad_performance", {
        "date_from": "2026-01-01", "date_to": "2026-01-31", "limit": 1,
    })
    assert not failed
    kwargs = handler.await_args.kwargs
    assert kwargs["date_field"] == "delivery"
    assert kwargs["from_date"] == date(2026, 1, 1)
    assert kwargs["to_date"] == date(2026, 1, 31)
    data = json.loads(content)
    assert data["data"]["totals"]["spend"] == 999
    assert data["data"]["rows"][0]["shopify_roas"] is None
    assert "preview_url" not in data["data"]["rows"][0]
    assert data["truncated"] and data["total_matching"] == 100
    assert data["source"]["url"] == "/user/analytics#ads-analyse"


async def test_inactive_historical_winners_keep_lifetime_semantics(session, monkeypatch):
    handler = AsyncMock(return_value=payload({"rows": [{"asset_id": "a", "roas": 2,
        "preview_url": "secret", "thumbnail_url": "secret"}], "total": 1, "totals": {"spend": 100}}))
    monkeypatch.setattr(tools.analytics, "get_asset_analysis", handler)
    content, error = await tools.execute_analytics_tool("get_asset_performance", {
        "status": "inactive", "only": "ever_won",
    })
    assert not error
    assert handler.await_args.kwargs["only"] == "ever_won"
    assert handler.await_args.kwargs["status"] == "inactive"
    assert handler.await_args.kwargs["from_date"] is None
    data = json.loads(content)
    assert "lifetime" in data["source"]["basis"]
    assert "Meta ROAS" in data["source"]["basis"]
    assert data["data"]["rows"] == [{"asset_id": "a", "roas": 2}]


@pytest.mark.parametrize("section,handler_name", [
    ("kpis", "get_dashboard_kpis"), ("sessions", "get_dashboard_sessions"),
    ("session_trend", "get_dashboard_session_trend"),
])
async def test_dashboard_sections_reuse_existing_handlers(section, handler_name, session, monkeypatch):
    handler = AsyncMock(return_value=payload({"session_data_to": "2026-01-29", "total_sessions": None}))
    monkeypatch.setattr(tools.analytics, handler_name, handler)
    content, error = await tools.execute_analytics_tool("get_dashboard_metrics", {
        "section": section, "date_from": "2026-01-01", "date_to": "2026-01-31",
    })
    assert not error
    data = json.loads(content)
    assert data["data"]["session_data_to"] == "2026-01-29"
    assert data["data"]["total_sessions"] is None
    assert data["source"]["filters"]["date_to"] == "2026-01-31"
    handler.assert_awaited_once()


async def test_repeat_filter_set_uses_dashboard_cache_without_second_query(session, monkeypatch):
    @cached_analytics(ttl=60)
    async def kpis(session, date_from=None, date_to=None):
        await session.execute("fake database call")
        return payload({"total_spend": 100})
    monkeypatch.setattr(tools.analytics, "get_dashboard_kpis", kpis)
    args = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
    await tools.execute_analytics_tool("get_dashboard_metrics", args)
    await tools.execute_analytics_tool("get_dashboard_metrics", args)
    session.execute.assert_awaited_once()


async def test_database_failure_stops_and_does_not_leak_credentials(session, monkeypatch):
    handler = AsyncMock(side_effect=RuntimeError("postgresql://user:SECRET@host/data"))
    monkeypatch.setattr(tools.analytics, "get_dashboard_kpis", handler)
    with pytest.raises(HTTPException) as e:
        await tools.execute_analytics_tool("get_dashboard_metrics", {})
    assert e.value.status_code == 503
    assert "SECRET" not in e.value.detail
    handler.assert_awaited_once()


async def test_tool_timeout_cancels_query_without_retry(session, monkeypatch):
    cancelled = False
    async def slow(**kwargs):
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True
    monkeypatch.setattr(tools, "TOOL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(tools.analytics, "get_dashboard_kpis", slow)
    with pytest.raises(HTTPException) as e:
        await tools.execute_analytics_tool("get_dashboard_metrics", {})
    assert e.value.status_code == 504 and cancelled


@pytest.fixture
def provider(monkeypatch):
    requests = []
    replies = []
    async def post(path, json):
        requests.append(json)
        assert path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": replies.pop(0)}]})
    client = SimpleNamespace(post=post)
    monkeypatch.setattr(assistant, "_get_http_client", lambda: client)
    monkeypatch.setattr(assistant, "get_settings", lambda: SimpleNamespace(assistant=SimpleNamespace(
        model="@cf/meta/llama-3.3-70b-instruct-fp8-fast")))
    return requests, replies


def call(name="get_dashboard_metrics", args=None):
    return {"content": None, "tool_calls": [{"id": "call_a", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args or {})}}]}


async def test_real_chat_loop_attaches_trusted_sources(provider, session, monkeypatch):
    requests, replies = provider
    replies.extend([call(), {"content": "Spend is 100 for the selected period."}])
    monkeypatch.setattr(tools.analytics, "get_dashboard_kpis", AsyncMock(return_value=payload({"total_spend": 100})))
    result = await assistant.assistant_chat(question())
    assert result.sources[0].label == "Dashboard"
    assert result.sources[0].filters["date_from"]
    # Exactly the declared registry, so a new section cannot silently fail to
    # reach the model and an undeclared tool cannot silently reach it either.
    assert ({t["function"]["name"] for t in requests[0]["tools"]}
            == {t["function"]["name"] for t in tools.ANALYTICS_TOOLS})
    assert len(requests) == 2


async def test_chat_stops_before_another_model_call_after_data_failure(provider, session, monkeypatch):
    requests, replies = provider
    replies.extend([call(), {"content": "must not execute"}])
    monkeypatch.setattr(tools.analytics, "get_dashboard_kpis", AsyncMock(side_effect=ConnectionError("SECRET")))
    with pytest.raises(HTTPException) as e:
        await assistant.assistant_chat(question())
    assert e.value.status_code == 503
    assert len(requests) == 1


async def test_analytics_mode_cannot_execute_undeclared_sql_tool(provider, monkeypatch):
    _, replies = provider
    replies.extend([call("query_sql", {"sql": "SELECT 1"}), {"content": "Please ask about analytics."}])
    executor = AsyncMock()
    monkeypatch.setattr(assistant, "_execute_tool", executor)
    result = await assistant.assistant_chat(question())
    executor.assert_not_awaited()
    assert result.sources == []


async def test_database_mode_preserves_existing_tools(provider, monkeypatch):
    requests, replies = provider
    replies.extend([call("list_tables"), {"content": "Tables listed."}])
    executor = AsyncMock(return_value=("[]", False))
    monkeypatch.setattr(assistant, "_execute_tool", executor)
    await assistant.assistant_chat(question(mode="database"))
    executor.assert_awaited_once_with("list_tables", {})
    assert "query_sql" in {t["function"]["name"] for t in requests[0]["tools"]}


async def test_full_turn_has_finite_budget(provider, monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(assistant, "_CHAT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(assistant, "_run_chat_turn", slow)
    with pytest.raises(HTTPException) as e:
        await assistant.assistant_chat(question())
    assert e.value.status_code == 504


def test_prompt_and_request_bounds():
    with pytest.raises(ValidationError):
        assistant.ChatMessage(role="user", content="a" * 12001)
    with pytest.raises(ValidationError):
        assistant.ChatRequest(messages=[{"role": "user", "content": "a" * 12000}] * 5)
    assert assistant._parse_tool_call_arguments('["not", "an", "object"]') == {}
    assert assistant._parse_tool_call_arguments('{"limit": 5}') == {"limit": 5}
    assert {t["name"] for t in assistant._tools_for_anthropic(tools.ANALYTICS_TOOLS)} == set(tools._TOOL_SPECS)
