"""Verify the server's OpenAI API credentials before setting up user authentication.

Reads ASSISTANT_API_OPENAI_KEY and ASSISTANT_API_MODEL from the environment or
the project-root .env. Uses only GET /models; no inference, database access,
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


def check(config: APISettings, client: httpx.Client, *, list_models: bool = False) -> list[str]:
    key = config.openai_key.get_secret_value().strip()
    model = config.model.strip()
    if not key:
        raise ValueError("Set ASSISTANT_API_OPENAI_KEY in the backend environment or project-root .env.")
    if not list_models and not model:
        raise ValueError("Set ASSISTANT_API_MODEL, or run this command with --list-models first.")
    path = "/models" if list_models else "/models/" + quote(model, safe="")
    try:
        response = client.get("https://api.openai.com/v1" + path,
                              headers={"Authorization": "Bearer " + key})
    except httpx.HTTPError:
        # Never print exception strings: HTTP clients may include sensitive request details.
        raise ValueError("Could not connect to OpenAI. Stopped without retrying.") from None
    if response.status_code != 200:
        messages = {
            401: "OpenAI rejected the API key. Check or replace it in the backend environment.",
            403: "OpenAI denied model access. Check the key's project and model-read permissions.",
            404: "The configured model was not found or is unavailable to this project.",
            429: "OpenAI rate or usage limits prevented verification. Check the project's limits.",
        }
        raise ValueError(messages.get(response.status_code, "OpenAI could not verify this connection.")
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
        raise ValueError("OpenAI returned an unexpected model response. Stopped without retrying.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-models", action="store_true", help="List model IDs available to the configured API key.")
    args = parser.parse_args()
    try:
        config = APISettings(_env_file=ROOT / ".env")
    except Exception:
        print("Could not load the assistant environment settings. Check their format; values were not printed.", file=sys.stderr)
        return 1
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            models = check(config, client, list_models=args.list_models)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.list_models:
        print("Available model IDs (choose one supporting Responses API function tools):")
        print("\n".join(models))
    else:
        print("API key accepted; configured model is accessible.")
        print("No inference or database query ran. API chat and user authentication were not enabled.")
        print("Billing availability and Responses tool support still need a small inference test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
