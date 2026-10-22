"""Provider setup works independently of user auth and never prints secrets."""
import os
import httpx
import pytest

from app.services.assistant_api_auth import APISettings
from scripts.check_assistant_provider import check


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    # Other application tests can load .env; provider fixtures must stay independent.
    for name in list(os.environ):
        if name.startswith("ASSISTANT_API_"):
            monkeypatch.delenv(name)


def config(**overrides):
    return APISettings(_env_file=None, openai_key="PRIVATE_PROVIDER_KEY", model="fixture-model", **overrides)


def test_key_and_model_check_does_not_require_auth_or_enable_access():
    settings = config()
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url == "https://api.openai.com/v1/models/fixture-model"
        assert request.headers["authorization"] == "Bearer PRIVATE_PROVIDER_KEY"
        return httpx.Response(200, json={"id": "fixture-model"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check(settings, client) == ["fixture-model"]
    assert len(requests) == 1 and settings.enabled is False
    assert settings.signing_key.get_secret_value() == ""


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
def test_provider_rejection_is_sanitized_and_not_retried(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="PRIVATE_PROVIDER_KEY echoed in upstream error")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError) as failure:
            check(config(), client)
    assert "PRIVATE_PROVIDER_KEY" not in str(failure.value)
    assert len(requests) == 1


def test_connection_failure_stops_and_sanitizes_exception():
    def handler(request):
        raise httpx.ConnectError("PRIVATE_PROVIDER_KEY")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Stopped without retrying") as failure:
            check(config(), client)
    assert "PRIVATE_PROVIDER_KEY" not in str(failure.value)


def test_missing_key_does_not_make_a_request():
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail("Must stay offline"))) as client:
        with pytest.raises(ValueError, match="ASSISTANT_API_OPENAI_KEY"):
            check(APISettings(_env_file=None), client)


def test_list_models_needs_no_model_and_returns_only_ids():
    settings = APISettings(_env_file=None, openai_key="fixture")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"data": [{"id": "b"}, {"id": "a"}], "secret": "PRIVATE"}))) as client:
        assert check(settings, client, list_models=True) == ["a", "b"]


def test_unexpected_model_reply_does_not_count_as_success():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "other"}))) as client:
        with pytest.raises(ValueError, match="unexpected"):
            check(config(), client)
