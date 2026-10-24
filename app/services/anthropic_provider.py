"""Shared Anthropic workspace routing and safe, actionable provider errors."""
from __future__ import annotations


def workspace_headers(workspace_id: str) -> dict[str, str]:
    value = workspace_id.strip()
    return {"anthropic-workspace-id": value} if value else {}


def error_message(status: int, body: object) -> str:
    # Inspect known error markers, but never return upstream text: it may echo
    # keys, request contents, or identifiers. Both chat and setup use this map.
    error = body.get("error", body) if isinstance(body, dict) else {}
    message = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
    if "anthropic-workspace-id" in message or "not scoped to a workspace" in message:
        detail = ("This API key needs a workspace ID. Set ASSISTANT_API_ANTHROPIC_WORKSPACE_ID "
                  "to a workspace ID from Claude Console, or use a workspace-scoped API key.")
    elif status == 404 and "workspace" in message:
        detail = "The configured Anthropic workspace was not found or this API key cannot access it."
    elif status == 400 and "credit balance" in message:
        detail = "The Anthropic API account has insufficient credits. Check its billing balance."
    else:
        detail = {
            400: "Claude rejected the request configuration for this model.",
            401: "Anthropic rejected the API key. Check or replace it in the backend environment.",
            403: "Anthropic denied access. Check the key's workspace and model permissions.",
            404: "The selected Claude model was not found or is unavailable to this account.",
            429: "Anthropic rate or usage limits were reached. Check the account's limits.",
        }.get(status, "Anthropic could not complete this request.")
    return f"Claude returned HTTP {status}. {detail} Stopped without retrying."
