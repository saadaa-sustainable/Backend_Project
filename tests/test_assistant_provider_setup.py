"""Provider setup works independently of user auth and never prints secrets."""
import os
import httpx
import pytest

from app.services.assistant_api_auth import APISettings
from app.services import assistant_api_auth as auth
from app.services.anthropic_provider import error_message
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


@pytest.mark.parametrize("workspace_id", ["", "  wrkspc_fixture  "])
def test_claude_key_check_uses_anthropic_only_without_inference(workspace_id):
    settings = config(anthropic_key="CLAUDE_PRIVATE_KEY", anthropic_workspace_id=workspace_id)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url == "https://api.anthropic.com/v1/models/claude-sonnet-5-5"
        assert request.headers["x-api-key"] == "CLAUDE_PRIVATE_KEY"
        assert request.headers.get("anthropic-workspace-id") == (workspace_id.strip() or None)
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"id": "claude-sonnet-5-5"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check(settings, client, provider="anthropic") == ["claude-sonnet-5-5"]
    assert len(requests) == 1


def test_openai_check_never_sends_anthropic_workspace():
    def handler(request):
        assert "anthropic-workspace-id" not in request.headers
        return httpx.Response(200, json={"id": "fixture-model"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check(config(anthropic_workspace_id="wrkspc_fixture"), client) == ["fixture-model"]


def test_missing_workspace_is_actionable_in_setup_and_never_echoes_secrets():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message":
            "API key PRIVATE_PROVIDER_KEY is not scoped to a workspace; include anthropic-workspace-id."}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="ASSISTANT_API_ANTHROPIC_WORKSPACE_ID") as failure:
            check(config(anthropic_key="fixture"), client, provider="anthropic")
    assert "PRIVATE_PROVIDER_KEY" not in str(failure.value)
    assert len(requests) == 1


@pytest.mark.parametrize("body", [None, [], {"error": "PRIVATE"},
    {"error": {"message": "Unknown request failure PRIVATE", "type": "invalid_request_error"}}])
def test_unrecognized_claude_errors_are_safe(body):
    message = error_message(400, body)
    assert "HTTP 400" in message and "request configuration" in message
    assert "PRIVATE" not in message and "without retrying" in message


def test_claude_verification_stops_on_first_error_without_secret_output():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(401, text="CLAUDE_PRIVATE_KEY")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Anthropic rejected") as error:
            check(config(anthropic_key="CLAUDE_PRIVATE_KEY"), client, provider="anthropic")
    assert "CLAUDE_PRIVATE_KEY" not in str(error.value)
    assert len(requests) == 1


def test_settings_pick_up_added_rotated_and_removed_keys_without_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("ASSISTANT_API_ENABLED=true\n")
    auth._cached_settings.cache_clear()
    try:
        initial = auth.settings()
        assert not any(m["available"] for m in initial.models())
        assert auth.settings() is initial
        env_file.write_text("ASSISTANT_API_ENABLED=true\nASSISTANT_API_ANTHROPIC_KEY=test-first\n")
        connected = auth.settings()
        assert connected is not initial
        assert connected.require_model("claude-haiku-5-5")["available"]
        # Same-length rotation must also invalidate the cached settings.
        env_file.write_text("ASSISTANT_API_ENABLED=true\nASSISTANT_API_ANTHROPIC_KEY=test-other\n")
        assert auth.settings().anthropic_key.get_secret_value() == "test-other"
        env_file.unlink()
        assert not auth.settings().anthropic_key.get_secret_value()
    finally:
        auth._cached_settings.cache_clear()


def test_default_model_choices_and_explicit_administrator_override():
    settings = config(anthropic_key="fixture-anthropic")
    models = settings.models()
    assert models[0]["id"] == "fixture-model"
    for model_id in ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"):
        assert settings.require_model(model_id)["provider"] == "openai"
    for model_id in settings.anthropic_models:
        assert settings.require_model(model_id)["provider"] == "anthropic"
    assert len(models) == len({m["id"] for m in models})
    assert [m["id"] for m in config(openai_models=()).models() if m["provider"] == "openai"] == ["fixture-model"]
