"""First-party session endpoints, accessed through the dashboard's same-origin proxy."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routers.assistant import ChatRequest, ChatResponse, ChatSource
from app.services import chatgpt_auth as auth, chatgpt_responses
from app.services.assistant_analytics import ANALYTICS_SYSTEM_PROMPT, execute_analytics_tool
from app.services.assistant_limits import CHAT_TIMEOUT_SECONDS

router = APIRouter(prefix="/admin/assistant/chatgpt", tags=["assistant"])


def json_response(data: dict | list, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def cookie(response, name: str, value: str, config: auth.ChatGPTSettings, ttl: int):
    response.set_cookie(name, value, max_age=ttl, httponly=True, samesite="lax",
                        secure=config.public_origin.startswith("https://"), path=auth.COOKIE_PATH)


def check_origin(request: Request, config: auth.ChatGPTSettings):
    if request.headers.get("origin") != config.public_origin:
        raise HTTPException(403, "This action must start from the dashboard.")


def connection(request: Request):
    config = auth.settings()
    config.require_configured()
    store = auth.AuthStore(config)
    session_id = request.cookies.get(auth.SESSION_COOKIE, "")
    auth.authenticated(config, store, session_id)
    return config, store, session_id


@router.get("/status")
async def status(request: Request):
    config = auth.settings()
    try:
        config.require_configured()
    except HTTPException:
        return json_response({"available": False, "connected": False, "plan_enabled": False,
                              "message": "ChatGPT connection is awaiting administrator setup."})
    store = auth.AuthStore(config)
    session_id = request.cookies.get(auth.SESSION_COOKIE, "")
    try:
        record = auth.authenticated(config, store, session_id)
    except HTTPException:
        return json_response({"available": True, "connected": False, "plan_enabled": False})
    return json_response({"available": True, "connected": True,
        "plan_enabled": config.plan_usage_enabled and auth.PLAN_SCOPE in record.get("scopes", []),
        "user": {"name": record["identity"]["name"], "email": record["identity"]["email"]}})


@router.post("/start")
async def start(request: Request):
    config = auth.settings()
    config.require_configured()
    check_origin(request, config)
    store = auth.AuthStore(config)
    # Starting another attempt invalidates the old transaction for this browser.
    store.delete(request.cookies.get(auth.TRANSACTION_COOKIE, ""))
    async with auth.http_client() as client:
        browser_id, url = await auth.begin(config, store, client)
    response = json_response({"url": url})
    cookie(response, auth.TRANSACTION_COOKIE, browser_id, config, 600)
    return response


@router.get("/callback")
async def callback(request: Request):
    config = auth.settings()
    config.require_configured()
    store = auth.AuthStore(config)
    try:
        async with asyncio.timeout(35), auth.http_client() as client:
            # Duplicate callback parameters are ambiguous and must not be accepted.
            if len(request.query_params.multi_items()) != len(request.query_params):
                store.delete(request.cookies.get(auth.TRANSACTION_COOKIE, ""))
                raise HTTPException(401, "Ambiguous callback")
            session_id = await auth.finish(config, store, client,
                request.cookies.get(auth.TRANSACTION_COOKIE, ""), dict(request.query_params))
        store.delete(request.cookies.get(auth.SESSION_COOKIE, ""))
        response = RedirectResponse(config.public_origin + "/user/assistant?assistant=chatgpt", status_code=303)
        cookie(response, auth.SESSION_COOKIE, session_id, config, auth.SESSION_SECONDS)
    except (HTTPException, TimeoutError) as exc:
        # Never reflect OAuth codes, upstream error descriptions or tokens into the UI.
        error = "access_denied" if isinstance(exc, HTTPException) and exc.status_code == 403 else "signin_failed"
        response = RedirectResponse(config.public_origin + "/user/assistant?chatgpt_error=" + error, status_code=303)
    response.delete_cookie(auth.TRANSACTION_COOKIE, path=auth.COOKIE_PATH)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


async def account_models(client, config, store, session_id, owner, token):
    record = auth.authenticated(config, store, session_id)
    if record.get("models_until", 0) > time.time():
        return record["models"]
    models = await chatgpt_responses.list_models(client, token)
    record.update(models=models, models_until=time.time() + 300)
    store.update(session_id, owner, record)
    return models


@router.get("/models")
async def models(request: Request):
    config, store, session_id = connection(request)
    owner = store.lease(session_id)
    try:
        async with asyncio.timeout(25), auth.http_client() as client:
            token = await auth.access_token(config, store, session_id, owner, client)
            return json_response(await account_models(client, config, store, session_id, owner, token))
    except TimeoutError as exc:
        raise HTTPException(504, "Loading ChatGPT models timed out. Stopped without retrying.") from exc
    finally:
        store.release(session_id, owner)


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    config, store, session_id = connection(request)
    check_origin(request, config)
    if body.mode != "analytics":
        raise HTTPException(403, "This connection can only read approved analytics.")
    owner = store.lease(session_id)
    sources: dict[str, ChatSource] = {}
    calls = 0

    def authorize():
        auth.authenticated(config, store, session_id)

    async def execute(name: str, args: dict):
        nonlocal calls
        authorize()
        calls += 1
        if calls > 10:
            raise HTTPException(422, "This question needs too many data requests. Split it into smaller questions.")
        content, failed = await execute_analytics_tool(name, args, read_only=True)
        if not failed:
            source = ChatSource.model_validate(json.loads(content)["source"])
            sources[json.dumps([source.url, source.filters], sort_keys=True)] = source
        return content, failed

    try:
        async with asyncio.timeout(CHAT_TIMEOUT_SECONDS), auth.http_client() as client:
            token = await auth.access_token(config, store, session_id, owner, client)
            available = await account_models(client, config, store, session_id, owner, token)
            model = body.model or available[0]["id"]
            if model not in {m["id"] for m in available}:
                raise HTTPException(400, "Choose a model available to your ChatGPT account.")
            prompt = ANALYTICS_SYSTEM_PROMPT + "\nToday's date in Asia/Kolkata is " + datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
            answer = await chatgpt_responses.answer(client, token, model, prompt,
                [{"role": m.role, "content": m.content} for m in body.messages], execute, authorize)
            return json_response(ChatResponse(message=answer, sources=list(sources.values())).model_dump())
    except HTTPException as exc:
        if exc.status_code == 401:
            store.delete(session_id)
        raise
    except TimeoutError as exc:
        raise HTTPException(504, f"The assistant exceeded {CHAT_TIMEOUT_SECONDS:g} seconds. Stopped without retrying.") from exc
    finally:
        store.release(session_id, owner)


@router.post("/disconnect")
async def disconnect(request: Request):
    config = auth.settings()
    config.require_configured()
    check_origin(request, config)
    store = auth.AuthStore(config)
    session_id = request.cookies.get(auth.SESSION_COOKIE, "")
    record = store.get(session_id, "session")
    confirmed = True
    if record:
        owner = store.lease(session_id)
        try:
            # A refresh could have completed between the first read and lease.
            record = store.get(session_id, "session") or {}
            refresh = record.get("refresh_token")
            if refresh:
                confirmed = False
                endpoint = auth.trusted_endpoint(record["metadata"].get("revocation_endpoint"))
                async with auth.http_client() as client:
                    response = await client.post(endpoint, headers=auth.token_headers(config),
                        data={"token": refresh, "token_type_hint": "refresh_token", "client_id": config.client_id})
                    confirmed = response.status_code == 200
        except Exception:
            confirmed = False
        finally:
            store.delete(session_id)
            store.release(session_id, owner)
    store.delete(request.cookies.get(auth.TRANSACTION_COOKIE, ""))
    response = json_response({"disconnected": True, "revocation_confirmed": confirmed,
        "message": "Disconnected." if confirmed else "Disconnected here. Remote revocation could not be confirmed; remove this app in ChatGPT Settings."})
    response.delete_cookie(auth.SESSION_COOKIE, path=auth.COOKIE_PATH)
    response.delete_cookie(auth.TRANSACTION_COOKIE, path=auth.COOKIE_PATH)
    return response
