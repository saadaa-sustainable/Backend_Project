"""Verify the server's OpenAI or Anthropic API credentials without user authentication.

Reads ASSISTANT_API_OPENAI_KEY and ASSISTANT_API_MODEL from the environment or
the project-root .env. --provider anthropic uses ASSISTANT_API_ANTHROPIC_KEY
and ASSISTANT_API_ANTHROPIC_MODELS. Uses only GET /models; no inference, database access,
credential writes, automatic retries, or user-auth configuration is involved.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.assistant_api_auth import APISettings  # noqa: E402
from app.services.anthropic_provider import error_message, workspace_headers  # noqa: E402


def check(config: APISettings, client: httpx.Client, *, list_models: bool = False,
          provider: str = "openai", model_id: str | None = None) -> list[str]:
    claude = provider == "anthropic"
    name = "Anthropic" if claude else "OpenAI"
    key = (config.anthropic_key if claude else config.openai_key).get_secret_value().strip()
    model = (model_id or (next(iter(config.anthropic_models), "") if claude else config.model)).strip()
    if not key:
        env_name = "ASSISTANT_API_ANTHROPIC_KEY" if claude else "ASSISTANT_API_OPENAI_KEY"
        raise ValueError(f"Set {env_name} in the backend environment or project-root .env.")
    if not list_models and not model:
        raise ValueError("Set ASSISTANT_API_MODEL, or run this command with --list-models first.")
    path = "/models" if list_models else "/models/" + quote(model, safe="")
    base = "https://api.anthropic.com/v1" if claude else "https://api.openai.com/v1"
    headers = ({"x-api-key": key, "anthropic-version": "2023-06-01"} if claude else
               {"Authorization": "Bearer " + key})
    if claude:
        headers.update(workspace_headers(config.anthropic_workspace_id))
    try:
        response = client.get(base + path, headers=headers)
    except httpx.HTTPError:
        # Never print exception strings: HTTP clients may include sensitive request details.
        raise ValueError(f"Could not connect to {name}. Stopped without retrying.") from None
    if response.status_code != 200:
        if claude:
            try:
                body = response.json()
            except ValueError:
                body = None
            raise ValueError(error_message(response.status_code, body))
        messages = {
            401: f"{name} rejected the API key. Check or replace it in the backend environment.",
            403: f"{name} denied model access. Check the key's project and model-read permissions.",
            404: "The configured model was not found or is unavailable to this project.",
            429: f"{name} rate or usage limits prevented verification. Check the project's limits.",
        }
        raise ValueError(messages.get(response.status_code, f"{name} could not verify this connection.")
                         + " Stopped without retrying.")
    try:
        body = response.json()
        models = body["data"] if list_models else [body]
        if not isinstance(models, list) or any(not isinstance(m, dict) or not isinstance(m.get("id"), str) for m in models):
            raise ValueError
        ids = sorted({m["id"] for m in models})
        if not ids or (not list_models and ids != [model]):
            raise ValueError
        return ids
    except (ValueError, KeyError, TypeError):
        raise ValueError(f"{name} returned an unexpected model response. Stopped without retrying.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-models", action="store_true", help="List model IDs available to the configured API key.")
    parser.add_argument("--provider", choices=("openai", "anthropic"), default="openai")
    parser.add_argument("--model", help="Exact model ID to verify; defaults to the configured first model.")
    args = parser.parse_args()
    try:
        config = APISettings(_env_file=ROOT / ".env")
    except Exception:
        print("Could not load the assistant environment settings. Check their format; values were not printed.", file=sys.stderr)
        return 1
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            models = check(config, client, list_models=args.list_models,
                           provider=args.provider, model_id=args.model)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.list_models:
        print("Available model IDs (choose one supporting the provider's function tools):")
        print("\n".join(models))
    else:
        print(f"{args.provider.title()} API key accepted; configured model is accessible.")
        print("No inference or database query ran. API chat and user authentication were not enabled.")
        print("Billing availability and tool support still need a small inference test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
