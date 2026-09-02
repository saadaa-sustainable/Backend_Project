"""One-shot migration: copy the three CTD content tables into
Backend_Project's Supabase.

Source (CTD -- Meta_ads_data)
    D:/Creative_Testing_Dashboard/backend/.env -> SUPABASE_DB_URL
Target (Backend_Project -- media_data_saadaa)
    D:/Backend_Project/.env                    -> DATABASE_URL_SYNC

Tables copied (each drives one media type in the Untested Assets UI):
  * content_asset_register    -- Video   (asset_id PK,       ~436 rows)
  * content_graphic_register  -- Graphic (requisition_id PK, ~1093 rows)
  * content_influencer_posts  -- Inf.    (id PK,             ~325 rows)

Each source mirrors from a workflow-optimiser Supabase and adds
computed_is_tested + matched_ad_id via substring match against
primary_table.ad_name (in CTD). We copy the snapshot; the untested
endpoint filters on ad_id / computed_is_tested per-table.

Usage:
    python scripts/migrate_asset_register_from_ctd.py [--dry-run] [--only TABLE]

Idempotent: ON CONFLICT DO UPDATE on the PK. Safe to re-run.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

CTD_ENV_PATH = Path("D:/Creative_Testing_Dashboard/backend/.env")
BACKEND_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


@dataclass
class TableSpec:
    name: str
    pk: str
    columns: list[str]
    ddl: str


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


ASSET_REGISTER = TableSpec(
    name="content_asset_register",
    pk="asset_id",
    columns=[
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
    ],
    ddl="""
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
""",
)


GRAPHIC_REGISTER = TableSpec(
    name="content_graphic_register",
    pk="requisition_id",
    columns=[
        "requisition_id", "asset_date", "priority", "creative", "nomenclature",
        "reference_links", "product", "audience_type", "graphic_type",
        "key_message", "things_to_note", "objective", "demographic",
        "who_is_this_for", "visuals", "count_9_16", "count_4_5",
        "count_16_9", "count_1_1", "total_count", "platform", "assignee",
        "catchphrase_main", "catchphrase_sub", "due_date",
        "status_of_completion", "date_of_completion", "status_of_testing",
        "test_results", "test_status", "status", "ad_id", "ad_launch_date",
        "impressions", "cac", "link_1", "link_2", "link_3",
        "summary_status", "summary_result", "mirrored_at",
        "computed_is_tested", "matched_ad_id", "matched_ad_name",
    ],
    ddl="""
CREATE TABLE IF NOT EXISTS public.content_graphic_register (
    requisition_id            text PRIMARY KEY,
    asset_date                date,
    priority                  text,
    creative                  text,
    nomenclature              text,
    reference_links           text,
    product                   text,
    audience_type             text,
    graphic_type              text,
    key_message               text,
    things_to_note            text,
    objective                 text,
    demographic               text,
    who_is_this_for           text,
    visuals                   text,
    count_9_16                integer,
    count_4_5                 integer,
    count_16_9                integer,
    count_1_1                 integer,
    total_count               integer,
    platform                  text,
    assignee                  text,
    catchphrase_main          text,
    catchphrase_sub           text,
    due_date                  date,
    status_of_completion      text,
    date_of_completion        date,
    status_of_testing         text,
    test_results              text,
    test_status               text,
    status                    text,
    ad_id                     text,
    ad_launch_date            date,
    impressions               bigint,
    cac                       numeric,
    link_1                    text,
    link_2                    text,
    link_3                    text,
    summary_status            text,
    summary_result            text,
    mirrored_at               timestamptz,
    computed_is_tested        boolean,
    matched_ad_id             text,
    matched_ad_name           text,
    ingested_from_ctd_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cgr_computed_is_tested
    ON public.content_graphic_register (computed_is_tested);
CREATE INDEX IF NOT EXISTS idx_cgr_product
    ON public.content_graphic_register (product);
""",
)


INFLUENCER_POSTS = TableSpec(
    name="content_influencer_posts",
    pk="id",
    columns=[
        "id", "post_id", "post_id_short", "username", "nomenclature",
        "content_type", "deliverable_type", "deliverable_role", "collab_type",
        "campaign_id", "post_date", "created_at", "updated_at",
        "workflow_status", "partnership_status", "ads_status", "ads_results",
        "ads_usage_rights", "post_link", "download_link", "post_thumbnail",
        "computed_is_tested", "matched_ad_id", "matched_ad_name", "mirrored_at",
    ],
    ddl="""
CREATE TABLE IF NOT EXISTS public.content_influencer_posts (
    id                        bigint PRIMARY KEY,
    post_id                   text,
    post_id_short             text,
    username                  text,
    nomenclature              text,
    content_type              text,
    deliverable_type          text,
    deliverable_role          text,
    collab_type               text,
    campaign_id               text,
    post_date                 date,
    created_at                timestamptz,
    updated_at                timestamptz,
    workflow_status           text,
    partnership_status        text,
    ads_status                text,
    ads_results               text,
    ads_usage_rights          text,
    post_link                 text,
    download_link             text,
    post_thumbnail            text,
    computed_is_tested        boolean,
    matched_ad_id             text,
    matched_ad_name           text,
    mirrored_at               timestamptz,
    ingested_from_ctd_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cip_computed_is_tested
    ON public.content_influencer_posts (computed_is_tested);
CREATE INDEX IF NOT EXISTS idx_cip_username
    ON public.content_influencer_posts (username);
""",
)


SPECS: list[TableSpec] = [ASSET_REGISTER, GRAPHIC_REGISTER, INFLUENCER_POSTS]


def upsert_sql(spec: TableSpec) -> str:
    col_list = ", ".join(spec.columns)
    placeholders = ", ".join(["%s"] * len(spec.columns))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in spec.columns if c != spec.pk
    )
    return (
        f"INSERT INTO public.{spec.name} ({col_list}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT ({spec.pk}) DO UPDATE SET "
        f"{updates}, ingested_from_ctd_at = now()"
    )


def migrate_one(src_url: str, tgt_url: str, spec: TableSpec, dry_run: bool) -> None:
    import psycopg2

    print(f"\n--- {spec.name} ---", flush=True)
    print("  fetching from CTD...", flush=True)
    with psycopg2.connect(src_url) as src_conn:
        with src_conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(spec.columns)} FROM public.{spec.name}")
            rows = cur.fetchall()
    print(f"  fetched {len(rows):,} rows", flush=True)

    if dry_run:
        print("  --dry-run: skipping target writes", flush=True)
        return

    print("  applying DDL on target...", flush=True)
    with psycopg2.connect(tgt_url) as tgt_conn:
        with tgt_conn.cursor() as cur:
            cur.execute(spec.ddl)
        tgt_conn.commit()

    print(f"  upserting {len(rows):,} rows...", flush=True)
    sql = upsert_sql(spec)
    with psycopg2.connect(tgt_url) as tgt_conn:
        with tgt_conn.cursor() as cur:
            cur.executemany(sql, rows)
        tgt_conn.commit()

    with psycopg2.connect(tgt_url) as tgt_conn:
        with tgt_conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM public.{spec.name}")
            (tot,) = cur.fetchone()
    print(f"  [OK] {spec.name}: target now has {tot:,} rows", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=[s.name for s in SPECS],
                        help="Migrate just one table (repeat as needed)")
    args = parser.parse_args()

    src_url, tgt_url = resolve_urls()
    t0 = datetime.utcnow()
    print(f"[{t0.isoformat(timespec='seconds')}Z] CTD content migration: start",
          flush=True)

    for spec in SPECS:
        if args.only and spec.name != args.only:
            continue
        migrate_one(src_url, tgt_url, spec, args.dry_run)

    dt = (datetime.utcnow() - t0).total_seconds()
    print(f"\n[OK] all migrations complete in {dt:.1f}s", flush=True)


if __name__ == "__main__":
    main()
