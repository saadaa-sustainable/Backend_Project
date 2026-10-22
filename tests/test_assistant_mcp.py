"""Real SDK protocol + API chat loop; data and model traffic are offline fixtures."""
import asyncio
import hashlib
import json
from datetime import timedelta
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr
from sqlalchemy.orm import Session
from starlette.routing import Route

from app.api.routers import assistant, assistant_api
from app.services.assistant_analytics import ANALYTICS_TOOLS
from app.api.middleware import AssistantAPIBoundary
from app.services import assistant_api_auth as auth, assistant_mcp
from app.services import assistant_analytics

#: The MCP/API surface must be exactly what the registry declares -- no more.
#: Spelling the names out here meant every new section broke three unrelated
#: tests; what actually matters is that nothing leaks in beyond the registry.
DECLARED_TOOLS = {t["function"]["name"] for t in ANALYTICS_TOOLS}

KEY = "sda_" + "a" * 43
DIGEST = hashlib.sha256(KEY.encode()).hexdigest()
SOURCE = {"label": "Ads Analyse", "url": "/user/analytics#ads-analyse", "filters": {"limit": 5},
          "basis": "delivery", "retrieved_at": "2026-10-17T10:00:00Z", "cache_note": "fixture",
          "link_note": "Apply filters"}


@pytest.fixture
def config(monkeypatch):
    value = auth.APISettings(_env_file=None, enabled=True, require_user_auth=True, public_origin="https://dashboard.example",
        mcp_url="https://api.example/mcp", signing_key="fixture-" * 8,
        access_key_hashes=json.dumps({"Team member": DIGEST}), openai_key="PROVIDER_SECRET", model="fixture-model")
    monkeypatch.setattr(auth, "settings", lambda: value)
    monkeypatch.setattr(assistant_api, "chat_limits", auth.Limits())
    return value


@pytest.fixture
async def app(config):
    app = FastAPI()
    app.add_middleware(AssistantAPIBoundary)
    app.include_router(assistant_api.router)
    app.include_router(assistant.router)
    app.state.analytics_mcp = assistant_mcp.AnalyticsMCP()
    app.router.routes.append(Route("/mcp", app.state.analytics_mcp, methods=["GET", "POST", "DELETE"]))
    ready, stop = asyncio.Event(), asyncio.Event()

    async def lifespan():
        async with app.state.analytics_mcp.manager.run():
            ready.set()
            await stop.wait()

    task = asyncio.create_task(lifespan())
    await ready.wait()
    try:
        yield app
    finally:
        stop.set()
        await task


def client(app, **kwargs):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.example", **kwargs)


def bearer(key=KEY):
    return {"Authorization": "Bearer " + key}


@pytest.mark.parametrize("change", [{"enabled": False}, {"signing_key": SecretStr("short")},
    {"access_key_hashes": SecretStr('{}')}, {"access_key_hashes": SecretStr('{"x":"raw-key"}')},
    {"public_origin": "http://dashboard.example"}, {"mcp_url": "https://api.example/mcp?key=bad"}])
def test_configuration_fails_closed(config, change):
    with pytest.raises(HTTPException):
        config.model_copy(update=change).require_configured()


async def test_sdk_initialize_list_call_and_read_only(app, monkeypatch):
    execute = AsyncMock(return_value=(json.dumps({"source": SOURCE, "data": {"spend": 50}}), False))
    monkeypatch.setattr(assistant_mcp, "execute_analytics_tool", execute)
    async with client(app, headers=bearer()) as http:
        async with streamable_http_client("https://api.example/mcp", http_client=http) as (read, write, get_id):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=3)) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "saadaa-analytics"
                catalog = await session.list_tools()
                assert {t.name for t in catalog.tools} == DECLARED_TOOLS
                assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in catalog.tools)
                reply = await session.call_tool("get_ad_performance", {"limit": 5})
                assert not reply.isError
                assert reply.structuredContent["data"]["spend"] == 50
                assert get_id() is None
    execute.assert_awaited_once_with("get_ad_performance", {"limit": 5}, read_only=True)


@pytest.mark.parametrize("headers,status", [({}, 401), (bearer("bad"), 401),
    ({**bearer(), "Origin": "https://attacker.example"}, 403), ({**bearer(), "Host": "attacker.example"}, 421)])
async def test_mcp_rejects_anonymous_origin_and_host(app, headers, status):
    async with client(app) as http:
        response = await http.post("/mcp", headers=headers, json={})
        assert response.status_code == status
        assert response.headers["cache-control"] == "no-store"


async def test_cookie_is_scoped_and_not_an_mcp_credential(app, config):
    async with client(app) as http:
        assert (await http.post("/admin/assistant/api/connect", json={"access_key": KEY})).status_code == 403
        response = await http.post("/admin/assistant/api/connect", headers={"Origin": config.public_origin}, json={"access_key": KEY})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert all(part in cookie for part in ["HttpOnly", "Secure", "SameSite=strict", "Path=/api/assistant/api"])
        assert KEY not in cookie and "PROVIDER_SECRET" not in response.text
        signed = http.cookies.get(auth.COOKIE)
        assert auth.signed_identity(signed, "dashboard")["name"] == "Team member"
        assert (await http.post("/mcp", headers=bearer(signed), json={})).status_code == 401
        auth_header = {"Cookie": auth.COOKIE + "=" + signed}
        assert (await http.get("/admin/assistant/api/models", headers=auth_header)).status_code == 200
        assert (await http.post("/admin/assistant/api/chat", headers=auth_header,
                               json={"messages": [{"role": "user", "content": "spend?"}]})).status_code == 403
        config.access_key_hashes = SecretStr(json.dumps({"Another user": "b" * 64}))
        assert (await http.get("/admin/assistant/api/models", headers=auth_header)).status_code == 401


def event(output):
    return 'data: ' + json.dumps({"type": "response.completed", "response": {"status": "completed", "output": output}}) + '\n\n'


async def test_guest_status_and_models_need_no_keys_but_external_mcp_does(app, config):
    config.require_user_auth = False
    config.signing_key = SecretStr("")
    config.access_key_hashes = SecretStr("{}")
    async with client(app) as http:
        response = await http.get("/admin/assistant/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] and data["chat_enabled"] and data["auth_required"] is False
        assert data["mcp_url"] is None and "PROVIDER_SECRET" not in response.text
        assert (await http.get("/admin/assistant/api/models")).status_code == 200
        assert (await http.post("/mcp", headers={"X-Assistant-Visitor": "guest", auth.INTERNAL_PRINCIPAL: "guest"}, json={})).status_code == 401
        assert (await http.post("/admin/assistant/api/chat", headers={"Origin": "https://other.example"},
                               json={"messages": [{"role": "user", "content": "status?"}]})).status_code == 403
        config.enabled = False
        assert (await http.get("/admin/assistant/api/models")).status_code == 503


def test_guest_mode_is_rechecked_and_quota_cannot_be_evaded_by_rotating_visitors(config):
    config.require_user_auth = False
    user = {"key_id": "guest:example", "public": True}
    assert auth.revalidate(user) == user
    config.require_user_auth = True
    with pytest.raises(HTTPException) as denied:
        auth.revalidate(user)
    assert denied.value.status_code == 401
    limits = auth.Limits()
    for visitor in range(3):
        with limits.admit(str(visitor), per_minute=10, concurrent=2, global_per_minute=3):
            pass
    with pytest.raises(HTTPException) as busy:
        with limits.admit("new-visitor", per_minute=10, concurrent=2, global_per_minute=3):
            pytest.fail("Global quota must reject this call")
    assert busy.value.status_code == 429


@pytest.mark.parametrize("guest", [False, True])
async def test_api_chat_reads_through_actual_mcp_protocol(app, config, monkeypatch, guest):
    if guest:
        config.require_user_auth = False
        config.access_key_hashes = SecretStr("{}")
        config.signing_key = SecretStr("")
    calls = []
    execute = AsyncMock(return_value=(json.dumps({"source": SOURCE, "data": {"spend": 50}}), False))
    monkeypatch.setattr(assistant_mcp, "execute_analytics_tool", execute)

    def provider(request):
        assert request.headers["authorization"] == "Bearer PROVIDER_SECRET"
        body = json.loads(request.content)
        calls.append(body)
        assert body["store"] is False and body["max_output_tokens"] == 4000
        assert {t["name"] for t in body["tools"]} == DECLARED_TOOLS
        if len(calls) == 1:
            return httpx.Response(200, text=event([{"type": "function_call", "name": "get_ad_performance", "arguments": '{"limit":5}', "call_id": "fixture-call"}]))
        assert any(m.get("type") == "function_call_output" and '"spend": 50' in m["output"] for m in body["input"])
        return httpx.Response(200, text=event([{"type": "message", "content": [{"type": "output_text", "text": "Spend is 50 in the fixture period."}]}]))

    monkeypatch.setattr(assistant_api, "provider_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    async with client(app) as http:
        response = await http.post("/admin/assistant/api/chat",
                                  headers={"Origin": config.public_origin} if guest else bearer(),
                                  json={"messages": [{"role": "user", "content": "spend?"}]})
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == [SOURCE]
    assert len(calls) == 2
    execute.assert_awaited_once_with("get_ad_performance", {"limit": 5}, read_only=True)
    assert not assistant_api.chat_limits.active


async def test_data_failure_stops_turn_without_provider_retry(app, monkeypatch):
    execute = AsyncMock(side_effect=HTTPException(504, "Data query timed out. Stopped without retrying."))
    monkeypatch.setattr(assistant_mcp, "execute_analytics_tool", execute)
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, text=event([{"type": "function_call", "name": "get_ad_performance", "arguments": '{}', "call_id": "x"}]))

    monkeypatch.setattr(assistant_api, "provider_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    async with client(app) as http:
        response = await http.post("/admin/assistant/api/chat", headers=bearer(), json={"messages": [{"role": "user", "content": "spend?"}]})
    assert response.status_code == 504, response.text
    assert len(calls) == 1
    assert not assistant_api.chat_limits.active


async def test_spend_query_longer_than_old_tool_and_mcp_deadlines_completes(app, monkeypatch):
    """Real tool + MCP + Responses loop; a slow fixture crosses both old cutoffs."""
    @asynccontextmanager
    async def session_factory():
        with Session() as sync_session:
            yield SimpleNamespace(sync_session=sync_session)

    reads = 0
    async def slow_spend(**kwargs):
        nonlocal reads
        reads += 1
        await asyncio.sleep(13)
        return SimpleNamespace(model_dump=lambda **kwargs: {"total_spend": 123.45})

    monkeypatch.setattr(assistant_analytics, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(assistant_analytics.analytics, "get_dashboard_kpis", slow_spend)
    calls = 0

    def provider(request):
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        assert "Today's date in Asia/Kolkata is" in body["instructions"]
        if calls == 1:
            return httpx.Response(200, text=event([{"type": "function_call", "name": "get_dashboard_metrics",
                "arguments": '{"section":"kpis","date_from":"2026-01-01","date_to":"2026-01-07"}', "call_id": "slow-spend"}]))
        assert any(m.get("type") == "function_call_output" and '"total_spend": 123.45' in m["output"] for m in body["input"])
        return httpx.Response(200, text=event([{"type": "message", "content": [{"type": "output_text", "text": "Fixture spend is 123.45."}]}]))

    monkeypatch.setattr(assistant_api, "provider_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    async with client(app) as http:
        response = await http.post("/admin/assistant/api/chat", headers=bearer(),
                                   json={"messages": [{"role": "user", "content": "Spend for 7 days?"}]})
    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Fixture spend is 123.45."
    assert response.json()["sources"][0]["filters"]["date_from"] == "2026-01-01"
    assert calls == 2 and reads == 1
    assert not assistant_api.chat_limits.active


async def test_no_sql_arbitrary_models_or_legacy_bypass(app):
    async with client(app) as http:
        for body in [{"mode": "database"}, {"model": "unapproved-model"}]:
            response = await http.post("/admin/assistant/api/chat", headers=bearer(), json={"messages": [{"role": "user", "content": "test"}], **body})
            assert response.status_code == 400
        assert (await http.get("/admin/assistant/models")).status_code == 403
        assert (await http.get("/mcp", headers=bearer())).status_code == 405


async def test_direct_api_requires_auth_and_caps_body(app):
    async with client(app) as http:
        for path in ["models", "chat"]:
            response = (await http.get("/admin/assistant/api/models") if path == "models" else
                        await http.post("/admin/assistant/api/chat", headers={"Origin": "https://dashboard.example"},
                                        json={"messages": [{"role": "user", "content": "Spend?"}]}))
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
        response = await http.post("/admin/assistant/api/chat", headers=bearer(), content=b"a" * 256001)
        assert response.status_code == 413
        response = await http.post("/mcp", headers={**bearer(), "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}, content=b"a" * 64001)
        assert response.status_code == 413


async def test_mcp_rejects_unknown_write_tools_and_bad_filters_without_database(app, monkeypatch):
    from app.services import assistant_analytics
    factory = AsyncMock(side_effect=AssertionError("Invalid input must not touch DB"))
    monkeypatch.setattr(assistant_analytics, "get_session_factory", factory)
    async with client(app, headers=bearer()) as http:
        async with streamable_http_client("https://api.example/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for name, arguments in [("execute_sql", {"sql": "DELETE FROM ads"}),
                                         ("get_ad_performance", {"limit": 5000}),
                                         ("get_asset_performance", {"sql": "DROP TABLE assets"})]:
                    result = await session.call_tool(name, arguments)
                    assert result.isError
    factory.assert_not_called()


def test_signed_credentials_expire_and_do_not_cross_audiences(config):
    user = auth.access_key(KEY)
    with pytest.raises(HTTPException):
        auth.signed_identity(auth.issue(user, "dashboard", -1), "dashboard")
    with pytest.raises(HTTPException):
        auth.signed_identity(auth.issue(user, "mcp", 90), "dashboard")
    with pytest.raises(HTTPException):
        auth.access_key("PROVIDER_SECRET")


async def test_main_application_owns_mcp_lifespan_and_routes(config, monkeypatch):
    from app import main
    from app.api.routers import analytics
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(main, "shutdown_scheduler", lambda: None)
    monkeypatch.setattr(main, "dispose_engine", AsyncMock())
    monkeypatch.setattr(analytics, "warm_ads_analyse_cache", AsyncMock())
    app = main.create_app()
    async with app.router.lifespan_context(app):
        async with client(app) as http:
            response = await http.post("/mcp", headers={**bearer(), "Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}})
            assert response.status_code == 200, response.text
            assert response.json()["result"]["serverInfo"]["name"] == "saadaa-analytics"
            assert response.headers["cache-control"] == "no-store"
            assert (await http.get("/admin/assistant/api/status")).status_code == 200


def test_limits_release_slots_even_on_failure():
    limits = auth.Limits()
    with limits.admit("a", per_minute=2, concurrent=1):
        with pytest.raises(HTTPException):
            with limits.admit("a", per_minute=2, concurrent=1):
                pass
    with pytest.raises(ValueError):
        with limits.admit("a", per_minute=2, concurrent=1):
            raise ValueError("fixture")
    assert not limits.active
    with pytest.raises(HTTPException):
        with limits.admit("a", per_minute=2, concurrent=1):
            pass
