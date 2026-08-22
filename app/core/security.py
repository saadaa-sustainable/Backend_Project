"""Meta OAuth access-token credential handling.

The service authenticates to the Meta Marketing API using a long-lived
access token (System User token recommended) supplied via environment
variables — there is no interactive OAuth dance at runtime. A single token
is shared across every configured ad account (the normal case for a System
User token with access to a whole Business Manager). This module resolves
per-account credentials into immutable value objects used throughout the
``services.meta`` package, plus a helper to validate the token against
Meta's ``/debug_token`` endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import ConfigurationError, MetaAuthenticationError


@dataclass(frozen=True, slots=True)
class MetaCredentials:
    """Resolved Meta API credentials scoped to a single ad account."""

    access_token: str
    ad_account_id: str
    account_key: str
    account_name: str
    api_version: str
    base_url: str
    business_id: str | None = None
    app_id: str | None = None
    app_secret: str | None = None

    @property
    def ad_account_id_prefixed(self) -> str:
        return f"act_{self.ad_account_id}"

    def auth_params(self) -> dict[str, str]:
        """Query parameters that must accompany every authenticated request."""
        return {"access_token": self.access_token}


def _build_credentials(settings: Settings, account_key: str, account_id: str, account_name: str) -> MetaCredentials:
    return MetaCredentials(
        access_token=settings.meta.access_token,
        ad_account_id=account_id,
        account_key=account_key,
        account_name=account_name,
        api_version=settings.meta.api_version,
        base_url=settings.meta.base_url,
        business_id=settings.meta.business_id,
        app_id=settings.meta.app_id,
        app_secret=settings.meta.app_secret,
    )


def get_meta_credentials(
    account_key: str | None = None, *, settings: Settings | None = None
) -> MetaCredentials:
    """Resolve :class:`MetaCredentials` for one ad account.

    ``account_key`` selects which configured account (``"1"``, ``"2"``,
    ...) — omit it to get the first configured account, a convenience for
    single-account callers (health checks, ad-hoc scripts) that don't care
    which account they're touching. Raises :class:`ConfigurationError` if
    credentials/accounts are missing or the key is unknown, so
    misconfiguration fails fast rather than mid-ingestion.
    """
    settings = settings or get_settings()
    meta = settings.meta

    if not meta.access_token:
        raise ConfigurationError("META_ACCESS_TOKEN is required but not set.")
    if not meta.accounts:
        raise ConfigurationError(
            "No Meta ad accounts configured — set META_ACCOUNT_1_ID (and "
            "optionally META_ACCOUNT_1_NAME) in .env."
        )

    if account_key is None:
        account = meta.accounts[0]
    else:
        try:
            account = meta.account_by_key(account_key)
        except KeyError as exc:
            raise ConfigurationError(str(exc)) from exc

    return _build_credentials(settings, account.key, account.account_id, account.name)


def get_all_meta_credentials(settings: Settings | None = None) -> list[MetaCredentials]:
    """Resolve :class:`MetaCredentials` for every configured ad account —
    the default for any sync operation that doesn't explicitly scope itself
    to one account."""
    settings = settings or get_settings()
    meta = settings.meta

    if not meta.access_token:
        raise ConfigurationError("META_ACCESS_TOKEN is required but not set.")
    if not meta.accounts:
        raise ConfigurationError(
            "No Meta ad accounts configured — set META_ACCOUNT_1_ID (and "
            "optionally META_ACCOUNT_1_NAME) in .env."
        )

    return [
        _build_credentials(settings, account.key, account.account_id, account.name)
        for account in meta.accounts
    ]


async def debug_token(
    credentials: MetaCredentials, *, http_client: httpx.AsyncClient
) -> dict[str, Any]:
    """Call Meta's ``/debug_token`` endpoint to validate the configured token
    and surface its scopes, expiry, and associated app/user.

    Requires ``app_id``/``app_secret`` to build the inspecting app's own
    access token; falls back to inspecting with the token itself if unset.
    """
    inspecting_token = credentials.access_token
    if credentials.app_id and credentials.app_secret:
        inspecting_token = f"{credentials.app_id}|{credentials.app_secret}"

    response = await http_client.get(
        f"{credentials.base_url}/debug_token",
        params={
            "input_token": credentials.access_token,
            "access_token": inspecting_token,
        },
    )

    payload = response.json()
    if response.status_code >= 400:
        raise MetaAuthenticationError(
            f"Token validation failed: {payload}",
            status_code_from_meta=response.status_code,
        )

    data = payload.get("data", {})
    if not data.get("is_valid", False):
        raise MetaAuthenticationError(f"Meta access token is not valid: {data}")

    return data
