"""Shared, standalone (Python-3.9-compatible) Instagram Graph API client
helpers -- the Instagram counterpart to shopify_client.py.

Unlike Shopify (a separate GraphQL API), the Instagram Graph API is the
SAME underlying Graph API as the Meta Marketing API already used
throughout this project: same `graph.facebook.com` host, same
`META_ACCESS_TOKEN`, same REST field-list + cursor-pagination shape, same
rate-limit error codes. It's a different set of nodes (ig-user, ig-media)
under one API, not a different API -- so this client mirrors
ingest_last_15_days.py's retry/pagination logic rather than
shopify_client.py's GraphQL-specific one.

Multi-account credential discovery: IG_USER_ID_<N> / IG_USERNAME_<N>
pairs (mirrors META_ACCOUNT_<N>_ID/_NAME and
SHOPIFY_STORE_<N>_DOMAIN/_NAME exactly) -- there is no per-account token;
every configured Instagram professional account is expected to be
reachable through the same META_ACCESS_TOKEN (it must have
instagram_basic / instagram_business_basic and pages_read_engagement
granted, in addition to whatever Marketing API scopes it already has).

Reference: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_API_VERSION = "v21.0"
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
#: Mirrors app/services/meta/client.py's RATE_LIMIT_ERROR_CODES exactly
#: -- same API, same throttling behavior.
RATE_LIMIT_ERROR_CODES = {
    4, 17, 32, 613,
    80000, 80001, 80002, 80003, 80004, 80005, 80006, 80008, 80009, 80014,
}
PAGE_SIZE = 50

_IG_USER_ID_PATTERN = re.compile(r"^IG_USER_ID_(\d+)$")
_IG_USERNAME_PATTERN = re.compile(r"^IG_USERNAME_(\d+)$")


@dataclass
class IGAccount:
    key: str
    username: str
    user_id: str


def discover_ig_accounts() -> dict[str, IGAccount]:
    """Scan os.environ for IG_USER_ID_<N> / IG_USERNAME_<N> pairs.

    NOTE: this project's .env also has a bare IG_USERNAME (no numeric
    suffix, "saadaadesigns") and an empty IG_USER_ID_3 -- neither pairs
    with anything (IG_USERNAME has no matching ID; IG_USER_ID_3 is blank)
    so both are deliberately ignored here rather than guessed at. If
    "saadaadesigns" is meant to be a real third account, add its numeric
    IG_USER_ID_3 value in .env and it'll be picked up automatically.
    """
    raw: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if m := _IG_USER_ID_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["user_id"] = value
        elif m := _IG_USERNAME_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["username"] = value
    return {
        k: IGAccount(key=k, username=f.get("username", f"account_{k}"), user_id=f["user_id"])
        for k, f in raw.items()
        if "user_id" in f
    }


def describe_ig_account_safely(account: IGAccount) -> str:
    return f"{account.key} (@{account.username}) -> user_id={account.user_id}"


def _usage_estimated_wait_seconds(headers: httpx.Headers) -> float | None:
    raw = headers.get("x-business-use-case-usage") or headers.get("x-app-usage")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    best: float | None = None
    values = parsed.values() if isinstance(parsed, dict) else []
    for value in values:
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            wait = entry.get("estimated_time_to_regain_access")
            if isinstance(wait, (int, float)):
                best = max(best or 0.0, float(wait) * 60)
    return best


async def get_with_retry(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None
) -> dict[str, Any]:
    """GET with retry on HTTP 429/5xx and Meta's in-body rate-limit error
    codes -- identical philosophy to ingest_last_15_days.py's
    _get_with_retry, since this is the same Graph API."""
    attempt = 0
    while True:
        attempt += 1
        try:
            response = await client.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            if attempt > MAX_RETRIES:
                raise RuntimeError(f"Network error after {MAX_RETRIES} retries: {exc}") from exc
            await asyncio.sleep(min(2**attempt, 30))
            continue

        try:
            body = response.json()
        except ValueError:
            body = None

        error_code = None
        if isinstance(body, dict):
            error_code = (body.get("error") or {}).get("code")

        is_rate_limited = response.status_code == 429 or error_code in RATE_LIMIT_ERROR_CODES
        is_retryable_status = response.status_code in RETRYABLE_STATUSES

        if (is_rate_limited or is_retryable_status) and attempt <= MAX_RETRIES:
            retry_after = response.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if retry_after
                else _usage_estimated_wait_seconds(response.headers) or min(2**attempt, 30)
            )
            safe_url = url.split("?")[0]
            print(
                f"    rate-limited/retryable (status={response.status_code}, "
                f"error_code={error_code}), attempt {attempt}/{MAX_RETRIES}, "
                f"sleeping {delay:.1f}s: {safe_url}"
            )
            await asyncio.sleep(delay)
            continue

        # Meta's own `paging.next` URLs embed access_token in their query
        # string -- always strip it before it reaches an error message.
        safe_url = url.split("?")[0]
        if body is None:
            raise RuntimeError(f"Non-JSON response ({response.status_code}) from {safe_url}: {response.text[:300]!r}")
        if response.status_code >= 400:
            raise RuntimeError(f"Instagram Graph API error {response.status_code} from {safe_url}: {body.get('error')}")
        return body


async def paginate(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    *,
    max_items: int | None = None,
    inter_page_delay_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    """Cursor pagination, identical shape to Meta's -- paging.cursors.after
    / paging.next, since it's the same Graph API.

    `max_items`, if given, stops fetching additional PAGES once enough
    items have been collected (truncating the final page's contribution
    to hit the cap exactly) -- this actually bounds the fetch itself.
    Confirmed live this matters: a caller that instead fetches everything
    and truncates client-side after the fact (the original bug here) can
    walk a 1000+ item list unnecessarily and hit Meta's own complexity
    throttle ("Please reduce the amount of data you're asking for",
    error code 1) long before the cap is even applied.

    `inter_page_delay_seconds`, if set, pauses between successful page
    fetches. Confirmed live: even with max_items unset, walking a large
    account's full media list (1391 items / ~28 pages) back-to-back with
    no gap still hits the same complexity throttle -- retrying within a
    page (exponential backoff) doesn't help because the problem is the
    *rate* of consecutive heavy requests, not any single one. A small
    fixed gap between pages avoided it in practice.
    """
    request_params = {**params, "limit": params.get("limit", PAGE_SIZE)}
    next_target: str | None = path
    next_params: dict[str, Any] | None = request_params
    items: list[dict[str, Any]] = []
    page_num = 0

    while next_target is not None:
        if page_num > 0 and inter_page_delay_seconds > 0:
            await asyncio.sleep(inter_page_delay_seconds)
        page_num += 1
        body = await get_with_retry(client, next_target, next_params)
        data = body.get("data", [])
        items.extend(data)

        if max_items is not None and len(items) >= max_items:
            items = items[:max_items]
            break

        paging = body.get("paging", {})
        next_url = paging.get("next")
        cursors_after = paging.get("cursors", {}).get("after")

        if next_url:
            next_target = next_url
            next_params = None
        elif cursors_after and len(data) == request_params["limit"]:
            next_params = {**request_params, "after": cursors_after}
            next_target = path
        else:
            next_target = None

    return items
