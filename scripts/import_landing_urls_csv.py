"""Landing page URLs from an Ads Manager export ("Link (ad settings)" or "Website URL").

Fills ads with no URL, and replaces URLs that only came from the preview
scraper (landing_page_source = 'ad_preview', a rendered guess). A URL read
from the creative itself is never overwritten.

Writes Bronze (raw_dump_meta adcreative rows, which the nightly
scripts/refresh_ad_media.py rebuild reads, newest per ad wins) and mirrors
the same values into ad_media so the dashboard shows them now.

Every ad in the CSV also goes into ad_landing_map, whether or not
ad_media knows the ad. ad_media is rebuilt each night from the ads the
ingest has already seen, so an ad launched since then is not in it and
used to be skipped here without a word -- and those are the ads doing
most of the spending. The map is never truncated, so it holds them
until the nightly catches up, and after.

Usage:
    .venv/bin/python scripts/import_landing_urls_csv.py ~/Downloads/export.csv           # dry run
    .venv/bin/python scripts/import_landing_urls_csv.py ~/Downloads/export.csv --write
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.dbq import connect  # noqa: E402

SOURCE = "ads_manager_export"
#: Ads Manager names the destination column differently per report preset.
URL_COLUMNS = ("Link (ad settings)", "Website URL")
#: ad_media.landing_page_url has a btree index; a tuple over 2704 bytes fails.
MAX_INDEXABLE_URL = 2000
COLUMNS = ["id", "meta_id", "raw_payload", "api_endpoint", "api_version", "batch_id",
           "request_params", "extracted_at", "sync_type", "payload_hash",
           "processing_status", "object_type", "parent_ids", "is_nested"]


MAP_DDL = """
CREATE TABLE IF NOT EXISTS public.ad_landing_map (
    ad_id            text PRIMARY KEY,
    landing_page_url text NOT NULL,
    source           text NOT NULL,
    imported_at      timestamptz NOT NULL DEFAULT now()
)
"""


def write_map(urls: dict[str, str]) -> int:
    """Upsert every CSV ad's URL into ad_landing_map. Newest import wins."""
    import psycopg2.extras
    rows = [(ad, url, SOURCE) for ad, url in urls.items()]
    with connect(autocommit=False, statement_timeout="300s") as conn, conn.cursor() as cur:
        cur.execute(MAP_DDL)
        conn.commit()
    for i in range(0, len(rows), 500):
        with connect(autocommit=False, statement_timeout="300s") as conn, conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO public.ad_landing_map (ad_id, landing_page_url, source)
                VALUES %s
                ON CONFLICT (ad_id) DO UPDATE SET
                    landing_page_url = EXCLUDED.landing_page_url,
                    source = EXCLUDED.source, imported_at = now()
            """, rows[i:i + 500])
            conn.commit()
    return len(rows)


def read_csv(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    col = next((c for c in URL_COLUMNS if rows and c in rows[0]), None)
    if not rows or "Ad ID" not in rows[0] or col is None:
        raise SystemExit(f"CSV needs 'Ad ID' and one of {URL_COLUMNS}")
    out = {}
    for r in rows:
        ad, url = (r["Ad ID"] or "").strip(), (r[col] or "").strip()
        if ad.isdigit() and url.startswith(("http://", "https://")):
            out[ad] = url
    return out


def same_page(a: str, b: str) -> bool:
    """Same page ignoring scheme, www, query string and trailing slash."""
    n = lambda u: u.split("?")[0].split("#")[0].rstrip("/").split("://", 1)[-1].removeprefix("www.")
    return n(a) == n(b)


def plan(urls: dict[str, str]) -> list[tuple]:
    """(ad_id, creative_id, account_id, account_name, url) for ads to write."""
    with connect(statement_timeout="300s") as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT m.ad_id, m.creative_id, l.account_id, l.account_name,
                   m.landing_page_url, m.landing_page_source
            FROM public.ad_media m
            LEFT JOIN public.ad_lifecycle l ON l.ad_id = m.ad_id
            WHERE m.ad_id = ANY(%s)""", (list(urls),))
        found = cur.fetchall()
    todo = []
    for ad, creative, acct_id, acct, cur_url, src in found:
        if cur_url is None or (src == "ad_preview" and same_page(cur_url, urls[ad]) is False):
            todo.append((ad, creative, acct_id, acct, urls[ad], cur_url is None))
    print(f"CSV ads with a URL: {len(urls):,}   in ad_media: {len(found):,}   "
          f"not in ad_media: {len(urls) - len(found):,}")
    print(f"to fill (blank): {sum(t[5] for t in todo):,}   "
          f"to replace (ad_preview guess): {sum(not t[5] for t in todo):,}")
    return todo


def write(todo: list[tuple]) -> None:
    import psycopg2.extras
    now, batch = datetime.now(timezone.utc), str(uuid.uuid4())
    bronze, silver = [], []
    for ad, creative, acct_id, acct, url, _ in todo:
        payload = {"id": creative, "landing_page_url": url, "landing_page_source": SOURCE}
        bronze.append((
            str(uuid.uuid4()), creative, json.dumps(payload), "ads_manager_export", "export", batch,
            json.dumps({"source": "ads_manager_csv"}), now, "backfill",
            hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "pending", "adcreative",
            json.dumps({"account_name": acct, "account_id": acct_id,
                        "ad_id": ad, "creative_id": creative}), False))
        if len(url) <= MAX_INDEXABLE_URL:
            silver.append((ad, url))
    for i in range(0, len(bronze), 500):
        with connect(autocommit=False, statement_timeout="300s") as conn, conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur, f"INSERT INTO raw_dump_meta ({', '.join(COLUMNS)}) VALUES %s", bronze[i:i + 500])
            psycopg2.extras.execute_values(cur, f"""
                UPDATE public.ad_media m
                   SET landing_page_url = v.url, landing_page_source = '{SOURCE}', refreshed_at = now()
                  FROM (VALUES %s) AS v(ad_id, url)
                 WHERE m.ad_id = v.ad_id
                   AND (m.landing_page_url IS NULL OR m.landing_page_source = 'ad_preview')
            """, silver[i:i + 500])
            conn.commit()
        print(f"  wrote {min(i + 500, len(bronze)):,}/{len(bronze):,}", flush=True)
    print(f"done: {len(bronze):,} Bronze rows, {len(silver):,} ad_media rows "
          f"({len(bronze) - len(silver)} over {MAX_INDEXABLE_URL} chars kept to Bronze only)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    urls = read_csv(a.csv)
    todo = plan(urls)
    if a.write:
        if todo:
            write(todo)
        print(f"ad_landing_map: {write_map(urls):,} ads upserted")
    else:
        print("dry run: pass --write to apply")
