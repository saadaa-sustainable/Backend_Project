"""Unit tests for multi-account discovery in app/config.py."""

from __future__ import annotations

import pytest

from app.config import MetaAPISettings, _discover_meta_accounts


@pytest.fixture(autouse=True)
def _isolate_from_real_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this module cares only about os.environ it sets
    itself — never a real `.env` file that happens to sit in the cwd."""
    monkeypatch.setattr("app.config.dotenv_values", lambda *args, **kwargs: {})


def _clear_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The autouse `meta_env` fixture in conftest.py already sets accounts
    1 and 2 — tests that need a genuinely clean slate (zero accounts, an
    orphaned _NAME with no _ID) must clear those first."""
    monkeypatch.delenv("META_ACCOUNT_1_ID", raising=False)
    monkeypatch.delenv("META_ACCOUNT_1_NAME", raising=False)
    monkeypatch.delenv("META_ACCOUNT_2_ID", raising=False)
    monkeypatch.delenv("META_ACCOUNT_2_NAME", raising=False)


def test_discover_meta_accounts_finds_numbered_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_ACCOUNT_1_ID", "111")
    monkeypatch.setenv("META_ACCOUNT_1_NAME", "First")
    monkeypatch.setenv("META_ACCOUNT_2_ID", "222")
    monkeypatch.setenv("META_ACCOUNT_2_NAME", "Second")

    accounts = _discover_meta_accounts()

    assert [a.key for a in accounts] == ["1", "2"]
    assert accounts[0].account_id == "111"
    assert accounts[0].name == "First"
    assert accounts[1].account_id == "222"
    assert accounts[1].name == "Second"


def test_discover_meta_accounts_sorts_numerically_not_lexically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_accounts(monkeypatch)
    monkeypatch.setenv("META_ACCOUNT_10_ID", "1010")
    monkeypatch.setenv("META_ACCOUNT_2_ID", "22")

    accounts = _discover_meta_accounts()

    assert [a.key for a in accounts] == ["2", "10"]


def test_discover_meta_accounts_strips_act_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_ACCOUNT_1_ID", "act_555")

    accounts = _discover_meta_accounts()

    assert accounts[0].account_id == "555"
    assert accounts[0].account_id_prefixed == "act_555"


def test_discover_meta_accounts_defaults_name_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_accounts(monkeypatch)
    monkeypatch.setenv("META_ACCOUNT_1_ID", "111")

    accounts = _discover_meta_accounts()

    assert accounts[0].name == "account_1"


def test_discover_meta_accounts_ignores_orphan_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_accounts(monkeypatch)
    monkeypatch.setenv("META_ACCOUNT_1_NAME", "Orphan")

    accounts = _discover_meta_accounts()

    assert accounts == []


def test_meta_api_settings_requires_at_least_one_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_accounts(monkeypatch)
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-token")
    with pytest.raises(Exception, match="No Meta ad accounts configured"):
        MetaAPISettings()


def test_account_by_key_raises_for_unknown_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_accounts(monkeypatch)
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_ACCOUNT_1_ID", "111")
    settings = MetaAPISettings()

    with pytest.raises(KeyError, match="No Meta ad account with key '9'"):
        settings.account_by_key("9")


def test_account_by_key_returns_matching_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_accounts(monkeypatch)
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_ACCOUNT_1_ID", "111")
    monkeypatch.setenv("META_ACCOUNT_2_ID", "222")
    settings = MetaAPISettings()

    assert settings.account_by_key("2").account_id == "222"
