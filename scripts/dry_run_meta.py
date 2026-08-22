"""Dry-run smoke test: fetch exactly one ad from the Meta Marketing API and
print it. No database writes, no dependency on the rest of this codebase
(the main app targets Python 3.12+; this script is deliberately
stdlib+requests only so it runs on whatever Python is on hand for a quick
connectivity/auth check before running a real sync).

Reads credentials from `.env` itself at runtime — never pass a token on the
command line or hardcode one here, and this script never prints the token
or any URL containing it (Meta's Graph API takes the token as a query
param, so printing a request URL would leak it into your terminal/logs).

Usage:
    python3 scripts/dry_run_meta.py            # first configured account
    python3 scripts/dry_run_meta.py --account 2 # a specific account

Requires in `.env` (same names as the main app's config, see .env.example):
    META_ACCESS_TOKEN
    META_ACCOUNT_1_ID   (and META_ACCOUNT_2_ID, _3_ID, ... for more accounts)
    META_API_VERSION    (optional, defaults to v21.0)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # fall back to already-exported shell env vars


# A representative subset of app/core/meta_registry.py's AD_FIELDS — kept
# small on purpose for a quick smoke test, not a full sync.
AD_FIELDS = [
    "id",
    "account_id",
    "campaign_id",
    "adset_id",
    "name",
    "status",
    "effective_status",
    "creative",
    "created_time",
    "updated_time",
]

_ACCOUNT_ID_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_ID$")
_ACCOUNT_NAME_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_NAME$")


def _discover_accounts() -> dict[str, dict[str, str]]:
    """Same discovery logic as app/config.py, reimplemented standalone
    (this script deliberately doesn't import the main app package, which
    requires Python 3.12+)."""
    accounts: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if m := _ACCOUNT_ID_PATTERN.match(key):
            accounts.setdefault(m.group(1), {})["id"] = value.removeprefix("act_")
        elif m := _ACCOUNT_NAME_PATTERN.match(key):
            accounts.setdefault(m.group(1), {})["name"] = value
    return {k: v for k, v in accounts.items() if "id" in v}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--account",
        default=None,
        help="Account key to query (the numeric suffix from META_ACCOUNT_<N>_ID, "
        "e.g. '2'). Defaults to the first configured account.",
    )
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv()

    access_token = os.environ.get("META_ACCESS_TOKEN")
    api_version = os.environ.get("META_API_VERSION", "v21.0")

    if not access_token:
        print("META_ACCESS_TOKEN is not set (checked .env and the environment).", file=sys.stderr)
        return 1

    accounts = _discover_accounts()
    if not accounts:
        print(
            "No Meta ad accounts configured — set META_ACCOUNT_1_ID (and optionally "
            "META_ACCOUNT_1_NAME) in .env.",
            file=sys.stderr,
        )
        return 1

    account_key = args.account or sorted(accounts, key=int)[0]
    if account_key not in accounts:
        print(
            f"No account with key '{account_key}'. Configured keys: "
            f"{', '.join(sorted(accounts, key=int))}",
            file=sys.stderr,
        )
        return 1

    account = accounts[account_key]
    account_id = account["id"]
    account_name = account.get("name", f"account_{account_key}")

    base_url = f"https://graph.facebook.com/{api_version}"
    path = f"act_{account_id}/ads"

    print(f"Account: {account_key} ({account_name}, act_{account_id})")
    print(f"GET {base_url}/{path}  (limit=1, fields={len(AD_FIELDS)} fields)")
    print("Token: [redacted, not printed] — loaded, present, not shown.")

    response = requests.get(
        f"{base_url}/{path}",
        params={
            "fields": ",".join(AD_FIELDS),
            "limit": 1,
            "access_token": access_token,
        },
        timeout=30,
    )

    # Deliberately do NOT print response.url or response.request.url here —
    # both embed the access_token in cleartext as a query param.
    print(f"Status: {response.status_code}")

    try:
        body = response.json()
    except ValueError:
        print("Response was not valid JSON:", response.text[:500], file=sys.stderr)
        return 1

    if response.status_code >= 400:
        error = body.get("error", {})
        print("Meta returned an error:", file=sys.stderr)
        print(json.dumps(error, indent=2), file=sys.stderr)
        return 1

    data = body.get("data", [])
    if not data:
        print("Request succeeded but the account returned zero ads (empty account, or "
              "every ad excluded by Meta's default effective_status filter).")
        return 0

    print("\nOne ad, raw as returned by Meta:\n")
    print(json.dumps(data[0], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
