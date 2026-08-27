"""Shared, standalone (Python-3.9-compatible) Shopify Admin GraphQL client
helpers -- the Shopify counterpart to the request/retry/pagination logic
duplicated across the scripts/dry_run_meta.py / ingest_last_15_days.py /
dump_test_table.py family, factored out here since Shopify's GraphQL
client is meaningfully more involved (cost-based throttling, cursor
connections, POST-only with errors possibly on HTTP 200) than Meta's REST
client and is worth sharing rather than re-copying per script.

Multi-store credential discovery mirrors app/config.py's
META_ACCOUNT_<N>_ID/_NAME pattern exactly, one env-var family per store
(each Shopify access token is store-specific, unlike Meta's one token
covering every ad account):

    SHOPIFY_STORE_1_DOMAIN=your-shop.myshopify.com
    SHOPIFY_STORE_1_NAME=Your Shop            # optional, human label
    SHOPIFY_STORE_1_ACCESS_TOKEN=shpat_...
    SHOPIFY_STORE_2_DOMAIN=second-shop.myshopify.com
    SHOPIFY_STORE_2_ACCESS_TOKEN=shpat_...
    ...

``SHOPIFY_API_VERSION`` (default: the version pinned in DEFAULT_API_VERSION
below) is shared across every store, mirroring META_API_VERSION.

Reference: https://shopify.dev/docs/api/admin-graphql/latest
* Auth: `X-Shopify-Access-Token` header, one token per store.
* Endpoint: https://{store_domain}/admin/api/{version}/graphql.json (POST only).
* Pagination: Relay-style cursor connections (edges/node/cursor, pageInfo
  with hasNextPage/endCursor).
* Rate limiting: leaky-bucket, cost-based -- every response carries
  extensions.cost.throttleStatus {maximumAvailable, currentlyAvailable,
  restoreRate}; a query that would exceed the bucket comes back as a
  THROTTLED error in the `errors` array, NOT a distinct HTTP status --
  GraphQL routinely returns HTTP 200 even for request-level failures, so
  every response's `errors` array must be checked regardless of status
  code.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_API_VERSION = "2026-07"
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 4
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
#: Shopify's own minimum recommended backoff after a THROTTLED error
#: (https://shopify.dev/docs/api/usage/rate-limits) -- used as a floor
#: even when a computed wait (from throttleStatus) comes out lower.
MIN_THROTTLE_BACKOFF_SECONDS = 1.0

_STORE_DOMAIN_PATTERN = re.compile(r"^SHOPIFY_STORE_(\d+)_DOMAIN$")
_STORE_NAME_PATTERN = re.compile(r"^SHOPIFY_STORE_(\d+)_NAME$")
_STORE_TOKEN_PATTERN = re.compile(r"^SHOPIFY_STORE_(\d+)_ACCESS_TOKEN$")


@dataclass
class ShopifyStore:
    key: str
    name: str
    domain: str
    access_token: str

    @property
    def graphql_url(self) -> str:
        api_version = os.environ.get("SHOPIFY_API_VERSION", DEFAULT_API_VERSION)
        domain = self.domain
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        return f"{domain.rstrip('/')}/admin/api/{api_version}/graphql.json"


def discover_stores() -> dict[str, ShopifyStore]:
    """Scan os.environ for SHOPIFY_STORE_<N>_DOMAIN / _NAME /
    _ACCESS_TOKEN triples and build one ShopifyStore per N found (mirrors
    dump_test_table.py's _discover_accounts() exactly), PLUS a single
    un-numbered store from SHOP_DOMAIN / ADMIN_ACCESS_TOKEN if present
    (given key "1" unless that key is already taken by the numbered
    pattern, in which case it's added as the next free numeric key) --
    the simpler single-store naming actually in use in this project's
    .env today."""
    raw: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if m := _STORE_DOMAIN_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["domain"] = value
        elif m := _STORE_NAME_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["name"] = value
        elif m := _STORE_TOKEN_PATTERN.match(key):
            raw.setdefault(m.group(1), {})["access_token"] = value

    domain = os.environ.get("SHOP_DOMAIN")
    access_token = os.environ.get("ADMIN_ACCESS_TOKEN")
    if domain and access_token:
        key = "1" if "1" not in raw else str(max((int(k) for k in raw), default=0) + 1)
        raw[key] = {"domain": domain, "access_token": access_token, "name": os.environ.get("SHOP_NAME", "default")}

    stores = {}
    for k, fields in raw.items():
        if "domain" not in fields or "access_token" not in fields:
            continue  # incomplete triple -- not enough to authenticate
        stores[k] = ShopifyStore(
            key=k, name=fields.get("name", f"store_{k}"),
            domain=fields["domain"], access_token=fields["access_token"],
        )
    return stores


def describe_store_safely(store: ShopifyStore) -> str:
    """Domain only -- never the access token -- for confirmation output."""
    return f"{store.key} ({store.name}) -> {store.domain}"


def _throttle_delay(errors: list[dict[str, Any]]) -> float:
    """Two DIFFERENT cost-extension shapes exist across Shopify's APIs, both
    confirmed live (2026-08-26) -- and the cost info lives on the
    individual ERROR's own `extensions.cost` (inside `errors[i]`), not
    `body["extensions"]`, which is absent/unrelated on a THROTTLED response:

    1. Regular Admin GraphQL: `extensions.cost.throttleStatus.
       {maximumAvailable, currentlyAvailable, restoreRate}` -- what this
       function originally (and wrongly) assumed was the only shape.
    2. ShopifyQL (`shopifyqlQuery`): `extensions.cost.{requestedQueryCost,
       maximumAvailable, currentlyAvailable, windowResetAt}` -- NO nested
       `throttleStatus`, no `restoreRate`, an absolute reset timestamp
       instead. A 90-field fulfillments query costs ~331 against a 1000
       budget -- confirmed live this shape's mismatch with the old code
       silently fell through to a useless flat 1.0s delay every time
       (`_throttle_status` returned None, since `.get("throttleStatus")`
       on a dict that doesn't have that key is None), so 4 retries burned
       ~4s total while Shopify's own `windowResetAt` needed tens of
       seconds -- the fetch failed identically twice before this was
       caught. `windowResetAt` is authoritative when present; use it
       directly instead of estimating from a restore rate that isn't in
       this shape at all.
    """
    cost = None
    for e in errors:
        c = (e.get("extensions") or {}).get("cost")
        if c:
            cost = c
            break
    if not cost:
        return MIN_THROTTLE_BACKOFF_SECONDS

    window_reset_at = cost.get("windowResetAt")
    if window_reset_at:
        try:
            reset_dt = datetime.fromisoformat(window_reset_at.replace("Z", "+00:00"))
            remaining = (reset_dt - datetime.now(timezone.utc)).total_seconds()
            return max(MIN_THROTTLE_BACKOFF_SECONDS, remaining + 0.5)  # small buffer past the reset instant
        except ValueError:
            pass  # fall through to the cost/restore-rate estimate below

    throttle_status = cost.get("throttleStatus") or cost
    needed = max(0.0, float(cost.get("requestedQueryCost", 1)) - float(throttle_status.get("currentlyAvailable", 0)))
    restore_rate = float(throttle_status.get("restoreRate", 1)) or 1.0
    return max(MIN_THROTTLE_BACKOFF_SECONDS, needed / restore_rate)


async def graphql_request(
    client: httpx.AsyncClient,
    store: ShopifyStore,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST one GraphQL request with retry on HTTP-level failures AND
    Shopify's THROTTLED/MAX_COST_EXCEEDED errors (which arrive inside the
    `errors` array on an HTTP 200, not as a distinct status code). Returns
    the parsed `data` object on success; raises RuntimeError with the
    query stripped out of the message (never logs the token, which lives
    only in the header, never in the URL or body echoed back)."""
    headers = {
        "X-Shopify-Access-Token": store.access_token,
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}
    attempt = 0
    while True:
        attempt += 1
        try:
            response = await client.post(
                store.graphql_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as exc:
            if attempt > MAX_RETRIES:
                raise RuntimeError(f"Network error after {MAX_RETRIES} retries: {exc}") from exc
            await asyncio.sleep(min(2**attempt, 30))
            continue

        if response.status_code in RETRYABLE_STATUSES and attempt <= MAX_RETRIES:
            delay = min(2**attempt, 30)
            print(f"    HTTP {response.status_code}, attempt {attempt}/{MAX_RETRIES}, sleeping {delay}s")
            await asyncio.sleep(delay)
            continue

        try:
            body = response.json()
        except ValueError:
            raise RuntimeError(
                f"Non-JSON response ({response.status_code}) from {store.key}: {response.text[:300]!r}"
            )

        errors = body.get("errors") or []
        error_codes = {
            (e.get("extensions") or {}).get("code")
            for e in errors
            if isinstance(e, dict)
        }
        is_throttled = "THROTTLED" in error_codes or "MAX_COST_EXCEEDED" in error_codes

        if is_throttled and attempt <= MAX_RETRIES:
            delay = _throttle_delay(errors)
            print(f"    throttled (attempt {attempt}/{MAX_RETRIES}), sleeping {delay:.1f}s: store={store.key}")
            await asyncio.sleep(delay)
            continue

        if errors:
            raise RuntimeError(f"Shopify GraphQL error(s) from store {store.key}: {json.dumps(errors)[:500]}")
        if response.status_code >= 400:
            raise RuntimeError(f"Shopify HTTP error {response.status_code} from store {store.key}: {body}")

        return body.get("data", {})


async def paginate_connection(
    client: httpx.AsyncClient,
    store: ShopifyStore,
    query_template: str,
    connection_path: list[str],
    *,
    page_size: int = 50,
    variables: dict[str, Any] | None = None,
    max_pages: int | None = None,
    on_page: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
) -> list[dict[str, Any]]:
    """Walk a Relay-style connection to exhaustion (or `max_pages`).
    `query_template` must accept `$first: Int!` and `$after: String` and
    return a connection (edges { node }, pageInfo { hasNextPage, endCursor })
    reachable by following `connection_path` (a list of dict keys) from
    the top-level `data` object, e.g. ["products"] or ["shop", "orders"].

    `on_page`, if given, is awaited with just that page's nodes right after
    each page is fetched -- lets a caller write to the DB incrementally
    (page by page) instead of only after the whole connection is exhausted,
    which matters once a connection spans many pages (a full-year date
    range can be thousands of pages) and a caller wants real progress
    rather than one write at the very end. The full accumulated list is
    still returned either way, unchanged.
    """
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    page = 0
    while True:
        page += 1
        page_variables = {**(variables or {}), "first": page_size, "after": cursor}
        data = await graphql_request(client, store, query_template, page_variables)
        node = data
        for key in connection_path:
            node = node.get(key) or {}
        edges = node.get("edges", [])
        page_items = [edge["node"] for edge in edges]
        items.extend(page_items)
        if on_page and page_items:
            await on_page(page_items)
        page_info = node.get("pageInfo", {})
        if not page_info.get("hasNextPage") or (max_pages and page >= max_pages):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return items
