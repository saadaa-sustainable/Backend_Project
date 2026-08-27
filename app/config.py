"""Centralized application configuration.

All runtime configuration is sourced from environment variables (optionally
loaded from a local ``.env`` file). Every other module reads configuration
through the :func:`get_settings` accessor so there is a single, cached
source of truth and configuration is trivially mockable in tests.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ACCOUNT_ID_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_ID$")
_ACCOUNT_NAME_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_NAME$")


class MetaAdAccount(BaseModel):
    """One configured Meta ad account.

    ``key`` is the numeric suffix from its env vars (``"1"``, ``"2"``, ...)
    — a stable identifier usable in API requests/scheduler jobs to scope a
    run to a single account. ``name`` is a purely local, human-assigned
    label (Meta's API has no concept of it) carried through to every Bronze
    row's ``parent_ids`` so Silver never needs a lookup table just to know
    which account a row belongs to.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    account_id: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def account_id_prefixed(self) -> str:
        return f"act_{self.account_id}"


def _discover_meta_accounts(env_file: str = ".env") -> list[MetaAdAccount]:
    """Scan the environment and ``.env`` for ``META_ACCOUNT_<N>_ID`` /
    ``META_ACCOUNT_<N>_NAME`` pairs and build one :class:`MetaAdAccount`
    per ``N`` found. ``N`` is not hardcoded to any particular count — add a
    4th account by adding ``META_ACCOUNT_4_ID``/``META_ACCOUNT_4_NAME``,
    no code change required. Returned sorted numerically by ``N``. Real
    environment variables (``os.environ``) take precedence over ``.env``
    file values for the same key, matching pydantic-settings' own
    precedence rules elsewhere in this module.
    """
    merged: dict[str, str] = {**dotenv_values(env_file), **os.environ}
    numbered: dict[str, dict[str, str]] = {}
    for key, value in merged.items():
        if not value:
            continue
        if m := _ACCOUNT_ID_PATTERN.match(key):
            numbered.setdefault(m.group(1), {})["account_id"] = value.removeprefix("act_")
        elif m := _ACCOUNT_NAME_PATTERN.match(key):
            numbered.setdefault(m.group(1), {})["name"] = value

    accounts: list[MetaAdAccount] = []
    for n in sorted(numbered, key=int):
        fields = numbered[n]
        if "account_id" not in fields:
            continue  # a stray _NAME with no matching _ID is not an account
        accounts.append(
            MetaAdAccount(
                key=n, name=fields.get("name", f"account_{n}"), account_id=fields["account_id"]
            )
        )
    return accounts


class MetaAPISettings(BaseSettings):
    """Credentials and tuning parameters for the Meta Marketing API client.

    Credentials that differ per ad account (``META_ACCOUNT_<N>_ID`` /
    ``META_ACCOUNT_<N>_NAME``) live in :attr:`accounts`; everything else
    here (token, API version, business id, HTTP tuning) is shared across
    every configured account, matching how a single System User token
    typically has access to all of an organization's ad accounts.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    access_token: str = Field(..., alias="META_ACCESS_TOKEN")
    accounts: list[MetaAdAccount] = Field(default_factory=_discover_meta_accounts)
    business_id: str | None = Field(default=None, alias="META_BUSINESS_ID")
    api_version: str = Field(default="v21.0", alias="META_API_VERSION")
    app_id: str | None = Field(default=None, alias="META_APP_ID")
    app_secret: str | None = Field(default=None, alias="META_APP_SECRET")
    graph_api_base_url: str = Field(
        default="https://graph.facebook.com", alias="META_GRAPH_API_BASE_URL"
    )

    http_timeout_seconds: float = Field(default=60.0, alias="META_HTTP_TIMEOUT_SECONDS")
    http_connect_timeout_seconds: float = Field(
        default=10.0, alias="META_HTTP_CONNECT_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(default=5, alias="META_MAX_RETRIES")
    retry_backoff_base_seconds: float = Field(
        default=1.0, alias="META_RETRY_BACKOFF_BASE_SECONDS"
    )
    retry_backoff_max_seconds: float = Field(
        default=120.0, alias="META_RETRY_BACKOFF_MAX_SECONDS"
    )
    page_size: int = Field(default=250, alias="META_PAGE_SIZE")
    #: Concurrent HTTP requests to ONE account's Meta API client. Lowered from
    #: 8 to 2 (2026-08-25) after live testing showed repeated "Application
    #: request limit reached" / "reduce the amount of data" failures compound
    #: under heavy same-session concurrent usage -- this, combined with
    #: MAX_CONCURRENT_ENDPOINT_SYNCS below, previously allowed up to 32
    #: simultaneous requests against a single account's own rate-limit
    #: budget. Cross-account concurrency (MAX_CONCURRENT_ACCOUNT_SYNCS in
    #: orchestrator.py) is lower-risk by comparison -- confirmed live that
    #: each account_id has its own independent ads_insights BUC usage
    #: bucket, not a shared one.
    max_concurrent_requests: int = Field(default=2, alias="META_MAX_CONCURRENT_REQUESTS")
    rate_limit_sleep_buffer_seconds: float = Field(
        default=5.0, alias="META_RATE_LIMIT_SLEEP_BUFFER_SECONDS"
    )

    @model_validator(mode="after")
    def _require_at_least_one_account(self) -> "MetaAPISettings":
        if not self.accounts:
            raise ValueError(
                "No Meta ad accounts configured. Set at least "
                "META_ACCOUNT_1_ID (and optionally META_ACCOUNT_1_NAME) in .env."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_url(self) -> str:
        return f"{self.graph_api_base_url.rstrip('/')}/{self.api_version}"

    def account_by_key(self, key: str) -> MetaAdAccount:
        """Look up a configured account by its numeric key (e.g. ``"1"``).
        Raises :class:`KeyError` with a helpful message if unknown."""
        for account in self.accounts:
            if account.key == key:
                return account
        known = ", ".join(a.key for a in self.accounts) or "none configured"
        raise KeyError(f"No Meta ad account with key '{key}'. Known keys: {known}.")


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection and pooling configuration."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = Field(
        default="postgresql+asyncpg://meta_ingest:meta_ingest@localhost:5432/meta_ingest",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://meta_ingest:meta_ingest@localhost:5432/meta_ingest",
        alias="DATABASE_URL_SYNC",
    )
    pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE")
    max_overflow: int = Field(default=20, alias="DATABASE_MAX_OVERFLOW")
    pool_timeout_seconds: int = Field(default=30, alias="DATABASE_POOL_TIMEOUT_SECONDS")
    echo: bool = Field(default=False, alias="DATABASE_ECHO")


class SchedulerSettings(BaseSettings):
    """APScheduler job configuration."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    daily_sync_hour: int = Field(default=3, alias="SCHEDULER_DAILY_SYNC_HOUR")
    daily_sync_minute: int = Field(default=0, alias="SCHEDULER_DAILY_SYNC_MINUTE")
    hourly_sync_enabled: bool = Field(default=False, alias="SCHEDULER_HOURLY_SYNC_ENABLED")
    retry_interval_minutes: int = Field(default=30, alias="SCHEDULER_RETRY_INTERVAL_MINUTES")
    flatten_poll_interval_minutes: int = Field(default=15, alias="SCHEDULER_FLATTEN_POLL_INTERVAL_MINUTES")
    timezone: str = Field(default="UTC", alias="SCHEDULER_TIMEZONE")


class AssistantSettings(BaseSettings):
    """Credentials/model choice for the admin-panel chat assistant
    (``app/api/routers/assistant.py``). Swapped from Claude Haiku to
    Cloudflare Workers AI 2026-08-18, per explicit user request, and
    made READ-ONLY at the same time -- no tool in this assistant may
    create/alter/delete anything; that capability was deliberately
    removed, not just left unconfirmed. Claude was added back 2026-08-20
    as an OPTIONAL second provider (not a replacement) -- selectable per
    request from the model dropdown, for when a Workers AI model gets
    something wrong or imprecise, at real per-token Anthropic API cost.
    Every credential here is intentionally optional -- the assistant
    endpoint reports 503 with a clear message when the credential for the
    REQUESTED model's provider is unset, rather than failing app startup,
    since the rest of the admin panel doesn't depend on any of this."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    cloudflare_api_token: str | None = Field(default=None, alias="CLOUDFLARE_API_TOKEN")
    cloudflare_account_id: str | None = Field(default=None, alias="CLOUDFLARE_ACCOUNT_ID")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    #: Llama 3.3 70B (fp8, fast variant) -- chosen for reliable OpenAI-style
    #: tool-calling on Workers AI; smaller/cheaper models are noticeably
    #: less reliable at strict JSON tool-call formatting for a DB-querying
    #: agent. Override via env if cost matters more than reliability here.
    #: This is only the DEFAULT when a chat request omits `model` --
    #: ASSISTANT_MODELS in assistant.py is the full selectable list.
    model: str = Field(default="@cf/meta/llama-3.3-70b-instruct-fp8-fast", alias="ASSISTANT_MODEL")


class Settings(BaseSettings):
    """Top-level application settings, composed of the settings above."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["development", "staging", "production", "test"] = Field(
        default="development", alias="APP_ENV"
    )
    app_name: str = Field(default="meta-marketing-ingestion", alias="APP_NAME")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    #: Origin of the Next.js admin app (admin/) -- CORS is restricted to
    #: this one origin, not a wildcard, since /admin/* can trigger
    #: ingestion. Override in .env if the admin app runs anywhere other
    #: than the default `next dev` port.
    admin_app_origin: str = Field(default="http://localhost:3000", alias="ADMIN_APP_ORIGIN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=False, alias="LOG_JSON")

    meta: MetaAPISettings = Field(default_factory=lambda: MetaAPISettings())  # type: ignore[call-arg]
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    assistant: AssistantSettings = Field(default_factory=AssistantSettings)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    ``lru_cache`` guarantees environment variables are parsed once; tests can
    call ``get_settings.cache_clear()`` to force a re-read after mutating
    ``os.environ``.
    """
    return Settings()
