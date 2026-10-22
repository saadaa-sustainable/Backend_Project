"""Hosted OAuth + Responses integration, fully offline with signed JWT fixtures."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException

from app.api.routers import assistant, chatgpt
from app.services import chatgpt_auth as auth, chatgpt_responses as responses


@pytest.fixture
def config(tmp_path, monkeypatch):
    config = auth.ChatGPTSettings(_env_file=None, oauth_enabled=True,
        plan_usage_enabled=True, client_id="oaiapp_test", public_origin="https://dashboard.example",
        auth_db_path=str(tmp_path / "sessions.auth.sqlite"), encryption_key=Fernet.generate_key().decode(),
        allowed_emails="approved@example.com")
    monkeypatch.setattr(auth, "settings", lambda: config)
    return config


@pytest.fixture
def store(config):
    return auth.AuthStore(config)


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def claims(config, **overrides):
    return {"iss": auth.ISSUER, "aud": config.client_id, "sub": "fixture-user",
            "iat": int(time.time()), "exp": int(time.time()) + 3600, "nonce": "nonce",
            "email": "approved@example.com", "email_verified": True, "name": "Fixture User", **overrides}


def metadata():
    return {"issuer": auth.ISSUER, "authorization_endpoint": auth.ISSUER + "/authorize",
            "token_endpoint": auth.ISSUER + "/token", "jwks_uri": auth.ISSUER + "/jwks",
            "revocation_endpoint": auth.ISSUER + "/revoke"}


def record(config, **overrides):
    return {"identity": {"issuer": auth.ISSUER, "client_id": config.client_id, "subject": "fixture-user",
                        "email": "approved@example.com", "email_verified": True, "name": "Fixture User"},
            "metadata": metadata(), "access_token": "PRIVATE_ACCESS", "refresh_token": "PRIVATE_REFRESH",
            "expires_at": time.time() + 3600, "scopes": [auth.PLAN_SCOPE], **overrides}


def transaction(store, key="browser", **overrides):
    store.save(key, "transaction", {"state": "state", "nonce": "nonce", "verifier": "verifier",
        "metadata": metadata(), "plan_requested": True, **overrides}, 600)


def jwks(key):
    return {"keys": [{**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())), "kid": "test", "alg": "RS256"}]}


def http(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
async def browser():
    app = FastAPI()
    app.include_router(assistant.router)
    app.include_router(chatgpt.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://dashboard.example") as client:
        yield client


def session_headers(key="session"):
    return {"Cookie": f"{auth.SESSION_COOKIE}={key}", "Origin": "https://dashboard.example"}


@pytest.mark.parametrize("field,value", [("oauth_enabled", False), ("client_id", "dynamic_agent_client"),
    ("allowed_emails", ""), ("auth_db_path", "relative.sqlite"), ("public_origin", "http://example.com"),
    ("public_origin", "https://dashboard.example/"), ("encryption_key", "invalid")])
def test_configuration_fails_closed(config, field, value):
    candidate = config.model_copy(update={field: value})
    with pytest.raises((HTTPException, AttributeError)):
        candidate.require_configured()


def test_store_encrypts_and_consumes_once_across_workers(config, store):
    store.save("token", "transaction", {"secret": "PRIVATE_ACCESS"}, 600)
    assert b"PRIVATE_ACCESS" not in store.path.read_bytes()
    second_worker = auth.AuthStore(config)
    assert second_worker.get("token", "transaction", consume=True)["secret"] == "PRIVATE_ACCESS"
    assert store.get("token", "transaction", consume=True) is None
    assert store.path.stat().st_mode & 0o777 == 0o600
    store.save("expired", "session", {}, -1)
    assert store.get("expired", "session") is None


def test_session_lease_prevents_refresh_and_disconnect_races(config, store):
    store.save("session", "session", record(config), 600)
    owner = store.lease("session")
    second_worker = auth.AuthStore(config)
    with pytest.raises(HTTPException) as e:
        second_worker.lease("session")
    assert e.value.status_code == 409
    store.release("session", "wrong-owner")
    with pytest.raises(HTTPException):
        second_worker.lease("session")
    store.release("session", owner)
    assert second_worker.lease("session")


def test_session_stays_leased_during_a_long_analytics_turn(config, store, monkeypatch):
    now = time.time()
    store.save("session", "session", record(config), 600)
    owner = store.lease("session")
    monkeypatch.setattr(auth.time, "time", lambda: now + 150)
    with pytest.raises(HTTPException) as busy:
        auth.AuthStore(config).lease("session")
    assert busy.value.status_code == 409
    store.release("session", owner)
    assert store.lease("session")


async def test_start_uses_registered_client_and_browser_bound_pkce(config, store):
    async with http(lambda r: httpx.Response(200, json=metadata())) as client:
        browser_id, url = await auth.begin(config, store, client)
    params = parse_qs(urlsplit(url).query)
    saved = store.get(browser_id, "transaction")
    assert params["client_id"] == [config.client_id]
    assert params["redirect_uri"] == [config.callback_url]
    expected = base64.urlsafe_b64encode(hashlib.sha256(saved["verifier"].encode()).digest()).decode().rstrip("=")
    assert params["code_challenge"] == [expected]
    assert saved["state"] == params["state"][0]
    assert saved["nonce"] == params["nonce"][0]
    assert auth.PLAN_SCOPE in params["scope"][0]
    assert "dynamic_agent_client" not in url


@pytest.mark.parametrize("overrides", [{"nonce": "wrong"}, {"aud": "other"}, {"iss": "https://attacker.example"},
    {"exp": 1}, {"iat": int(time.time()) + 10000}, {"email_verified": False},
    {"email": "stranger@example.com"}, {"azp": "other"}, {"sub": ""}])
async def test_id_token_rejects_wrong_identity_and_unapproved_users(config, signing_key, overrides):
    raw = jwt.encode(claims(config, **overrides), signing_key, algorithm="RS256", headers={"kid": "test"})
    async with http(lambda r: httpx.Response(200, json=jwks(signing_key))) as client:
        with pytest.raises(HTTPException):
            await auth.verify_identity(client, metadata(), raw, config, "nonce")


async def test_unsigned_or_forged_id_tokens_are_rejected(config, signing_key):
    raw = jwt.encode(claims(config), "wrong-secret" * 4, algorithm="HS256", headers={"kid": "test"})
    async with http(lambda r: pytest.fail("Unsupported algorithms must fail before network access")) as client:
        with pytest.raises(HTTPException):
            await auth.verify_identity(client, metadata(), raw, config, "nonce")
    bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    raw = jwt.encode(claims(config), bad_key, algorithm="RS256", headers={"kid": "test"})
    async with http(lambda r: httpx.Response(200, json=jwks(signing_key))) as client:
        with pytest.raises(HTTPException):
            await auth.verify_identity(client, metadata(), raw, config, "nonce")


@pytest.mark.parametrize("params", [{"state": "wrong", "code": "code"},
    {"state": "state", "error": "access_denied", "code": "code"},
    {"state": "state", "code": "code", "client_id": "other"},
    {"state": "state", "code": "code", "iss": "other"}, {"state": "state"}])
async def test_bad_callback_is_consumed_without_redeeming_code(config, store, params):
    transaction(store)
    async with http(lambda r: pytest.fail("Bad callback must not make a provider request")) as client:
        with pytest.raises(HTTPException):
            await auth.finish(config, store, client, "browser", params)
    assert store.get("browser", "transaction") is None


async def test_identity_only_login_never_grants_inference(config, store, signing_key):
    transaction(store, plan_requested=False)
    raw = jwt.encode(claims(config), signing_key, algorithm="RS256", headers={"kid": "test"})
    async with http(lambda r: httpx.Response(200, json=jwks(signing_key) if r.url.path == "/jwks" else {"id_token": raw})) as client:
        key = await auth.finish(config, store, client, "browser", {"state": "state", "code": "code"})
        saved = auth.authenticated(config, store, key)
        assert saved["scopes"] == [] and "access_token" not in saved
        with pytest.raises(HTTPException) as e:
            await auth.access_token(config, store, key, store.lease(key), client)
        assert e.value.status_code == 403


async def test_callback_sets_opaque_cookie_keeps_tokens_server_side(config, store, signing_key, browser, monkeypatch):
    transaction(store)
    raw = jwt.encode(claims(config), signing_key, algorithm="RS256", headers={"kid": "test"})
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(200, json=jwks(signing_key) if request.url.path == "/jwks" else {
            "id_token": raw, "access_token": "PRIVATE_ACCESS", "refresh_token": "PRIVATE_REFRESH",
            "token_type": "Bearer", "expires_in": 3600, "scope": auth.PLAN_SCOPE})
    monkeypatch.setattr(auth, "http_client", lambda: http(provider))
    result = await browser.get("/admin/assistant/chatgpt/callback?state=state&code=CODE",
                               headers={"Cookie": f"{auth.TRANSACTION_COOKIE}=browser"})
    assert result.status_code == 303
    assert result.headers["location"] == config.public_origin + "/user/assistant?assistant=chatgpt"
    key = result.cookies[auth.SESSION_COOKIE]
    assert "httponly" in result.headers["set-cookie"].lower() and "secure" in result.headers["set-cookie"].lower()
    assert "PRIVATE" not in str(result.headers) + result.text
    assert store.get(key, "session")["access_token"] == "PRIVATE_ACCESS"
    form = parse_qs(calls[0].content.decode())
    assert form["code_verifier"] == ["verifier"] and form["redirect_uri"] == [config.callback_url]
    result = await browser.get("/admin/assistant/chatgpt/status", headers=session_headers(key))
    assert result.json()["plan_enabled"] and "PRIVATE" not in result.text
    assert len(calls) == 2


async def test_refresh_is_atomic_rotates_token_and_retains_permissions(config, store):
    store.save("session", "session", record(config, expires_at=0), 600)
    owner = store.lease("session")
    requests = []
    def provider(request):
        requests.append(request)
        return httpx.Response(200, json={"access_token": "NEW_ACCESS", "refresh_token": "NEW_REFRESH",
                                       "token_type": "Bearer", "expires_in": 3600})
    async with http(provider) as client:
        assert await auth.access_token(config, store, "session", owner, client) == "NEW_ACCESS"
        assert await auth.access_token(config, store, "session", owner, client) == "NEW_ACCESS"
    assert len(requests) == 1
    assert store.get("session", "session")["refresh_token"] == "NEW_REFRESH"


async def test_failed_refresh_invalidates_ambiguous_rotation_and_stops(config, store):
    store.save("session", "session", record(config, expires_at=0), 600)
    def provider(request):
        raise httpx.ConnectError("PRIVATE_REFRESH", request=request)
    async with http(provider) as client:
        with pytest.raises(HTTPException) as e:
            await auth.access_token(config, store, "session", store.lease("session"), client)
    assert "PRIVATE" not in e.value.detail
    assert store.get("session", "session") is None


async def test_access_removal_applies_to_existing_session(config, store):
    store.save("session", "session", record(config), 600)
    config.allowed_emails = "another@example.com"
    with pytest.raises(HTTPException):
        auth.authenticated(config, store, "session")
    assert store.get("session", "session") is None


async def test_routes_reject_anonymous_cross_origin_and_database_mode(config, store, browser):
    url = "/admin/assistant/chatgpt/chat"
    body = {"messages": [{"role": "user", "content": "Spend?"}]}
    assert (await browser.post(url, json=body)).status_code == 401
    store.save("session", "session", record(config), 600)
    assert (await browser.post(url, json=body, headers={"Cookie": f"{auth.SESSION_COOKIE}=session"})).status_code == 403
    assert (await browser.post(url, json={**body, "mode": "database"}, headers=session_headers())).status_code == 403
    assert (await browser.post("/admin/assistant/chat", json=body)).status_code == 403


def sse(output):
    return "data: " + json.dumps({"type": "response.completed", "response": {"status": "completed", "output": output}}) + "\n\n"


async def test_real_route_runs_account_model_with_readonly_tools_and_sources(config, store, browser, monkeypatch):
    store.save("session", "session", record(config), 600)
    source = {"label": "Dashboard", "url": "/user/analytics#dashboard", "filters": {}, "basis": "fixture",
              "retrieved_at": "2026-10-17", "cache_note": "fixture", "link_note": "fixture"}
    tool = AsyncMock(return_value=(json.dumps({"source": source, "data": {"spend": 100}}), False))
    monkeypatch.setattr(chatgpt, "execute_analytics_tool", tool)
    requests = []
    def provider(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"slug": "fixture-model", "display_name": "Fixture", "visibility": "list"}]})
        assert request.headers["Authorization"] == "Bearer PRIVATE_ACCESS"
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, text=sse([{"type": "function_call", "name": "get_dashboard_metrics", "arguments": "{}", "call_id": "call1", "id": "fc1"}]))
        return httpx.Response(200, text=sse([{"type": "message", "content": [{"type": "output_text", "text": "Fixture spend: 100"}]}]))
    monkeypatch.setattr(auth, "http_client", lambda: http(provider))
    result = await browser.post("/admin/assistant/chatgpt/chat", json={"model": "fixture-model",
        "messages": [{"role": "user", "content": "Spend?"}]}, headers=session_headers())
    assert result.status_code == 200, result.text
    assert result.json()["sources"] == [source]
    tool.assert_awaited_once_with("get_dashboard_metrics", {}, read_only=True)
    assert len(requests) == 2
    assert all(r["store"] is False and r["stream"] is True for r in requests)
    assert all(t["name"] != "query_sql" for t in requests[0]["tools"])
    assert requests[1]["input"][-1]["type"] == "function_call_output"


@pytest.mark.parametrize("ending", ["", "data: {\"type\":\"response.incomplete\"}\n\n", "data: {\"type\":\"response.failed\"}\n\n"])
async def test_partial_response_never_counts_as_answer(ending):
    data = "data: {\"type\":\"response.output_text.delta\",\"delta\":\"Unconfirmed number\"}\n\n" + ending
    async with http(lambda r: httpx.Response(200, text=data)) as client:
        with pytest.raises(HTTPException):
            await responses.completed_response(client, "token", {})


async def test_failed_tool_prevents_second_model_request():
    requests = []
    def provider(request):
        requests.append(request)
        return httpx.Response(200, text=sse([{"type": "function_call", "name": "get_dashboard_metrics", "arguments": "{}", "call_id": "c"}]))
    async with http(provider) as client:
        with pytest.raises(HTTPException):
            await responses.answer(client, "token", "fixture", "prompt", [],
                AsyncMock(side_effect=HTTPException(503, "Stopped")), lambda: None)
    assert len(requests) == 1


async def test_disconnect_deletes_tokens_even_if_remote_revocation_fails(config, store, browser, monkeypatch):
    store.save("session", "session", record(config), 600)
    requests = []
    def provider(request):
        requests.append(request)
        raise httpx.ConnectError("SECRET", request=request)
    monkeypatch.setattr(auth, "http_client", lambda: http(provider))
    result = await browser.post("/admin/assistant/chatgpt/disconnect", json={}, headers=session_headers())
    assert result.status_code == 200
    assert not result.json()["revocation_confirmed"]
    assert "ChatGPT Settings" in result.json()["message"]
    assert store.get("session", "session") is None and len(requests) == 1


def test_confidential_client_uses_basic_secret_only(config):
    from pydantic import SecretStr
    config.token_auth_method = "client_secret_basic"
    config.client_secret = SecretStr("private:secret+")
    header = auth.token_headers(config)["Authorization"]
    assert base64.b64decode(header.split()[1]).decode() == "oaiapp_test:private%3Asecret%2B"


async def test_turn_timeout_releases_session(config, store, browser, monkeypatch):
    store.save("session", "session", record(config, models=[{"id": "fixture"}], models_until=time.time()+300), 600)
    monkeypatch.setattr(auth, "http_client", lambda: http(lambda r: pytest.fail("No provider request needed")))
    async def timeout(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(responses, "answer", timeout)
    result = await browser.post("/admin/assistant/chatgpt/chat", json={"messages": [{"role": "user", "content": "Spend?"}]}, headers=session_headers())
    assert result.status_code == 504
    assert store.lease("session")


async def test_tool_call_limit_stops_before_eleventh_query(config, store, browser, monkeypatch):
    store.save("session", "session", record(config, models=[{"id": "fixture"}], models_until=time.time()+300), 600)
    monkeypatch.setattr(auth, "http_client", lambda: http(lambda r: pytest.fail("No real provider")))
    tool = AsyncMock(return_value=("Unknown tool", True))
    monkeypatch.setattr(chatgpt, "execute_analytics_tool", tool)
    async def many_tools(client, token, model, prompt, messages, execute, authorize):
        for _ in range(11):
            await execute("query_sql", {})
    monkeypatch.setattr(responses, "answer", many_tools)
    result = await browser.post("/admin/assistant/chatgpt/chat", json={"messages": [{"role": "user", "content": "Spend?"}]}, headers=session_headers())
    assert result.status_code == 422
    assert tool.await_count == 10


async def test_unavailable_connection_never_attempts_network(config, browser, monkeypatch):
    config.oauth_enabled = False
    monkeypatch.setattr(auth, "http_client", lambda: pytest.fail("Unconfigured must stay offline"))
    assert (await browser.get("/admin/assistant/chatgpt/status")).json()["available"] is False
    assert (await browser.post("/admin/assistant/chatgpt/start", json={}, headers=session_headers())).status_code == 503


async def test_duplicate_callback_parameters_are_rejected(config, store, browser, monkeypatch):
    transaction(store)
    monkeypatch.setattr(auth, "http_client", lambda: http(lambda r: pytest.fail("Invalid callback")))
    result = await browser.get("/admin/assistant/chatgpt/callback?state=state&state=other&code=c",
                              headers={"Cookie": f"{auth.TRANSACTION_COOKIE}=browser"})
    assert "signin_failed" in result.headers["location"]
    assert store.get("browser", "transaction") is None


def test_readonly_guard_is_lazy_and_reapplies_for_each_transaction():
    from sqlalchemy.orm import Session
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.services.assistant_analytics import enforce_read_only
    session = Session()
    connection = Mock()
    enforce_read_only(SimpleNamespace(sync_session=session))
    connection.exec_driver_sql.assert_not_called()
    for _ in range(2):
        session.dispatch.after_begin(session, None, connection)
    assert [call.args[0] for call in connection.exec_driver_sql.call_args_list] == [
        "SET TRANSACTION READ ONLY", "SET LOCAL statement_timeout = '120000ms'",
        "SET TRANSACTION READ ONLY", "SET LOCAL statement_timeout = '120000ms'",
    ]
