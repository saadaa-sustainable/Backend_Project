"""Dry run: confirm the Instagram Graph API works with the existing
META_ACCESS_TOKEN and show the shape of the data before building anything
bigger -- the Instagram counterpart to scripts/dry_run_meta.py /
scripts/dry_run_shopify.py. Fetches the IG user profile plus a small page
of media (default 5) for every configured IG account. No database writes.

Reads IG_USER_ID_<N> / IG_USERNAME_<N> and META_ACCESS_TOKEN /
META_API_VERSION from .env at runtime (see scripts/instagram_client.py's
docstring for the exact format). The access token is never printed, not
even partially.

Usage:
    python3 scripts/dry_run_instagram.py                 # every configured IG account
    python3 scripts/dry_run_instagram.py --account 1        # just one account
    python3 scripts/dry_run_instagram.py --limit 10          # more sample media items
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instagram_client import (  # noqa: E402
    DEFAULT_API_VERSION,
    IGAccount,
    describe_ig_account_safely,
    discover_ig_accounts,
    get_with_retry,
)

IG_USER_FIELDS = [
    "id", "username", "name", "biography", "followers_count", "follows_count",
    "media_count", "profile_picture_url", "website", "has_profile_pic", "is_published",
]
IG_MEDIA_SAMPLE_FIELDS = [
    "id", "caption", "media_type", "media_product_type", "media_url", "thumbnail_url",
    "permalink", "shortcode", "timestamp", "like_count", "comments_count",
]


async def _dry_run_one_account(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount, limit: int
) -> dict[str, Any]:
    try:
        user_params = {"access_token": access_token, "fields": ",".join(IG_USER_FIELDS)}
        user_data = await get_with_retry(client, f"{base_url}/{account.user_id}", user_params)

        media_params = {
            "access_token": access_token,
            "fields": ",".join(IG_MEDIA_SAMPLE_FIELDS),
            "limit": limit,
        }
        media_body = await get_with_retry(client, f"{base_url}/{account.user_id}/media", media_params)
        return {"account": account, "user": user_data, "media": media_body.get("data", []), "error": None}
    except RuntimeError as exc:
        return {"account": account, "user": None, "media": [], "error": str(exc)}


async def _run(accounts: list[IGAccount], base_url: str, access_token: str, limit: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        tasks = [_dry_run_one_account(client, base_url, access_token, account, limit) for account in accounts]
        return await asyncio.gather(*tasks)


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default=None, help="Restrict to one account key. Default: every configured account.")
    parser.add_argument("--limit", type=int, default=5, help="Number of sample media items to fetch (default 5).")
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv()

    access_token = os.environ.get("META_ACCESS_TOKEN")
    api_version = os.environ.get("META_API_VERSION", DEFAULT_API_VERSION)
    if not access_token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 1

    accounts_by_key = discover_ig_accounts()
    if not accounts_by_key:
        print(
            "No Instagram accounts configured -- set IG_USER_ID_1 and IG_USERNAME_1 in .env.",
            file=sys.stderr,
        )
        return 1
    if args.account:
        if args.account not in accounts_by_key:
            print(f"No account with key '{args.account}'. Configured: {', '.join(sorted(accounts_by_key, key=int))}", file=sys.stderr)
            return 1
        accounts = [accounts_by_key[args.account]]
    else:
        accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]

    print("IG accounts: " + ", ".join(describe_ig_account_safely(a) for a in accounts))
    print("Access token: [redacted, not printed] -- loaded, present, not shown (same META_ACCESS_TOKEN as Marketing API).\n")

    base_url = f"https://graph.facebook.com/{api_version}"
    results = asyncio.run(_run(accounts, base_url, access_token, args.limit))

    any_error = False
    for r in results:
        account = r["account"]
        if r["error"]:
            any_error = True
            print(f"[{account.key}] (.env label: @{account.username}): FAILED\n  {r['error']}\n")
            continue
        # Trust the API's own `username`, not the .env label -- confirmed
        # live that IG_USERNAME_1/_2 don't match what their IDs actually
        # resolve to (labels ignored per explicit instruction; API is the
        # source of truth for display everywhere in this script family).
        real_username = r["user"].get("username", "?")
        label_note = "" if real_username == account.username else f"  [.env label was '{account.username}' -- MISMATCH]"
        print(f"[{account.key}] @{real_username}: OK{label_note}")
        print(f"  user: {json.dumps(r['user'], indent=2)}")
        print(f"  sample media ({len(r['media'])}):")
        for m in r["media"]:
            print(f"    - {m.get('id')}  {m.get('media_type')}/{m.get('media_product_type')}  "
                  f"likes={m.get('like_count')} comments={m.get('comments_count')}")
        print()

    return 1 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
