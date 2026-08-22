"""Fetch Instagram data (profile, media, media insights) via the
Instagram Graph API, across every configured account, and write it into
``raw_dump_instagram`` in Supabase via the REST Data API -- the Instagram
counterpart to ingest_last_15_days.py / ingest_shopify.py, kept
structurally identical: same Bronze row envelope, same REST-write path,
same log-and-continue error philosophy, same safety rules (access token
never printed, never stored in request_params).

Why this looks like the Meta scripts, not the Shopify ones: Instagram
Graph API IS the Meta Marketing API's underlying Graph API (same
graph.facebook.com host, same META_ACCESS_TOKEN, same REST field-list +
cursor-pagination shape, same rate-limit codes) -- just different node
types (ig-user, ig-media instead of campaign/adset/ad). See
scripts/instagram_client.py.

KNOWN DATA CAVEAT (confirmed live, not a bug): IG_USERNAME_1/_2 in .env
don't match what those account IDs actually resolve to on Instagram
(IG_USER_ID_1 -> @saadaadesigns, not @saadaa_men; IG_USER_ID_2 ->
@saadaa_men, not @saadaa_women). Per explicit instruction, this script
ignores the .env labels entirely and always uses the live `username`
field from the API as the source of truth for display/logging.

Scope: user profile (1 call/account) + full media list (paginated,
comprehensive field set -- confirmed live that all 28 documented IG
Media fields work in one request, no pruning needed unlike the Meta
Insights/Shopify sagas) + collaborative media and pending collaboration
invites (1 paginated call each, always on -- influencer/UGC posts that
tag this account as a co-author) + per-media insights (opt-in via
--include-insights, since it's one extra API call per media item --
mirrors ingest_last_15_days.py's --include-roster opt-in pattern for the
same reason: cost, not correctness).

PostgREST can't run DDL, so ``raw_dump_instagram`` must already exist --
run ``scripts/sql/raw_dump_instagram.sql`` once in the Supabase SQL
Editor first.

Usage:
    python3 scripts/ingest_instagram.py                        # every account, profile + media, writes to Supabase
    python3 scripts/ingest_instagram.py --account 1               # just one account
    python3 scripts/ingest_instagram.py --include-insights          # also fetch per-media insights (1 extra call per media item)
    python3 scripts/ingest_instagram.py --no-insert                   # fetch + time only
    python3 scripts/ingest_instagram.py --max-media 50                 # cap media count for a quick trial
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    paginate,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DDL_PATH = REPO_ROOT / "scripts" / "sql" / "raw_dump_instagram.sql"
ERROR_LOG_PATH = REPO_ROOT / "logs" / "instagram_ingest_errors.log"

IG_USER_FIELDS = [
    "id", "username", "name", "biography", "followers_count", "follows_count",
    "media_count", "profile_picture_url", "website", "has_profile_pic", "is_published",
]

#: Confirmed live (2026-07-30): 27 of the 28 documented IG Media fields
#: work fine together across a real, mixed-media-type list -- fields
#: inapplicable to a given item (e.g. alt_text with no accessibility text
#: set) are silently omitted from the response, not rejected.
#:
#: NOTE: "copyright_check_information" deliberately excluded -- it's
#: VIDEO-only ("copyright check only eligible to video media type",
#: error code 9005 / subcode 1452042), and a real account's /media list
#: is always a mix of VIDEO, CAROUSEL_ALBUM, and IMAGE items, so
#: requesting it here always 400s the whole page as soon as a non-video
#: item appears. A single-item smoke test against one video happened to
#: pass and masked this -- only found once the full paginated list (a
#: genuine mix of types) was actually fetched.
IG_MEDIA_FIELDS = [
    "id", "caption", "media_type", "media_url", "thumbnail_url", "permalink",
    "shortcode", "timestamp", "username", "owner", "alt_text", "like_count",
    "comments_count", "is_comment_enabled", "media_product_type",
    "is_shared_to_feed", "media_audio_type", "is_ai_generated",
    "legacy_instagram_media_id",
    "boost_ads_list", "boost_eligibility_info", "reposts_count", "saved_count",
    "shares_count", "total_comments_count", "total_like_count", "total_views_count",
]

#: Valid metrics differ by media_product_type -- see
#: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/insights
IG_INSIGHTS_METRICS_BY_PRODUCT_TYPE = {
    "FEED": ["comments", "follows", "likes", "profile_activity", "profile_visits", "reach",
             "saved", "shares", "total_interactions"],
    "REELS": ["comments", "ig_reels_avg_watch_time", "ig_reels_video_view_total_time", "likes",
              "reach", "reels_skip_rate", "saved", "shares", "total_interactions", "views"],
    "STORY": ["follows", "navigation", "profile_activity", "profile_visits", "reach",
              "replies", "shares", "views"],
    "AD": [],  # ads-surfaced media -- insights not attempted here
}


# ----------------------------------------------------------------------
# Fetch orchestration
# ----------------------------------------------------------------------


@dataclass
class FetchResult:
    account: IGAccount
    object_type: str
    items: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    request_params: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    item_errors: list[dict[str, str]] = field(default_factory=list)


async def _fetch_user(client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount) -> FetchResult:
    params = {"fields": ",".join(IG_USER_FIELDS)}
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="ig_user", request_params=params)
    try:
        data = await get_with_retry(client, f"{base_url}/{account.user_id}", {**params, "access_token": access_token})
        result.items = [data]
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_media(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount, *, max_media: int | None
) -> FetchResult:
    # Confirmed live: a 1.5s inter-page gap + the default 50-item page
    # size still exhausted retries on a 1391-media account -- the
    # throttle scales with SUSTAINED load over the full pagination run,
    # not just back-to-back timing. Smaller pages (less complexity per
    # request) plus a longer gap (less cumulative load per unit time)
    # together, not either alone, is what's being tried here.
    params = {"fields": ",".join(IG_MEDIA_FIELDS), "limit": 25}
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="ig_media", request_params=params)
    try:
        result.items = await paginate(
            client, f"{base_url}/{account.user_id}/media",
            {**params, "access_token": access_token}, max_items=max_media,
            inter_page_delay_seconds=4.0,
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


#: Confirmed live (2026-07-30): both collaboration-related ig-user edges
#: work with this token. `collaborative_media` = posts where this account
#: is an ACCEPTED collaborator on someone else's media (already public,
#: co-authored). `collaboration_invites` = PENDING collaboration requests
#: from other creators tagging this account, not yet accepted -- useful
#: for influencer/UGC campaign tracking. There's also a `collaborators`
#: edge on individual ig-media (who's been added as a collaborator on
#: OUR OWN media) -- not fetched here since it's an N+1 per-media call
#: like insights; add a --include-collaborators-per-media flag later if
#: needed the same way --include-insights works.
async def _fetch_collaborative_media(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount
) -> FetchResult:
    # Confirmed live (2026-07-30): unpaced deep pagination on this edge
    # hit Meta's complexity throttle on a large account (813 items /
    # ~17 pages) -- same fix as _fetch_media's inter_page_delay_seconds.
    params = {"fields": ",".join(IG_MEDIA_FIELDS)}
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="ig_collaborative_media", request_params=params)
    try:
        result.items = await paginate(
            client, f"{base_url}/{account.user_id}/collaborative_media",
            {**params, "access_token": access_token},
            inter_page_delay_seconds=1.5,
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_collaboration_invites(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount
) -> FetchResult:
    # NOTE: this edge has a FIXED field shape -- confirmed live that
    # requesting extra fields (timestamp, status, media_type, etc.) is
    # silently ignored, not an error; only media_id, media_owner_username,
    # caption, media_url are ever returned.
    params: dict[str, Any] = {}
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="ig_collaboration_invites", request_params=params)
    try:
        result.items = await paginate(
            client, f"{base_url}/{account.user_id}/collaboration_invites",
            {"access_token": access_token},
            inter_page_delay_seconds=1.5,
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_media_insights(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount, media_items: list[dict[str, Any]]
) -> FetchResult:
    """One insights call per media item -- opt-in (--include-insights)
    since it's N extra API calls, not one. Per-item failures (e.g. media
    too old, insufficient reach for insights) are logged and skipped;
    they don't abort the whole batch."""
    t0 = time.monotonic()
    result = FetchResult(account=account, object_type="ig_media_insights")
    for media in media_items:
        media_id = media.get("id")
        product_type = media.get("media_product_type", "FEED")
        metrics = IG_INSIGHTS_METRICS_BY_PRODUCT_TYPE.get(product_type, [])
        if not metrics:
            continue
        params = {"access_token": access_token, "metric": ",".join(metrics)}
        try:
            body = await get_with_retry(client, f"{base_url}/{media_id}/insights", params)
            insights_by_name = {m["name"]: m["values"][0]["value"] for m in body.get("data", []) if m.get("values")}
            result.items.append({"media_id": media_id, "media_product_type": product_type, "insights": insights_by_name})
        except RuntimeError as exc:
            result.item_errors.append({"media_id": media_id, "error": str(exc)})
    result.duration_seconds = time.monotonic() - t0
    return result


async def _run(
    accounts: list[IGAccount], base_url: str, access_token: str, *, max_media: int | None, include_insights: bool
) -> tuple[list[FetchResult], list[FetchResult], list[FetchResult], list[FetchResult]]:
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        user_results = await asyncio.gather(*[_fetch_user(client, base_url, access_token, a) for a in accounts])
        media_results = await asyncio.gather(
            *[_fetch_media(client, base_url, access_token, a, max_media=max_media) for a in accounts]
        )
        # Confirmed live (2026-08-02): running collaborative_media +
        # collaboration_invites concurrently -- even across DIFFERENT
        # accounts -- reliably triggers Meta's "reduce the amount of data
        # you're asking for" throttle. This app's ads_api_access_tier is
        # development_access, and X-App-Usage showed the same call_count
        # shared across accounts/tokens, so the budget is app-level, not
        # per-account. A fully sequential, one-edge-at-a-time fetch (no
        # gather) is the only combination that has succeeded so far.
        collaboration_results: list[FetchResult] = []
        for a in accounts:
            collaboration_results.append(await _fetch_collaborative_media(client, base_url, access_token, a))
            collaboration_results.append(await _fetch_collaboration_invites(client, base_url, access_token, a))
        insights_results: list[FetchResult] = []
        if include_insights:
            insights_results = await asyncio.gather(
                *[
                    _fetch_media_insights(client, base_url, access_token, mr.account, mr.items)
                    for mr in media_results if not mr.error
                ]
            )
        return list(user_results), list(media_results), insights_results, list(collaboration_results)


# ----------------------------------------------------------------------
# Bronze row shaping (same envelope as raw_dump_meta / raw_dump_shopify)
# ----------------------------------------------------------------------


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_rows(result: FetchResult, *, batch_id: uuid.UUID, api_version: str, extracted_at: datetime) -> list[dict[str, Any]]:
    rows = []
    for item in result.items:
        if result.object_type in ("ig_media_insights", "ig_collaboration_invites"):
            source_id = item.get("media_id")
        else:
            source_id = item.get("id")
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "source_id": source_id,
                "raw_payload": item,
                "api_endpoint": result.object_type,
                "api_version": api_version,
                "batch_id": str(batch_id),
                "request_params": result.request_params,
                "extracted_at": extracted_at.isoformat(),
                "sync_type": "manual",
                "payload_hash": _hash_payload(item),
                "processing_status": "pending",
                "object_type": result.object_type,
                "parent_ids": {
                    "account_key": result.account.key,
                    "ig_user_id": result.account.user_id,
                },
                "is_nested": False,
            }
        )
    return rows


def _log_error(account: IGAccount, object_type: str, error: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    block = f"=== {timestamp} | account={account.key} (user_id={account.user_id}) | object_type={object_type} ===\nError: {error}\n\n"
    print(f"    [error] account={account.key} object_type={object_type} -- logged to {ERROR_LOG_PATH.relative_to(REPO_ROOT)}")
    ERROR_LOG_PATH.parent.mkdir(exist_ok=True)
    with open(ERROR_LOG_PATH, "a") as f:
        f.write(block)


# ----------------------------------------------------------------------
# Supabase REST Data API writes (identical pattern to dump_test_table.py / ingest_shopify.py)
# ----------------------------------------------------------------------


def _resolve_supabase_creds() -> tuple[str, str] | None:
    supabase_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_URL")
    service_role_key = (
        os.environ.get("DATABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not supabase_url or not service_role_key:
        print(
            "A Supabase project URL (DATABASE_URL or SUPABASE_URL) and a service-role key "
            "(DATABASE_SERVICE_KEY, SUPABASE_KEY, or SUPABASE_SERVICE_ROLE_KEY) must both be set in .env.",
            file=sys.stderr,
        )
        return None
    if not supabase_url.startswith("http"):
        print(f"'{supabase_url}' doesn't look like a Supabase project URL.", file=sys.stderr)
        return None
    return supabase_url, service_role_key


async def _check_table_exists(client: httpx.AsyncClient, supabase_url: str, service_role_key: str, table: str) -> bool:
    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
    resp = await client.get(f"{supabase_url.rstrip('/')}/rest/v1/{table}", headers=headers, params={"limit": "0"}, timeout=30.0)
    return resp.status_code == 200


async def _insert_rows_supabase(
    client: httpx.AsyncClient, supabase_url: str, service_role_key: str, table: str, rows: list[dict[str, Any]], *, chunk_size: int
) -> int:
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/{table}"
    inserted = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        resp = await client.post(endpoint, headers=headers, json=chunk, timeout=60.0)
        if resp.status_code >= 300:
            raise RuntimeError(f"Supabase insert failed ({resp.status_code}): {resp.text[:500]}")
        inserted += len(chunk)
    return inserted


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default=None, help="Restrict to one account key. Default: every configured account.")
    parser.add_argument("--max-media", type=int, default=None, help="Cap media items fetched per account (default: no cap).")
    parser.add_argument("--include-insights", action="store_true", help="Also fetch per-media insights (1 extra API call per media item).")
    parser.add_argument("--table", default="raw_dump_instagram", help="Target Supabase table (default: raw_dump_instagram).")
    parser.add_argument("--chunk-size", type=int, default=200, help="Rows per Supabase REST insert request (default 200).")
    parser.add_argument("--no-insert", action="store_true", help="Fetch and time only -- skip the Supabase write.")
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
        print("No Instagram accounts configured -- set IG_USER_ID_1 and IG_USERNAME_1 in .env.", file=sys.stderr)
        return 1
    if args.account:
        if args.account not in accounts_by_key:
            print(f"No account with key '{args.account}'. Configured: {', '.join(sorted(accounts_by_key, key=int))}", file=sys.stderr)
            return 1
        accounts = [accounts_by_key[args.account]]
    else:
        accounts = [accounts_by_key[k] for k in sorted(accounts_by_key, key=int)]

    supabase_url = service_role_key = None
    if not args.no_insert:
        creds = _resolve_supabase_creds()
        if creds is None:
            return 1
        supabase_url, service_role_key = creds

    print("IG accounts (.env labels -- verify against API `username` in output, known to be mismatched, see script docstring):")
    print("  " + ", ".join(describe_ig_account_safely(a) for a in accounts))
    if args.include_insights:
        print("Including per-media insights (1 extra API call per media item).")
    if supabase_url:
        print(f"Target Supabase project: {supabase_url}")
        print(f"Target table: {args.table}")
    else:
        print("--no-insert set: fetching and timing only, no Supabase write.")
    print("Access token: [redacted, not printed] -- loaded, present, not shown.\n")

    base_url = f"https://graph.facebook.com/{api_version}"

    fetch_start = time.monotonic()
    user_results, media_results, insights_results, collaboration_results = asyncio.run(
        _run(accounts, base_url, access_token, max_media=args.max_media, include_insights=args.include_insights)
    )
    fetch_wall_time = time.monotonic() - fetch_start

    all_results = user_results + media_results + insights_results + collaboration_results
    print("Fetch results:")
    total_rows = 0
    any_error = False
    for r in all_results:
        real_username = None
        if r.object_type == "ig_user" and r.items:
            real_username = r.items[0].get("username")
        label = f"@{real_username}" if real_username else f".env:@{r.account.username}"
        status = "OK" if not r.error else "FAILED"
        print(f"  [{r.account.key}] {label:<20} {r.object_type:<18} {status:<7} {len(r.items):>6} rows  {r.duration_seconds:6.2f}s")
        if r.error:
            any_error = True
            _log_error(r.account, r.object_type, r.error)
        if r.item_errors:
            print(f"      {len(r.item_errors)} item-level error(s) (logged, other items still fetched)")
            for ie in r.item_errors:
                _log_error(r.account, f"{r.object_type}:{ie['media_id']}", ie["error"])
        total_rows += len(r.items)

    print(f"\nInstagram fetch wall time (profile+media parallel, collaboration edges sequential): {fetch_wall_time:.2f}s")
    print(f"Total rows fetched: {total_rows}")

    if args.no_insert:
        print("\n--no-insert set -- stopping before any Supabase write.")
        return 1 if any_error else 0

    async def _write() -> tuple[int, bool]:
        async with httpx.AsyncClient() as client:
            exists = await _check_table_exists(client, supabase_url, service_role_key, args.table)
            if not exists:
                print(
                    f"\nTable '{args.table}' doesn't exist yet. Run {DDL_PATH.relative_to(REPO_ROOT)} "
                    "once in the Supabase SQL Editor, then re-run this.",
                    file=sys.stderr,
                )
                return 0, True

            extracted_at = datetime.now(timezone.utc)
            total_inserted = 0
            write_any_error = False
            for r in all_results:
                if r.error or not r.items:
                    if r.error:
                        write_any_error = True
                    continue
                batch_id = uuid.uuid4()
                rows = _build_rows(r, batch_id=batch_id, api_version=api_version, extracted_at=extracted_at)
                inserted = await _insert_rows_supabase(client, supabase_url, service_role_key, args.table, rows, chunk_size=args.chunk_size)
                total_inserted += inserted
                print(f"  [{r.account.key}] {r.object_type:<18} inserted {inserted} rows")
            return total_inserted, write_any_error

    write_start = time.monotonic()
    total_inserted, write_any_error = asyncio.run(_write())
    write_wall_time = time.monotonic() - write_start

    print(f"\nSupabase write time: {write_wall_time:.2f}s")
    print(f"Total rows inserted into {args.table}: {total_inserted}")
    print(f"\nGrand total (Instagram fetch + Supabase write): {fetch_wall_time + write_wall_time:.2f}s")

    return 1 if (any_error or write_any_error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
