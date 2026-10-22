"""OAuth Responses adapter: account models, completed SSE turns, bounded tools."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
from fastapi import HTTPException

from app.services.assistant_analytics import ANALYTICS_TOOLS
from app.services.chatgpt_auth import RESOURCE, provider_json


async def list_models(client: httpx.AsyncClient, token: str) -> list[dict]:
    catalog = await provider_json(client, "GET", RESOURCE + "/models",
                                  headers={"Authorization": "Bearer " + token})
    # The plan-usage catalog differs from the ordinary API-key catalog.
    models = [{"id": m["slug"], "label": m.get("display_name") or m["slug"], "provider": "chatgpt"}
              for m in catalog.get("models", [])
              if isinstance(m, dict) and m.get("visibility") == "list"
              and isinstance(m.get("slug"), str)]
    if not models:
        raise HTTPException(502, "No models were available for this ChatGPT connection.")
    return models


async def completed_response(client: httpx.AsyncClient, token: str, body: dict) -> dict:
    """Don't use partial text or run tools until the terminal completed event."""
    try:
        async with client.stream("POST", RESOURCE + "/responses", json=body,
                                 headers={"Authorization": "Bearer " + token}, timeout=45) as response:
            if not response.is_success:
                status = 401 if response.status_code in {401, 403} else 502
                raise HTTPException(status, f"ChatGPT returned HTTP {response.status_code}. The request was stopped.")
            data_lines: list[str] = []
            size = 0
            async for line in response.aiter_lines():
                size += len(line)
                if size > 2_000_000:
                    raise HTTPException(502, "ChatGPT returned too much data. Try a smaller question.")
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif not line and data_lines:
                    raw = "\n".join(data_lines)
                    data_lines = []
                    if raw == "[DONE]":
                        break
                    event = json.loads(raw)
                    if event.get("type") in {"error", "response.failed", "response.incomplete"}:
                        code = event.get("response", {}).get("error", {}).get("code", "")
                        if code in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable"}:
                            raise HTTPException(429, "ChatGPT plan usage is unavailable or its limit was reached. Check your ChatGPT usage settings.")
                        raise HTTPException(502, "ChatGPT did not complete the answer. The request was stopped.")
                    if event.get("type") == "response.completed":
                        result = event.get("response", {})
                        if result.get("status") != "completed" or not isinstance(result.get("output"), list):
                            raise ValueError("Invalid completion")
                        return result
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(503, "ChatGPT's response was interrupted. Stopped without retrying.") from exc
    raise HTTPException(502, "ChatGPT's response ended before completion. The request was stopped.")


async def answer(client: httpx.AsyncClient, token: str, model: str, prompt: str,
                 messages: list[dict], execute: Callable[[str, dict], Awaitable[tuple[str, bool]]],
                 authorize: Callable[[], None], *, tool_definitions: list[dict] | None = None,
                 max_output_tokens: int | None = None) -> str:
    tools = (tool_definitions if tool_definitions is not None else
             [{"type": "function", **t["function"], "strict": False} for t in ANALYTICS_TOOLS])
    history = list(messages)
    for _ in range(8):
        authorize()
        result = await completed_response(client, token, {
            "model": model, "instructions": prompt, "input": history,
            "tools": tools, "tool_choice": "auto", "parallel_tool_calls": False,
            "store": False, "stream": True, "include": ["reasoning.encrypted_content"],
            **({"max_output_tokens": max_output_tokens} if max_output_tokens else {}),
        })
        calls = [item for item in result["output"] if item.get("type") == "function_call"]
        if not calls:
            text = "".join(block.get("text", "") for item in result["output"]
                           if item.get("type") == "message" for block in item.get("content", [])
                           if block.get("type") == "output_text")
            if not text.strip():
                raise HTTPException(502, "ChatGPT returned no answer. Try a more specific question.")
            authorize()
            return text
        history.extend(result["output"])
        for call in calls:
            authorize()
            try:
                args = json.loads(call["arguments"])
                if not isinstance(args, dict):
                    raise ValueError("Expected object")
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(502, "ChatGPT returned an invalid data request. The request was stopped.") from exc
            content, failed = await execute(call["name"], args)
            history.append({"type": "function_call_output", "call_id": call["call_id"],
                            "output": ("ERROR: " if failed else "") + content})
    raise HTTPException(422, "This question needs too many steps. Split it into smaller questions.")
