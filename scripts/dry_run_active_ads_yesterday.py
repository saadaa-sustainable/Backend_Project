"""Dry-run: fetch **active** ads that had delivery **yesterday**, per
account, across every configured Meta ad account — in parallel. No
database writes.

"Active" here means Meta's `effective_status = ACTIVE` on the ad itself
(applied as a `filtering` param on the Insights request, server-side —
cheaper than fetching everything and filtering client-side). "Ran
yesterday" means the Insights endpoint returned a row for that ad for
`date_preset=yesterday` at all — Meta only returns ad-level insight rows
for ads that actually had impressions/spend that day, so no separate
"did it deliver" check is needed.

Every account's request runs concurrently via `asyncio.gather` over one
shared `httpx.AsyncClient` — mirrors the real service's per-account
parallelism (see `MultiAccountSyncCoordinator` in
`app/services/meta/orchestrator.py`), without needing Python 3.12+ or a
database. Results are printed grouped by account (not merged-then-
truncated), so a high-volume account never crowds smaller accounts out of
the output — the whole point of this script is comparing accounts.

Usage:
    python3 scripts/dry_run_active_ads_yesterday.py                      # 10 rows shown per account
    python3 scripts/dry_run_active_ads_yesterday.py --per-account 5      # fewer rows shown per account
    python3 scripts/dry_run_active_ads_yesterday.py --fetch-limit 100    # fetch deeper per account

Requires in `.env`:
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
    load_dotenv = None

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
]

_ACCOUNT_ID_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_ID$")
_ACCOUNT_NAME_PATTERN = re.compile(r"^META_ACCOUNT_(\d+)_NAME$")
REQUEST_TIMEOUT_SECONDS = 30.0


@dataclass
class AccountConfig:
    key: str
    name: str
    account_id: str


@dataclass
class AccountFetch:
    account_key: str
    account_name: str
    duration_seconds: float = 0.0
    status_code: int | None = None
    error: str | None = None
    ads: list[dict[str, Any]] = field(default_factory=list)


def _discover_accounts() -> dict[str, AccountConfig]:
    raw: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if m := _ACCOUNT_ID_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["id"] = value.removeprefix("act_")
        elif m := _ACCOUNT_NAME_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["name"] = value
    return {
        k: AccountConfig(key=k, name=f.get("name", f"account_{k}"), account_id=f["id"])
        for k, f in raw.items()
        if "id" in f
    }


async def _fetch_active_ads_yesterday(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    access_token: str,
    account: AccountConfig,
    per_account_limit: int,
) -> AccountFetch:
    started = time.monotonic()
    try:
        response = await client.get(
            f"{base_url}/act_{account.account_id}/insights",
            params={
                "level": "ad",
                "date_preset": "yesterday",
                "fields": ",".join(INSIGHTS_FIELDS),
                "filtering": json.dumps(
                    [{"field": "ad.effective_status", "operator": "IN", "value": ["ACTIVE"]}]
                ),
                "limit": per_account_limit,
                "access_token": access_token,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return AccountFetch(
            account_key=account.key,
            account_name=account.name,
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=time.monotonic() - started,
        )

    duration = time.monotonic() - started
    try:
        body = response.json()
    except ValueError:
        return AccountFetch(
            account_key=account.key,
            account_name=account.name,
            status_code=response.status_code,
            error=f"Non-JSON response: {response.text[:300]!r}",
            duration_seconds=duration,
        )

    if response.status_code >= 400:
        return AccountFetch(
            account_key=account.key,
            account_name=account.name,
            status_code=response.status_code,
            error=json.dumps(body.get("error", {})),
            duration_seconds=duration,
        )

    return AccountFetch(
        account_key=account.key,
        account_name=account.name,
        status_code=response.status_code,
        ads=body.get("data", []),
        duration_seconds=duration,
    )


async def _run(
    accounts: list[AccountConfig], *, base_url: str, access_token: str, per_account_limit: int
) -> list[AccountFetch]:
    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_active_ads_yesterday(
                client,
                base_url=base_url,
                access_token=access_token,
                account=account,
                per_account_limit=per_account_limit,
            )
            for account in accounts
        ]
        return await asyncio.gather(*tasks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--per-account", type=int, default=10, help="Active ads to show per account (not a global total)."
    )
    parser.add_argument(
        "--fetch-limit",
        type=int,
        default=50,
        help="Page size requested from Meta per account — kept above --per-account so a "
        "small display cap doesn't misrepresent how many an account actually has.",
    )
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv()

    access_token = os.environ.get("META_ACCESS_TOKEN")
    api_version = os.environ.get("META_API_VERSION", "v21.0")

    if not access_token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 1

    accounts_by_key = _discover_accounts()
    if not accounts_by_key:
        print("No Meta ad accounts configured — set META_ACCOUNT_1_ID in .env.", file=sys.stderr)
        return 1

    accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]
    base_url = f"https://graph.facebook.com/{api_version}"

    print(f"Accounts: {', '.join(f'{a.key} ({a.name})' for a in accounts)}")
    print(f"Fetching yesterday's ACTIVE-ad insights from all {len(accounts)} accounts in parallel...")
    print("Token: [redacted, not printed] — loaded, present, not shown.\n")

    wall_start = time.monotonic()
    results = asyncio.run(
        _run(accounts, base_url=base_url, access_token=access_token, per_account_limit=args.fetch_limit)
    )
    wall_total = time.monotonic() - wall_start

    failed = [r for r in results if r.error]
    for r in failed:
        print(f"[{r.account_key}] {r.account_name}: ERROR ({r.duration_seconds:.2f}s) — {r.error}", file=sys.stderr)

    # Grouped per account (not flattened-then-truncated) — otherwise a
    # high-volume account fills the whole display before smaller accounts
    # ever show up.
    print(f"{'#':<3} {'Ad Name':<45} {'Spend':>8} {'Impr.':>8} {'Reach':>8} {'CTR%':>6}")
    for r in results:
        header = f"\n[{r.account_key}] {r.account_name} — {len(r.ads)} active ad(s) with delivery yesterday"
        print(header)
        print("-" * 108)
        if not r.ads:
            print("  (none)")
            continue
        for i, ad in enumerate(r.ads[: args.per_account], start=1):
            name = (ad.get("ad_name") or "")[:43]
            print(
                f"{i:<3} {name:<45} "
                f"{float(ad.get('spend', 0)):>8.2f} {int(ad.get('impressions', 0)):>8} "
                f"{int(ad.get('reach', 0)):>8} {float(ad.get('ctr', 0)):>6.2f}"
            )
        remaining = len(r.ads) - args.per_account
        if remaining > 0:
            print(f"  ... and {remaining} more (raise --per-account to see them)")
        if len(r.ads) == args.fetch_limit:
            print(f"  (hit the {args.fetch_limit}-row page limit — this account may have even more; raise --fetch-limit)")

    print(f"\n{'=' * 60}")
    print("Per-account fetch times (ETA for a real sync of yesterday's data, all 3 accounts):")
    for r in results:
        status = "OK" if not r.error else "FAILED"
        print(f"  [{r.account_key}] {r.account_name}: {r.duration_seconds:.3f}s ({status}, {len(r.ads)} active ads)")
    slowest = max((r.duration_seconds for r in results), default=0.0)
    total_sequential_estimate = sum(r.duration_seconds for r in results)
    print(f"\nWall-clock time — all 3 accounts, in parallel (this is the real ETA): {wall_total:.3f}s")
    print(f"Slowest single account (the parallel run's floor):                     {slowest:.3f}s")
    print(f"Sum of all 3 calls if run one-by-one (sequential, old behavior):       {total_sequential_estimate:.3f}s")
    if wall_total > 0:
        print(f"Speedup from parallelism: ~{total_sequential_estimate / wall_total:.2f}x")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
