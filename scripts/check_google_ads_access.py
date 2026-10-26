"""Does the Google Ads developer token actually work? Read-only probe.

WHY A PROBE AND NOT A FETCHER
-----------------------------
Google Ads API access has four independent parts, and three of them
fail with errors that do not name the real cause:

  1. a DEVELOPER TOKEN            -> env GOOGLE_ADS_API
  2. an OAuth token with the      -> secrets/google_oauth_token_*ads*.json
     `adwords` scope                 (sheets/drive scopes are NOT enough)
  3. a CUSTOMER ID                -> 6770669478 (SAADAA), from MapleMonk
  4. a LOGIN CUSTOMER ID          -> only if the account sits under a
                                     manager (MCC) account

The trap worth knowing about: a developer token at **Test Access**
authenticates perfectly and then returns nothing for a real account.
That is not an error, it is an empty result, so it reads as "no data"
rather than "wrong token tier". This probe calls
`listAccessibleCustomers` first, which tells you what the token can
actually see, and only then tries a one-row query.

WHY REST AND NOT THE google-ads LIBRARY
---------------------------------------
The official client is a large protobuf package pinned to one API
version, and it would be a new dependency for what is two HTTP calls.
`httpx` is already here. The API version is probed rather than hardcoded
so a yearly deprecation does not silently 404.

Nothing secret is printed. The repo is PUBLIC.

Usage:
    ./.venv/bin/python scripts/check_google_ads_access.py
    ./.venv/bin/python scripts/check_google_ads_access.py --customer-id 6770669478
    ./.venv/bin/python scripts/check_google_ads_access.py --login-customer-id <MCC id>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

SECRETS = ROOT / "secrets"
ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"
DEFAULT_CUSTOMER = "6770669478"          # SAADAA, per MapleMonk

#: Newest first. Google retires roughly one version a year and a retired
#: one answers 404 on every path, which looks like a broken URL rather
#: than an expired version.
API_VERSIONS = [f"v{n}" for n in range(24, 15, -1)]

#: The token may be named for any scope combination it was minted with,
#: so match on content rather than filename.
def _ads_token_file() -> Path | None:
    for p in sorted(glob.glob(str(SECRETS / "google_oauth_token_*.json")),
                    key=os.path.getmtime, reverse=True):
        try:
            if ADWORDS_SCOPE in (json.load(open(p)).get("scopes") or []):
                return Path(p)
        except (OSError, ValueError):
            continue
    return None


def _access_token(path: Path) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(path))
    if not creds.valid:
        creds.refresh(Request())
        path.write_text(creds.to_json())      # keep the refreshed access token
    return creds.token


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--customer-id", default=DEFAULT_CUSTOMER)
    ap.add_argument("--login-customer-id",
                    help="The MCC id, if the account is under a manager.")
    ap.add_argument("--api-version", help="Skip probing and use this one.")
    args = ap.parse_args()

    dev_token = os.getenv("GOOGLE_ADS_API") or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not dev_token:
        print("GOOGLE_ADS_API is not set in .env", file=sys.stderr)
        return 2
    print(f"developer token   present, {len(dev_token)} chars (value not shown)")

    token_file = _ads_token_file()
    if token_file is None:
        have = [Path(p).name for p in glob.glob(str(SECRETS / "google_oauth_token_*.json"))]
        print("\nNo OAuth token carries the `adwords` scope.", file=sys.stderr)
        print(f"   present: {have or '(none)'}", file=sys.stderr)
        print("\nMint one (the browser step is yours):", file=sys.stderr)
        print("   ./.venv/bin/python scripts/google_oauth_login.py --scopes ads",
              file=sys.stderr)
        return 2
    print(f"oauth token       {token_file.name}")

    try:
        bearer = _access_token(token_file)
    except Exception as exc:  # noqa: BLE001
        print(f"\nCould not refresh the OAuth token: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bearer {bearer}", "developer-token": dev_token}
    if args.login_customer_id:
        headers["login-customer-id"] = args.login_customer_id.replace("-", "")

    versions = [args.api_version] if args.api_version else API_VERSIONS
    with httpx.Client(timeout=60.0) as client:
        version, listing = None, None
        for v in versions:
            r = client.get(
                f"https://googleads.googleapis.com/{v}/customers:listAccessibleCustomers",
                headers=headers)
            if r.status_code == 404:
                continue
            version, listing = v, r
            break

        if listing is None:
            print(f"\nEvery API version 404'd ({versions[0]}..{versions[-1]}). "
                  f"The endpoint or project may be wrong.", file=sys.stderr)
            return 1
        print(f"api version       {version}")

        if listing.status_code != 200:
            _explain(listing)
            return 1

        names = listing.json().get("resourceNames", [])
        print(f"\naccessible accounts ({len(names)}):")
        for n in names:
            print(f"   {n.split('/')[-1]}")
        if not names:
            print("   NONE -- this is the signature of a TEST-ACCESS developer "
                  "token, or a login the account has not been shared with.")
            return 1

        # One row, newest day. Proves data access rather than mere auth.
        cid = args.customer_id.replace("-", "")
        q = ("SELECT campaign.id, campaign.name, metrics.cost_micros, "
             "metrics.clicks, segments.date FROM campaign "
             "WHERE segments.date DURING LAST_7_DAYS "
             "ORDER BY metrics.cost_micros DESC LIMIT 3")
        r = client.post(
            f"https://googleads.googleapis.com/{version}/customers/{cid}/googleAds:search",
            headers=headers, json={"query": q})
        if r.status_code != 200:
            print(f"\nquery against {cid} failed:")
            _explain(r)
            return 1

        rows = r.json().get("results", [])
        print(f"\nquery OK -- top {len(rows)} campaigns by spend, last 7 days:")
        for row in rows:
            c = row.get("campaign", {})
            m = row.get("metrics", {})
            spend = int(m.get("costMicros", 0)) / 1e6
            print(f"   {c.get('name','?')[:44]:<44} Rs {spend:>10,.0f}  "
                  f"{m.get('clicks','?')} clicks")
        if not rows:
            print("   (no rows -- account had no delivery in the window, or "
                  "the token is Test Access)")
    print("\n[OK] read access confirmed.")
    return 0


def _explain(r: httpx.Response) -> None:
    """Say what the status actually means -- Google's own message buries it."""
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:400]}
    err = body.get("error", {}) if isinstance(body, dict) else {}
    msg = err.get("message", "")
    print(f"   HTTP {r.status_code}: {msg or json.dumps(body)[:400]}", file=sys.stderr)
    hints = {
        401: "the OAuth token is invalid or lacks the `adwords` scope.",
        403: "usually the developer token: not approved, wrong tier, or not "
             "permitted for this customer. PERMISSION_DENIED here can also "
             "mean login-customer-id is required because the account sits "
             "under a manager.",
        400: "often a malformed customer id, or login-customer-id set to an "
             "account that does not manage this one.",
    }
    if r.status_code in hints:
        print(f"   -> {hints[r.status_code]}", file=sys.stderr)
    if "DEVELOPER_TOKEN_NOT_APPROVED" in json.dumps(body):
        print("   -> TEST ACCESS token. It authenticates but returns nothing "
              "for a production account; Basic Access is a separate "
              "application and review.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
