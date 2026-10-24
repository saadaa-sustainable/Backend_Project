"""Claude Messages adapter for the same authorized, read-only MCP tools as GPT.

No provider retries or automatic provider switching. Execute tools only after a
complete tool-use response, and never return truncated answers as successful.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import anthropic
from fastapi import HTTPException

from app.services.anthropic_provider import error_message


async def answer(
    client: anthropic.AsyncAnthropic, model: str, prompt: str, messages: list[dict],
    execute: Callable[[str, dict], Awaitable[tuple[str, bool]]],
    authorize: Callable[[], None], *, tool_definitions: list[dict],
    max_output_tokens: int = 4000,
) -> str:
    tools = [{"name": tool["name"], "description": tool["description"],
              "input_schema": tool["parameters"]} for tool in tool_definitions]
    names = {tool["name"] for tool in tools}
    history = [dict(message) for message in messages]
    for _ in range(8):
        authorize()
        try:
            response = await client.messages.create(
                model=model, max_tokens=max_output_tokens, system=prompt,
                messages=history, tools=tools,
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            )
        except anthropic.APIStatusError as exc:
            status = 429 if exc.status_code == 429 else 502
            raise HTTPException(status, error_message(exc.status_code, exc.body)) from None
        except anthropic.APIConnectionError:
            raise HTTPException(503, "Could not reach Claude. Stopped without retrying.") from None
        authorize()
        if response.stop_reason not in {"tool_use", "end_turn"}:
            raise HTTPException(502, "Claude did not complete the answer. Stopped without retrying.")
        calls = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason == "end_turn":
            if calls:
                raise HTTPException(502, "Claude returned an invalid tool response. The request was stopped.")
            message = "".join(block.text for block in response.content if block.type == "text")
            if not message.strip():
                raise HTTPException(502, "Claude returned no answer. Try a more specific question.")
            return message
        if (not calls or any(call.name not in names or not isinstance(call.input, dict)
                             or not call.id for call in calls)
                or len({call.id for call in calls}) != len(calls)):
            raise HTTPException(502, "Claude returned an invalid analytics request. The request was stopped.")
        # Preserve all blocks (including signed thinking) unmodified for the
        # next turn; tool_result messages immediately follow their tool_use.
        history.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in response.content]})
        results = []
        for call in calls:
            authorize()
            content, failed = await execute(call.name, call.input)
            if failed:
                raise HTTPException(422, "The analytics tool failed. Stopped without retrying.")
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": content})
        history.append({"role": "user", "content": results})
    raise HTTPException(422, "This question needs too many steps. Split it into smaller questions.")
