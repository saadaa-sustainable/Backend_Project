"""One-shot migration: copy content_asset_register from the legacy
Creative_Testing_Dashboard Supabase to Backend_Project's Supabase.

Source (CTD -- Meta_ads_data)
    D:/Creative_Testing_Dashboard/backend/.env -> SUPABASE_DB_URL
Target (Backend_Project -- media_data_saadaa)
    D:/Backend_Project/.env                    -> DATABASE_URL_SYNC

The CTD asset register mirrors from `content_workflow_optimiser` and adds
computed_is_tested + matched_ad_id via substring match against
primary_table.ad_name. We copy the whole snapshot -- ongoing mirroring
can be wired later as a scheduled fetch.

Usage (from either directory):
    python scripts/migrate_asset_register_from_ctd.py [--dry-run]

Idempotent: PK on asset_id, ON CONFLICT DO UPDATE. Safe to re-run.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

CTD_ENV_PATH = Path("D:/Creative_Testing_Dashboard/backend/.env")
BACKEND_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def resolve_urls() -> tuple[str, str]:
    if not CTD_ENV_PATH.exists():
        sys.exit(f"CTD .env not found at {CTD_ENV_PATH}")
    if not BACKEND_ENV_PATH.exists():
        sys.exit(f"Backend_Project .env not found at {BACKEND_ENV_PATH}")

    ctd_env = dotenv_values(str(CTD_ENV_PATH))
    src = ctd_env.get("SUPABASE_DB_URL")
    if not src:
        sys.exit("CTD .env has no SUPABASE_DB_URL")

    load_dotenv(str(BACKEND_ENV_PATH), override=True)
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        sys.exit("Backend_Project .env has no DATABASE_URL_SYNC / DATABASE_URL")
    tgt = raw.replace("postgresql+psycopg2://", "postgresql://").split("?")[0]
    return src, tgt


# Table schema. Mirrors CTD's 49 columns 1:1 -- keeps downstream ports
# straightforward and matches the row shape we'll SELECT below.
DDL = """
CREATE TABLE IF NOT EXISTS public.content_asset_register (
    seq                       integer,
    asset_id                  text PRIMARY KEY,
    source_parent             text,
    asset_type                text,
    category                  text,
    planning_nomenclature     text,
    link_to_asset             text,
    origin                    text,
    creative_effort_type      text,
    type_of_content           text,
    date_of_production        date,
    date_testing_ads          date,
    date_testing_posting_ig   date,
    ad_id                     text,
    is_test                   boolean,
    created_at                timestamptz,
    source                    text,
    ads_name                  text,
    ads_result                text,
    ads_status                text,
    ads_count                 integer,
    ads_impressions           bigint,
    ads_spend                 numeric,
    ads_conv_value            numeric,
    ads_roas                  numeric,
    ads_ncp                   integer,
    ads_cost_per_ncp          numeric,
    ads_ftewv                 integer,
    ads_cost_per_ftewv        numeric,
    ads_purchases             integer,
    ads_shopify_orders        integer,
    ads_shopify_sales         numeric,
    ads_shopify_aov           numeric,
    ads_shopify_roas          numeric,
    ads_synced_at             timestamptz,
    ads_testing_status        text,
    ads_instagram_posted      text,
    ads_instagram_permalink   text,
    ads_reach                 bigint,
    ads_ctr                   numeric,
    ads_hook_rate             numeric,
    ads_hold_rate             numeric,
    ads_thruplay_rate         numeric,
    mirrored_at               timestamptz,
    brief_shoot_required      text,
    brief_aspect_ratio        text,
    computed_is_tested        boolean,
    matched_ad_id             text,
    matched_ad_name           text,
    ingested_from_ctd_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_car_ad_id
    ON public.content_asset_register (ad_id);
CREATE INDEX IF NOT EXISTS idx_car_computed_is_tested
    ON public.content_asset_register (computed_is_tested);
CREATE INDEX IF NOT EXISTS idx_car_planning_prefix
    ON public.content_asset_register (split_part(planning_nomenclature, '_', 1));
"""

COLUMNS = [
    "seq", "asset_id", "source_parent", "asset_type", "category",
    "planning_nomenclature", "link_to_asset", "origin", "creative_effort_type",
    "type_of_content", "date_of_production", "date_testing_ads",
    "date_testing_posting_ig", "ad_id", "is_test", "created_at", "source",
    "ads_name", "ads_result", "ads_status", "ads_count", "ads_impressions",
    "ads_spend", "ads_conv_value", "ads_roas", "ads_ncp", "ads_cost_per_ncp",
    "ads_ftewv", "ads_cost_per_ftewv", "ads_purchases", "ads_shopify_orders",
    "ads_shopify_sales", "ads_shopify_aov", "ads_shopify_roas",
    "ads_synced_at", "ads_testing_status", "ads_instagram_posted",
    "ads_instagram_permalink", "ads_reach", "ads_ctr", "ads_hook_rate",
    "ads_hold_rate", "ads_thruplay_rate", "mirrored_at",
    "brief_shoot_required", "brief_aspect_ratio", "computed_is_tested",
    "matched_ad_id", "matched_ad_name",
]


def upsert_sql() -> str:
    col_list = ", ".join(COLUMNS)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "asset_id"
    )
    return (
        f"INSERT INTO public.content_asset_register ({col_list}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (asset_id) DO UPDATE SET "
        f"{updates}, ingested_from_ctd_at = now()"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch + validate, do not write to target")
    args = parser.parse_args()

    src_url, tgt_url = resolve_urls()

    import psycopg2
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] asset_register migration: start",
          flush=True)

    print("  fetching from CTD...", flush=True)
    with psycopg2.connect(src_url) as src_conn:
        with src_conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(COLUMNS)} FROM public.content_asset_register"
            )
            rows = cur.fetchall()
    print(f"  fetched {len(rows):,} rows", flush=True)

    if args.dry_run:
        print("  --dry-run: skipping target writes", flush=True)
        print(f"  sample row (first): {rows[0] if rows else '(empty)'}", flush=True)
        return

    print("  applying DDL on target...", flush=True)
    with psycopg2.connect(tgt_url) as tgt_conn:
        with tgt_conn.cursor() as cur:
            cur.execute(DDL)
        tgt_conn.commit()

    print(f"  upserting {len(rows):,} rows into target...", flush=True)
    sql = upsert_sql()
    with psycopg2.connect(tgt_url) as tgt_conn:
        with tgt_conn.cursor() as cur:
            cur.executemany(sql, rows)
        tgt_conn.commit()

    with psycopg2.connect(tgt_url) as tgt_conn:
        with tgt_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), "
                "COUNT(*) FILTER (WHERE ad_id IS NULL) AS untested, "
                "COUNT(*) FILTER (WHERE ad_id IS NOT NULL) AS tested "
                "FROM public.content_asset_register"
            )
            tot, untested, tested = cur.fetchone()

    dt = (datetime.utcnow() - t0).total_seconds()
    print(f"\n[OK] migration complete in {dt:.1f}s "
          f"-- target has {tot:,} rows "
          f"({untested:,} untested / {tested:,} tested)", flush=True)


if __name__ == "__main__":
    main()
