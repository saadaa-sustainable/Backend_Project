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

historic    Same creatorhub project, public.historic_posts -- 11,261 more
influencer  influencer posts, post_id_short 'SIF-9436-P2', ZERO overlap
            with public.posts (checked live 2026-09-16). Lands in the
            SAME table as the live posts, content_influencer_posts,
            because it is the same kind of asset with the same id shape;
            `source_table` records which side a row came from.

graphics    A SECOND graphics file (GRAPHICS_HISTORIC_SHEET_ID), the
historic    fuller requisition register -- 1,558 ids against the 1,093
            the one-shot migration left behind. Same "Requisition ID"
            key, landing in the SAME table (content_graphic_register) so
            the graphics asset count simply grows. Written BEFORE the
            live tab so a requisition present in both keeps the live
            tab's version.

            Named "historic" for the gap it was added to close, but it
            is not only history: it carries both the old requisitions
            the register never had (GAD-Jun-117..191) and recent ones
            the register's stale tail is missing (GAD-Sep-1494). It
            covers 153 of the 171 ids that live ads reference and the
            register lacks.

iterated    Google Sheet "Iterated Content" -- Requisition ID
video       'ITE-Sep-273', Nomenclature
            'SDCP_UGC_RV_916_ITE-Sep-273_06/11/25_V1'. Video, but keyed
            on a REQUISITION id rather than the asset_id the main video
            register uses, so it gets its own table
            (content_iterated_register) and its own join branch in
            refresh_ad_asset_map.py. It still reports as media='video'
            -- that column is a Literal["video","graphic","influencer"]
            all the way out to the UI, and an iterated video is a video.

THE id COLLISION THAT ALMOST HAPPENED
-------------------------------------
The influencer upsert used to key on `id`. posts.id and
historic_posts.id are BOTH sequences starting at 1, and they collide on
9,678 values -- mirroring historic posts under that key would have
silently overwritten 9,678 unrelated live posts, each with a completely
unrelated influencer's row. The key is now `post_id`, which is what
actually identifies an influencer asset, is what refresh_ad_asset_map
joins on, and is unique across the union of both tables (12,055 rows,
12,055 distinct, checked live).

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
    ./.venv/bin/python scripts/ingest_asset_sources.py --source historic
    ./.venv/bin/python scripts/ingest_asset_sources.py --source iterated
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

Optional, and cheaper than the two above:
    CREATORHUB_REST_URL        https://<ref>.supabase.co -- PostgREST
    CREATORHUB_ANON_KEY        publishable/anon key. historic_posts has
                               RLS disabled, so this reads it without a
                               database password. Used as a FALLBACK when
                               CREATORHUB_DB_URL is absent.
    ITERATED_SHEET_ID          1sv8zcIT5gDE2e7zIC_ajsXW30VwOdn_9h8-SAJHKRg4
    GRAPHICS_SHEET_GID         optional; enables the CSV fallback for the
                               live graphics tab when there is no service
                               account.
    GRAPHICS_HISTORIC_SHEET_ID sheet holding the fuller graphics register
                               (defaults to GRAPHICS_SHEET_ID).
    GRAPHICS_HISTORIC_TAB      its tab name, used on the Sheets API path.
    GRAPHICS_HISTORIC_GID      its gid, used on the CSV path.
    ITERATED_SHEET_GID         1385136722 ("Iterated Content" tab)
                               Read through the sheet's public CSV export,
                               so it needs no Google credentials at all as
                               long as the sheet stays link-viewable.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
import sys
import time
from datetime import datetime
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

#: historic_posts carries most of the same fields, but not all of them:
#: it has no deliverable_type / deliverable_role / updated_at /
#: partnership_status / post_thumbnail. Listing the intersection
#: explicitly (rather than reusing INFLUENCER_COLUMNS and hoping) means a
#: missing column fails loudly at the source query instead of arriving as
#: a silent NULL.
#: NB: both influencer pulls filter on post_id, NOT post_id_short.
#: post_id is the upsert key and the column refresh_ad_asset_map joins
#: on, so filtering by a different column can only ever drop rows the
#: mapping needed -- it silently cost one historic post, and would cost
#: more the moment the two columns diverge.
HISTORIC_INFLUENCER_COLUMNS = [
    "id", "post_id", "post_id_short", "username", "nomenclature",
    "content_type", "collab_type", "campaign_id", "post_date", "created_at",
    "workflow_status", "ads_usage_rights", "post_link", "download_link",
]

#: Sheet header -> BP column for the "Iterated Content" tab. The tab also
#: carries a run of empty "Column 14".."Column 25" headers; anything not
#: listed here is ignored, so they cost nothing.
ITERATED_HEADER_MAP = {
    "requisition id": "requisition_id",
    "nomenclature": "nomenclature",
    "timestamp": "submitted_at",
    "edited link": "edited_link",
    "edited by": "edited_by",
    "video format": "video_format",
    "remarks / comments": "remarks",
    "approval status": "approval_status",
    "priority": "priority",
    "testing status": "testing_status",
    "ad id": "source_ad_id",
    "testing date": "testing_date",
    "testing week": "testing_week",
}

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

-- Which creatorhub table a row came from: 'posts', 'historic_posts' or
-- 'cleaned_data'.
ALTER TABLE public.content_influencer_posts
    ADD COLUMN IF NOT EXISTS source_table text;

-- `id` was the primary key before post_id took over (see below). It is
-- now just a mirrored creatorhub column, and rows recovered from
-- cleaned_data have no creatorhub id at all -- their id extraction is
-- exactly what failed. Keeping NOT NULL on a column that is no longer
-- the key only blocks real assets from being stored.
ALTER TABLE public.content_influencer_posts
    ALTER COLUMN id DROP NOT NULL;

-- Re-key the influencer register on post_id.
--
-- The old primary key was `id`, mirrored straight from creatorhub. That
-- was fine while `posts` was the only source; historic_posts is a second
-- sequence from 1 that collides with it on 9,678 values, so keeping `id`
-- as the key would have made the two sources overwrite each other.
-- post_id is unique across both (12,055 / 12,055 live) and is the column
-- refresh_ad_asset_map actually joins on.
--
-- Guarded so a re-run is a no-op, and skipped rather than half-applied
-- if post_id is not yet unique.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'content_influencer_posts_pkey'
                  AND conrelid = 'public.content_influencer_posts'::regclass
                  AND (SELECT attname FROM pg_attribute
                        WHERE attrelid = conrelid AND attnum = conkey[1]) = 'id')
       AND NOT EXISTS (SELECT 1 FROM public.content_influencer_posts
                        WHERE post_id IS NULL)
       AND (SELECT COUNT(*) = COUNT(DISTINCT post_id)
              FROM public.content_influencer_posts)
    THEN
        ALTER TABLE public.content_influencer_posts
            DROP CONSTRAINT content_influencer_posts_pkey;
        ALTER TABLE public.content_influencer_posts
            ADD CONSTRAINT content_influencer_posts_pkey PRIMARY KEY (post_id);
    END IF;
END $$;

-- Iterated video content. Separate table from content_asset_register
-- because it is keyed on a requisition id ('ITE-Sep-273'), not on the
-- asset_id ('CPL012-0963') that register is keyed on -- two id schemes in
-- one column would make the map's join ambiguous.
--
-- One requisition can yield several cuts (V1, V2...), each its own row in
-- the sheet, so the key is (requisition_id, nomenclature): 262 sheet rows
-- over 249 distinct requisition ids. For MATCHING only requisition_id
-- matters, and the map de-duplicates on it.
CREATE TABLE IF NOT EXISTS public.content_iterated_register (
    requisition_id    text NOT NULL,
    nomenclature      text NOT NULL DEFAULT '',
    submitted_at      text,
    edited_link       text,
    edited_by         text,
    video_format      text,
    remarks           text,
    approval_status   text,
    priority          text,
    testing_status    text,
    source_ad_id      text,
    testing_date      text,
    testing_week      text,
    mirrored_at       timestamptz,
    PRIMARY KEY (requisition_id, nomenclature)
);
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


def _pull_postgrest(table: str, columns: list[str], source_match: dict[str, str],
                    query: str = "",
                    base_env: str = "CREATORHUB_REST_URL",
                    key_env: str = "CREATORHUB_ANON_KEY") -> list[tuple]:
    """Page a creatorhub table out through PostgREST.

    Exists because the DSN path needs a database password this project
    does not have, while `historic_posts` has RLS disabled and is
    therefore readable with the publishable key alone. Same rows, no
    secret to hold.

    PostgREST caps a response at 1,000 rows regardless of what you ask
    for, so this walks the Range header until a short page comes back
    rather than trusting a single request to have returned everything --
    the failure mode of NOT doing that is a silently truncated mirror,
    which is exactly the bug this whole script exists to fix.
    """
    base = (os.environ.get(base_env) or "").rstrip("/")
    key = os.environ.get(key_env) or ""
    if not base or not key:
        raise SystemExit(
            f"{base_env} / {key_env} are not set -- cannot reach {table} "
            "without either those or the project's pooler DSN."
        )
    select_cols = columns + list(source_match.keys())
    url = f"{base}/rest/v1/{table}?select={','.join(select_cols)}"
    if query:
        url += f"&{query}"

    out: list[tuple] = []
    page = 1000
    offset = 0
    while True:
        req = urllib.request.Request(url, headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Range-Unit": "items",
            "Range": f"{offset}-{offset + page - 1}",
        })
        with urllib.request.urlopen(req, timeout=120) as resp:
            chunk = json.loads(resp.read().decode("utf-8"))
        if not chunk:
            break
        out.extend(tuple(row.get(c) for c in select_cols) for row in chunk)
        if len(chunk) < page:
            break
        offset += len(chunk)
    return out


def _iterated_rows() -> tuple[list[str], list[tuple]]:
    """Read the "Iterated Content" tab through the sheet's CSV export.

    No Google credentials: the export endpoint serves any sheet that is
    link-viewable, and this one is. The graphics tab could NOT be read
    this way -- a Drive text export truncates a 9MB sheet and flattens
    cells -- but this tab is 50KB, so the export returns it whole. If it
    ever grows past that, the symptom is a short row count, which is why
    the count is printed.

    Requisition ids in this tab are hand-entered and some are dirty:
    'ITE-Nov-321.' with a trailing dot, bare 'Aug-176' / 'Sep-271'
    missing the ITE- prefix, and one row carrying a whole nomenclature
    ('BR_PRC_916_ITE-May-148') in the id column. Each is repaired below
    rather than dropped, because every one of them is a real requisition
    that real ads reference.
    """
    sheet_id = os.environ.get("ITERATED_SHEET_ID")
    gid = os.environ.get("ITERATED_SHEET_GID", "0")
    if not sheet_id:
        raise SystemExit("ITERATED_SHEET_ID is not set (see this file's docstring).")
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/export?format=csv&gid={gid}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    cols = ["requisition_id", "nomenclature", "submitted_at", "edited_link",
            "edited_by", "video_format", "remarks", "approval_status",
            "priority", "testing_status", "source_ad_id", "testing_date",
            "testing_week"]
    header_lookup = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}

    seen: set[tuple[str, str]] = set()
    rows: list[tuple] = []
    skipped = 0
    for raw in reader:
        rec: dict[str, str | None] = {}
        for sheet_header, bp_col in ITERATED_HEADER_MAP.items():
            src = header_lookup.get(sheet_header)
            val = (raw.get(src) or "").strip() if src else ""
            rec[bp_col] = val or None
        rid = _clean_requisition_id(rec.get("requisition_id"))
        if not rid:
            skipped += 1
            continue
        rec["requisition_id"] = rid
        rec["nomenclature"] = rec.get("nomenclature") or ""
        key = (rid, rec["nomenclature"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(tuple(rec.get(c) for c in cols))
    print(f"    iterated sheet: {len(rows)} rows, {skipped} without a usable "
          f"requisition id", flush=True)
    return cols, rows


#: 'ITE-Sep-273' with the punctuation and prefix damage seen in the tab.
_ITE_RE = re.compile(r"(ITE-[A-Za-z]{3}-\d+)", re.IGNORECASE)
_BARE_MONTH_RE = re.compile(r"^([A-Za-z]{3}-\d+)\.?$")


def _clean_requisition_id(raw: str | None) -> str | None:
    """Pull a canonical 'ITE-Mon-N' out of a hand-typed cell."""
    if not raw:
        return None
    val = raw.strip().rstrip(".").strip()
    if not val:
        return None
    hit = _ITE_RE.search(val)
    if hit:
        return hit.group(1).upper().replace("ITE-", "ITE-", 1)
    bare = _BARE_MONTH_RE.match(val)
    if bare:
        # 'Aug-176' / 'Sep-271' -- the prefix was simply not typed.
        return f"ITE-{bare.group(1)}"
    return None


def _graphics_values_via_api(sheet_id: str, tab: str) -> list[list[str]]:
    """Read a tab as a real 2-D cell array through the Sheets API.

    Deliberately preferred over a Drive text export: that export
    truncates (measured 2026-09-15 -- 699KB of a 9MB file, cut off
    mid-row at GAD-Sep-1377, while live ads already reference
    GAD-Sep-1493) and flattens cells to comma-joined text, so any value
    containing a comma silently shifts every later column.
    """
    try:
        from google.oauth2 import service_account          # type: ignore
        from googleapiclient.discovery import build        # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "google-api-python-client / google-auth are required for the "
            "graphics source. pip install -r requirements.txt"
        ) from exc

    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDS_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    api = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return (
        api.spreadsheets().values()
        .get(spreadsheetId=sheet_id, range=f"'{tab}'!A:AZ")
        .execute()
        .get("values", [])
    )


def _graphics_values_via_csv(sheet_id: str, gid: str) -> list[list[str]]:
    """Read one tab through the sheet's CSV export.

    Only usable when the file is link-viewable -- this mastersheet
    currently is NOT (the export returns HTTP 401), which is why the
    Sheets API path above stays the default. Kept because sharing the
    file read-only is a much smaller ask than provisioning a service
    account, and because the per-TAB csv export does not have the
    whole-file truncation problem the Drive text export has.

    Unlike the API path this cannot tell a genuinely empty trailing cell
    from a short row, so rows are padded to the header width.
    """
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/export?format=csv&gid={gid}")
    # A private sheet answers 401 here, and an interstitial "request
    # access" page answers 200 with HTML. Both mean the same thing to the
    # caller, so both get the same actionable message rather than a
    # urllib traceback.
    no_access = (
        f"Cannot read gid={gid} of sheet {sheet_id} without credentials.\n"
        "        Either:\n"
        "          - share the sheet (Anyone with the link -> Viewer), or\n"
        "          - set GOOGLE_CREDS_JSON and share the sheet with that\n"
        "            service account's email (Viewer is enough)."
    )
    try:
        with urllib.request.urlopen(url, timeout=180) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise SystemExit(no_access) from exc
        raise
    if body.lstrip().startswith("<"):
        raise SystemExit(no_access)
    rows = list(csv.reader(io.StringIO(body)))
    if not rows:
        return []
    width = len(rows[0])
    return [r + [""] * (width - len(r)) for r in rows]


#: Typed columns in content_graphic_register whose sheet cells are free
#: text. A spreadsheet column has no type: the "Due Date" column holds
#: '19-04-25', the first "Date" column holds 'Men', and "CAC" holds
#: 'DONE'. Every one of those aborts a 1,558-row insert if handed to
#: Postgres raw, so each typed target is coerced here and becomes NULL
#: when the cell is not actually of that type.
_GRAPHICS_DATE_COLUMNS = frozenset({
    "asset_date", "due_date", "date_of_completion", "ad_launch_date",
})
_GRAPHICS_NUMERIC_COLUMNS = frozenset({
    "impressions", "cac", "count_9_16", "count_4_5", "count_16_9",
    "count_1_1", "total_count",
})

#: Digits, an optional decimal part, and nothing else -- after stripping
#: the thousands separators, currency marks and stray % these sheets
#: collect. 'DONE' and '-' yield None rather than a failed insert.
_NUMERIC_CLEAN_RE = re.compile(r"[,\s\u20b9$%]")


def _coerce_number(raw: str | None) -> str | None:
    if not raw:
        return None
    val = _NUMERIC_CLEAN_RE.sub("", raw.strip())
    if not val:
        return None
    try:
        float(val)
    except ValueError:
        return None
    return val

#: Day-first, because these sheets are written in India: '19-04-25' is
#: 19 April 2025. Tried in order; the first that parses wins.
_DATE_FORMATS = (
    "%d-%m-%y", "%d-%m-%Y", "%d/%m/%y", "%d/%m/%Y",
    "%d/%b/%Y", "%d-%b-%Y", "%d %b %Y", "%d/%b/%y", "%d-%b-%y",
    "%Y-%m-%d", "%Y/%m/%d",
)


def _coerce_date(raw: str | None) -> str | None:
    """A sheet cell -> an ISO date string, or None.

    Postgres is handed ISO or nothing. Passing the cell through raw made
    the ingest die on the first oddity -- `date/time field value out of
    range: "19-04-25"`, because the server read a day-first date under a
    month-first datestyle -- and would have mis-parsed anything
    ambiguous like 04-05-25 silently rather than loudly.

    Unparseable cells become NULL instead of aborting the run. That
    matters more than it sounds: this sheet's first "Date" column holds
    'Men' / 'Women' / 'GP' in five rows, so one stray demographic label
    would otherwise cost the whole 1,558-row register.
    """
    if not raw:
        return None
    val = raw.strip()
    if not val:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(val, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _graphics_map_rows(values: list[list[str]], tab: str) -> tuple[list[str], list[tuple]]:
    """Header-map a graphics tab. Shared by both read paths so the two
    can never drift in what they produce."""
    if not values:
        raise SystemExit(f"Sheet tab '{tab}' returned no rows.")

    header = [(h or "").strip().lower() for h in values[0]]
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

    if "requisition_id" not in index.values():
        raise SystemExit(
            f"Tab '{tab}' has no 'Requisition ID' column. Headers seen: "
            + ", ".join(h for h in header if h)
        )
    unmapped = sorted({h for i, h in enumerate(header) if h and i not in index})
    if unmapped:
        print(f"    [{tab}] ignoring unmapped headers: {', '.join(unmapped)}", flush=True)

    columns = sorted(set(index.values()))
    rows: list[tuple] = []
    seen: set[str] = set()
    skipped = 0
    for raw in values[1:]:
        rec: dict[str, str | None] = {c: None for c in columns}
        for i, target in index.items():
            if i < len(raw):
                rec[target] = (raw[i] or "").strip() or None
        for date_col in _GRAPHICS_DATE_COLUMNS & set(rec):
            rec[date_col] = _coerce_date(rec[date_col])
        for num_col in _GRAPHICS_NUMERIC_COLUMNS & set(rec):
            rec[num_col] = _coerce_number(rec[num_col])
        rid = rec.get("requisition_id")
        if not rid:
            skipped += 1
            continue  # a spacer or notes row, not a requisition
        # requisition_id is the upsert key, so a tab that repeats one
        # would make execute_values raise "ON CONFLICT DO UPDATE command
        # cannot affect row a second time". First occurrence wins.
        if rid in seen:
            continue
        seen.add(rid)
        rows.append(tuple(rec[c] for c in columns))
    print(f"    [{tab}] {len(rows)} requisitions, {skipped} rows without an id",
          flush=True)
    return columns, rows


def _graphics_rows(tab: str, gid: str | None = None,
                   sheet_id: str | None = None) -> tuple[list[str], list[tuple]]:
    """One graphics tab, by whichever access path is available.

    `sheet_id` is per-source: the graphics requisitions are not all in
    one file. The original mastersheet is shared to the saadaa.in domain
    only, which reads as private to a script (no Google identity -> HTTP
    401), while the fuller register lives in a link-viewable file. Each
    source therefore names its own sheet rather than assuming one id.
    """
    sheet_id = sheet_id or os.environ.get("GRAPHICS_SHEET_ID")
    if not sheet_id:
        raise SystemExit("GRAPHICS_SHEET_ID is not set.")
    if os.environ.get("GOOGLE_CREDS_JSON"):
        return _graphics_map_rows(_graphics_values_via_api(sheet_id, tab), tab)
    if gid:
        return _graphics_map_rows(_graphics_values_via_csv(sheet_id, gid), tab)
    raise SystemExit(
        f"Cannot read graphics tab '{tab}': GOOGLE_CREDS_JSON is not set and "
        "no gid is configured for the CSV fallback."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source",
                    choices=["video", "influencer", "historic", "graphics",
                             "graphics_historic", "iterated", "all"],
                    default="all")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch from every source and report counts, then ROLL BACK.")
    args = ap.parse_args()

    want = (("video", "historic", "influencer", "graphics_historic", "graphics",
             "iterated")
            if args.source == "all" else (args.source,))
    t0 = time.time()
    summary: list[tuple[str, int]] = []

    #: With an explicit --source the caller asked for exactly one thing,
    #: so a failure is a failure. With --source all it is not: the
    #: sources have INDEPENDENT credentials, and aborting the batch
    #: because one of them is unconfigured means the two that would have
    #: worked mirror nothing. That is how the nightly `asset_sources`
    #: step managed to refresh no register at all -- it runs `--source
    #: all`, and the very first source needs a DSN this project does not
    #: have, so it exited before reaching any of the others.
    tolerate_failures = args.source == "all"
    skipped: list[tuple[str, str]] = []

    def _run(name: str, fn) -> None:
        """Run one source inside a SAVEPOINT so a failure rolls back only
        that source's writes, never the batch's."""
        if name not in want:
            return
        cur.execute(f"SAVEPOINT src_{name}")
        try:
            summary.append((name, fn()))
        except SystemExit as exc:
            if not tolerate_failures:
                raise
            cur.execute(f"ROLLBACK TO SAVEPOINT src_{name}")
            skipped.append((name, str(exc).strip().splitlines()[0]))
        else:
            cur.execute(f"RELEASE SAVEPOINT src_{name}")

    conn = psycopg2.connect(TARGET_DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            cur.execute(DDL)

            def _video() -> int:
                # Same DSN-or-PostgREST fallback as the influencer
                # sources. asset_register has RLS enabled but still
                # serves these rows to the publishable key, so the video
                # mirror no longer needs a database password -- it had
                # been frozen at the one-shot 2026-09-01 migration (436
                # of 955 assets) for want of one.
                if os.environ.get("ASSET_REGISTER_DB_URL"):
                    rows = _pull_supabase("ASSET_REGISTER_DB_URL", "asset_register",
                                          VIDEO_COLUMNS, VIDEO_SOURCE_MATCH)
                else:
                    rows = _pull_postgrest(
                        "asset_register", VIDEO_COLUMNS, VIDEO_SOURCE_MATCH,
                        query="asset_id=not.is.null",
                        base_env="ASSET_REGISTER_REST_URL",
                        key_env="ASSET_REGISTER_ANON_KEY")
                return _upsert(cur, "content_asset_register", "asset_id",
                               VIDEO_COLUMNS + list(VIDEO_SOURCE_MATCH.values()), rows)

            _run("video", _video)

            def _influencer() -> int:
                # DSN when configured, PostgREST otherwise -- same
                # fallback the historic source uses. `posts` has RLS
                # ENABLED (unlike historic_posts), but the policy still
                # serves these rows to the publishable key, so the live
                # mirror no longer needs a database password either.
                # Verified live 2026-09-17; without the
                # post_id_short filter the first rows come back with a
                # null post_id, which is what made this look blocked.
                if os.environ.get("CREATORHUB_DB_URL"):
                    rows = _pull_supabase(
                        "CREATORHUB_DB_URL", "posts",
                        INFLUENCER_COLUMNS, INFLUENCER_SOURCE_MATCH,
                        where="WHERE post_id IS NOT NULL "
                              "AND COALESCE(is_test, false) = false")
                else:
                    rows = _pull_postgrest(
                        "posts", INFLUENCER_COLUMNS, INFLUENCER_SOURCE_MATCH,
                        query="post_id=not.is.null&is_test=not.is.true")
                cols = INFLUENCER_COLUMNS + list(INFLUENCER_SOURCE_MATCH.values())
                # post_id, NOT id -- see the docstring's id-collision note.
                return _upsert(cur, "content_influencer_posts", "post_id",
                               cols + ["source_table"],
                               [tuple(r) + ("posts",) for r in rows])


            def _historic() -> int:
                # DSN if one is configured, PostgREST otherwise: this
                # table has RLS disabled, so the publishable key is
                # enough and the mirror stops being blocked on a DB
                # password.
                if os.environ.get("CREATORHUB_DB_URL"):
                    rows = _pull_supabase("CREATORHUB_DB_URL", "historic_posts",
                                          HISTORIC_INFLUENCER_COLUMNS,
                                          INFLUENCER_SOURCE_MATCH,
                                          where="WHERE post_id IS NOT NULL")
                else:
                    rows = _pull_postgrest("historic_posts",
                                           HISTORIC_INFLUENCER_COLUMNS,
                                           INFLUENCER_SOURCE_MATCH,
                                           query="post_id=not.is.null")
                cols = HISTORIC_INFLUENCER_COLUMNS + list(INFLUENCER_SOURCE_MATCH.values())
                return _upsert(cur, "content_influencer_posts", "post_id",
                               cols + ["source_table"],
                               [tuple(r) + ("historic_posts",) for r in rows])

            _run("historic", _historic)
            # AFTER historic, deliberately: all influencer sources upsert
            # on post_id and the last write wins, so the maintained live
            # table must be the one that lands last.
            _run("influencer", _influencer)

            def _iterated() -> int:
                cols, rows = _iterated_rows()
                return _upsert(cur, "content_iterated_register",
                               "requisition_id, nomenclature", cols, rows)

            _run("iterated", _iterated)

            # Historic BEFORE live, deliberately: both upsert into
            # content_graphic_register keyed on requisition_id, so if a
            # requisition appears in both tabs the one written LAST wins.
            # The live tab is the maintained one, so it goes second.
            def _graphics(tab_env: str, default_tab: str, gid_env: str,
                          sheet_env: str = "GRAPHICS_SHEET_ID"):
                def run() -> int:
                    cols, rows = _graphics_rows(
                        os.environ.get(tab_env, default_tab),
                        os.environ.get(gid_env),
                        os.environ.get(sheet_env),
                    )
                    return _upsert(cur, "content_graphic_register",
                                   "requisition_id", cols, rows)
                return run

            _run("graphics_historic",
                 _graphics("GRAPHICS_HISTORIC_TAB", "Graphics",
                           "GRAPHICS_HISTORIC_GID", "GRAPHICS_HISTORIC_SHEET_ID"))
            _run("graphics",
                 _graphics("GRAPHICS_SHEET_TAB", "Performance Ad Req",
                           "GRAPHICS_SHEET_GID"))

            if args.dry_run:
                conn.rollback()
                print("[pg] ROLLED BACK -- --dry-run, nothing written", flush=True)
            else:
                conn.commit()
    finally:
        conn.close()

    print(f"\n[OK] asset sources mirrored in {time.time() - t0:.1f}s")
    for name, n in summary:
        print(f"    {name:<18} {n:>7,} rows")
    if skipped:
        print("\n    SKIPPED -- these sources are unconfigured, the rest still ran:")
        for name, why in skipped:
            print(f"      {name:<18} {why}")
    # Non-zero when NOTHING mirrored: a run that skipped every source is
    # a failed run, and the nightly pipeline should see it as one.
    return 0 if summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
