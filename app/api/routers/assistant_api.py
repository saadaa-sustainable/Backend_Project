"""API-billed dashboard chat, with optional user authentication and read-only MCP tools."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import anthropic
from fastapi import APIRouter, HTTPException, Request
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, Field, SecretStr
from starlette.responses import JSONResponse

from app.api.routers.assistant import ChatRequest, ChatResponse, ChatSource
from app.services import assistant_api_auth as auth, chatgpt_responses, claude_messages
from app.services.anthropic_provider import workspace_headers
from app.services.assistant_analytics import ANALYTICS_SYSTEM_PROMPT
from app.services.assistant_limits import CHAT_TIMEOUT_SECONDS, MCP_TIMEOUT_SECONDS

router = APIRouter(prefix="/admin/assistant/api", tags=["assistant-api"])
chat_limits = auth.Limits()


def result(body, status=200):
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


class Connection(BaseModel):
    access_key: SecretStr = Field(min_length=47, max_length=47)


@router.get("/status")
async def status(request: Request):
    config = auth.settings()
    try:
        config.require_configured()
    except HTTPException as exc:
        return result({"available": False, "connected": False, "chat_enabled": False,
                       "auth_required": config.require_user_auth, "message": exc.detail})
    try:
        user = auth.authenticated(request)
    except HTTPException:
        user = None
    chat_enabled = any(model["available"] for model in config.models())
    return result({"available": True, "connected": user is not None, "chat_enabled": chat_enabled,
                   "auth_required": config.require_user_auth,
                   "anthropic_configured": bool(config.anthropic_key.get_secret_value().strip()),
                   "user": {"name": user["name"]} if user else None,
                   "mcp_url": config.mcp_url if user and config.require_user_auth else None})


@router.post("/connect")
async def connect(body: Connection, request: Request):
    auth.browser_origin(request)
    user = auth.access_key(body.access_key.get_secret_value())
    config = auth.settings()
    response = result({"available": True, "connected": True, "user": {"name": user["name"]},
                       "auth_required": config.require_user_auth,
                       "chat_enabled": any(model["available"] for model in config.models()),
                       "anthropic_configured": bool(config.anthropic_key.get_secret_value().strip()),
                       "mcp_url": config.mcp_url})
    response.set_cookie(auth.COOKIE, auth.issue(user, "dashboard", 8 * 3600),
                        max_age=8 * 3600, path=auth.COOKIE_PATH, httponly=True, samesite="strict",
                        secure=auth.settings().public_origin.startswith("https://"))
    return response


@router.post("/disconnect")
async def disconnect(request: Request):
    auth.browser_origin(request)
    response = result({"message": "Disconnected from API chat on this browser."})
    response.delete_cookie(auth.COOKIE, path=auth.COOKIE_PATH, httponly=True, samesite="strict",
                           secure=auth.settings().public_origin.startswith("https://"))
    return response


@router.get("/models")
async def models(request: Request):
    auth.authenticated(request)
    config = auth.settings()
    config.require_model()
    return result(config.models())


def provider_client():
    return httpx.AsyncClient(timeout=45, follow_redirects=False)


def anthropic_client(key: str, workspace_id: str = ""):
    return anthropic.AsyncAnthropic(api_key=key.strip(), max_retries=0, timeout=45.0,
                                    default_headers=workspace_headers(workspace_id))


async def mcp_answer(request: Request, body: ChatRequest, user: dict) -> ChatResponse:
    config = auth.settings()
    selected = config.require_model(body.model)
    sources: list[ChatSource] = []
    tool_calls = 0
    # Real HTTP protocol over ASGI, avoiding a network round trip back to our own Render service.
    # Public dashboard chat carries its principal in private ASGI context. Network clients
    # still require MCP bearer keys; HTTP headers cannot inject ASGI scope entries.
    async def internal_mcp(scope, receive, send):
        await request.app.state.analytics_mcp({**scope, auth.INTERNAL_PRINCIPAL: user}, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=internal_mcp),
                                timeout=MCP_TIMEOUT_SECONDS) as transport:
        async with streamable_http_client(config.mcp_url, http_client=transport) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=MCP_TIMEOUT_SECONDS)) as session:
                await session.initialize()
                catalog = await session.list_tools()
                definitions = [{"type": "function", "name": tool.name, "description": tool.description,
                                "parameters": tool.inputSchema, "strict": False} for tool in catalog.tools]
                names = {tool.name for tool in catalog.tools}

                async def execute(name: str, arguments: dict):
                    nonlocal tool_calls
                    auth.revalidate(user)
                    tool_calls += 1
                    if tool_calls > 10 or name not in names:
                        raise HTTPException(422, "This question exceeded the allowed analytics tools. Try a smaller question.")
                    reply = await session.call_tool(name, arguments)
                    content = "\n".join(item.text for item in reply.content if item.type == "text")
                    if reply.isError:
                        failure = reply.structuredContent or {}
                        # A data/tool failure ends the turn before another provider request.
                        raise HTTPException(failure.get("status", 422), failure.get("error", "The analytics request was invalid. Check your filters and try again."))
                    payload = reply.structuredContent or json.loads(content)
                    if payload.get("source"):
                        source = ChatSource.model_validate(payload["source"])
                        if source not in sources:
                            sources.append(source)
                    return content, False

                prompt = ANALYTICS_SYSTEM_PROMPT + "\nToday's date in Asia/Kolkata is " + datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
                if selected["provider"] == "anthropic":
                    async with anthropic_client(config.anthropic_key.get_secret_value(), config.anthropic_workspace_id) as client:
                        message = await claude_messages.answer(
                            client, selected["id"], prompt,
                            [message.model_dump() for message in body.messages], execute,
                            lambda: auth.revalidate(user), tool_definitions=definitions,
                        )
                    return ChatResponse(message=message, sources=sources)
                async with provider_client() as client:
                    try:
                        message = await chatgpt_responses.answer(
                            client, config.openai_key.get_secret_value(), selected["id"], prompt,
                            [message.model_dump() for message in body.messages], execute,
                            lambda: auth.revalidate(user), tool_definitions=definitions,
                            max_output_tokens=4000,
                        )
                    except HTTPException as exc:
                        # A provider API key failure is an administrator setup problem, not user sign-out.
                        if "ChatGPT" in str(exc.detail):
                            raise HTTPException(502 if exc.status_code == 401 else exc.status_code,
                                                str(exc.detail).replace("ChatGPT", "OpenAI API")) from exc
                        raise
    return ChatResponse(message=message, sources=sources)


def _http_failure(exc: BaseException) -> HTTPException | None:
    # AnyIO task groups wrap failures raised inside the MCP client contexts.
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for nested in exc.exceptions:
            if found := _http_failure(nested):
                return found
    return None


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    user = auth.authenticated(request, mutation=True)
    config = auth.settings()
    config.require_model(body.model)
    if body.mode != "analytics":
        raise HTTPException(400, "Use analytics mode and a configured API model.")
    with chat_limits.admit(user["key_id"], per_minute=10, concurrent=2, global_per_minute=30):
        try:
            async with asyncio.timeout(CHAT_TIMEOUT_SECONDS):
                response = await mcp_answer(request, body, user)
            return result(response.model_dump(mode="json"))
        except TimeoutError as exc:
            raise HTTPException(504, f"The answer exceeded {CHAT_TIMEOUT_SECONDS:g} seconds. Stopped without retrying.") from exc
        except Exception as exc:
            if failure := _http_failure(exc):
                raise failure from exc
            raise HTTPException(503, "Could not complete the API/MCP connection. Stopped without retrying.") from exc
