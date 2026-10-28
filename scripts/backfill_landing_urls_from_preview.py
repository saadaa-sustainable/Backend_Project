"""Destination URLs for the ads the creative fields cannot answer.

WHY THIS EXISTS

scripts/backfill_ad_landing_urls.py reads the destination off the creative
-- object_story_spec, asset_feed_spec, link_url and friends. For 6,150 ads
none of those fields exist: they are boosted organic posts, where the ad
carries only an `effective_object_story_id` pointing at a Page post that
holds the destination. Reading that post needs `pages_read_engagement`,
which this token does not have (code 10), and I recorded that as a hard
ceiling.

It is not. The ad PREVIEW renders the destination, and the preview is
readable with the token we already hold. Measured on 30 random
boosted-post ads with no creative URL: 26 recovered, a 87% hit rate.

THREE THINGS THE OBVIOUS VERSION GETS WRONG

1. ad_format decides whether this works at all. MOBILE_FEED_STANDARD,
   MOBILE_FEED_BASIC and INSTAGRAM_STANDARD all RENDER the ad -- the copy
   is visibly there -- and emit ZERO anchors. Only DESKTOP_FEED_STANDARD
   produces them. Testing with a mobile format returns nothing and looks
   exactly like "this ad has no destination".
2. The preview is drawn by JavaScript. The served HTML is ~264 KB with no
   <a> tags at all, so requests + BeautifulSoup can never see the link;
   it needs a real browser.
3. The destination is wrapped in l.facebook.com/l.php?u=<encoded>, so the
   natural filter -- skip anything on facebook.com -- discards the one
   link wanted. The wrapped value is double-encoded: %257B%257B is {{
   after two passes.

Output: Bronze rows with object_type='adcreative', the same shape
scripts/backfill_ad_landing_urls.py writes, so scripts/refresh_ad_media.py
picks them up with no change. landing_page_source is 'ad_preview' to keep
them distinguishable from a creative-field read, which is the more
authoritative source where both exist.

Usage:
    .venv/bin/python scripts/backfill_landing_urls_from_preview.py
    .venv/bin/python scripts/backfill_landing_urls_from_preview.py --limit 50 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import pathlib
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from scripts.dbq import connect  # noqa: E402  -- owns the DSN; see CLAUDE.md
from scripts.ingest_last_15_days import (  # noqa: E402
    RATE_LIMIT_ERROR_CODES,
    _usage_estimated_wait_seconds,
)

#: The ONE format that yields anchors. See the module docstring.
AD_FORMAT = "DESKTOP_FEED_STANDARD"
OBJECT_TYPE = "adcreative"
SOURCE = "ad_preview"
#: (cputime%, total_time%) from the most recent 200, for pace().
LAST_USAGE: list[int] = [0, 0]

CONCURRENCY = 6       # browser pages, not Graph calls; 4 measured 2.8s/ad
CHUNK = 250           # ads fetched and WRITTEN before the next chunk starts
WRITE_CHUNK = 200           # the Supabase pooler drops long single statements
#: Retries per chunk, each on a fresh connection. See write_rows.
WRITE_ATTEMPTS = 5
NAV_TIMEOUT = 60_000
SETTLE_MS = 3000      # the anchors appear after the frame settles
#: Hard ceiling per ad, Graph call + render. See `guarded`.
AD_DEADLINE = 75.0
RATE_LIMIT_BASE = 60.0
RATE_LIMIT_MAX = 900.0
MAX_ATTEMPTS = 6


class Throttle:
    """One shared gate: a rate limit parks every worker, not just one.

    Reopening the gate belongs to the Throttle, never to whichever
    worker happened to see the 429. That worker is running inside
    `asyncio.wait_for(..., AD_DEADLINE)`, and a park is capped at
    RATE_LIMIT_MAX = 900s -- so for any park longer than the 75s
    deadline it is CERTAIN to be cancelled before it can re-set the
    gate. The gate then stays shut with nobody left to open it and
    every other worker blocked in before_request(): a permanent
    deadlock, not a slow run.

    Observed exactly once in the wild, 2026-10-27: one `throttled`
    line, no `resumed`, then 29 minutes of 0% CPU, zero established
    sockets and no browser process. A dedicated releaser task cannot be
    cancelled by any ad's deadline, so the gate always reopens.
    """

    def __init__(self) -> None:
        self._gate = asyncio.Event()
        self._gate.set()
        self._resume_at = 0.0
        self._lock = asyncio.Lock()
        self._releaser: asyncio.Task[None] | None = None
        self.pauses = 0

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
                print(f"\n    throttled: {reason} -- parking {seconds:.0f}s", flush=True)
            if self._releaser is None or self._releaser.done():
                self._releaser = asyncio.create_task(self._release())
        await self._gate.wait()

    async def _release(self) -> None:
        """Reopen the gate once the park has elapsed. Owned by the
        Throttle, so no worker's deadline can take it down."""
        while (remaining := self._resume_at - time.monotonic()) > 0:
            await asyncio.sleep(min(remaining, 5.0))
        async with self._lock:
            if not self._gate.is_set():
                self._gate.set()
                print("    resumed", flush=True)

    async def aclose(self) -> None:
        """Stop the releaser, so a finished run leaves no pending task."""
        task, self._releaser = self._releaser, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._gate.set()


def destination(hrefs: list[str]) -> str | None:
    """The first real destination among a preview's anchors.

    l.php first: that is where the link actually is, and a filter that
    skips facebook.com throws it away. Double unquote because the wrapped
    value is encoded twice.
    """
    for href in hrefs:
        if "l.facebook.com/l.php" in href or "/l.php?" in href:
            u = parse_qs(urlsplit(href).query).get("u", [None])[0]
            if u:
                return unquote(unquote(u))
    for href in hrefs:
        host = urlsplit(href).netloc
        if host and "facebook.com" not in host and "instagram.com" not in host:
            return unquote(unquote(href))
    return None



# ----------------------------------------------------------------------
# Silver write, and pacing driven by Meta's own usage header
# ----------------------------------------------------------------------

#: ad_media is a TRUNCATE+INSERT rebuild table and the nightly runs
#: scripts/refresh_ad_media.py, so a URL written ONLY here is erased at
#: 01:30 UTC. Every row therefore goes to Bronze first (durable, and what
#: the rebuild reads) and is mirrored here second, so the dashboard shows
#: it now instead of after the next rebuild. The two cannot drift: a
#: rebuild reproduces exactly these values from the Bronze rows.
_UPDATE_SILVER = """
UPDATE public.ad_media AS m
   SET landing_page_url    = v.url,
       landing_page_source = v.src,
       refreshed_at        = now()
  FROM (VALUES %s) AS v(ad_id, url, src)
 WHERE m.ad_id = v.ad_id
   AND m.landing_page_url IS NULL
"""


#: ad_media.landing_page_url carries a plain btree index
#: (ix_ad_media_landing), and a btree tuple cannot exceed 2704 bytes.
#: One real destination breaks that: a Click-to-WhatsApp link with a JWT
#: in its query string, 6,622 characters long. It is valid data, not
#: corruption -- and it aborted an entire 9,493-ad run at chunk 1 with
#: ProgramLimitExceeded, losing the whole batch's mirror.
#:
#: Bronze has no such index and keeps the full URL, so nothing is lost by
#: holding the oversized ones out of Silver. The proper fix is to index a
#: hash or a prefix instead of the raw column; until that lands, this
#: keeps the run alive and reports what it skipped.
MAX_INDEXABLE_URL = 2000


def update_ad_media(found: list[tuple[str, str, str]]) -> tuple[int, int]:
    """Mirror freshly found URLs into Silver.

    Returns (updated, skipped). Never overwrites an existing URL --
    Bronze stays the authority and a creative-field read outranks a
    later preview guess.
    """
    if not found:
        return 0, 0
    import psycopg2
    import psycopg2.extras

    usable, skipped = [], 0
    for ad_id, url, src in found:
        if url is not None and len(url) > MAX_INDEXABLE_URL:
            skipped += 1
            continue
        usable.append((ad_id, url, src))
    if skipped:
        print(f"\n      {skipped} URL(s) over {MAX_INDEXABLE_URL} chars held out of "
              f"ad_media (btree index limit); they are in Bronze", flush=True)
    if not usable:
        return 0, skipped

    updated = 0
    for i in range(0, len(usable), WRITE_CHUNK):
        batch = usable[i:i + WRITE_CHUNK]
        for attempt in range(1, WRITE_ATTEMPTS + 1):
            try:
                with connect(autocommit=False, statement_timeout="300s") as conn:
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(cur, _UPDATE_SILVER, batch)
                        updated += cur.rowcount
                    conn.commit()
                break
            except (SystemExit, psycopg2.Error):
                if attempt == WRITE_ATTEMPTS:
                    raise
                time.sleep(min(2.0 ** attempt, 30.0))
    return updated, skipped


def usage_pct(headers) -> tuple[int, int]:
    """(cputime%, total_time%) for this ad account, from Meta's header.

    The limit that actually bites is NOT call_count. Measured live while
    throttled: call_count 1%, total_cputime 129%, total_time 98%, with
    ads_api_access_tier=development_access. Pacing on request count would
    therefore have paced on the wrong number entirely.
    """
    raw = headers.get("x-business-use-case-usage")
    if not raw:
        return 0, 0
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return 0, 0
    cpu = total = 0
    for entries in parsed.values():
        for e in entries if isinstance(entries, list) else [entries]:
            if isinstance(e, dict):
                cpu = max(cpu, int(e.get("total_cputime") or 0))
                total = max(total, int(e.get("total_time") or 0))
    return cpu, total


async def pace(cpu: int, total: int, lo: float, hi: float) -> None:
    """Idle between batches so the budget refills instead of being raced.

    The budget recovers on Meta's clock. Spending it as fast as it arrives
    is what produces a run that is throttled more than it works, so this
    deliberately gives time back, and gives more of it as usage climbs.
    """
    import random
    wait = random.uniform(lo, hi)
    worst = max(cpu, total)
    if worst >= 90:
        wait *= 4
    elif worst >= 75:
        wait *= 2.5
    elif worst >= 50:
        wait *= 1.5
    print(f"      pacing {wait:.0f}s   (cpu {cpu}%, time {total}%)", flush=True)
    await asyncio.sleep(wait)


_WORK_SQL = """
-- Only ads the creative route could not answer, and not already done here.
-- ad_media is one row per ad and carries the creative id we need for meta_id.
-- An ad that was ATTEMPTED is done, not merely one that succeeded.
--
-- A miss writes a row with a null URL, and keying resumability on
-- success alone meant every past failure sat at the head of the queue
-- and was re-rendered on every run. Measured: a random draw of untried
-- ads returns 58 to 70 in every hundred, while repeat runs over the
-- already-failed head returned 47, then 32, then 0. The browser time
-- was being spent almost entirely on ads already known to render no
-- anchor. --retry-missed forces a re-render when that is wanted.
WITH already AS (
    SELECT DISTINCT parent_ids->>'ad_id' AS ad_id
    FROM raw_dump_meta
    WHERE object_type = %(object_type)s
      AND (%(retry_missed)s IS FALSE
           OR raw_payload->>'landing_page_source' = %(source)s)
      AND raw_payload->>'ad_format' = %(fmt)s
)
SELECT m.ad_id, m.creative_id, l.account_id, l.account_name
FROM public.ad_media m
LEFT JOIN public.ad_lifecycle l ON l.ad_id = m.ad_id
LEFT JOIN already a ON a.ad_id = m.ad_id
WHERE m.landing_page_url IS NULL
  AND a.ad_id IS NULL
  AND (%(active_only)s IS FALSE OR l.ad_effective_status = 'ACTIVE')
-- Newest first, ACTIVE ahead of the rest.
--
-- Ordering decides the yield of a PARTIAL run, and these runs get
-- interrupted. Measured on the same population: a random draw returns
-- 58 to 70 in every hundred, while the head of the old order (ACTIVE,
-- then ad_id ASCENDING = oldest) returned 47, then 32, then 0 across
-- three batches. Old ads render a preview with no anchor in it, so the
-- cheapest change available -- the sort -- beats any amount of tuning.
--
-- No per-cent signs in this comment: psycopg2 reads one as a parameter
-- placeholder and the whole query dies with "argument formats can't be
-- mixed".
ORDER BY (l.ad_effective_status = 'ACTIVE') DESC NULLS LAST, m.ad_id DESC
"""


def load_work(*, active_only: bool, limit: int | None,
              retry_missed: bool = False) -> list[dict]:
    with connect(statement_timeout="300s") as conn, conn.cursor() as cur:
        cur.execute(_WORK_SQL, {"object_type": OBJECT_TYPE, "source": SOURCE,
                                "active_only": active_only, "fmt": AD_FORMAT,
                                "retry_missed": retry_missed})
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows[:limit] if limit else rows


async def preview_src(client: httpx.AsyncClient, throttle: Throttle,
                      token: str, base: str, ad_id: str) -> str | None:
    """The preview iframe's URL, backing off on a Graph rate limit."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        await throttle.before_request()
        try:
            r = await client.get(f"{base}/{ad_id}/previews",
                                 params={"access_token": token, "ad_format": AD_FORMAT})
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt >= MAX_ATTEMPTS:
                return None
            await asyncio.sleep(min(2.0 ** attempt, 60.0))
            continue
        if r.status_code == 200:
            LAST_USAGE[:] = usage_pct(r.headers)
            data = r.json().get("data") or []
            if not data:
                return None
            tag = BeautifulSoup(data[0]["body"], "html.parser").find("iframe")
            return tag["src"] if tag and tag.has_attr("src") else None
        try:
            code = (r.json().get("error") or {}).get("code")
        except ValueError:
            code = None
        if (code in RATE_LIMIT_ERROR_CODES or r.status_code in {429, 500, 502, 503, 504}) \
           and attempt < MAX_ATTEMPTS:
            wait = (_usage_estimated_wait_seconds(r.headers)
                    or min(RATE_LIMIT_BASE * 2 ** (attempt - 1), RATE_LIMIT_MAX))
            await throttle.pause(wait, f"code={code} status={r.status_code}")
            continue
        return None
    return None


_COLUMNS = ["id", "meta_id", "raw_payload", "api_endpoint", "api_version", "batch_id",
            "request_params", "extracted_at", "sync_type", "payload_hash",
            "processing_status", "object_type", "parent_ids", "is_nested"]


def build_row(item: dict, url: str | None, *, batch_id: uuid.UUID,
              api_version: str, extracted_at: datetime) -> dict[str, Any]:
    payload = {"id": item["creative_id"],
               "landing_page_url": url,
               "landing_page_source": SOURCE if url else None,
               "ad_format": AD_FORMAT}
    return {
        "id": str(uuid.uuid4()),
        "meta_id": item["creative_id"],
        "raw_payload": json.dumps(payload),
        "api_endpoint": "previews",
        "api_version": api_version,
        "batch_id": str(batch_id),
        "request_params": json.dumps({"ad_format": AD_FORMAT, "render": "chromium"}),
        "extracted_at": extracted_at,
        "sync_type": "backfill",
        "payload_hash": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "processing_status": "pending",
        "object_type": OBJECT_TYPE,
        "parent_ids": json.dumps({"account_name": item["account_name"],
                                  "account_id": item["account_id"],
                                  "ad_id": item["ad_id"],
                                  "creative_id": item["creative_id"]}),
        "is_nested": False,
    }


def write_rows(rows: list[dict[str, Any]]) -> int:
    """Write in chunks, each on its own connection, each retried.

    The Supabase pooler drops a connection mid-operation often enough that
    a single unretried write loses real work: one run fetched 499
    creatives -- paying the ads_management CPU budget for them -- and threw
    every one away when the pooler closed the socket at commit time, with
    no retry and no way to recover them except re-fetching.

    A fresh connection per chunk means a drop costs one chunk's attempt,
    not the run. dbq.connect raises SystemExit (a BaseException, so a bare
    `except Exception` does NOT catch it), which is why it is named here.
    """
    import psycopg2
    import psycopg2.extras
    sql = f"INSERT INTO raw_dump_meta ({', '.join(_COLUMNS)}) VALUES %s"
    written = 0
    for i in range(0, len(rows), WRITE_CHUNK):
        chunk = rows[i:i + WRITE_CHUNK]
        values = [tuple(r[c] for c in _COLUMNS) for r in chunk]
        for attempt in range(1, WRITE_ATTEMPTS + 1):
            try:
                with connect(autocommit=False, statement_timeout="300s") as conn:
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(cur, sql, values)
                    conn.commit()
                break
            except (SystemExit, psycopg2.Error) as exc:
                if attempt == WRITE_ATTEMPTS:
                    raise
                wait = min(2.0 ** attempt, 30.0)
                print(f"\n    write retry {attempt}/{WRITE_ATTEMPTS - 1} in {wait:.0f}s "
                      f"({type(exc).__name__})", flush=True)
                time.sleep(wait)
        written += len(chunk)
    return written

async def run(work: list[dict], *, token: str, api_version: str,
              dry_run: bool, chunk_size: int, concurrency: int = CONCURRENCY,
              pace_lo: float = 2.0, pace_hi: float = 5.0) -> None:
    base = f"https://graph.facebook.com/{api_version}"
    throttle = Throttle()
    batch_id = uuid.uuid4()
    totals = {"ads": 0, "found": 0, "no_anchor": 0, "no_preview": 0, "written": 0}
    chunks = [work[i:i + chunk_size] for i in range(0, len(work), chunk_size)]

    async with httpx.AsyncClient(timeout=60.0) as client, async_playwright() as pw:
        browser = None
        sem = asyncio.Semaphore(concurrency)
        for index, chunk in enumerate(chunks, start=1):
            # One browser per chunk. A single long-lived browser means one
            # wedged renderer stalls every remaining chunk; relaunching
            # costs about a second and bounds the damage to one chunk.
            if browser is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(browser.close(), 15)
            browser = await pw.chromium.launch()
            print(f"  chunk {index}/{len(chunks)}: {len(chunk)} ads")
            results: list[tuple[dict, str | None, str]] = []

            async def one(item: dict) -> None:
                # The deadline starts AFTER the semaphore is acquired, not
                # when the task is created. asyncio.wait_for around the
                # whole coroutine counted queueing time too: with 250 tasks
                # started at once and 6 slots, everything past the first
                # couple of hundred expired before issuing a single
                # request. Measured: 8,190 of 9,203 ads recorded as
                # "timeout" in a run lasting 3,134s -- real 75s timeouts
                # would have needed 102,375s. They were never attempted.
                async with sem:
                    # Wait out any park BEFORE the deadline starts. A
                    # park can be 900s and the deadline is 75s, so an ad
                    # that merely queued behind a rate limit would be
                    # recorded as a timeout it never deserved.
                    await throttle.before_request()
                    await asyncio.wait_for(_one_inner(item), AD_DEADLINE)

            async def _one_inner(item: dict) -> None:
                if True:
                    src = await preview_src(client, throttle, token, base, item["ad_id"])
                    if not src:
                        results.append((item, None, "no_preview"))
                    else:
                        page = await browser.new_page()
                        try:
                            await page.goto(src, wait_until="networkidle", timeout=NAV_TIMEOUT)
                            await page.wait_for_timeout(SETTLE_MS)
                            hrefs = await page.eval_on_selector_all(
                                "a[href]", "els => els.map(e => e.href)")
                        except Exception:
                            hrefs = []
                        finally:
                            # close() must not be able to hang the run.
                            # On a wedged browser it blocks forever, and
                            # because this is a finally during
                            # cancellation, the enclosing wait_for cannot
                            # interrupt it. Measured: 0.4% CPU, all
                            # Chromium processes idle, ZERO established
                            # sockets -- nothing in flight, deadlocked.
                            with contextlib.suppress(Exception):
                                await asyncio.wait_for(page.close(), 10)
                        url = destination(hrefs)
                        results.append((item, url, "found" if url else "no_anchor"))
                    print(f"      {len(results)}/{len(chunk)}", end="\r", flush=True)

            # A hard per-ad deadline. page.goto(wait_until="networkidle")
            # can sit for its full timeout on a preview that never goes
            # idle, and one run spent NINE HOURS inside a single chunk of
            # 250 after a throttle cleared -- the gate had reopened, the
            # renders had not. Nothing here is worth more than AD_DEADLINE
            # seconds, and an ad that exceeds it is recorded as a miss and
            # retried by a later run rather than blocking the chunk.
            async def guarded(item: dict) -> None:
                try:
                    await one(item)
                except asyncio.TimeoutError:
                    results.append((item, None, "timeout"))

            t_chunk = time.monotonic()
            await asyncio.gather(*(guarded(i) for i in chunk))
            print(f"      chunk fetched in {time.monotonic() - t_chunk:.0f}s"
                  + " " * 20, flush=True)

            extracted_at = datetime.now(timezone.utc)
            # A timeout means NOT ATTEMPTED, not "attempted and found
            # nothing". Writing one marks the ad done and the resume query
            # never looks at it again -- which is how 8,876 ads were
            # retired without ever being fetched.
            rows = [build_row(i, u, batch_id=batch_id, api_version=api_version,
                              extracted_at=extracted_at)
                    for i, u, o in results if o != "timeout"]
            for _i, _u, outcome in results:
                totals[outcome] = totals.get(outcome, 0) + 1
            totals["ads"] += len(chunk)
            hit = 100.0 * totals["found"] / max(totals["ads"], 1)
            found = [(i["ad_id"], u, SOURCE) for i, u, _o in results if u]
            if dry_run:
                print(f"      --dry-run: {len(rows)} rows built   hit {hit:.0f}%")
            else:
                totals["written"] += write_rows(rows)
                mirrored, skipped_long = update_ad_media(found)
                totals["mirrored"] = totals.get("mirrored", 0) + mirrored
                totals["skipped_long"] = totals.get("skipped_long", 0) + skipped_long
                print(f"      wrote {len(rows)} rows ({totals['written']:,} total), "
                      f"{mirrored} into ad_media   hit {hit:.0f}%")
            if index < len(chunks):
                await pace(*LAST_USAGE, pace_lo, pace_hi)
        if browser is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(browser.close(), 15)

    print(f"\n  ads processed : {totals['ads']:,}")
    print(f"  URL found     : {totals['found']:,} "
          f"({100.0 * totals['found'] / max(totals['ads'], 1):.1f}%)")
    print(f"  no anchor     : {totals['no_anchor']:,}")
    print(f"  no preview    : {totals['no_preview']:,}")
    print(f"  timed out     : {totals.get('timeout', 0):,}")
    print(f"  rows written  : {totals['written']:,}")
    print(f"  into ad_media : {totals.get('mirrored', 0):,}")
    print(f"  throttle pauses: {throttle.pauses}")
    await throttle.aclose()


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--active-only", action="store_true",
                    help="Only ACTIVE ads. They are ordered first regardless.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--chunk", type=int, default=CHUNK)
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY,
                    help="Parallel browser pages. Measured: too many and frames "
                         "do not finish rendering, which looks exactly like an ad "
                         "with no destination.")
    ap.add_argument("--retry-missed", action="store_true",
                    help="Re-render ads a previous run already tried and found "
                         "no anchor for. Off by default -- those renders are the "
                         "most expensive thing here and the least likely to pay.")
    ap.add_argument("--pace", default="2,5",
                    help="Seconds to idle between chunks, as lo,hi. Short by "
                         "default: /previews is cheap on the ads_management CPU "
                         "budget, and the expensive part -- rendering -- happens "
                         "here, not at Meta. Raised automatically as usage climbs.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 1
    api_version = os.environ.get("META_API_VERSION", "v21.0")

    print("Loading work list ...")
    work = load_work(active_only=args.active_only, limit=args.limit,
                     retry_missed=args.retry_missed)
    if not work:
        print("Nothing to do.")
        return 0
    print(f"  {len(work):,} ads with no landing page, ACTIVE first")
    print(f"  format: {AD_FORMAT}   concurrency: {args.concurrency}   chunk: {args.chunk}")
    print("Token: [redacted]\n")

    started = time.monotonic()
    asyncio.run(run(work, token=token, api_version=api_version,
                    dry_run=args.dry_run, chunk_size=max(1, args.chunk),
                    concurrency=max(1, args.concurrency),
                    pace_lo=float(args.pace.split(",")[0]),
                    pace_hi=float(args.pace.split(",")[1])))
    print(f"\nDone in {time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
