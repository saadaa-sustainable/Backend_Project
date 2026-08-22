"""Shared pytest fixtures.

Every test that touches :func:`app.config.get_settings` gets a clean,
fully-populated fake environment via the autouse ``meta_env`` fixture, so
individual tests never need to know which env vars ``Settings`` requires.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.core.security import MetaCredentials


@pytest.fixture(autouse=True)
def meta_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-token-123")
    monkeypatch.setenv("META_ACCOUNT_1_ID", "act_1234567890")
    monkeypatch.setenv("META_ACCOUNT_1_NAME", "Test Account One")
    monkeypatch.setenv("META_ACCOUNT_2_ID", "1234567891")
    monkeypatch.setenv("META_ACCOUNT_2_NAME", "Test Account Two")
    monkeypatch.setenv("META_API_VERSION", "v21.0")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql+psycopg2://test:test@localhost:5432/test")
    # Account discovery also reads a real `.env` file (so file-only values,
    # never exported to the shell, are still picked up in normal use) —
    # force it to see nothing but the monkeypatched os.environ above, so
    # tests never pick up whatever accounts happen to be in a real `.env`
    # sitting in the working directory they run from.
    monkeypatch.setattr("app.config.dotenv_values", lambda *args, **kwargs: {})
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def credentials() -> MetaCredentials:
    return MetaCredentials(
        access_token="test-token-123",
        ad_account_id="1234567890",
        account_key="1",
        account_name="Test Account One",
        api_version="v21.0",
        base_url="https://graph.facebook.com/v21.0",
        business_id=None,
    )
