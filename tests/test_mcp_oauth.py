"""The OAuth flow a connector UI performs, end to end, plus what must refuse.

Bearer-key clients (Claude Code) never touch any of this. Connector UIs cannot
set a header, so without these endpoints the server is not addable at all.

The security property worth testing is narrow and easy to lose: registration is
OPEN, so the authorization page is the only gate. Anyone may register a client;
nobody gets a token without a provisioned access key, and nobody can redirect a
minted code somewhere the registered client did not declare.
"""
import base64
import hashlib
import json
import secrets

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app.api.routers.mcp_oauth_routes import authorize_page, authorize_submit
from app.services import assistant_api_auth as auth
from app.services import mcp_oauth

KEY = "sda_" + "b" * 43
DIGEST = hashlib.sha256(KEY.encode()).hexdigest()


@pytest.fixture
def config(monkeypatch, tmp_path):
    value = auth.APISettings(
        _env_file=None, enabled=True, require_user_auth=True,
        public_origin="https://dashboard.example", mcp_url="https://api.example/mcp",
        signing_key="fixture-" * 8, access_key_hashes=json.dumps({"Team member": DIGEST}),
        oauth_store_path=str(tmp_path / "oauth.sqlite3"),
    )
    monkeypatch.setattr(auth, "settings", lambda: value)
    mcp_oauth._db.cache_clear()
    yield value
    mcp_oauth._db.cache_clear()


@pytest.fixture
def client(config):
    app = Starlette(routes=[
        Route("/mcp/authorize", authorize_page, methods=["GET"]),
        Route("/mcp/authorize", authorize_submit, methods=["POST"]),
    ])
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://api.example")


async def register(redirect="https://claude.ai/api/mcp/auth_callback", name="Claude"):
    from mcp.shared.auth import OAuthClientInformationFull

    info = OAuthClientInformationFull(
        client_id="client-" + secrets.token_hex(4), client_name=name,
        redirect_uris=[redirect], grant_types=["authorization_code"],
        response_types=["code"], token_endpoint_auth_method="none",
    )
    await mcp_oauth.SaadaaOAuthProvider().register_client(info)
    return info


def pending(info, redirect=None, state="xyz"):
    return json.dumps({
        "client_id": info.client_id,
        "redirect_uri": redirect or str(info.redirect_uris[0]),
        "redirect_uri_provided_explicitly": True,
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(b"verifier").digest()).decode().rstrip("="),
        "state": state, "resource": "", "scopes": [mcp_oauth.SCOPE],
    }, separators=(",", ":"))


# ── the happy path ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_page_names_the_app_and_says_it_is_read_only(client):
    info = await register(name="Claude")
    page = (await client.get("/mcp/authorize", params={"request": pending(info)})).text
    assert "Claude" in page and "Read-only" in page
    # The key field must never be a plain text input.
    assert 'type="password"' in page


@pytest.mark.asyncio
async def test_valid_key_redirects_with_a_code_and_preserves_state(client):
    info = await register()
    res = await client.post("/mcp/authorize",
                            data={"request": pending(info), "access_key": KEY})
    assert res.status_code == 302
    location = res.headers["location"]
    assert location.startswith("https://claude.ai/api/mcp/auth_callback")
    assert "state=xyz" in location and "code=sdc_" in location


@pytest.mark.asyncio
async def test_code_exchanges_for_a_token_the_mcp_already_accepts(client, config):
    """The whole point of reusing `issue`: no second token system."""
    info = await register()
    res = await client.post("/mcp/authorize", data={"request": pending(info), "access_key": KEY})
    code = httpx.URL(res.headers["location"]).params["code"]

    provider = mcp_oauth.SaadaaOAuthProvider()
    loaded = await provider.load_authorization_code(info, code)
    assert loaded is not None and loaded.subject == DIGEST

    token = await provider.exchange_authorization_code(info, loaded)
    principal = auth.signed_identity(token.access_token, "mcp")
    assert principal["key_id"] == DIGEST and principal["name"] == "Team member"


@pytest.mark.asyncio
async def test_a_code_cannot_be_replayed(client):
    info = await register()
    res = await client.post("/mcp/authorize", data={"request": pending(info), "access_key": KEY})
    code = httpx.URL(res.headers["location"]).params["code"]
    provider = mcp_oauth.SaadaaOAuthProvider()
    loaded = await provider.load_authorization_code(info, code)
    await provider.exchange_authorization_code(info, loaded)
    assert await provider.load_authorization_code(info, code) is None


# ── the refusals ──────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_key", ["", "sda_short", "not-a-key", "sda_" + "z" * 43])
@pytest.mark.asyncio
async def test_a_bad_key_mints_nothing(client, bad_key):
    """Unknown, revoked and malformed all return ONE message: no key oracle."""
    info = await register()
    res = await client.post("/mcp/authorize",
                            data={"request": pending(info), "access_key": bad_key})
    assert res.status_code == 400
    assert "not accepted" in res.text
    assert "code=" not in res.headers.get("location", "")


@pytest.mark.asyncio
async def test_a_redirect_the_client_never_registered_is_refused(client):
    """Registration is open, so this is the check that makes that safe.

    Without it: register a client pointing at yourself, send someone the
    authorization URL, and collect a code minted from their key.
    """
    info = await register(redirect="https://claude.ai/api/mcp/auth_callback")
    res = await client.post("/mcp/authorize", data={
        "request": pending(info, redirect="https://attacker.example/collect"),
        "access_key": KEY,
    })
    assert res.status_code == 400
    assert "not registered" in res.text


@pytest.mark.asyncio
async def test_an_unregistered_client_is_refused(client):
    from mcp.shared.auth import OAuthClientInformationFull

    ghost = OAuthClientInformationFull(
        client_id="never-registered", redirect_uris=["https://claude.ai/cb"],
        grant_types=["authorization_code"], response_types=["code"],
        token_endpoint_auth_method="none",
    )
    res = await client.post("/mcp/authorize",
                            data={"request": pending(ghost), "access_key": KEY})
    assert res.status_code == 400 and "Unknown application" in res.text


@pytest.mark.asyncio
async def test_revoking_the_key_hash_kills_the_issued_token(client, config):
    """Revocation stays where it already was: remove the hash, access stops."""
    from pydantic import SecretStr

    info = await register()
    res = await client.post("/mcp/authorize", data={"request": pending(info), "access_key": KEY})
    code = httpx.URL(res.headers["location"]).params["code"]
    provider = mcp_oauth.SaadaaOAuthProvider()
    loaded = await provider.load_authorization_code(info, code)
    token = await provider.exchange_authorization_code(info, loaded)

    config.access_key_hashes = SecretStr(json.dumps({"Someone else": "c" * 64}))
    assert await provider.load_access_token(token.access_token) is None


@pytest.mark.asyncio
async def test_no_refresh_token_is_issued(client):
    info = await register()
    provider = mcp_oauth.SaadaaOAuthProvider()
    assert await provider.load_refresh_token(info, "anything") is None


@pytest.mark.asyncio
async def test_malformed_request_blob_is_rejected(client):
    res = await client.post("/mcp/authorize", data={"request": "{not json", "access_key": KEY})
    assert res.status_code == 400
