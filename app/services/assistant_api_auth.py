"""Independent, opt-in API/MCP access. Provider keys never authenticate users."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from collections import deque
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException, Request
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

COOKIE = "saadaa_assistant_api"
COOKIE_PATH = "/api/assistant/api"
ISSUER = "saadaa-assistant"
INTERNAL_PRINCIPAL = "saadaa.assistant.internal_principal"


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASSISTANT_API_", env_file=".env", extra="ignore")
    enabled: bool = False
    require_user_auth: bool = False
    public_origin: str = "http://localhost:3000"
    mcp_url: str = "http://localhost:8002/mcp"
    # JSON {human-readable user label: sha256(access_key)}. Never store raw access keys.
    access_key_hashes: SecretStr = SecretStr("{}")
    signing_key: SecretStr = SecretStr("")
    openai_key: SecretStr = SecretStr("")
    model: str = ""
    # Explicit administrator allowlists, never arbitrary client-selected billing.
    openai_models: tuple[str, ...] = ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra")
    anthropic_key: SecretStr = SecretStr("")
    anthropic_workspace_id: str = ""
    anthropic_models: tuple[str, ...] = (
        "claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5",
    )
    #: Clients and pending authorization codes for the connector OAuth flow.
    #: Never holds an access key or a token -- see app/services/mcp_oauth.py.
    #: Losing this file costs a re-add of the connector, nothing more.
    oauth_store_path: str = "var/mcp_oauth.sqlite3"

    def require_configured(self) -> dict[str, str]:
        try:
            origin, mcp = urlsplit(self.public_origin), urlsplit(self.mcp_url)
            for url in (origin, mcp):
                if (not url.hostname or url.username or url.password or url.query or url.fragment
                    or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))):
                    raise ValueError("Invalid URL")
            if not self.enabled or origin.path or mcp.path != "/mcp":
                raise ValueError("Invalid configuration")
        except (ValueError, TypeError) as exc:
            raise HTTPException(503, "API chat has not been enabled or its URLs are not configured.") from exc
        return self.require_keys() if self.require_user_auth else {}

    def require_keys(self) -> dict[str, str]:
        try:
            hashes = json.loads(self.access_key_hashes.get_secret_value())
            if (not self.enabled or len(self.signing_key.get_secret_value()) < 32
                or not isinstance(hashes, dict) or not hashes or len(hashes) > 500
                or any(not isinstance(k, str) or not 1 <= len(k) <= 100
                       or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                       for k, v in hashes.items())
                or len(set(hashes.values())) != len(hashes)):
                raise ValueError("Invalid configuration")
            return hashes
        except (ValueError, TypeError) as exc:
            raise HTTPException(503, "API and MCP access has not been configured by the administrator.") from exc

    def models(self) -> list[dict]:
        """Public catalog: show setup state without leaking credentials or calling providers."""
        labels = {"gpt-6-luna": "GPT-6 Luna", "gpt-6.1-sol": "GPT-6.1 Sol", "gpt-6-astra": "GPT-6 Astra",
                  "claude-sonnet-5-5": "Claude Sonnet 5.5",
                  "claude-haiku-5-5": "Claude Haiku 5.5", "claude-opus-5-5": "Claude Opus 5.5"}
        catalog = []
        seen = set()
        for provider, ids, key in (
            ("openai", (self.model, *self.openai_models), self.openai_key),
            ("anthropic", self.anthropic_models, self.anthropic_key),
        ):
            for model_id in ids:
                model_id = model_id.strip()
                if not model_id:
                    continue
                if model_id in seen:
                    continue
                seen.add(model_id)
                available = bool(key.get_secret_value().strip())
                name = "Anthropic" if provider == "anthropic" else "OpenAI"
                catalog.append({"id": model_id, "label": labels.get(model_id, model_id),
                                "provider": provider, "available": available,
                                "note": (f"Uses the team's {name} API account."
                                         if available else f"{name} has not been connected by your administrator.")})
        return catalog

    def require_model(self, model_id: str | None = None) -> dict:
        catalog = self.models()
        if model_id:
            selected = next((m for m in catalog if m["id"] == model_id), None)
            if selected is None:
                raise HTTPException(400, "Choose one of the configured API models.")
        else:
            selected = next((m for m in catalog if m["available"]), None)
        if selected is None or not selected["available"]:
            raise HTTPException(503, "The administrator needs to configure the selected provider's API key and model for chat.")
        return selected


@lru_cache(maxsize=1)
def _cached_settings(env_path: Path, signature: tuple | None) -> APISettings:
    return APISettings(_env_file=env_path)


def settings() -> APISettings:
    # Adding/rotating a key in .env must not leave the model catalog disabled
    # until a process restart. Reuse settings until the file actually changes.
    env_path = Path(".env").resolve()
    try:
        stat = env_path.stat()
        signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    except FileNotFoundError:
        signature = None
    return _cached_settings(env_path, signature)


def identity(digest: str) -> dict:
    settings().require_configured()
    for name, allowed in settings().require_keys().items():
        if hmac.compare_digest(digest, allowed):
            return {"name": name, "key_id": digest}
    raise HTTPException(401, "Access key expired or was revoked. Ask your administrator for access.")


def access_key(key: str) -> dict:
    settings().require_configured()
    if not re.fullmatch(r"sda_[A-Za-z0-9_-]{43}", key):
        raise HTTPException(401, "Invalid assistant access key.")
    return identity(hashlib.sha256(key.encode()).hexdigest())


def issue(principal: dict, audience: str, seconds: int) -> str:
    now = int(time.time())
    return jwt.encode({"iss": ISSUER, "aud": audience, "sub": principal["key_id"],
                       "iat": now, "exp": now + seconds},
                      settings().signing_key.get_secret_value(), algorithm="HS256")


def signed_identity(token: str, audience: str) -> dict:
    settings().require_configured()
    settings().require_keys()
    try:
        claims = jwt.decode(token, settings().signing_key.get_secret_value(), algorithms=["HS256"],
                            issuer=ISSUER, audience=audience,
                            options={"require": ["iss", "aud", "sub", "iat", "exp"]})
        if not re.fullmatch(r"[0-9a-f]{64}", claims["sub"]):
            raise ValueError("Invalid subject")
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Assistant connection expired. Connect again.") from exc
    return identity(claims["sub"])


def bearer(request: Request) -> str:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 2048:
        raise HTTPException(401, "An assistant access key is required.", headers={"WWW-Authenticate": "Bearer"})
    return token


def mcp_identity(request: Request) -> dict:
    # This scope entry is injected only by our in-process ASGI transport, never a header.
    if principal := request.scope.get(INTERNAL_PRINCIPAL):
        return revalidate(principal)
    token = bearer(request)
    return access_key(token) if token.startswith("sda_") else signed_identity(token, "mcp")


def browser_origin(request: Request) -> None:
    if request.headers.get("origin") != settings().public_origin:
        raise HTTPException(403, "This action must start from the dashboard.")


def authenticated(request: Request, *, mutation: bool = False) -> dict:
    config = settings()
    config.require_configured()
    if request.headers.get("authorization"):
        return access_key(bearer(request))
    if not config.require_user_auth:
        if mutation:
            browser_origin(request)
        # Visitor IDs are only rate-limit hints, not credentials. A global quota also applies.
        visitor = request.headers.get("x-assistant-visitor", "")
        try:
            visitor = str(uuid.UUID(visitor))
        except ValueError:
            visitor = request.client.host if request.client else "unknown"
        return {"name": "Team analytics", "key_id": "guest:" + visitor, "public": True}
    # Bearer keys allow API clients; browser sessions also require exact Origin on mutations.
    if mutation:
        browser_origin(request)
    return signed_identity(request.cookies.get(COOKIE, ""), "dashboard")


def revalidate(principal: dict) -> dict:
    config = settings()
    config.require_configured()
    if principal.get("public") is True:
        if config.require_user_auth:
            raise HTTPException(401, "Direct chat access has been disabled.")
        return principal
    return identity(principal["key_id"])


class Limits:
    """Per-worker admission limits. No waiting queue or automatic retries."""
    def __init__(self):
        self.active: set[str] = set()
        self.recent: dict[str, deque] = {}

    @contextmanager
    def admit(self, key: str, *, per_minute: int, concurrent: int, global_per_minute: int = 120):
        now = time.monotonic()
        # Bounded to recently used identities even after allowlist rotations.
        self.recent = {k: q for k, q in self.recent.items() if q and q[-1] > now - 60}
        for recent in self.recent.values():
            while recent and recent[0] <= now - 60:
                recent.popleft()
        queue = self.recent.setdefault(key, deque())
        while queue and queue[0] <= now - 60:
            queue.popleft()
        if (key in self.active or len(self.active) >= concurrent or len(queue) >= per_minute
            or sum(len(q) for q in self.recent.values()) >= global_per_minute):
            raise HTTPException(429, "Assistant is busy or the request limit was reached. Try again shortly.")
        queue.append(now)
        self.active.add(key)
        try:
            yield
        finally:
            self.active.discard(key)
