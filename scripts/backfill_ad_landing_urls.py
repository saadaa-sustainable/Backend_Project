"""backfill_ad_landing_urls.py -- the landing-page URL for every Meta ad.

WHY THIS IS ITS OWN SCRIPT, and not two more fields on the /ads roster:

`object_story_spec` and `asset_feed_spec` cannot be requested on a bulk
/ads (or /adcreatives) page. Meta cross-validates the two for any
Degrees-of-Freedom ad and rejects the ENTIRE page when they disagree --
code 100 / subcode 2446211, "For a Degrees of freedom enabled ad, the
first value of Asset Feed Spec field should match the corresponding field
in Object Story Spec." Confirmed live: account 1 holds one such ad, and
asking for object_story_spec in any form (even narrowed to
object_story_spec{link_data{link}}) fails at roster page 8 and takes all
23,735 ads down with it. /adcreatives fails identically at page 9.

So this script reads creatives through the batched `GET /?ids=` form, 50
at a time, and BISECTS a failing batch down to singles. One poisoned ad
costs that one ad, not the account.

Two passes are needed for the same reason: pass A asks for
object_story_spec, pass B asks for asset_feed_spec, and they are never in
the same request.

Where the URL actually lives, measured over 362 readable creatives on
account 1:

    108 (29.8%)  object_story_spec.link_data.link
     96 (26.5%)  asset_feed_spec.link_urls[0].website_url
     73 (20.2%)  object_story_spec.video_data.call_to_action.value.link
     85 (23.5%)  nothing readable -- see below

The 20.2% from video_data is the reason this matters beyond staleness:
app/services/gold/landing_page.py never looked there, so those ads could
never have had a landing page even with a perfectly fresh feed.

The last 23.5% are boosted organic posts: no object_story_spec of their
own, just an `effective_object_story_id` pointing at the Page post that
holds the destination. Reading it needs `pages_read_engagement` or Page
Public Content Access, which this token does not have (code 10). They are
recorded with their story id and instagram_permalink_url so the gap is
visible and closes by itself the day that permission is granted.

WORK LIST AND RESUMABILITY

The ad -> creative mapping comes from Bronze, not from a fresh /ads
roster: we already know which ads are missing a URL, and re-walking the
roster would spend the account's rate-limit budget re-learning it. By
default only ads with no landing page in ad_media are fetched; --all does
every ad.

Already-backfilled ads are skipped, so an interrupted run resumes by just
being re-run. Rows are written after every --chunk ads rather than once at
the end, so a throttle or a dropped pooler connection keeps everything
already fetched.

RATE LIMITING

Meta signals an exhausted ad-account budget as HTTP 400 with code 80004
("There have been too many calls to this ad-account"), not as 429 --
status_code alone misses it. On any such code every in-flight worker is
parked behind one shared gate for as long as Meta's own
X-Business-Use-Case-Usage header says it needs
(estimated_time_to_regain_access), falling back to exponential backoff.
Pausing globally matters: letting the other five workers keep firing
during one worker's backoff is what re-triggers the limit.

Output: append-only Bronze rows, object_type='adcreative', meta_id = the
creative id, parent_ids.ad_id = the ad it belongs to, raw_payload = the
merged creative. Nothing existing is updated or deleted, and the /ads
roster payload is left completely alone -- it still feeds meta_ads.

Usage:
    .venv/bin/python scripts/backfill_ad_landing_urls.py              # ads missing a URL
    .venv/bin/python scripts/backfill_ad_landing_urls.py --all        # every ad
    .venv/bin/python scripts/backfill_ad_landing_urls.py --account 1
    .venv/bin/python scripts/backfill_ad_landing_urls.py --limit 500 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import pathlib
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from scripts.dbq import connect  # noqa: E402  -- owns the DSN; see CLAUDE.md
from scripts.ingest_last_15_days import (  # noqa: E402
    RATE_LIMIT_ERROR_CODES,
    _usage_estimated_wait_seconds,
)

#: Pass A -- object_story_spec and everything that is safe beside it.
CREATIVE_FIELDS_A = (
    "id,object_story_spec,object_story_id,effective_object_story_id,"
    "link_url,object_url,template_url,url_tags,object_type,"
    "call_to_action_type,instagram_permalink_url,link_destination_display_url"
)
#: Pass B -- asset_feed_spec, alone. Never alongside pass A's fields.
CREATIVE_FIELDS_B = "id,asset_feed_spec"

BATCH = 50                 # Meta's ceiling for the `ids` batch-read form
CONCURRENCY = 4            # shares the app-level budget with the nightly fetch
CHUNK = 2000               # ads fetched and WRITTEN before the next chunk starts
REQUEST_TIMEOUT = 90.0
MAX_ATTEMPTS = 8
RATE_LIMIT_BASE = 60.0     # first throttle pause, doubling
RATE_LIMIT_MAX = 900.0     # 15 min -- Meta's ad-account windows are hourly
WRITE_CHUNK = 200          # the Supabase pooler drops long single statements

#: Written into raw_dump_meta.object_type. Read by
#: scripts/refresh_ad_media.py and app/services/gold/landing_page.py.
OBJECT_TYPE = "adcreative"


# ----------------------------------------------------------------------
# Throttle: one shared gate, so a 429 parks every worker, not just one.
# ----------------------------------------------------------------------


class Throttle:
    def __init__(self) -> None:
        self._gate = asyncio.Event()
        self._gate.set()
        self._resume_at = 0.0
        self._lock = asyncio.Lock()
        self.pauses = 0
        self.paused_seconds = 0.0

    async def before_request(self) -> None:
        await self._gate.wait()

    async def pause(self, seconds: float, reason: str) -> None:
        seconds = max(1.0, min(seconds, RATE_LIMIT_MAX))
        async with self._lock:
            target = time.monotonic() + seconds
            if target > self._resume_at:
                self._resume_at = target
                if self._gate.is_set():
                    self._gate.clear()
                    self.pauses += 1
                    self.paused_seconds += seconds
                    print(f"\n    throttled: {reason} -- parking all workers "
                          f"{seconds:.0f}s", flush=True)
        while True:
            remaining = self._resume_at - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 5.0))
        async with self._lock:
            if time.monotonic() >= self._resume_at and not self._gate.is_set():
                self._gate.set()
                print("    resumed", flush=True)


async def _get(client: httpx.AsyncClient, throttle: Throttle,
               url: str, params: dict) -> httpx.Response | None:
    """GET that backs the whole run off on a rate limit.

    Returns None when the request is not worth retrying any further;
    returns the response (success OR a hard error) otherwise, so the
    caller can bisect on Meta's DOF validation error.
    """
    attempt = 0
    while True:
        attempt += 1
        await throttle.before_request()
        try:
            response = await client.get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt >= MAX_ATTEMPTS:
                print(f"\n    giving up after {attempt} transport errors: "
                      f"{type(exc).__name__}", flush=True)
                return None
            await asyncio.sleep(min(2.0 ** attempt, 60.0))
            continue

        if response.status_code == 200:
            return response

        try:
            error = response.json().get("error", {}) or {}
        except ValueError:
            error = {}
        code = error.get("code")
        throttled = code in RATE_LIMIT_ERROR_CODES or response.status_code in {429, 500, 502, 503, 504}

        if throttled and attempt < MAX_ATTEMPTS:
            wait = (_usage_estimated_wait_seconds(response.headers)
                    or min(RATE_LIMIT_BASE * 2 ** (attempt - 1), RATE_LIMIT_MAX))
            await throttle.pause(wait, f"code={code} status={response.status_code}")
            continue
        # Hard error (e.g. the DOF validation failure) -- let the caller bisect.
        return response


# ----------------------------------------------------------------------
# URL resolution
# ----------------------------------------------------------------------


def landing_url(creative: dict[str, Any]) -> tuple[str | None, str | None]:
    """The destination URL and the field it came from.

    Order matters: the creative's own object_story_spec beats the
    asset-feed variant, because a DOF ad's link_urls[0] is only the FIRST
    of several candidate URLs while object_story_spec carries the one the
    ad actually resolved to.
    """
    story = creative.get("object_story_spec") or {}
    feed = creative.get("asset_feed_spec") or {}
    link_urls = feed.get("link_urls") or []
    ctas = feed.get("call_to_actions") or []
    candidates = (
        ("object_story_spec.link_data.link",
         (story.get("link_data") or {}).get("link")),
        ("object_story_spec.video_data.call_to_action.value.link",
         (((story.get("video_data") or {}).get("call_to_action") or {}).get("value") or {}).get("link")),
        ("object_story_spec.photo_data.url",
         (story.get("photo_data") or {}).get("url")),
        ("object_story_spec.template_data.link",
         (story.get("template_data") or {}).get("link")),
        ("asset_feed_spec.link_urls[0].website_url",
         (link_urls[0] or {}).get("website_url") if link_urls else None),
        ("asset_feed_spec.call_to_actions[0].value.link",
         ((ctas[0] or {}).get("value") or {}).get("link") if ctas else None),
        ("link_url", creative.get("link_url")),
        ("object_url", creative.get("object_url")),
        ("template_url", creative.get("template_url")),
    )
    for source, value in candidates:
        if value:
            return str(value), source
    return None, None


# ----------------------------------------------------------------------
# Work list -- from Bronze, not from a fresh roster walk
# ----------------------------------------------------------------------


_WORK_SQL = """
-- ad_media already holds ad_id -> creative_id for every ad, one row each.
-- Deriving it from Bronze instead means a DISTINCT ON over 1.46M `ad`
-- rows carrying full jsonb payloads -- the first version of this query
-- did exactly that and did not finish inside a 300s statement timeout.
--
-- `already` makes the run resumable: re-running after an interruption
-- picks up where it stopped. It is an index scan, not a seq scan --
-- ix_raw_dump_meta_object_type covers the only predicate.
WITH already AS (
    SELECT DISTINCT parent_ids->>'ad_id' AS ad_id
    FROM raw_dump_meta
    WHERE object_type = %(object_type)s
      AND raw_payload->>'landing_page_url' IS NOT NULL
)
SELECT m.ad_id,
       m.creative_id,
       l.account_id,
       l.account_name
FROM public.ad_media m
LEFT JOIN public.ad_lifecycle l ON l.ad_id = m.ad_id
LEFT JOIN already a ON a.ad_id = m.ad_id
WHERE m.creative_id IS NOT NULL
  AND a.ad_id IS NULL
  AND (%(every)s OR m.landing_page_url IS NULL)
  AND (%(account)s IS NULL OR l.account_id = %(account)s)
  AND (%(statuses)s IS NULL OR l.ad_effective_status = ANY(%(statuses)s::text[]))
ORDER BY m.ad_id
"""


def load_work(*, every: bool, account_id: str | None, limit: int | None,
              statuses: list[str] | None = None) -> list[dict]:
    with connect(statement_timeout="300s") as conn:
        with conn.cursor() as cur:
            cur.execute(_WORK_SQL, {"object_type": OBJECT_TYPE, "every": every,
                                    "account": account_id,
                                    "statuses": statuses})
            columns = [d[0] for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
    return rows[:limit] if limit else rows


# ----------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------


async def _read_ids(client: httpx.AsyncClient, throttle: Throttle, base: str,
                    token: str, ids: list[str], fields: str,
                    out: dict[str, dict], unreadable: set[str]) -> None:
    """Batched ?ids= read that bisects around Meta's DOF validation error."""
    queue: list[list[str]] = [ids]
    while queue:
        chunk = queue.pop()
        response = await _get(client, throttle, f"{base}/", {
            "access_token": token, "ids": ",".join(chunk), "fields": fields,
        })
        if response is None:
            unreadable.update(chunk)
            continue
        if response.status_code == 200:
            for creative_id, creative in response.json().items():
                out.setdefault(creative_id, {}).update(creative)
            continue
        if len(chunk) == 1:
            unreadable.add(chunk[0])
            continue
        mid = len(chunk) // 2
        queue += [chunk[:mid], chunk[mid:]]


async def fetch_creatives(client: httpx.AsyncClient, throttle: Throttle, base: str,
                          token: str, creative_ids: list[str],
                          ) -> tuple[dict[str, dict], set[str]]:
    merged: dict[str, dict] = {}
    unreadable: set[str] = set()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    batches = [creative_ids[i:i + BATCH] for i in range(0, len(creative_ids), BATCH)]
    total = len(batches) * 2
    done = 0

    async def one(chunk: list[str], fields: str) -> None:
        nonlocal done
        async with semaphore:
            await _read_ids(client, throttle, base, token, chunk, fields,
                            merged, unreadable)
            done += 1
            print(f"      batch {done}/{total}  ({len(merged)} creatives)",
                  end="\r", flush=True)

    await asyncio.gather(*(one(c, CREATIVE_FIELDS_A) for c in batches))
    await asyncio.gather(*(one(c, CREATIVE_FIELDS_B) for c in batches))
    print(f"      {len(merged)} creatives read, {len(unreadable)} un-readable"
          + " " * 24)
    return merged, unreadable


# ----------------------------------------------------------------------
# Bronze write
# ----------------------------------------------------------------------


_COLUMNS = ["id", "meta_id", "raw_payload", "api_endpoint", "api_version", "batch_id",
            "request_params", "extracted_at", "sync_type", "payload_hash",
            "processing_status", "object_type", "parent_ids", "is_nested"]


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_rows(work: list[dict], creatives: dict[str, dict], *, batch_id: uuid.UUID,
               api_version: str, extracted_at: datetime) -> list[dict[str, Any]]:
    rows = []
    for item in work:
        creative = creatives.get(item["creative_id"])
        if not creative:
            continue
        url, source = landing_url(creative)
        payload = {**creative, "landing_page_url": url, "landing_page_source": source}
        rows.append({
            "id": str(uuid.uuid4()),
            "meta_id": item["creative_id"],
            "raw_payload": json.dumps(payload),
            "api_endpoint": "adcreatives",
            "api_version": api_version,
            "batch_id": str(batch_id),
            "request_params": json.dumps({"form": "ids-batch",
                                          "pass_a": CREATIVE_FIELDS_A,
                                          "pass_b": CREATIVE_FIELDS_B}),
            "extracted_at": extracted_at,
            "sync_type": "backfill",
            "payload_hash": _hash_payload(payload),
            "processing_status": "pending",
            "object_type": OBJECT_TYPE,
            "parent_ids": json.dumps({
                "account_name": item["account_name"],
                "account_id": item["account_id"],
                "ad_id": item["ad_id"],
                "creative_id": item["creative_id"],
            }),
            "is_nested": False,
        })
    return rows


def write_rows(rows: list[dict[str, Any]]) -> int:
    import psycopg2.extras
    sql = f"INSERT INTO raw_dump_meta ({', '.join(_COLUMNS)}) VALUES %s"
    written = 0
    with connect(autocommit=False, statement_timeout="300s") as conn:
        with conn.cursor() as cur:
            for i in range(0, len(rows), WRITE_CHUNK):
                chunk = rows[i:i + WRITE_CHUNK]
                psycopg2.extras.execute_values(
                    cur, sql, [tuple(r[c] for c in _COLUMNS) for r in chunk])
                conn.commit()
                written += len(chunk)
    return written


# ----------------------------------------------------------------------


async def run(work: list[dict], *, token: str, api_version: str, dry_run: bool,
              chunk_size: int = CHUNK) -> None:
    base = f"https://graph.facebook.com/{api_version}"
    throttle = Throttle()
    batch_id = uuid.uuid4()
    totals = {"ads": 0, "creatives": 0, "unreadable": 0, "with_url": 0, "written": 0}
    by_source: dict[str, int] = {}
    chunks = [work[i:i + chunk_size] for i in range(0, len(work), chunk_size)]

    limits = httpx.Limits(max_connections=CONCURRENCY + 2)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, limits=limits) as client:
        for index, chunk in enumerate(chunks, start=1):
            unique = sorted({item["creative_id"] for item in chunk})
            print(f"  chunk {index}/{len(chunks)}: {len(chunk)} ads, "
                  f"{len(unique)} distinct creatives")
            creatives, unreadable = await fetch_creatives(
                client, throttle, base, token, unique)

            extracted_at = datetime.now(timezone.utc)
            rows = build_rows(chunk, creatives, batch_id=batch_id,
                              api_version=api_version, extracted_at=extracted_at)
            totals["ads"] += len(chunk)
            totals["creatives"] += len(creatives)
            totals["unreadable"] += len(unreadable)
            for creative in creatives.values():
                _url, source = landing_url(creative)
                if source:
                    totals["with_url"] += 1
                    by_source[source] = by_source.get(source, 0) + 1

            if dry_run:
                print(f"      --dry-run: {len(rows)} rows built, not written")
            else:
                totals["written"] += write_rows(rows)
                print(f"      wrote {len(rows)} Bronze rows "
                      f"({totals['written']:,} total)")

    print(f"\n  ads processed      : {totals['ads']:,}")
    print(f"  creatives read     : {totals['creatives']:,}")
    print(f"  un-readable        : {totals['unreadable']:,}")
    if totals["creatives"]:
        pct = 100.0 * totals["with_url"] / totals["creatives"]
        print(f"  creatives with URL : {totals['with_url']:,}  ({pct:.1f}%)")
    for source, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"      {n:7,}  {source}")
    print(f"  Bronze rows written: {totals['written']:,}")
    print(f"  throttle pauses    : {throttle.pauses} "
          f"({throttle.paused_seconds:.0f}s total)")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default=None,
                        help="Restrict to one Meta account_id (digits, no act_ prefix).")
    parser.add_argument("--all", action="store_true", dest="every",
                        help="Every ad, not just those missing a landing page.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after this many ads (for a cheap trial run).")
    parser.add_argument("--chunk", type=int, default=CHUNK,
                        help="Ads fetched and written per chunk "
                             f"(default {CHUNK}).")
    parser.add_argument("--status", default=None,
                        help="Comma-separated ad_effective_status values to "
                             "restrict to, e.g. ACTIVE. Worth using: only 1,060 "
                             "of 23,735 ads are ACTIVE, so an ACTIVE-only pass "
                             "costs ~26 requests and finishes in minutes, while "
                             "the full run is hours of mostly paused and "
                             "archived ads. The run stays resumable either way.")
    parser.add_argument("--active-only", action="store_true",
                        help="Shorthand for --status ACTIVE.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and report coverage, write nothing.")
    args = parser.parse_args()


    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 1
    api_version = os.environ.get("META_API_VERSION", "v21.0")

    statuses = None
    if args.active_only:
        statuses = ["ACTIVE"]
    elif args.status:
        statuses = [x.strip().upper() for x in args.status.split(",") if x.strip()]

    print("Loading work list ...")
    work = load_work(every=args.every,
                     account_id=(args.account or "").removeprefix("act_") or None,
                     limit=args.limit, statuses=statuses)
    if not work:
        print("Nothing to do -- every ad in scope already has a backfilled URL.")
        return 0
    accounts = sorted({(w["account_name"] or w["account_id"] or "?") for w in work})
    print(f"  {len(work):,} ads to fetch across account(s) {', '.join(accounts)}")
    chunk_size = max(1, args.chunk)
    print(f"  mode: {'every ad' if args.every else 'ads with no landing page'}"
          f"   status: {','.join(statuses) if statuses else 'any'}"
          f"   chunk: {chunk_size}   concurrency: {CONCURRENCY}")
    print("Token: [redacted]\n")

    started = time.monotonic()
    asyncio.run(run(work, token=token, api_version=api_version,
                    dry_run=args.dry_run, chunk_size=chunk_size))
    print(f"\nDone in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
