"""BRONZE: the Google Ads roster, exactly as the API returned it.

This is the first half of a pair, mirroring Meta's
`ingest_last_15_days.py --roster-only` -> `refresh_meta_entities.py`:

    python scripts/fetch_google_ads_entities.py   # API  -> raw_dump_google_ads
    python scripts/refresh_google_entities.py     # that -> google_* (Silver)

It writes `raw_dump_google_ads` and nothing else. No derived columns, no
current-state collapse, no label fallback -- every one of those is a
Silver concern and lives in app/services/google/entity_flatten.py. The
column vocabulary is lifted from `raw_dump_meta` (object_type,
raw_payload, batch_id, extracted_at, payload_hash, processing_status) so
the two bronze tables read the same way.

WHAT A ROW HOLDS
----------------
One GAQL result row, whole, per fetched object. GAQL returns the parents
inline, so an ad's payload carries its ad group and campaign too:

    campaign   {"campaign": {...}}
    ad_group   {"adGroup": {...}, "campaign": {...}}
    ad         {"adGroupAd": {"ad": {...}, ...}, "adGroup": {...}, "campaign": {...}}

Storing the whole row rather than picked fields is the point of Bronze:
when a Silver column turns out to be wrong, it is re-derivable without
re-fetching, and a field nobody thought to keep is still there.

APPEND-ONLY, AND WHY THAT IS AFFORDABLE HERE
--------------------------------------------
One row per object per run, like `raw_dump_meta`, with no de-duplication
on `payload_hash`. That records something a de-duplicated table cannot:
that the API was asked on a given day and said this. The account holds
~806 objects, so a nightly run adds ~294k rows a year against
raw_dump_meta's existing 4.45M -- small enough that keeping the honest
version costs nothing worth saving.

It is also what makes Silver able to outlive the API. Google ages
removed campaigns and ads out of GAQL; because Bronze never deletes, a
name learned once stays derivable forever, so attribution for a closed
month does not change when Google forgets.

Usage:
    ./.venv/bin/python scripts/fetch_google_ads_entities.py
    ./.venv/bin/python scripts/fetch_google_ads_entities.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2.extras  # noqa: E402

from scripts.dbq import connect as db_connect  # noqa: E402
from scripts.google_ads_auth import GoogleAdsAuthError, connect as ads_connect  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS public.raw_dump_google_ads (
    id                uuid PRIMARY KEY,
    -- 'campaign' | 'ad_group' | 'ad'
    object_type       varchar NOT NULL,
    google_id         varchar NOT NULL,
    -- {"campaign_id": ..., "ad_group_id": ...} where GAQL gave them.
    -- Mirrors raw_dump_meta.parent_ids; lets a Silver rebuild filter by
    -- parent without opening raw_payload.
    parent_ids        jsonb,
    raw_payload       jsonb NOT NULL,
    api_endpoint      varchar,
    api_version       varchar,
    batch_id          uuid NOT NULL,
    request_params    jsonb,
    extracted_at      timestamptz NOT NULL,
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    sync_type         varchar,
    payload_hash      varchar,
    processing_status  varchar DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS ix_raw_dump_google_ads_entity
    ON public.raw_dump_google_ads(object_type, google_id, extracted_at DESC);
CREATE INDEX IF NOT EXISTS ix_raw_dump_google_ads_batch
    ON public.raw_dump_google_ads(batch_id);
"""

#: Removed entities are fetched on purpose -- an order from three months
#: ago can name an ad since paused or deleted, and skipping it would file
#: a matchable order as unmatched.
#:
#: `campaign.start_date` / `end_date` do NOT exist in v24; they answer
#: UNRECOGNIZED_FIELD. The v24 names are start_date_time / end_date_time,
#: found by probing the account on 2026-10-21.
QUERIES = {
    "campaign": ("SELECT campaign.id, campaign.name, campaign.status, "
                 "campaign.serving_status, campaign.advertising_channel_type, "
                 "campaign.bidding_strategy_type, campaign.start_date_time, "
                 "campaign.end_date_time FROM campaign"),
    "ad_group": ("SELECT ad_group.id, ad_group.name, ad_group.status, "
                 "ad_group.type, campaign.id, campaign.name FROM ad_group"),
    "ad": ("SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.ad.type, "
           "ad_group_ad.status, ad_group.id, ad_group.name, "
           "campaign.id, campaign.name FROM ad_group_ad"),
}

INSERT = """
INSERT INTO public.raw_dump_google_ads
  (id, object_type, google_id, parent_ids, raw_payload, api_endpoint,
   api_version, batch_id, request_params, extracted_at, sync_type,
   payload_hash, processing_status)
VALUES %s
"""


def _identify(object_type: str, row: dict) -> tuple[str | None, dict]:
    """-> (the object's own id, its parent ids). Shape per QUERIES above."""
    campaign_id = str((row.get("campaign") or {}).get("id") or "") or None
    ad_group_id = str((row.get("adGroup") or {}).get("id") or "") or None
    if object_type == "campaign":
        return campaign_id, {}
    if object_type == "ad_group":
        return ad_group_id, {"campaign_id": campaign_id}
    ad = (row.get("adGroupAd") or {}).get("ad") or {}
    return (str(ad.get("id") or "") or None,
            {"campaign_id": campaign_id, "ad_group_id": ad_group_id})


def _rows(object_type: str, results: list[dict], *, batch_id: uuid.UUID,
          query: str, version: str, customer_id: str,
          extracted_at: datetime) -> tuple[list[tuple], int]:
    out: list[tuple] = []
    skipped = 0
    for row in results:
        google_id, parents = _identify(object_type, row)
        if not google_id:
            # No id means nothing downstream could ever join to it. Counted
            # and reported rather than dropped in silence.
            skipped += 1
            continue
        payload = json.dumps(row, sort_keys=True)
        out.append((
            str(uuid.uuid4()), object_type, google_id,
            json.dumps(parents), payload,
            f"customers/{customer_id}/googleAds:searchStream", version,
            str(batch_id), json.dumps({"query": query}), extracted_at,
            "full_roster",
            hashlib.sha256(payload.encode()).hexdigest(), "pending",
        ))
    return out, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and summarise, write nothing.")
    args = ap.parse_args()

    try:
        ads = ads_connect()
    except GoogleAdsAuthError as exc:
        print(exc, file=sys.stderr)
        return 2

    batch_id = uuid.uuid4()
    extracted_at = datetime.now(timezone.utc)
    print(f"API:       {ads.version}, customer {ads.customer_id}")
    print(f"Batch:     {batch_id}")

    rows: list[tuple] = []
    for object_type, query in QUERIES.items():
        try:
            results = ads.search_stream(query)
        except GoogleAdsAuthError as exc:
            print(exc, file=sys.stderr)
            return 1
        got, skipped = _rows(object_type, results, batch_id=batch_id,
                             query=query, version=ads.version,
                             customer_id=ads.customer_id,
                             extracted_at=extracted_at)
        rows.extend(got)
        note = f"  ({skipped} without an id, skipped)" if skipped else ""
        print(f"           {object_type:<9} {len(got):>5} rows{note}")

    # An empty roster is far more likely to be a broken credential than an
    # account with no campaigns, and writing it would teach Bronze a lie
    # that Silver would then faithfully reproduce.
    if not rows:
        print("Refusing to write: the API returned nothing.", file=sys.stderr)
        return 1

    print(f"Total:     {len(rows):,} rows  (3 operations, no fee)")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    with db_connect(autocommit=False, statement_timeout="120s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            psycopg2.extras.execute_values(cur, INSERT, rows, page_size=500)
            cur.execute("SELECT object_type, count(*) "
                        "  FROM public.raw_dump_google_ads "
                        " GROUP BY object_type ORDER BY object_type")
            held = cur.fetchall()
        conn.commit()

    print(f"\n[OK] {len(rows):,} rows -> raw_dump_google_ads")
    print("     bronze now holds: "
          + ", ".join(f"{t}={n:,}" for t, n in held))
    print("     next: ./.venv/bin/python scripts/refresh_google_entities.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
