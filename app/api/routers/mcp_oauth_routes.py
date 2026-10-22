"""The authorization page the connector sends people to, and its POST.

The SDK supplies every other OAuth endpoint. This is the one piece it cannot:
what actually authenticates the person. See app/services/mcp_oauth.py for why
that is an access key rather than a login.
"""
from __future__ import annotations

import html
import json
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from app.services.mcp_oauth import SaadaaOAuthProvider

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect SAADAA Analytics</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font: 15px/1.5 system-ui, sans-serif; max-width: 30rem; margin: 4rem auto; padding: 0 1.25rem; }}
 h1 {{ font-size: 1.25rem; margin-bottom: .25rem; }}
 p  {{ color: #666; }}
 ul {{ color: #666; padding-left: 1.1rem; }}
 label {{ display: block; font-weight: 600; margin: 1.5rem 0 .4rem; }}
 input {{ width: 100%; padding: .6rem .7rem; font: inherit; font-family: ui-monospace, monospace;
          border: 1px solid #bbb; border-radius: .4rem; box-sizing: border-box; }}
 button {{ margin-top: 1rem; padding: .6rem 1.1rem; font: inherit; font-weight: 600;
           border: 0; border-radius: .4rem; background: #111; color: #fff; cursor: pointer; }}
 .err {{ color: #b00020; font-weight: 600; }}
</style></head><body>
<h1>Connect SAADAA Analytics</h1>
<p><strong>{client}</strong> is asking to read your dashboard analytics.</p>
<ul>
  <li>Read-only. It cannot change campaigns, budgets, data or schedules.</li>
  <li>Dashboard sections only &mdash; no raw SQL and no customer records.</li>
  <li>Access lasts one hour, then the connector asks again.</li>
</ul>
{error}
<form method="post">
  <input type="hidden" name="request" value="{request}">
  <label for="key">Your assistant access key</label>
  <input id="key" name="access_key" type="password" autocomplete="off" spellcheck="false"
         placeholder="sda_&hellip;" required autofocus>
  <button type="submit">Allow access</button>
</form>
<p style="margin-top:2rem;font-size:13px">
  No key? Ask your administrator to issue one. Removing its hash revokes this
  connection and every other use of that key.</p>
</body></html>"""


def _render(pending_raw: str, client_label: str, error: str = "") -> HTMLResponse:
    return HTMLResponse(_PAGE.format(
        client=html.escape(client_label or "An application"),
        request=html.escape(pending_raw, quote=True),
        error=f'<p class="err">{html.escape(error)}</p>' if error else "",
    ), status_code=400 if error else 200)


async def authorize_page(request: Request) -> HTMLResponse:
    raw = request.query_params.get("request", "")
    try:
        pending = json.loads(raw)
    except ValueError:
        return HTMLResponse("Malformed authorization request.", status_code=400)
    client = await SaadaaOAuthProvider().get_client(pending.get("client_id", ""))
    return _render(raw, client.client_name if client else "An application")


async def authorize_submit(request: Request):
    form = await request.form()
    raw = str(form.get("request", ""))
    try:
        pending = json.loads(raw)
    except ValueError:
        return HTMLResponse("Malformed authorization request.", status_code=400)

    provider = SaadaaOAuthProvider()
    client = await provider.get_client(pending.get("client_id", ""))
    label = client.client_name if client else "An application"

    # Re-check the redirect against the REGISTERED client, not the posted form.
    # Registration is open, so without this anyone could register a client,
    # craft an authorization URL pointing at themselves and collect a code
    # minted from somebody else's key.
    if client is None:
        return _render(raw, label, "Unknown application. Re-add the connector and try again.")
    allowed = {str(u) for u in (client.redirect_uris or [])}
    if pending.get("redirect_uri") not in allowed:
        return _render(raw, label, "This application's redirect address is not registered.")

    try:
        code = provider.mint_code(pending, str(form.get("access_key", "")))
    except Exception:
        # Deliberately one message for malformed, unknown and revoked keys:
        # the page must not say which, or it becomes a key oracle.
        return _render(raw, label, "That access key was not accepted.")

    query = {"code": code}
    if pending.get("state"):
        query["state"] = pending["state"]
    joiner = "&" if "?" in pending["redirect_uri"] else "?"
    return RedirectResponse(pending["redirect_uri"] + joiner + urlencode(query), status_code=302)
