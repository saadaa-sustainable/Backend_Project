"""Mint a long-lived Google refresh token from a Desktop OAuth client.

WHY THIS EXISTS
---------------
`gcloud auth application-default login` cannot be granted the scopes
this project actually needs. Google blocks its own client from the
sensitive ones -- ask it for Sheets or Drive and it refuses outright,
which is why reading the media plan has meant exporting .xlsx by hand.
A Desktop OAuth client owned by this GCP project has no such
restriction: it can request `adwords`, `spreadsheets.readonly` and
`drive.readonly` like any other app.

It also fixes the nightly. Every Google-sourced fetcher
(`fetch_ga4_daily`, `fetch_ga4_arpu`, `fetch_ga4_order_attribution`,
`fetch_google_ads_spend`) fails in CI for want of credentials and has
to be run by hand on a laptop. A refresh token minted here is a
credential that CAN live in CI, because it does not expire with a
browser session.

WHAT IT DOES NOT DO
-------------------
A refresh token is only half of Google Ads API access. The other half
is a DEVELOPER TOKEN from the manager account's API Center, and no
OAuth flow can produce one. Worse, a token at *Test Access* returns
nothing at all for a real account -- Basic Access is a separate
application and review. So this script is useful immediately for
Sheets, Drive and GA4, and only becomes useful for Google Ads once that
token exists.

THE BROWSER STEP IS YOURS
-------------------------
`run_local_server` opens a consent screen and you sign in as yourself.
That is deliberate -- the token is scoped to YOUR access, and nobody
else should be typing your password. Run it from the terminal:

    ./.venv/bin/python scripts/google_oauth_login.py --scopes ads
    ./.venv/bin/python scripts/google_oauth_login.py --scopes sheets,drive
    ./.venv/bin/python scripts/google_oauth_login.py --scopes ga4,sheets --label analytics

Nothing secret is printed. The token is written to secrets/ (which is
gitignored, and this repo is PUBLIC) with 0600 permissions, and the
summary names only scopes, expiry and account.
"""
from __future__ import annotations

import argparse
import glob
import json
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SECRETS = ROOT / "secrets"

#: Short names so nobody has to retype a scope URL. `adwords` is the
#: Google Ads API's only scope -- it is all-or-nothing, there is no
#: read-only variant.
SCOPES = {
    "ads": "https://www.googleapis.com/auth/adwords",
    "sheets": "https://www.googleapis.com/auth/spreadsheets.readonly",
    "drive": "https://www.googleapis.com/auth/drive.readonly",
    "ga4": "https://www.googleapis.com/auth/analytics.readonly",
    "bq": "https://www.googleapis.com/auth/bigquery",
}


def _desktop_clients() -> list[Path]:
    """Client JSONs of type `installed`, newest first.

    A Web client is rejected rather than attempted: it only works
    against an exactly-registered redirect URI, so the loopback flow
    below fails with redirect_uri_mismatch and the error does not say
    why. Desktop clients download with an `installed` key.
    """
    out = []
    for p in glob.glob(str(SECRETS / "client_secret_*.json")):
        try:
            with open(p) as fh:
                if next(iter(json.load(fh))) == "installed":
                    out.append(Path(p))
        except (OSError, ValueError, StopIteration):
            continue
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scopes", default="ads",
                    help=f"Comma-separated, from: {', '.join(sorted(SCOPES))}")
    ap.add_argument("--client-file", help="Defaults to the newest Desktop client in secrets/.")
    ap.add_argument("--label", help="Token filename suffix (defaults to the scope list).")
    ap.add_argument("--port", type=int, default=0, help="0 lets the OS pick.")
    ap.add_argument("--list", action="store_true",
                    help="Show the usable clients and exit, opening no browser.")
    args = ap.parse_args()

    clients = _desktop_clients()
    if args.list:
        print("Desktop OAuth clients in secrets/ (newest first):")
        for p in clients:
            cid = json.load(open(p))["installed"].get("client_id", "")
            print(f"  {p.name}\n      client_id {cid.split('-')[0]}-...")
        if not clients:
            print("  (none -- download an OAuth client of type 'Desktop app')")
        print(f"\nScope names: {', '.join(sorted(SCOPES))}")
        return 0 if clients else 1

    wanted = [s.strip() for s in args.scopes.split(",") if s.strip()]
    unknown = [s for s in wanted if s not in SCOPES]
    if unknown:
        print(f"Unknown scope(s): {', '.join(unknown)}. "
              f"Known: {', '.join(sorted(SCOPES))}", file=sys.stderr)
        return 2
    scope_urls = [SCOPES[s] for s in wanted]

    client_file = Path(args.client_file) if args.client_file else (
        clients[0] if clients else None)
    if client_file is None:
        print("No Desktop OAuth client in secrets/. In Cloud Console: "
              "Credentials -> Create credentials -> OAuth client ID -> "
              "Application type: Desktop app, then save the JSON to secrets/.",
              file=sys.stderr)
        return 2
    if next(iter(json.load(open(client_file)))) != "installed":
        print(f"{client_file.name} is a WEB client, not a Desktop one. The "
              f"loopback flow needs type 'installed' -- re-download as "
              f"'Desktop app'.", file=sys.stderr)
        return 2

    label = args.label or "-".join(wanted)
    out = SECRETS / f"google_oauth_token_{label}.json"

    print(f"Client:  {client_file.name}")
    print(f"Scopes:  {', '.join(scope_urls)}")
    print(f"Token:   {out}")
    print("\nA browser window is about to open. Sign in as yourself and "
          "approve the scopes above.")
    if "ads" in wanted:
        print("NOTE: the `adwords` scope alone does NOT grant Google Ads API "
              "access -- a developer token from the manager account's API "
              "Center is still required, at Basic Access, not Test.")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scope_urls)
    try:
        creds = flow.run_local_server(port=args.port, open_browser=True,
                                      prompt="consent", access_type="offline")
    except Exception as exc:  # noqa: BLE001 -- the message is the useful part
        print(f"\nConsent failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("\nCommon causes:\n"
              "  * the consent screen is in Testing mode and your account is "
              "not on its test-user list\n"
              "  * the scope is not listed on the consent screen\n"
              "  * the API is not enabled for this GCP project",
              file=sys.stderr)
        return 1

    if not creds.refresh_token:
        # Without this the token dies in an hour and CI is no better off
        # than a browser session, which is the whole point of the script.
        print("\nNo refresh token was returned -- re-run after revoking the "
              "app's prior grant at myaccount.google.com/permissions, so "
              "Google issues a fresh offline grant.", file=sys.stderr)
        return 1

    SECRETS.mkdir(exist_ok=True)
    out.write_text(creds.to_json())
    out.chmod(stat.S_IRUSR | stat.S_IWUSR)        # 0600, same as ga4_token.json

    print("\n[OK] refresh token saved.")
    print(f"     file     {out}  (0600, gitignored)")
    print(f"     scopes   {', '.join(creds.scopes or scope_urls)}")
    print(f"     expiry   {creds.expiry} (access token; the refresh token persists)")
    print("     The value is NOT printed here on purpose -- this repo is public.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
