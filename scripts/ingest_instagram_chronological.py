"""Chronological (oldest-first), resumable Instagram backfill.

``ingest_instagram.py`` always walks newest-first via cursor pagination --
fine for "give me what's current," wrong for "backfill everything
starting from the oldest post." This script instead:

1. **Discovers** each account's exact oldest post timestamp using Meta's
   `until` param -- confirmed live 2026-08-11 that it's a genuine
   time-window filter, not silently ignored (a call with `until=X`
   reliably excludes items at/after X and resumes exactly where that
   boundary implies). Uses exponential-then-binary search: ~15-20 tiny
   (`limit=1`) probe calls total, regardless of whether the account has
   50 posts or 5,000 -- nothing like walking every page to reach the end.
2. **Fetches forward** from that oldest date to now in fixed-size date
   windows (`--window-days`, default 30) via `since`/`until` on `/media`
   only. Each completed window is checkpointed to a local JSON file, so
   re-running resumes instead of re-fetching from the start -- this is
   the "smaller fragments" the fetch itself is broken into.
   `/collaborative_media` and `/collaboration_invites` are each fetched
   ONCE per account in full, not windowed -- `/collaboration_invites` has
   no timestamp field at all (Meta's API returns a fixed shape there,
   confirmed in ingest_instagram.py's docstring); `/collaborative_media`
   DOES have a timestamp field but confirmed live 2026-08-11 that Meta
   silently ignores `since`/`until` on this specific edge -- a first
   version of this script windowed it anyway, which sent the same
   unfiltered full list back on every "window" and inserted the same 78
   posts 14 times before this was caught (1092 rows, 78 distinct
   `source_id`s). Only `/media` has been confirmed to genuinely honor
   `since`/`until` -- do not assume any other edge does without testing
   it the same way first (compare `COUNT(*)` vs `COUNT(DISTINCT source_id)`
   after a small multi-window trial).

Same Bronze row shape and same `raw_dump_instagram` table as
``ingest_instagram.py`` (see ``scripts/sql/raw_dump_instagram.sql``) --
this is an alternate FETCH ORDER, not a new table. Reuses that script's
field lists and row-building helpers directly rather than duplicating
them.

Writes via the direct Postgres DSN (``DATABASE_URL``, asyncpg) instead of
``ingest_instagram.py``'s PostgREST path -- that path currently can't
work here anyway, since ``DATABASE_URL`` was repointed to the Postgres
DSN for the admin panel (see ``app/config.py``) and no longer looks like
a Supabase REST URL. Deliberately uses raw ``asyncpg``, not
``app.database.session``, to keep this script standalone and
Python-3.9-compatible like the rest of ``scripts/`` -- it does not
depend on the ``app`` package at all.

Every window and the final summary print a progress bar (elapsed date
range covered / total date range for that account), the number of items
fetched, and the CUMULATIVE number of real HTTP calls made so far
(counted via an httpx event_hook, so retries count too -- they're real
requests against the same rate budget).

Usage:
    python3 scripts/ingest_instagram_chronological.py --discover-only --token-env DUMMY_TOKEn
        # just find + print each account's oldest post date, fetch/write nothing
    python3 scripts/ingest_instagram_chronological.py --no-insert --token-env DUMMY_TOKEn --account 1 --max-windows 2
        # dry run: discover + fetch 2 windows for one account, print only
    python3 scripts/ingest_instagram_chronological.py --token-env DUMMY_TOKEn --table dump_instagram
        # real fetch + write, every account, resumable, default 30-day windows
    python3 scripts/ingest_instagram_chronological.py --token-env DUMMY_TOKEn --table dump_instagram --account 1 --window-days 14
        # smaller fragments, one account
    python3 scripts/ingest_instagram_chronological.py --token-env DUMMY_TOKEn --table dump_instagram --refresh-existing
        # re-walk ALL history (not just new posts) to refresh like/comment/view counts on
        # already-fetched posts -- heavier, run this deliberately/periodically, not every time
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

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
from ingest_instagram import (  # noqa: E402
    IG_INSIGHTS_METRICS_BY_PRODUCT_TYPE,
    IG_MEDIA_FIELDS,
    IG_USER_FIELDS,
    FetchResult,
    _build_rows,
    _log_error,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DDL_PATH = REPO_ROOT / "scripts" / "sql" / "raw_dump_instagram.sql"
CHECKPOINT_PATH = REPO_ROOT / "logs" / "instagram_chronological_checkpoint.json"

MEDIA_PAGE_SIZE = 25  # same size ingest_instagram.py settled on to avoid Meta's complexity throttle
INTER_PAGE_DELAY_SECONDS = 4.0
INTER_WINDOW_DELAY_SECONDS = 2.0

#: The complexity throttle on /collaborative_media is driven by field-count
#: x page-size TOGETHER, not either alone -- confirmed live 2026-08-11 by
#: bisection against account 3 (which had failed with the full 26-field
#: IG_MEDIA_FIELDS list on every attempt): 13 fields @ limit=25 -> throttled;
#: 13 fields @ limit=20 -> throttled; 13 fields @ limit=15 -> succeeds
#: (also succeeds @ limit=10/5). Using 15 as a safe ceiling with margin, not
#: pushed right up against the measured boundary.
COLLABORATIVE_MEDIA_PAGE_SIZE = 15

#: Plain fields on the ig-media node itself -- NOT the /insights endpoint.
#: Confirmed live 2026-08-11: these ARE returned for media owned by another
#: account (unlike /insights, which returned error code 10 "Application
#: does not have permission for this action" on every tagged post tested,
#: whether accepted collaborative_media or still-pending
#: collaboration_invites -- that requires either ownership or the creator
#: explicitly enabling insights-sharing for that post, which none of ours
#: have). These public fields need no such grant: engagement counters
#: (likes/comments/saves/shares/views) plus identity/display fields
#: (permalink/media_type/thumbnail_url/username -- collaboration_invites'
#: own fixed-shape edge only returns media_id/media_owner_username/caption/
#: media_url, missing these). Does NOT get reach -- that's /insights-only
#: and genuinely blocked, confirmed above; not worth re-testing per-item,
#: the denial is a structural ownership rule, not the rate throttle.
ENGAGEMENT_FIELDS = (
    "like_count,comments_count,total_like_count,total_comments_count,"
    "total_views_count,saved_count,shares_count,reposts_count,"
    "permalink,media_type,thumbnail_url,username"
)


class CallCounter:
    """Counts every real HTTP request made through one httpx.AsyncClient --
    attached via event_hooks, so it transparently counts calls made deep
    inside instagram_client.py's get_with_retry()/paginate() (including
    retries, which are real requests against the same rate budget) without
    threading a counter through every fetch function's signature."""

    def __init__(self) -> None:
        self.count = 0

    async def on_request(self, request: httpx.Request) -> None:
        self.count += 1


def _progress_bar(current: datetime, start: datetime, end: datetime, *, width: int = 24) -> str:
    total_seconds = (end - start).total_seconds()
    done_seconds = (current - start).total_seconds()
    frac = 0.0 if total_seconds <= 0 else max(0.0, min(1.0, done_seconds / total_seconds))
    filled = int(frac * width)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {frac * 100:5.1f}%"


# ----------------------------------------------------------------------
# Checkpoint file -- {"1": {"oldest_discovered_at": iso, "media_completed_until": iso, "collaborative_media_completed_until": iso}, ...}
# ----------------------------------------------------------------------


def _load_checkpoint() -> dict[str, dict[str, str]]:
    if not CHECKPOINT_PATH.exists():
        return {}
    return json.loads(CHECKPOINT_PATH.read_text())


def _save_checkpoint(checkpoint: dict[str, dict[str, str]]) -> None:
    CHECKPOINT_PATH.parent.mkdir(exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2, sort_keys=True))


async def _resume_state_from_db(conn: Any, table: str, account_key: str) -> dict[str, Any]:
    """DB-native substitute for the JSON checkpoint file -- used for
    admin-panel-triggered runs (``use_checkpoint_file=False``), correct
    regardless of which table is targeted. The file-based checkpoint is
    keyed by account only, not by table, so pointing ``--table`` at a
    second table for the same account would wrongly reuse the first
    table's progress; querying the target table directly sidesteps that
    entirely. Three cheap indexed lookups, not cached -- the next
    admin-triggered run just re-queries and gets the now-updated state
    naturally, no separate persistence needed. ``table`` is trusted here,
    same as ``_insert_rows``/``_replace_snapshot`` below -- the caller
    (the admin API) is responsible for validating it before triggering a
    run."""
    media_max = await conn.fetchval(
        f'SELECT MAX(extracted_at) FROM "{table}" WHERE object_type = $1 AND parent_ids ->> \'account_key\' = $2',
        "ig_media", account_key,
    )
    collab_exists = await conn.fetchval(
        f'SELECT EXISTS(SELECT 1 FROM "{table}" WHERE object_type = $1 AND parent_ids ->> \'account_key\' = $2)',
        "ig_collaborative_media", account_key,
    )
    profile_exists = await conn.fetchval(
        f'SELECT EXISTS(SELECT 1 FROM "{table}" WHERE object_type = $1 AND parent_ids ->> \'account_key\' = $2)',
        "ig_user", account_key,
    )
    ckpt: dict[str, Any] = {
        "collaborative_media_fetched": bool(collab_exists),
        "profile_fetched": bool(profile_exists),
    }
    if media_max is not None:
        ckpt["media_completed_until"] = media_max.isoformat()
    return ckpt


# ----------------------------------------------------------------------
# Phase 1: oldest-post discovery via exponential-then-binary search on `until`
# ----------------------------------------------------------------------


async def discover_oldest_timestamp(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount
) -> datetime | None:
    """Finds the account's exact oldest /media post timestamp.

    `until=X` reliably returns only items strictly before X (confirmed
    live). So: `until=X` returning 0 items means the true oldest post is
    at-or-after X; returning >=1 items means the oldest post is strictly
    before X. That's a monotonic predicate in X, so exponential search
    finds a bracket, then binary search narrows it to under a day, using
    only `limit=1` probe calls -- cheap regardless of how deep the
    account's history actually goes.

    Returns None if the account has no posts at all.
    """

    async def probe(until_dt: datetime) -> dict[str, Any] | None:
        params = {
            "fields": "id,timestamp", "limit": 1, "access_token": access_token,
            "until": int(until_dt.timestamp()),
        }
        body = await get_with_retry(client, f"{base_url}/{account.user_id}/media", params)
        items = body.get("data", [])
        return items[0] if items else None

    now = datetime.now(timezone.utc)
    newest = await probe(now + timedelta(seconds=1))
    if newest is None:
        return None  # no posts at all

    # Exponential backward search: hi always has >=1 item before it (a
    # confirmed upper bound on how far back we need to look); lo is the
    # first point found with 0 items before it (a confirmed lower bound).
    hi = now
    step = timedelta(days=90)
    lo: datetime | None = None
    while lo is None:
        candidate = hi - step
        item = await probe(candidate)
        if item is None:
            lo = candidate
        else:
            hi = candidate
            step *= 2
        if step.days > 366 * 20:  # 20 years -- treat as "no meaningful floor found"
            lo = candidate
            break

    # Binary search: narrow [lo, hi] to under a day.
    while (hi - lo) > timedelta(days=1):
        mid = lo + (hi - lo) / 2
        item = await probe(mid)
        if item is None:
            lo = mid
        else:
            hi = mid

    # hi is now within a day of the true oldest post and is confirmed to
    # have >=1 item before it -- fetch that item directly for its exact
    # timestamp rather than trusting the day-level bracket.
    oldest_item = await probe(hi)
    if oldest_item is None:
        return None
    return datetime.fromisoformat(oldest_item["timestamp"].replace("+0000", "+00:00"))


# ----------------------------------------------------------------------
# Phase 2: windowed forward fetch
# ----------------------------------------------------------------------


async def _fetch_window(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount,
    edge: str, fields: list[str], window_start: datetime, window_end: datetime,
) -> FetchResult:
    params = {"fields": ",".join(fields), "limit": MEDIA_PAGE_SIZE}
    object_type = "ig_media" if edge == "media" else "ig_collaborative_media"
    result = FetchResult(account=account, object_type=object_type, request_params=params)
    t0 = time.monotonic()
    try:
        result.items = await paginate(
            client, f"{base_url}/{account.user_id}/{edge}",
            {**params, "access_token": access_token,
             "since": int(window_start.timestamp()), "until": int(window_end.timestamp())},
            inter_page_delay_seconds=INTER_PAGE_DELAY_SECONDS,
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _fetch_full_edge(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount,
    edge: str, object_type: str, params: dict[str, Any], *, inter_page_delay_seconds: float = 1.5,
) -> FetchResult:
    """For edges with no timestamp field (collaboration_invites) -- fetched
    in full every run, same as ingest_instagram.py, no windowing possible.

    The field-count/page-size fix (COLLABORATIVE_MEDIA_PAGE_SIZE) makes a
    SINGLE page succeed reliably, but confirmed live 2026-08-11 that
    pagination through many pages under sustained load can still trip the
    throttle partway through -- same "scales with sustained load, not any
    single request" behavior instagram_client.py's paginate() already
    documented for /media. A longer per-page delay for edges likely to
    paginate deep (collaborative_media) reduces that risk; collaboration_invites
    keeps the original 1.5s default since it has succeeded reliably at that pace."""
    result = FetchResult(account=account, object_type=object_type, request_params=params)
    t0 = time.monotonic()
    try:
        result.items = await paginate(
            client, f"{base_url}/{account.user_id}/{edge}",
            {**params, "access_token": access_token},
            inter_page_delay_seconds=inter_page_delay_seconds,
        )
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


async def _enrich_with_engagement_fields(
    client: httpx.AsyncClient, base_url: str, access_token: str, items: list[dict[str, Any]]
) -> None:
    """Mutates each item in place, adding ENGAGEMENT_FIELDS via one direct
    per-media_id node query -- collaboration_invites' own edge has a fixed
    response shape that omits these (confirmed: requesting extra fields on
    that edge is silently ignored), but the plain media node accepts them
    even for content owned by another account. Best-effort per item: a
    single item failing (deleted media, etc.) doesn't abort the batch."""
    for item in items:
        media_id = item.get("media_id") or item.get("id")
        if not media_id:
            continue
        try:
            body = await get_with_retry(
                client, f"{base_url}/{media_id}", {"fields": ENGAGEMENT_FIELDS, "access_token": access_token}
            )
        except RuntimeError:
            continue
        for field in ENGAGEMENT_FIELDS.split(","):
            if field in body:
                item[field] = body[field]


async def _enrich_with_insights(
    client: httpx.AsyncClient, base_url: str, access_token: str, items: list[dict[str, Any]]
) -> None:
    """Mutates each OWN media item in place, adding a nested "insights" dict
    with product-type-appropriate /insights metrics -- confirmed live
    2026-08-18 that /insights genuinely works for content we OWN (unlike
    collaborative_media/collaboration_invites, where it's hard-blocked with
    error code 10 regardless of permissions -- see the earlier /insights
    finding). This is the ONLY source for ig_reels_avg_watch_time
    ("average video play time"), ig_reels_video_view_total_time ("total
    watch time"), and reels_skip_rate ("percentage who skipped in the
    first three seconds" -- Meta's closest thing to a raw "3-second views"
    count, which isn't exposed as a count anywhere in this API) -- none of
    these are plain object fields, they only exist behind /insights.

    One extra API call PER ITEM, not batched -- opt-in via --include-insights
    for exactly this cost reason (mirrors ingest_instagram.py's own
    --include-insights flag). Best-effort per item: media too old / a
    product type with no metrics (AD) / a deleted post are all skipped,
    not fatal to the batch."""
    for item in items:
        media_id = item.get("id")
        product_type = item.get("media_product_type", "FEED")
        metrics = IG_INSIGHTS_METRICS_BY_PRODUCT_TYPE.get(product_type, [])
        if not media_id or not metrics:
            continue
        try:
            body = await get_with_retry(
                client, f"{base_url}/{media_id}/insights",
                {"metric": ",".join(metrics), "access_token": access_token},
            )
        except RuntimeError:
            continue
        item["insights"] = {
            m["name"]: m["values"][0]["value"] for m in body.get("data", []) if m.get("values")
        }


async def _fetch_user(
    client: httpx.AsyncClient, base_url: str, access_token: str, account: IGAccount
) -> FetchResult:
    params = {"fields": ",".join(IG_USER_FIELDS)}
    result = FetchResult(account=account, object_type="ig_user", request_params=params)
    t0 = time.monotonic()
    try:
        data = await get_with_retry(client, f"{base_url}/{account.user_id}", {**params, "access_token": access_token})
        result.items = [data]
    except RuntimeError as exc:
        result.error = str(exc)
    result.duration_seconds = time.monotonic() - t0
    return result


# ----------------------------------------------------------------------
# Direct-Postgres write (asyncpg -- standalone, no `app` package dependency)
# ----------------------------------------------------------------------


def _to_asyncpg_dsn(database_url: str) -> str:
    """asyncpg wants a bare postgresql:// DSN -- strip SQLAlchemy's
    +asyncpg driver suffix if present."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _replace_snapshot(conn: Any, table: str, object_type: str, account_key: str) -> int:
    """Deletes existing rows for one (object_type, account) pair before a
    fresh insert -- for edges fetched in FULL every run with no windowing/
    checkpoint to make plain INSERT append-safe (collaboration_invites has
    no timestamp field, so there's no way to only fetch "new" items -- every
    run re-fetches the account's whole current pending-invites list). Plain
    append would duplicate the same items on every run. Replacing the whole
    snapshot is also the semantically correct behavior for a "pending
    invites" list: an invite that got accepted/declined between runs should
    disappear, not linger as a stale duplicate."""
    result = await conn.execute(
        f'DELETE FROM "{table}" WHERE object_type = $1 AND parent_ids ->> \'account_key\' = $2',
        object_type, account_key,
    )
    # asyncpg's Connection.execute returns a status string like "DELETE 5"
    return int(result.split()[-1]) if result else 0


async def _insert_rows(conn: Any, table: str, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Upserts on (object_type, source_id) -- requires the partial unique
    index `ux_dump_instagram_object_type_source_id` (created 2026-08-18).
    Re-fetching a post you already have now REFRESHES it in place (new
    like/comment/view counts, updated payload_hash, ingested_at bumped to
    now) instead of erroring or silently duplicating -- engagement numbers
    change after a post is published, so a one-time snapshot goes stale.
    The row's original `id` (PK) and first-seen `extracted_at` are NOT
    preserved on conflict -- `extracted_at` here means "when this specific
    fetch happened," which SHOULD move forward on a refresh; if you need
    genuine first-seen tracking later, add a separate `first_seen_at`
    column that only gets set on INSERT (COALESCE against the existing
    value), don't repurpose extracted_at for it.

    Returns (inserted_count, updated_count) -- distinguished via the
    classic `xmax = 0` trick (0 means this command created the row; any
    other value means an existing row's xmax got stamped by the UPDATE
    path of the upsert)."""
    if not rows:
        return 0, 0
    columns = list(rows[0].keys())
    placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
    update_cols = [c for c in columns if c not in ("id", "source_id", "object_type")]
    update_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols) + ', "ingested_at" = now()'
    sql = (
        f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({placeholders}) '
        f'ON CONFLICT (object_type, source_id) WHERE source_id IS NOT NULL '
        f'DO UPDATE SET {update_clause} '
        f'RETURNING (xmax = 0) AS inserted'
    )
    inserted = updated = 0
    for row in rows:
        values = [
            uuid.UUID(row[c]) if c in ("id", "batch_id") else
            json.dumps(row[c]) if c in ("raw_payload", "request_params", "parent_ids") and row[c] is not None else
            datetime.fromisoformat(row[c]) if c == "extracted_at" else
            row[c]
            for c in columns
        ]
        was_insert = await conn.fetchval(sql, *values)
        if was_insert:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default=None, help="Restrict to one account key. Default: every configured account.")
    parser.add_argument("--token-env", default="META_ACCESS_TOKEN", help="Env var to read the access token from (default META_ACCESS_TOKEN; use DUMMY_TOKEn for a safe test).")
    parser.add_argument("--window-days", type=int, default=30, help="Size of each date fragment (default 30).")
    parser.add_argument("--max-windows", type=int, default=None, help="Cap windows fetched per account per edge (default: no cap, walk to now).")
    parser.add_argument("--discover-only", action="store_true", help="Only find and print each account's oldest post date -- fetch/write nothing.")
    parser.add_argument("--no-insert", action="store_true", help="Fetch and time only -- skip the Supabase write.")
    parser.add_argument("--table", default="raw_dump_instagram", help="Target table (default: raw_dump_instagram).")
    parser.add_argument(
        "--refresh-existing", action="store_true",
        help=(
            "Re-walk ALREADY-fetched history (media windows, collaborative_media) instead of only "
            "checking for new items -- picks up updated like/comment/view counts on old posts via "
            "upsert. Heavier than a normal run (re-fetches everything, not just what's new) -- "
            "expect more calls and a higher chance of hitting Meta's complexity throttle. "
            "collaboration_invites already refreshes every run regardless of this flag."
        ),
    )
    parser.add_argument(
        "--include-insights", action="store_true",
        help=(
            "Also fetch /insights for OWN media (ig_reels_avg_watch_time, "
            "ig_reels_video_view_total_time, reels_skip_rate, reach, views, etc.) -- ONE EXTRA "
            "API call per post, not batched. Only works for content you own -- confirmed blocked "
            "for collaborative_media/collaboration_invites regardless of this flag."
        ),
    )
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env")

    access_token = os.environ.get(args.token_env)
    api_version = os.environ.get("META_API_VERSION", DEFAULT_API_VERSION)
    if not access_token:
        print(f"{args.token_env} is not set.", file=sys.stderr)
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

    database_url = None
    if not args.no_insert and not args.discover_only:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url or not database_url.startswith("postgresql"):
            print(
                "DATABASE_URL must be a real postgresql(+asyncpg):// connection string to write -- "
                "use --no-insert or --discover-only to run without one.",
                file=sys.stderr,
            )
            return 1

    print(f"Token source: {args.token_env} [redacted, not printed]")
    print("Accounts (.env labels -- verify against API `username` in output):")
    print("  " + ", ".join(describe_ig_account_safely(a) for a in accounts))
    base_url = f"https://graph.facebook.com/{api_version}"

    return asyncio.run(_run(args, accounts, base_url, access_token, database_url))


async def _run(
    args: argparse.Namespace,
    accounts: list[IGAccount],
    base_url: str,
    access_token: str,
    database_url: str | None,
    *,
    use_checkpoint_file: bool = True,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    since_override: datetime | None = None,
) -> int:
    """``use_checkpoint_file=False``, ``on_progress``, and ``since_override``
    are all additions for the admin-panel-triggered path (see
    ``app/api/routers/admin.py``'s ``_run_instagram``) -- the CLI
    entrypoint (``main()``) always uses the defaults (file-based
    checkpoint, no callback, no override), so this remains fully backward
    compatible for manual runs.

    ``since_override``, when given, is used as ``oldest`` directly for
    EVERY account (skipping the ~15-20-call discovery probe entirely) and
    as the media window's starting point, taking priority over both
    discovery and whatever the checkpoint file/DB resume state would
    otherwise say -- lets an admin pick an explicit start date instead of
    trusting auto-discovery/auto-resume, for a brand-new table (skip
    older history on purpose) or an existing one (re-walk from further
    back than its own last-updated point)."""
    checkpoint = _load_checkpoint() if use_checkpoint_file else {}
    conn = None
    if database_url:
        import asyncpg  # imported lazily -- only needed on a real (non-dry-run) run

        conn = await asyncpg.connect(_to_asyncpg_dsn(database_url))

    any_error = False
    counter = CallCounter()
    run_start = time.monotonic()
    total_items = 0
    total_inserted = 0
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    try:
        async with httpx.AsyncClient(limits=limits, event_hooks={"request": [counter.on_request]}) as client:
            for account in accounts:
                if use_checkpoint_file:
                    acc_ckpt = checkpoint.setdefault(account.key, {})
                elif conn:
                    acc_ckpt = await _resume_state_from_db(conn, args.table, account.key)
                else:
                    acc_ckpt = {}
                calls_before_account = counter.count
                items_before_account = total_items
                print(f"\n=== Account {account.key} (@{account.username}) ===")

                if since_override is not None:
                    oldest = since_override
                    acc_ckpt["media_completed_until"] = since_override.isoformat()
                    print(f"  Start date overridden: {oldest.isoformat()} (discovery skipped)")
                else:
                    oldest_iso = acc_ckpt.get("oldest_discovered_at")
                    if oldest_iso:
                        oldest = datetime.fromisoformat(oldest_iso)
                        print(f"  Oldest post (cached): {oldest.isoformat()}")
                    else:
                        print("  Discovering oldest post date...")
                        calls_before_discovery = counter.count
                        oldest = await discover_oldest_timestamp(client, base_url, access_token, account)
                        discovery_calls = counter.count - calls_before_discovery
                        if oldest is None:
                            # No DIRECT posts -- but that says nothing about tagged content
                            # (collaborative_media/collaboration_invites are independent of
                            # whether this account has ever posted anything itself). A bare
                            # `continue` here used to skip profile/collaborative_media/
                            # collaboration_invites entirely for a zero-direct-post account --
                            # fixed: only the windowed `media` loop below is actually gated on
                            # `oldest`, everything else still runs.
                            print(f"  No direct posts found -- media backfill skipped, still checking tagged content. ({discovery_calls} call(s))")
                        else:
                            acc_ckpt["oldest_discovered_at"] = oldest.isoformat()
                            if use_checkpoint_file:
                                _save_checkpoint(checkpoint)
                            print(f"  Oldest post discovered: {oldest.isoformat()}  ({discovery_calls} call(s))")

                if args.discover_only:
                    continue

                if not conn:
                    print("  (--no-insert: fetch only, no DB write)")

                extracted_at = datetime.now(timezone.utc)

                if not acc_ckpt.get("profile_fetched") or args.refresh_existing:
                    user_result = await _fetch_user(client, base_url, access_token, account)
                    if user_result.error:
                        any_error = True
                        _log_error(account, "ig_user", user_result.error)
                        print(f"  [ig_user] FAILED: {user_result.error[:120]}")
                        if on_progress:
                            on_progress({"account": account.key, "edge": "ig_user", "status": "failed", "error": user_result.error})
                    else:
                        rows = _build_rows(user_result, batch_id=uuid.uuid4(), api_version=os.environ.get("META_API_VERSION", DEFAULT_API_VERSION), extracted_at=extracted_at)
                        if conn:
                            inserted, updated = await _insert_rows(conn, args.table, rows)
                            print(f"  [ig_user] inserted {inserted}, refreshed {updated}")
                            # Only a REAL write earns "done" -- a --no-insert dry run must
                            # never advance this, or a later real run would silently skip
                            # ever inserting the profile row (confirmed live: it did, before
                            # this fix -- see chat history).
                            acc_ckpt["profile_fetched"] = True
                            if use_checkpoint_file:
                                _save_checkpoint(checkpoint)
                        else:
                            print("  [ig_user] fetched (not inserted)")
                        if on_progress:
                            on_progress({"account": account.key, "edge": "ig_user", "status": "succeeded"})
                # Empty when oldest is None (no direct posts) -- the loop body needs a
                # real start date to window from, everything else below it doesn't.
                media_edges = [("media", "ig_media", IG_MEDIA_FIELDS, "media_completed_until")] if oldest is not None else []
                for edge, object_type, field_list, ckpt_key in media_edges:
                    # --refresh-existing re-walks from the very start every time (upserting refreshes
                    # engagement counts on already-fetched posts) instead of resuming past them.
                    window_start_iso = None if args.refresh_existing else acc_ckpt.get(ckpt_key)
                    window_start = datetime.fromisoformat(window_start_iso) if window_start_iso else oldest
                    now = datetime.now(timezone.utc)
                    windows_done = 0

                    while window_start < now:
                        if args.max_windows is not None and windows_done >= args.max_windows:
                            print(f"  [{edge}] reached --max-windows={args.max_windows}, stopping for this run")
                            break

                        window_end = min(window_start + timedelta(days=args.window_days), now)
                        result = await _fetch_window(client, base_url, access_token, account, edge, field_list, window_start, window_end)

                        if result.error:
                            any_error = True
                            _log_error(account, object_type, result.error)
                            print(f"  [{edge}] {window_start.date()} -> {window_end.date()}  FAILED: {result.error[:120]}")
                            if on_progress:
                                on_progress({"account": account.key, "edge": edge, "status": "failed", "error": result.error})
                            break  # stop this edge for this account -- checkpoint not advanced, safe to resume

                        total_items += len(result.items)
                        if args.include_insights and edge == "media":
                            await _enrich_with_insights(client, base_url, access_token, result.items)
                        rows = _build_rows(result, batch_id=uuid.uuid4(), api_version=os.environ.get("META_API_VERSION", DEFAULT_API_VERSION), extracted_at=extracted_at)
                        progress = _progress_bar(window_end, oldest, now)
                        if conn:
                            inserted, updated = await _insert_rows(conn, args.table, rows)
                            total_inserted += inserted + updated
                            print(
                                f"  [{edge}] {progress}  {window_start.date()} -> {window_end.date()}  "
                                f"{len(result.items)} item(s), inserted {inserted}, refreshed {updated}  "
                                f"(calls so far: {counter.count}, items so far: {total_items})"
                            )
                            # Persisted checkpoint only advances on a REAL write -- a
                            # --no-insert dry run must never mark a window "done", or a
                            # later real run would silently skip ever inserting it (confirmed
                            # live: it did, before this fix -- see chat history).
                            acc_ckpt[ckpt_key] = window_end.isoformat()
                            if use_checkpoint_file:
                                _save_checkpoint(checkpoint)
                        else:
                            print(
                                f"  [{edge}] {progress}  {window_start.date()} -> {window_end.date()}  "
                                f"{len(result.items)} item(s) (not inserted)  "
                                f"(calls so far: {counter.count}, items so far: {total_items})"
                            )

                        if on_progress:
                            on_progress({
                                "account": account.key, "edge": edge, "status": "succeeded",
                                "items_so_far": total_items, "inserted_so_far": total_inserted,
                                "calls_so_far": counter.count,
                            })

                        window_start = window_end
                        windows_done += 1

                        if window_start < now:
                            await asyncio.sleep(INTER_WINDOW_DELAY_SECONDS)

                # collaborative_media: confirmed live 2026-08-11 that since/until is silently
                # IGNORED on this specific edge (unlike /media, where it's genuinely honored) --
                # every "windowed" call just returned this account's full list unfiltered, so 14
                # windowed fetches inserted the same 78 posts 14 times (1092 rows, 78 distinct
                # source_ids -- confirmed via a direct COUNT DISTINCT). Switched to a single full
                # fetch per account instead, exactly like collaboration_invites below, with a
                # boolean "done" checkpoint rather than a date-windowed one.
                #
                # Trimmed field list + smaller page size, not the full IG_MEDIA_FIELDS @ 25 --
                # confirmed live 2026-08-11 (account 3, which had failed on every prior attempt)
                # that the complexity throttle here is field-count x page-size, not call volume:
                # the full 26-field list failed at every page size tried; id + our 12 needed
                # fields succeeds reliably at limit=15. Fields we don't actually use (alt_text,
                # is_ai_generated, legacy_instagram_media_id, boost_eligibility_info/
                # boost_ads_list -- the latter two confirmed always null for content we don't
                # own anyway) are dropped rather than fetched and discarded.
                if not acc_ckpt.get("collaborative_media_fetched") or args.refresh_existing:
                    collab_result = await _fetch_full_edge(
                        client, base_url, access_token, account, "collaborative_media", "ig_collaborative_media",
                        {"fields": f"id,{ENGAGEMENT_FIELDS}", "limit": COLLABORATIVE_MEDIA_PAGE_SIZE},
                        inter_page_delay_seconds=INTER_PAGE_DELAY_SECONDS,
                    )
                    if collab_result.error:
                        any_error = True
                        _log_error(account, "ig_collaborative_media", collab_result.error)
                        print(f"  [collaborative_media] FAILED: {collab_result.error[:120]}")
                        if on_progress:
                            on_progress({"account": account.key, "edge": "collaborative_media", "status": "failed", "error": collab_result.error})
                    else:
                        total_items += len(collab_result.items)
                        rows = _build_rows(collab_result, batch_id=uuid.uuid4(), api_version=os.environ.get("META_API_VERSION", DEFAULT_API_VERSION), extracted_at=extracted_at)
                        if conn:
                            inserted, updated = await _insert_rows(conn, args.table, rows)
                            total_inserted += inserted + updated
                            print(f"  [collaborative_media] {len(collab_result.items)} item(s), inserted {inserted}, refreshed {updated}")
                            acc_ckpt["collaborative_media_fetched"] = True
                            if use_checkpoint_file:
                                _save_checkpoint(checkpoint)
                        else:
                            print(f"  [collaborative_media] {len(collab_result.items)} item(s) (not inserted)")

                        if on_progress:
                            on_progress({
                                "account": account.key, "edge": "collaborative_media", "status": "succeeded",
                                "items_so_far": total_items, "inserted_so_far": total_inserted,
                                "calls_so_far": counter.count,
                            })

                # collaboration_invites: no timestamp field, fetched in full every run (matches
                # ingest_instagram.py). Enriched with ENGAGEMENT_FIELDS per item (confirmed live
                # 2026-08-11: likes/comments/saves/shares/views ARE available even for content we
                # don't own, unlike /insights -- see ENGAGEMENT_FIELDS comment above). Written with
                # replace-snapshot semantics (_replace_snapshot), not plain append -- this edge has
                # no checkpoint/windowing to make append-safe, so a plain INSERT would duplicate the
                # same items on every run.
                invites_result = await _fetch_full_edge(client, base_url, access_token, account, "collaboration_invites", "ig_collaboration_invites", {})
                if invites_result.error:
                    any_error = True
                    _log_error(account, "ig_collaboration_invites", invites_result.error)
                    print(f"  [collaboration_invites] FAILED: {invites_result.error[:120]}")
                    if on_progress:
                        on_progress({"account": account.key, "edge": "collaboration_invites", "status": "failed", "error": invites_result.error})
                else:
                    await _enrich_with_engagement_fields(client, base_url, access_token, invites_result.items)
                    total_items += len(invites_result.items)
                    rows = _build_rows(invites_result, batch_id=uuid.uuid4(), api_version=os.environ.get("META_API_VERSION", DEFAULT_API_VERSION), extracted_at=extracted_at)
                    if conn:
                        deleted = await _replace_snapshot(conn, args.table, "ig_collaboration_invites", account.key)
                        inserted, updated = await _insert_rows(conn, args.table, rows)
                        total_inserted += inserted + updated
                        print(f"  [collaboration_invites] {len(invites_result.items)} item(s), replaced {deleted} -> inserted {inserted}")
                    else:
                        print(f"  [collaboration_invites] {len(invites_result.items)} item(s) (not inserted)")

                    if on_progress:
                        on_progress({
                            "account": account.key, "edge": "collaboration_invites", "status": "succeeded",
                            "items_so_far": total_items, "inserted_so_far": total_inserted,
                            "calls_so_far": counter.count,
                        })

                print(
                    f"  --- account {account.key} totals: "
                    f"{counter.count - calls_before_account} call(s), "
                    f"{total_items - items_before_account} item(s) ---"
                )
    finally:
        if conn:
            await conn.close()

    wall_time = time.monotonic() - run_start
    print(
        f"\n=== Run totals: {counter.count} call(s), {total_items} item(s) fetched, "
        f"{total_inserted} row(s) inserted, {wall_time:.1f}s wall time ==="
    )

    return 1 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
