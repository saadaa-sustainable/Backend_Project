"""Mirror the three creative-asset registers into Backend_Project.

WHY THIS EXISTS
---------------
The asset->ad mapping is only as good as the register behind it, and BP's
copies of all three registers were a ONE-SHOT migration
(migrate_asset_register_from_ctd.py, hardcoded D:/ Windows paths, never
runnable again on another machine). Measured 2026-09-15, BP against the
live sources:

    media                BP mirror      live source     BP is missing
    video                      436              949              54%
    influencer                 325            9,504              97%
    graphics                 1,093        ~1,490+ *              27%

    * the graphics sheet's true row count is not knowable from a Drive
      export (it truncates); ads in ad_lifecycle reference requisition
      ids up to GAD-Sep-1493 while BP's mirror stops well short.

All three mirrors last moved 2026-09-01. Nothing refreshed them since.

THE THREE SOURCES
-----------------
video       Supabase `content-workflow-optimizer` (npxpywozmrptzzytzdmg)
            public.asset_register -- asset_id 'CPL012-0963',
            planning_nomenclature 'M-WTW_TBG_BT_CPL012-0963_14092026'.
            Already carries ad_id / ads_name / ads_testing_status, synced
            daily 05:30 UTC by that project's own cron.

influencer  Supabase `saadaa-creatorhub` (xynyvbagcudjrzklwnqp)
            public.posts -- post_id_short 'SIF-14755-P1',
            nomenclature 'SIF-14755-P1-nann.tbh-VRP-2026-09-07'.

graphics    Google Sheet "Creative Mastersheet - Graphics", tab
            "Performance Ad Req" -- Requisition ID 'GAD-Sep-1377',
            Nomenclature 'SDCCP_VRP_PL_SC_GAD-Sep-1377'.

A DELIBERATE INDEPENDENCE CHOICE
--------------------------------
Both Supabase sources already resolve assets to ads themselves, and their
ad_id / ads_testing_status columns are mirrored here as
`source_ad_id` / `source_testing_status`. They are NOT used as this
project's answer, because both upstreams derive them from the LEGACY
CTD warehouse (ae_table_view) that Backend_Project exists to replace --
consuming them as truth would make BP's asset mapping depend on the
system it is retiring.

They are kept as a RECONCILIATION column instead: refresh_ad_asset_map.py
computes BP's own match from ad_lifecycle.ad_name, and disagreement
between the two is a signal worth surfacing, not something to hide.

Idempotent: upsert on each register's primary key. Safe to re-run.

Usage:
    ./.venv/bin/python scripts/ingest_asset_sources.py --source all
    ./.venv/bin/python scripts/ingest_asset_sources.py --source graphics
    ./.venv/bin/python scripts/ingest_asset_sources.py --source all --dry-run

Required env (see .env.example):
    DATABASE_URL_SYNC          BP target
    ASSET_REGISTER_DB_URL      content-workflow-optimizer pooler DSN
    CREATORHUB_DB_URL          saadaa-creatorhub pooler DSN
    GRAPHICS_SHEET_ID          1qlz0u88IheUw9GDWXLD6X8TBP_wTEN3RbH-tRr628n0
    GRAPHICS_SHEET_TAB         Performance Ad Req
    GOOGLE_CREDS_JSON          service-account JSON (one line). The sheet
                               MUST be shared with that account's email,
                               read-only is enough.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:  # noqa: BLE001
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="backslashreplace")

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402


def _dsn(raw: str) -> str:
    return raw.replace("postgresql+psycopg2://", "postgresql://").split("?")[0]


TARGET_DSN = _dsn(os.environ["DATABASE_URL_SYNC"])

#: Columns mirrored 1:1 from the live source into BP's register table.
#: Deliberately a fixed list rather than SELECT * -- an upstream schema
#: change should surface as a loud KeyError here, not silently widen or
#: reorder what lands in BP.
VIDEO_COLUMNS = [
    "seq", "asset_id", "source_parent", "asset_type", "category",
    "planning_nomenclature", "link_to_asset", "origin", "creative_effort_type",
    "type_of_content", "date_of_production", "date_testing_ads",
    "date_testing_posting_ig", "is_test", "created_at", "source",
]
#: Upstream's own ad resolution -- kept for reconciliation, never as truth.
VIDEO_SOURCE_MATCH = {"ad_id": "source_ad_id", "ads_name": "source_ad_name",
                      "ads_testing_status": "source_testing_status"}

INFLUENCER_COLUMNS = [
    "id", "post_id", "post_id_short", "username", "nomenclature",
    "content_type", "deliverable_type", "deliverable_role", "collab_type",
    "campaign_id", "post_date", "created_at", "updated_at",
    "workflow_status", "partnership_status", "ads_usage_rights",
    "post_link", "download_link", "post_thumbnail",
]
INFLUENCER_SOURCE_MATCH = {"ads_status": "source_testing_status",
                           "ads_results": "source_ad_result"}

#: Sheet header -> BP column. Header text is matched case-insensitively
#: with surrounding whitespace stripped. Anything not listed is ignored.
#: Two columns in the tab are literally both named "Date"; only the first
#: is taken (as asset_date) -- see _graphics_rows.
GRAPHICS_HEADER_MAP = {
    "requisition id": "requisition_id",
    "nomenclature": "nomenclature",
    "product": "product",
    "priority": "priority",
    "creative": "creative",
    "audience type": "audience_type",
    "graphic type": "graphic_type",
    "objective": "objective",
    "due date": "due_date",
    "status of completion": "status_of_completion",
    "date of completion": "date_of_completion",
    "status of testing": "status_of_testing",
    "test results": "test_results",
    "test status": "test_status",
    "status": "status",
    "ad id": "source_ad_id",
    "impressions": "impressions",
    "cac": "cac",
    "links 1": "link_1",
    "links 2": "link_2",
    "links 3": "link_3",
}


DDL = """
-- Upstream's own asset->ad resolution, mirrored for reconciliation only.
ALTER TABLE public.content_asset_register
    ADD COLUMN IF NOT EXISTS source_ad_id           text,
    ADD COLUMN IF NOT EXISTS source_ad_name         text,
    ADD COLUMN IF NOT EXISTS source_testing_status  text;

ALTER TABLE public.content_influencer_posts
    ADD COLUMN IF NOT EXISTS source_testing_status  text,
    ADD COLUMN IF NOT EXISTS source_ad_result       text;

ALTER TABLE public.content_graphic_register
    ADD COLUMN IF NOT EXISTS source_ad_id  text,
    ADD COLUMN IF NOT EXISTS priority      text,
    ADD COLUMN IF NOT EXISTS creative      text,
    ADD COLUMN IF NOT EXISTS objective     text,
    ADD COLUMN IF NOT EXISTS cac           numeric;
"""


def _upsert(cur, table: str, pk: str, columns: list[str], rows: list[tuple]) -> int:
    """Insert-or-update `rows` keyed on `pk`, stamping mirrored_at."""
    if not rows:
        return 0
    cols = columns + ["mirrored_at"]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != pk)
    sql = (
        f"INSERT INTO public.{table} ({', '.join(cols)}) VALUES %s "
        f"ON CONFLICT ({pk}) DO UPDATE SET {updates}"
    )
    psycopg2.extras.execute_values(
        cur, sql, [r + (time.strftime("%Y-%m-%d %H:%M:%S+00"),) for r in rows],
        page_size=500,
    )
    return len(rows)


def _pull_supabase(env_var: str, table: str, columns: list[str],
                   source_match: dict[str, str], where: str = "") -> list[tuple]:
    """SELECT the mirrored columns out of one upstream Supabase project."""
    raw = os.environ.get(env_var)
    if not raw:
        raise SystemExit(
            f"{env_var} is not set -- cannot reach the {table} source. "
            f"Add the project's pooler DSN to .env (see this file's docstring)."
        )
    select_cols = columns + list(source_match.keys())
    conn = psycopg2.connect(_dsn(raw), connect_timeout=30)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(select_cols)} FROM public.{table} {where}")
            return cur.fetchall()
    finally:
        conn.close()


def _graphics_rows() -> tuple[list[str], list[tuple]]:
    """Read the 'Performance Ad Req' tab through the Sheets API.

    Deliberately NOT read through a Drive text export: that export
    truncates (measured 2026-09-15 -- it returned 699KB of a 9MB file,
    cut off mid-row at GAD-Sep-1377, while live ads already reference
    GAD-Sep-1493) and it flattens cells to comma-joined text, so any
    value containing a comma silently shifts every later column. The
    Sheets API returns a real 2-D cell array, which is the only form
    safe to key a mapping off.
    """
    try:
        from google.oauth2 import service_account          # type: ignore
        from googleapiclient.discovery import build        # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "google-api-python-client / google-auth are required for the "
            "graphics source. pip install -r requirements.txt"
        ) from exc

    creds_raw = os.environ.get("GOOGLE_CREDS_JSON")
    if not creds_raw:
        raise SystemExit("GOOGLE_CREDS_JSON is not set -- cannot read the graphics sheet.")
    sheet_id = os.environ.get("GRAPHICS_SHEET_ID")
    if not sheet_id:
        raise SystemExit("GRAPHICS_SHEET_ID is not set.")
    tab = os.environ.get("GRAPHICS_SHEET_TAB", "Performance Ad Req")

    creds = service_account.Credentials.from_service_account_info(
        json.loads(creds_raw),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    api = build("sheets", "v4", credentials=creds, cache_discovery=False)
    values = (
        api.spreadsheets().values()
        .get(spreadsheetId=sheet_id, range=f"'{tab}'!A:AZ")
        .execute()
        .get("values", [])
    )
    if not values:
        raise SystemExit(f"Sheet tab '{tab}' returned no rows.")

    header = [h.strip().lower() for h in values[0]]
    # First "date" header only -- the tab carries two columns both titled
    # "Date" (requisition date, and the ad launch date after "Ad ID").
    seen_date = False
    index: dict[int, str] = {}
    for i, h in enumerate(header):
        if h == "date":
            index[i] = "asset_date" if not seen_date else "ad_launch_date"
            seen_date = True
        elif h in GRAPHICS_HEADER_MAP:
            index[i] = GRAPHICS_HEADER_MAP[h]

    columns = sorted(set(index.values()))
    rows: list[tuple] = []
    for raw in values[1:]:
        rec: dict[str, str | None] = {c: None for c in columns}
        for i, target in index.items():
            if i < len(raw):
                rec[target] = (raw[i] or "").strip() or None
        if not rec.get("requisition_id"):
            continue  # a spacer or notes row, not a requisition
        rows.append(tuple(rec[c] for c in columns))
    return columns, rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", choices=["video", "influencer", "graphics", "all"],
                    default="all")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch from every source and report counts, then ROLL BACK.")
    args = ap.parse_args()

    want = ("video", "influencer", "graphics") if args.source == "all" else (args.source,)
    t0 = time.time()
    summary: list[tuple[str, int]] = []

    conn = psycopg2.connect(TARGET_DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            cur.execute(DDL)

            if "video" in want:
                rows = _pull_supabase("ASSET_REGISTER_DB_URL", "asset_register",
                                      VIDEO_COLUMNS, VIDEO_SOURCE_MATCH)
                cols = VIDEO_COLUMNS + list(VIDEO_SOURCE_MATCH.values())
                summary.append(("video", _upsert(cur, "content_asset_register",
                                                 "asset_id", cols, rows)))

            if "influencer" in want:
                rows = _pull_supabase("CREATORHUB_DB_URL", "posts",
                                      INFLUENCER_COLUMNS, INFLUENCER_SOURCE_MATCH,
                                      where="WHERE post_id_short IS NOT NULL "
                                            "AND COALESCE(is_test, false) = false")
                cols = INFLUENCER_COLUMNS + list(INFLUENCER_SOURCE_MATCH.values())
                summary.append(("influencer", _upsert(cur, "content_influencer_posts",
                                                      "id", cols, rows)))

            if "graphics" in want:
                cols, rows = _graphics_rows()
                summary.append(("graphics", _upsert(cur, "content_graphic_register",
                                                    "requisition_id", cols, rows)))

            if args.dry_run:
                conn.rollback()
                print("[pg] ROLLED BACK -- --dry-run, nothing written", flush=True)
            else:
                conn.commit()
    finally:
        conn.close()

    print(f"\n[OK] asset sources mirrored in {time.time() - t0:.1f}s")
    for name, n in summary:
        print(f"    {name:<12} {n:>7,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
