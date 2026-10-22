"""OAuth 2.1 authorization server for the MCP endpoint, so connector UIs can attach.

WHY THIS EXISTS BESIDE THE BEARER KEYS
--------------------------------------
`assistant_api_auth` already provisions `sda_` access keys, and any MCP client
that can set a header uses them directly -- Claude Code does. Connector UIs do
not offer that field: they perform OAuth discovery, register themselves, and
send the user through an authorization page. Without the endpoints below the
server is simply not addable as a connector.

So this is a second door onto the SAME principal, not a second permission
system. The flow ends by minting the signed token `assistant_api_auth.issue()`
already produces, which `mcp_identity()` already validates. Rate limits, the
read-only transaction guard and the key allowlist are untouched -- revoking a
key hash still revokes every OAuth session built on it.

WHAT GATES THE AUTHORIZATION PAGE, AND WHY IT HAD TO BE SOMETHING
-----------------------------------------------------------------
This dashboard has no user accounts, so there is no login to delegate to. An
authorization page that simply says "Allow" would hand every reader of the URL
a read-only key to the whole business -- open registration makes the URL easy
to find, which is the point of a connector.

The page therefore asks for an existing `sda_` access key. That keeps the
properties the key system already has: one key per person, issued offline by
`scripts/create_assistant_access_key.py`, revoked by removing its hash, and
rate-limited per key id. Someone without a key cannot complete the flow.

WHAT IS DELIBERATELY NOT STORED
-------------------------------
No access key, and no token, is ever written to disk. The authorization code
holds the principal's `key_id` -- already a hash -- and codes are single-use
and short-lived. Access tokens are stateless JWTs verified by signature, so
there is nothing to leak from the store and nothing to keep in sync.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from app.services import assistant_api_auth as auth

#: Short, because the connector can refresh silently and a leaked token should
#: age out well inside an incident response.
ACCESS_TOKEN_SECONDS = 3600
#: An authorization code lives only as long as a redirect round trip needs.
CODE_SECONDS = 300
SCOPE = "analytics:read"


@lru_cache(maxsize=1)
def _db() -> sqlite3.Connection:
    """Clients and pending codes only. See the docstring on what is absent.

    Same single-host assumption as chatgpt_auth: a private persistent disk,
    several workers on that host. A client registration lost to a redeploy
    costs one re-add of the connector, not a data incident.
    """
    path = Path(auth.settings().oauth_store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, info TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL)")
    conn.commit()
    return conn


@contextmanager
def _tx():
    conn = _db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class SaadaaOAuthProvider:
    """Implements mcp.server.auth's provider protocol over the existing keys."""

    # ---- clients ----------------------------------------------------
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = _db().execute("SELECT info FROM clients WHERE client_id=?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row[0]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with _tx() as conn:
            conn.execute("INSERT OR REPLACE INTO clients VALUES (?,?)",
                         (client_info.client_id, client_info.model_dump_json()))

    # ---- authorization ----------------------------------------------
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Hand the user to the consent page; it is what actually authenticates.

        The pending request is passed in the URL rather than stored, so a page
        that is never completed leaves nothing behind to expire.
        """
        pending = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "state": params.state or "",
            "resource": params.resource or "",
            "scopes": params.scopes or [SCOPE],
        }
        return "/mcp/authorize?" + urlencode({"request": json.dumps(pending, separators=(",", ":"))})

    def mint_code(self, pending: dict[str, Any], access_key: str) -> str:
        """Called by the consent page once the access key checks out.

        `auth.access_key` raises 401 on an unknown or malformed key, so an
        invalid key never reaches a stored code.
        """
        principal = auth.access_key(access_key)
        code = "sdc_" + secrets.token_urlsafe(32)
        payload = {**pending, "subject": principal["key_id"], "code": code}
        with _tx() as conn:
            conn.execute("DELETE FROM codes WHERE expires_at < ?", (time.time(),))
            conn.execute("INSERT INTO codes VALUES (?,?,?)",
                         (code, json.dumps(payload), time.time() + CODE_SECONDS))
        return code

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str,
    ) -> AuthorizationCode | None:
        row = _db().execute("SELECT payload, expires_at FROM codes WHERE code=?",
                            (authorization_code,)).fetchone()
        if row is None or row[1] < time.time():
            return None
        data = json.loads(row[0])
        if data["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code, scopes=data["scopes"], expires_at=row[1],
            client_id=data["client_id"], code_challenge=data["code_challenge"],
            redirect_uri=AnyUrl(data["redirect_uri"]),
            redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
            resource=data["resource"] or None, subject=data["subject"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode,
    ) -> Any:
        from mcp.shared.auth import OAuthToken

        # Single use: a replayed code must not mint a second token.
        with _tx() as conn:
            conn.execute("DELETE FROM codes WHERE code=?", (authorization_code.code,))
        principal = auth.identity(authorization_code.subject or "")
        return OAuthToken(
            access_token=auth.issue(principal, "mcp", ACCESS_TOKEN_SECONDS),
            token_type="Bearer", expires_in=ACCESS_TOKEN_SECONDS,
            scope=" ".join(authorization_code.scopes),
        )

    # ---- tokens ------------------------------------------------------
    async def load_access_token(self, token: str) -> AccessToken | None:
        """Stateless: the signature and the key allowlist are the whole check."""
        try:
            principal = auth.signed_identity(token, "mcp")
        except Exception:
            return None
        return AccessToken(token=token, client_id=principal.get("key_id", ""),
                           scopes=[SCOPE], subject=principal.get("key_id"))

    # Refresh tokens are not issued: the connector re-runs the flow, and a
    # stored long-lived credential is the thing this design avoids.
    async def load_refresh_token(self, client, refresh_token: str) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(self, client, refresh_token, scopes) -> Any:
        raise NotImplementedError("Refresh tokens are not issued by this server.")

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Tokens are stateless and short-lived; revocation is by key hash.

        Accepting the call keeps the endpoint RFC-compliant rather than
        returning an error a client would surface as a failure.
        """
        return None
