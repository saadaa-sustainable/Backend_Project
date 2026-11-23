"""Fetch specific Meta ads by id into Bronze, for ads the nightly roster missed.

The roster step (ingest_last_15_days.py --roster-only) pages every ad in
every account and keeps timing out, so ads that spent are left with no
`ad` row -- and no ad_media row, thumbnail or landing page. This asks
Graph for just those ids (?ids=..., 50 per call), with the same fields,
retry and Bronze row shape as the roster.

Default work list: ads with spend or a conversion in the last 30 days of
insights_daily_by_ad that have no ad_media row.

--recent (the nightly): every ad whose status matters -- spent in the last
30 days, or not paused/archived in meta_ads -- so statuses stay current
without paging the whole roster, which hits Meta's ads-management rate
limit (error 80004) and never finishes inside the step.

Usage:
    .venv/bin/python scripts/fetch_ads_by_id.py --dry-run
    .venv/bin/python scripts/fetch_ads_by_id.py
    .venv/bin/python scripts/fetch_ads_by_id.py --ids 1202...,1202...
    .venv/bin/python scripts/fetch_ads_by_id.py --recent
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.dbq import connect  # noqa: E402
from scripts import ingest_last_15_days as ing  # noqa: E402

BATCH = 50  # Graph's limit for ?ids=

WORK_SQL = """
WITH s AS (
  SELECT ad_id FROM public.insights_daily_by_ad
  WHERE day > (SELECT MAX(day) FROM public.insights_daily_by_ad) - 30
  GROUP BY 1
  HAVING SUM(spend) > 0
      OR SUM(COALESCE(add_to_cart,0) + COALESCE(checkout_initiate,0) + COALESCE(purchases,0)) > 0
)
SELECT s.ad_id FROM s LEFT JOIN public.ad_media m USING (ad_id) WHERE m.ad_id IS NULL
"""

RECENT_SQL = """
SELECT ad_id FROM public.insights_daily_by_ad
 WHERE day > (SELECT MAX(day) FROM public.insights_daily_by_ad) - 30
 GROUP BY 1 HAVING SUM(spend) > 0
UNION
SELECT ad_id FROM public.meta_ads
 WHERE ad_effective_status IN ('ACTIVE', 'WITH_ISSUES', 'IN_PROCESS', 'PENDING_REVIEW')
"""


async def fetch(ids: list[str], token: str, base: str) -> tuple[list[dict], list[str]]:
    items, failed = [], []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            try:
                body = await ing._get_with_retry(client, f"{base}/", {
                    "access_token": token, "ids": ",".join(chunk), "fields": ",".join(ing.AD_FIELDS)})
            except RuntimeError as exc:
                print(f"  batch {i // BATCH + 1} failed: {str(exc)[:200]}", flush=True)
                failed += chunk
                continue
            got = [v for v in body.values() if isinstance(v, dict) and v.get("id")]
            items += got
            failed += [a for a in chunk if a not in body]
            print(f"  fetched {min(i + BATCH, len(ids)):,}/{len(ids):,} ({len(items):,} ads back)", flush=True)
    return items, failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=None, help="comma-separated ad ids; default: the work query")
    ap.add_argument("--recent", action="store_true",
                    help="ads that spent in 30 days or are live -- the nightly status refresh")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if ing.load_dotenv:
        ing.load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        print("META_ACCESS_TOKEN is not set.", file=sys.stderr)
        return 1
    api_version = os.environ.get("META_API_VERSION", "v21.0")
    if a.ids:
        ids = [x.strip() for x in a.ids.split(",") if x.strip().isdigit()]
    else:
        with connect(statement_timeout="300s") as conn, conn.cursor() as cur:
            cur.execute(RECENT_SQL if a.recent else WORK_SQL)
            ids = [r[0] for r in cur.fetchall()]
    print(f"ads to fetch: {len(ids):,}", flush=True)
    if a.dry_run or not ids:
        return 0

    items, failed = asyncio.run(fetch(ids, token, f"https://graph.facebook.com/{api_version}"))
    accounts = {acc.account_id: acc for acc in ing._discover_accounts().values()}
    by_acct: dict[str, list[dict]] = {}
    for it in items:
        by_acct.setdefault(str(it.get("account_id")), []).append(it)
    results = []
    for acct_id, its in by_acct.items():
        acc = accounts.get(acct_id) or ing.AccountConfig(key="?", name="?", account_id=acct_id)
        results.append(ing.FetchResult(account=acc, object_type="ad", api_endpoint="ads",
                                       items=its, request_params={"ids": "by_id", "count": len(its)}))
    dsn = ing._to_psycopg2_dsn(os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"])
    ing._write_results(dsn, results, api_version=api_version)
    no_creative = sum(1 for it in items if not (it.get("creative") or {}).get("id"))
    print(f"done: {len(items):,} ads written, {len(failed):,} not returned by Meta, "
          f"{no_creative:,} without a creative id", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
