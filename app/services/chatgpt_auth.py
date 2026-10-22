"""Hosted Sign in with ChatGPT. Disabled until a partner client is provisioned.

This store is separate from the analytics warehouse. Use a private persistent
disk on ONE backend host (multiple workers on that host are supported). All
stored records are encrypted; browser cookies contain only random identifiers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote_plus, urlencode, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.assistant_limits import SESSION_LEASE_SECONDS

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
COOKIE_PATH = "/api/assistant/chatgpt"
SESSION_COOKIE = "saadaa_chatgpt_session"
TRANSACTION_COOKIE = "saadaa_chatgpt_signin"
SESSION_SECONDS = 8 * 3600


class ChatGPTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHATGPT_", env_file=".env", extra="ignore")
    oauth_enabled: bool = False
    plan_usage_enabled: bool = False
    client_id: str = ""
    client_secret: SecretStr | None = None
    token_auth_method: Literal["none", "client_secret_basic"] = "none"
    public_origin: str = "http://localhost:3000"
    auth_db_path: str = ""
    encryption_key: SecretStr | None = None
    # Comma-separated exact verified addresses. Each approved user has read
    # access to this single SAADAA dataset. No automatic account linking.
    allowed_emails: str = ""

    @property
    def emails(self) -> set[str]:
        return {e.strip().casefold() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def callback_url(self) -> str:
        return self.public_origin + COOKIE_PATH + "/callback"

    def require_configured(self) -> None:
        url = urlsplit(self.public_origin)
        valid_origin = (
            url.scheme in {"http", "https"} and bool(url.hostname)
            and not url.username and not url.password and not url.path
            and not url.query and not url.fragment
            and (url.scheme == "https" or url.hostname in {"localhost", "127.0.0.1"})
        )
        if not (
            self.oauth_enabled and self.client_id.startswith("oaiapp_")
            and valid_origin and self.auth_db_path and Path(self.auth_db_path).is_absolute()
            and self.encryption_key and self.emails
            and (self.token_auth_method == "none" or self.client_secret)
        ):
            raise HTTPException(503, "ChatGPT connection is awaiting administrator setup.")
        try:
            Fernet(self.encryption_key.get_secret_value().encode())
        except (ValueError, TypeError) as exc:
            raise HTTPException(503, "ChatGPT connection is awaiting administrator setup.") from exc


@lru_cache
def settings() -> ChatGPTSettings:
    return ChatGPTSettings()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AuthStore:
    """Atomic consume/update/lease operations, with no network I/O in a transaction."""
    def __init__(self, config: ChatGPTSettings):
        config.require_configured()
        self.path = Path(config.auth_db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = Fernet(config.encryption_key.get_secret_value().encode())
        # Create with owner-only permissions before SQLite opens it.
        import os
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                       "payload BLOB NOT NULL, expires REAL NOT NULL, lease TEXT, lease_until REAL)")
            db.execute("CREATE INDEX IF NOT EXISTS records_expiry ON records(expires)")
            db.execute("DELETE FROM records WHERE expires < ?", (time.time(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, key: str, kind: str, value: dict, ttl: int) -> None:
        blob = self.cipher.encrypt(json.dumps(value).encode())
        with self.connect() as db:
            db.execute("INSERT INTO records(id,kind,payload,expires) VALUES(?,?,?,?)",
                       (digest(key), kind, blob, time.time() + ttl))

    def get(self, key: str, kind: str, *, consume: bool = False) -> dict | None:
        with self.connect() as db:
            if consume:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload,expires FROM records WHERE id=? AND kind=?",
                             (digest(key), kind)).fetchone()
            if consume or (row and row[1] <= time.time()):
                db.execute("DELETE FROM records WHERE id=? AND kind=?", (digest(key), kind))
        if not row or row[1] <= time.time():
            return None
        return json.loads(self.cipher.decrypt(row[0]))

    def delete(self, key: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM records WHERE id=?", (digest(key),))

    def lease(self, key: str) -> str:
        owner = secrets.token_urlsafe(24)
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE records SET lease=?,lease_until=? WHERE id=? AND kind='session' "
                "AND expires>? AND (lease_until IS NULL OR lease_until<?)",
                (owner, time.time() + SESSION_LEASE_SECONDS, digest(key), time.time(), time.time()),
            )
            if cursor.rowcount != 1:
                raise HTTPException(409, "Another request is using this connection. Wait for it to finish.")
        return owner

    def release(self, key: str, owner: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE records SET lease=NULL,lease_until=NULL WHERE id=? AND lease=?",
                       (digest(key), owner))

    def update(self, key: str, owner: str, value: dict) -> None:
        with self.connect() as db:
            cursor = db.execute("UPDATE records SET payload=? WHERE id=? AND lease=? AND expires>?",
                                (self.cipher.encrypt(json.dumps(value).encode()), digest(key),
                                 owner, time.time()))
            if cursor.rowcount != 1:
                raise HTTPException(401, "Your connection expired. Continue with ChatGPT again.")


def http_client() -> httpx.AsyncClient:
    # No automatic retries or redirects carrying credentials to another host.
    return httpx.AsyncClient(timeout=10, follow_redirects=False)


async def provider_json(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
    try:
        response = await client.request(method, url, **kwargs)
        if not response.is_success:
            status = 401 if response.status_code in {401, 403} else 502
            raise HTTPException(status, f"OpenAI returned HTTP {response.status_code}. The request was stopped.")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected object")
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Could not complete the OpenAI request. Stopped without retrying.") from exc


def trusted_endpoint(value: Any) -> str:
    if not isinstance(value, str):
        raise HTTPException(502, "OpenAI sign-in configuration is incomplete.")
    url = urlsplit(value)
    if url.scheme != "https" or url.netloc != "auth.openai.com" or url.fragment:
        raise HTTPException(502, "OpenAI sign-in configuration could not be verified.")
    return value


async def discovery(client: httpx.AsyncClient) -> dict:
    data = await provider_json(client, "GET", ISSUER + "/.well-known/openid-configuration")
    if data.get("issuer") != ISSUER:
        raise HTTPException(502, "OpenAI sign-in issuer could not be verified.")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        trusted_endpoint(data.get(field))
    return data


def token_headers(config: ChatGPTSettings) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if config.token_auth_method == "client_secret_basic":
        credential = quote_plus(config.client_id) + ":" + quote_plus(config.client_secret.get_secret_value())
        headers["Authorization"] = "Basic " + base64.b64encode(credential.encode()).decode()
    return headers


def permitted(identity: dict, config: ChatGPTSettings) -> bool:
    return (
        identity.get("email_verified") is True
        and isinstance(identity.get("email"), str)
        and identity["email"].casefold() in config.emails
        and identity.get("issuer") == ISSUER and identity.get("client_id") == config.client_id
        and bool(identity.get("subject"))
    )


async def verify_identity(client: httpx.AsyncClient, metadata: dict, raw: str,
                          config: ChatGPTSettings, nonce: str | None) -> dict:
    try:
        header = jwt.get_unverified_header(raw)
        if header.get("alg") not in {"RS256", "ES256"} or not header.get("kid"):
            raise ValueError("Unsupported signing key")
        # Fetch once per sign-in (also handles rotation); never a retry loop.
        jwks = await provider_json(client, "GET", trusted_endpoint(metadata["jwks_uri"]))
        candidates = [k for k in jwks.get("keys", []) if k.get("kid") == header["kid"]]
        if len(candidates) != 1:
            raise ValueError("Unknown signing key")
        key = jwt.PyJWK.from_dict(candidates[0], algorithm=header["alg"])
        claims = jwt.decode(raw, key.key, algorithms=[header["alg"]], audience=config.client_id,
                            issuer=ISSUER, leeway=5,
                            options={"require": ["iss", "aud", "sub", "exp", "iat"]})
        if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("Invalid nonce")
        if claims.get("azp", config.client_id) != config.client_id:
            raise ValueError("Invalid authorized party")
        if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and not claims.get("azp"):
            raise ValueError("Missing authorized party")
        identity = {"issuer": ISSUER, "client_id": config.client_id, "subject": claims["sub"],
                    "email": claims.get("email"), "email_verified": claims.get("email_verified"),
                    "name": claims.get("name")}
        if not permitted(identity, config):
            raise HTTPException(403, "This account has not been granted access to the analytics assistant.")
        return identity
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(401, "ChatGPT identity could not be verified. Start sign-in again.") from exc


async def begin(config: ChatGPTSettings, store: AuthStore, client: httpx.AsyncClient) -> tuple[str, str]:
    metadata = await discovery(client)
    browser_id, state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    scopes = "openid profile email"
    params = {"client_id": config.client_id, "redirect_uri": config.callback_url,
              "response_type": "code", "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    if config.plan_usage_enabled:
        scopes += " offline_access resource.invoke " + PLAN_SCOPE
        params["resource"] = RESOURCE
    params["scope"] = scopes
    store.save(browser_id, "transaction", {"state": state, "nonce": nonce, "verifier": verifier,
               "metadata": metadata, "plan_requested": config.plan_usage_enabled}, 600)
    return browser_id, metadata["authorization_endpoint"] + "?" + urlencode(params)


def token_record(tokens: dict, previous: dict | None = None) -> dict:
    old = previous or {}
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access or tokens.get("token_type", "").lower() != "bearer":
        raise HTTPException(502, "OpenAI did not return a usable ChatGPT plan connection.")
    try:
        ttl = int(tokens["expires_in"])
        if ttl <= 0:
            raise ValueError("expired")
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(502, "OpenAI returned invalid token expiry information.") from exc
    scope = tokens.get("scope")
    if scope is not None and not isinstance(scope, str):
        raise HTTPException(502, "OpenAI returned invalid permission information.")
    return {"access_token": access, "refresh_token": tokens.get("refresh_token", old.get("refresh_token")),
            "expires_at": time.time() + ttl, "scopes": scope.split() if scope is not None else old.get("scopes", [])}


async def finish(config: ChatGPTSettings, store: AuthStore, client: httpx.AsyncClient,
                 browser_id: str, params: dict) -> str:
    transaction = store.get(browser_id, "transaction", consume=True)
    if not transaction or not secrets.compare_digest(transaction["state"], params.get("state", "")):
        raise HTTPException(401, "Sign-in expired or could not be verified. Continue with ChatGPT again.")
    if params.get("error"):
        raise HTTPException(400, "ChatGPT sign-in was cancelled. You can try again when ready.")
    if not params.get("code") or params.get("client_id", config.client_id) != config.client_id:
        raise HTTPException(401, "ChatGPT sign-in callback could not be verified.")
    if params.get("iss", ISSUER) != ISSUER:
        raise HTTPException(401, "ChatGPT sign-in callback issuer could not be verified.")
    body = {"grant_type": "authorization_code", "code": params["code"],
            "redirect_uri": config.callback_url, "client_id": config.client_id,
            "code_verifier": transaction["verifier"]}
    if transaction["plan_requested"]:
        body["resource"] = RESOURCE
    tokens = await provider_json(client, "POST", trusted_endpoint(transaction["metadata"]["token_endpoint"]),
                                 data=body, headers=token_headers(config))
    identity = await verify_identity(client, transaction["metadata"], tokens.get("id_token", ""),
                                     config, transaction["nonce"])
    # Identity-only success stays signed in, with inference explicitly disabled.
    record = {"identity": identity, "metadata": transaction["metadata"], "scopes": []}
    if transaction["plan_requested"] and tokens.get("access_token"):
        record.update(token_record(tokens))
    session_id = secrets.token_urlsafe(32)
    store.save(session_id, "session", record, SESSION_SECONDS)
    return session_id


def authenticated(config: ChatGPTSettings, store: AuthStore, session_id: str) -> dict:
    record = store.get(session_id, "session")
    if not record or not permitted(record.get("identity", {}), config):
        store.delete(session_id)
        raise HTTPException(401, "Your connection expired or access was removed. Continue with ChatGPT again.")
    return record


async def access_token(config: ChatGPTSettings, store: AuthStore, session_id: str,
                       owner: str, client: httpx.AsyncClient) -> str:
    record = authenticated(config, store, session_id)
    if not config.plan_usage_enabled or PLAN_SCOPE not in record.get("scopes", []):
        raise HTTPException(403, "Signed in, but ChatGPT plan usage is not enabled for this connection.")
    if record.get("expires_at", 0) < time.time() + 60:
        refresh = record.get("refresh_token")
        if not refresh:
            raise HTTPException(401, "ChatGPT access expired. Continue with ChatGPT again.")
        try:
            tokens = await provider_json(client, "POST", trusted_endpoint(record["metadata"]["token_endpoint"]),
                headers=token_headers(config), data={"grant_type": "refresh_token", "client_id": config.client_id,
                    "refresh_token": refresh, "resource": RESOURCE})
            if tokens.get("id_token"):
                identity = await verify_identity(client, record["metadata"], tokens["id_token"], config, None)
                if identity["subject"] != record["identity"]["subject"]:
                    raise HTTPException(401, "ChatGPT account changed. Connect again.")
            record.update(token_record(tokens, record))
            store.update(session_id, owner, record)
        except Exception:
            # A timed-out rotation may already have consumed the refresh token.
            # Never reuse it automatically on the next request.
            store.delete(session_id)
            raise
    if PLAN_SCOPE not in record["scopes"]:
        raise HTTPException(403, "ChatGPT plan permission was removed. Connect again to authorize usage.")
    return record["access_token"]
