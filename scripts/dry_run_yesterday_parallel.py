"""Dry-run smoke test: fetch **yesterday's** data across **every configured
Meta ad account, in parallel** — no database writes, no dependency on the
rest of this codebase (the main app targets Python 3.12+; this script is
deliberately stdlib+httpx only so it runs on whatever Python is on hand).

For each configured account, two calls run concurrently:
  1. "ads data"  — yesterday's ad-level Insights (spend, impressions,
     clicks, purchases, CTR, CPM, ...) via `date_preset=yesterday`.
  2. "id data"   — the account's ad roster (id, name, status) — a handful
     of rows, just enough to confirm identity data resolves correctly.

Every account's two calls, and every account against every other account,
all run concurrently via `asyncio.gather` over one shared `httpx.AsyncClient`
— this exercises the same "fan out across accounts" shape the real
`MultiAccountSyncCoordinator` uses, without touching Postgres or importing
the (Python 3.12+-only) app package.

Reads credentials from `.env` itself at runtime — never pass a token on the
command line or hardcode one here, and this script never prints the token
or any URL containing it (Meta's Graph API takes the token as a query
param, so printing a request URL would leak it into your terminal/logs).

Usage:
    python3 scripts/dry_run_yesterday_parallel.py
    python3 scripts/dry_run_yesterday_parallel.py --account 2   # just one account
    python3 scripts/dry_run_yesterday_parallel.py --limit 10    # more ad-roster rows

Requires in `.env` (same names as the main app's config, see .env.example):
    META_ACCESS_TOKEN
    META_ACCOUNT_1_ID   (and META_ACCOUNT_2_ID, _3_ID, ... for more accounts)
    META_API_VERSION    (optional, defaults to v21.0)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # fall back to already-exported shell env vars


# A representative subset of app/core/meta_registry.py's fields — kept
# small on purpose for a quick smoke test, not a full sync.
INSIGHTS_FIELDS = [
    "ad_id",
    "ad_name",
    "campaign_name",
    "adset_name",
    "spend",
    "impressions",
    "reach",
    "clicks",
    "ctr",
    "cpm",
    "actions",
]
AD_FIELDS = ["id", "name", "status", "effective_status", "created_time", "updated_time"]

_ACCOUNT_ID_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_ID$")
_ACCOUNT_NAME_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_NAME$")

REQUEST_TIMEOUT_SECONDS = 30.0
ROSTER_LIMIT_DEFAULT = 5
INSIGHTS_LIMIT_DEFAULT = 25


@dataclass
class AccountConfig:
    key: str
    name: str
    account_id: str


@dataclass
class CallResult:
    account_key: str
    account_name: str
    call: str  # "insights" | "ads_roster"
    status_code: int | None = None
    duration_seconds: float = 0.0
    error: str | None = None
    data: list[dict[str, Any]] = field(default_factory=list)


def _discover_accounts() -> dict[str, AccountConfig]:
    """Same discovery logic as app/config.py, reimplemented standalone
    (this script deliberately doesn't import the main app package, which
    requires Python 3.12+)."""
    raw: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if m := _ACCOUNT_ID_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["id"] = value.removeprefix("act_")
        elif m := _ACCOUNT_NAME_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["name"] = value

    accounts: dict[str, AccountConfig] = {}
    for k, fields in raw.items():
        if "id" not in fields:
            continue
        accounts[k] = AccountConfig(key=k, name=fields.get("name", f"account_{k}"), account_id=fields["id"])
    return accounts


async def _fetch_insights(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    access_token: str,
    account: AccountConfig,
    limit: int,
) -> CallResult:
    started = time.monotonic()
    try:
        response = await client.get(
            f"{base_url}/act_{account.account_id}/insights",
            params={
                "level": "ad",
                "date_preset": "yesterday",
                "fields": ",".join(INSIGHTS_FIELDS),
                "limit": limit,
                "access_token": access_token,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return CallResult(
            account_key=account.key,
            account_name=account.name,
            call="insights",
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=time.monotonic() - started,
        )

    duration = time.monotonic() - started
    try:
        body = response.json()
    except ValueError:
        return CallResult(
            account_key=account.key,
            account_name=account.name,
            call="insights",
            status_code=response.status_code,
            error=f"Non-JSON response: {response.text[:300]!r}",
            duration_seconds=duration,
        )

    if response.status_code >= 400:
        error = body.get("error", {})
        return CallResult(
            account_key=account.key,
            account_name=account.name,
            call="insights",
            status_code=response.status_code,
            error=json.dumps(error),
            duration_seconds=duration,
        )

    return CallResult(
        account_key=account.key,
        account_name=account.name,
        call="insights",
        status_code=response.status_code,
        data=body.get("data", []),
        duration_seconds=duration,
    )


async def _fetch_ad_roster(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    access_token: str,
    account: AccountConfig,
    limit: int,
) -> CallResult:
    started = time.monotonic()
    try:
        response = await client.get(
            f"{base_url}/act_{account.account_id}/ads",
            params={
                "fields": ",".join(AD_FIELDS),
                "limit": limit,
                "access_token": access_token,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return CallResult(
            account_key=account.key,
            account_name=account.name,
            call="ads_roster",
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=time.monotonic() - started,
        )

    duration = time.monotonic() - started
    try:
        body = response.json()
    except ValueError:
        return CallResult(
            account_key=account.key,
            account_name=account.name,
            call="ads_roster",
            status_code=response.status_code,
            error=f"Non-JSON response: {response.text[:300]!r}",
            duration_seconds=duration,
        )

    if response.status_code >= 400:
        error = body.get("error", {})
        return CallResult(
            account_key=account.key,
            account_name=account.name,
            call="ads_roster",
            status_code=response.status_code,
            error=json.dumps(error),
            duration_seconds=duration,
        )

    return CallResult(
        account_key=account.key,
        account_name=account.name,
        call="ads_roster",
        status_code=response.status_code,
        data=body.get("data", []),
        duration_seconds=duration,
    )


async def _run(accounts: list[AccountConfig], *, base_url: str, access_token: str, roster_limit: int, insights_limit: int) -> list[CallResult]:
    async with httpx.AsyncClient() as client:
        tasks = []
        for account in accounts:
            tasks.append(
                _fetch_insights(
                    client, base_url=base_url, access_token=access_token, account=account, limit=insights_limit
                )
            )
            tasks.append(
                _fetch_ad_roster(
                    client, base_url=base_url, access_token=access_token, account=account, limit=roster_limit
                )
            )
        return await asyncio.gather(*tasks)


def _print_result(result: CallResult) -> None:
    label = "Insights (yesterday)" if result.call == "insights" else "Ad roster (id data)"
    header = f"[{result.account_key}] {result.account_name} — {label}"
    print(f"\n{header}\n{'-' * len(header)}")
    print(f"  duration: {result.duration_seconds:.2f}s")
    if result.error:
        print(f"  ERROR: {result.error}", file=sys.stderr)
        return
    print(f"  status: {result.status_code}")
    print(f"  rows returned: {len(result.data)}")
    if not result.data:
        print("  (empty — no delivery yesterday, or account has zero ads)")
        return
    print(f"  first row:\n{json.dumps(result.data[0], indent=4)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--account",
        default=None,
        help="Restrict to one account key (the numeric suffix from META_ACCOUNT_<N>_ID). "
        "Default: every configured account, in parallel.",
    )
    parser.add_argument(
        "--roster-limit", type=int, default=ROSTER_LIMIT_DEFAULT, help="Ad-roster rows per account."
    )
    parser.add_argument(
        "--insights-limit", type=int, default=INSIGHTS_LIMIT_DEFAULT, help="Insights rows per account."
    )
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv()

    access_token = os.environ.get("META_ACCESS_TOKEN")
    api_version = os.environ.get("META_API_VERSION", "v21.0")

    if not access_token:
        print("META_ACCESS_TOKEN is not set (checked .env and the environment).", file=sys.stderr)
        return 1

    accounts_by_key = _discover_accounts()
    if not accounts_by_key:
        print(
            "No Meta ad accounts configured — set META_ACCOUNT_1_ID (and optionally "
            "META_ACCOUNT_1_NAME) in .env.",
            file=sys.stderr,
        )
        return 1

    if args.account:
        if args.account not in accounts_by_key:
            print(
                f"No account with key '{args.account}'. Configured keys: "
                f"{', '.join(sorted(accounts_by_key, key=int))}",
                file=sys.stderr,
            )
            return 1
        accounts = [accounts_by_key[args.account]]
    else:
        accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]

    base_url = f"https://graph.facebook.com/{api_version}"

    print(f"Accounts: {', '.join(f'{a.key} ({a.name})' for a in accounts)}")
    print(f"Firing {len(accounts) * 2} requests in parallel (insights + ad roster x {len(accounts)} accounts)...")
    print("Token: [redacted, not printed] — loaded, present, not shown.")

    started = time.monotonic()
    results = asyncio.run(
        _run(
            accounts,
            base_url=base_url,
            access_token=access_token,
            roster_limit=args.roster_limit,
            insights_limit=args.insights_limit,
        )
    )
    total_duration = time.monotonic() - started

    for result in results:
        _print_result(result)

    ok = sum(1 for r in results if r.error is None)
    failed = len(results) - ok
    print(f"\n{'=' * 60}")
    print(f"Total wall time: {total_duration:.2f}s for {len(results)} concurrent requests")
    print(f"OK: {ok}   Failed: {failed}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
