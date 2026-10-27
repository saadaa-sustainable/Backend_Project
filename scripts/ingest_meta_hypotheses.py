"""Mirror the Meta hypothesis-testing sheet into Postgres.

The sheet is the team's own record of every test run on Meta: what was
hypothesised, which campaign or ad set carried it, the primary KPI, and
what came of it. Meta exposes no notion of an experiment, so this sheet
IS the experiment register and the dashboard can only read it.

Every column is mirrored as written, including the free-text ones. The
dashboard section shows the sheet's own headers, so narrowing the schema
here would silently drop what the team actually recorded.

MATCHING, and why only part of it resolves

`Campaign/Adset Name/ Ad Name` is hand-typed and drifts from Meta. Of 62
distinct names measured 2026-10-27: 28 resolve exactly to a campaign or
ad set, 4 only with a LIKE, and 30 match nothing at all. None match an
ad name, despite the header. It is not a history problem -- the roster
reaches back to 2022-06-14.

So the match is stored per row (`matched_level`, `matched_id`) and left
NULL where it fails, rather than guessed. An unmatched test is still a
real test and still shown; it just carries no Meta metrics.

A cell may hold SEVERAL names on separate lines (5 of 65 do). They are
kept in `entity_names` as an array, and the first one that resolves wins.

Usage:
    .venv/bin/python scripts/ingest_meta_hypotheses.py
    .venv/bin/python scripts/ingest_meta_hypotheses.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import pathlib
import re
import sys
import urllib.request
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from scripts.dbq import connect  # noqa: E402  -- owns the DSN; see CLAUDE.md

DEFAULT_SHEET_ID = "1SOzvtg3y-njNGCypIpV9n4Fiwc40z8LZN3ZmoiX0w5g"
DEFAULT_GID = "1626951161"

#: Sheet header -> column. Order is the sheet's, so the dashboard can
#: render the tests exactly as the team records them.
COLUMNS: list[tuple[str, str]] = [
    ("Date",                         "test_date"),
    ("Month of testing ",            "month_of_testing"),
    ("Test Category",                "test_category"),
    ("Hypothesis Code",              "hypothesis_code"),
    ("Hypothesis & Objective",       "hypothesis"),
    ("Test Status",                  "test_status"),
    ("Primary KPI",                  "primary_kpi"),
    ("Success Criteria",             "success_criteria"),
    ("Test Threshold",               "test_threshold"),
    ("confidence interval",          "confidence_interval"),
    ("supp metrics",                 "supporting_metrics"),
    ("Budget Allocated/Day",         "budget_per_day"),
    ("Launch Date",                  "launch_date"),
    ("Ad Account",                   "ad_account"),
    ("Campaign/Adset Name/ Ad Name", "entity_raw"),
    ("Completion Date",              "completion_date"),
    ("Total Ad Spend",               "total_ad_spend"),
    ("Performance Summary",          "performance_summary"),
    ("Key Insights - Audience",      "insight_audience"),
    ("Key Insights - Creative",      "insight_creative"),
    ("Key Insights - Extra",         "insight_extra"),
    ("KPI Change (Before vs After)", "kpi_change"),
    ("Outcome & Next Steps",         "outcome_next_steps"),
    ("Test Detail Link",             "detail_link"),
    ("Test Result",                  "test_result"),
]

#: Written as text, not date, on purpose. The sheet holds '26-Sep-2024',
#: '26/10/2024' and '8-2026' in the same columns, and a parse that
#: guesses between them would invent precision the record does not have.
#: `*_parsed` below carries a date ONLY where the format is unambiguous.
DATE_FIELDS = ("test_date", "launch_date", "completion_date")

#: Applied on every run so the table self-migrates, the way it was first
#: created. The important part is `source`: the sheet and the dashboard
#: each own their own rows.
#:
#: Without it this ingest would destroy anything the team enters in the
#: dashboard -- it ends with
#:     DELETE ... WHERE row_index > max(sheet row)
#: which would take every dashboard row with it on the next sync.
MIGRATE = """
ALTER TABLE public.meta_hypothesis_tests
    ADD COLUMN IF NOT EXISTS id         bigserial,
    ADD COLUMN IF NOT EXISTS source     text NOT NULL DEFAULT 'sheet',
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS created_by text;

DO $$
BEGIN
    -- Order matters: row_index cannot drop NOT NULL while it is still
    -- part of the primary key, so the constraint goes first.
    IF EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'meta_hypothesis_tests_pkey'
                  AND conrelid = 'public.meta_hypothesis_tests'::regclass) THEN
        ALTER TABLE public.meta_hypothesis_tests
            DROP CONSTRAINT meta_hypothesis_tests_pkey;
    END IF;

    ALTER TABLE public.meta_hypothesis_tests ALTER COLUMN row_index DROP NOT NULL;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'meta_hypothesis_tests_id_pkey'
                      AND conrelid = 'public.meta_hypothesis_tests'::regclass) THEN
        ALTER TABLE public.meta_hypothesis_tests
            ADD CONSTRAINT meta_hypothesis_tests_id_pkey PRIMARY KEY (id);
    END IF;
END $$;

-- row_index is the SHEET's index, so it can only be unique among sheet
-- rows. Dashboard rows carry NULL there and are keyed on id.
CREATE UNIQUE INDEX IF NOT EXISTS meta_hypothesis_sheet_row
    ON public.meta_hypothesis_tests (row_index) WHERE source = 'sheet';
"""

DDL = """
CREATE TABLE IF NOT EXISTS public.meta_hypothesis_tests (
    row_index            integer PRIMARY KEY,
    test_date            text,
    test_date_parsed     date,
    month_of_testing     text,
    test_category        text,
    hypothesis_code      text,
    hypothesis           text,
    test_status          text,
    primary_kpi          text,
    success_criteria     text,
    test_threshold       text,
    confidence_interval  text,
    supporting_metrics   text,
    budget_per_day       text,
    launch_date          text,
    launch_date_parsed   date,
    ad_account           text,
    entity_raw           text,
    entity_names         text[],
    matched_level        text,
    matched_id           text,
    matched_name         text,
    completion_date      text,
    completion_date_parsed date,
    total_ad_spend       text,
    performance_summary  text,
    insight_audience     text,
    insight_creative     text,
    insight_extra        text,
    kpi_change           text,
    outcome_next_steps   text,
    detail_link          text,
    test_result          text,
    ingested_at          timestamptz NOT NULL DEFAULT now()
);
"""

#: Day-first throughout: the sheet is kept by an India-based team and
#: values like 17/10/25 and 20/06/26 have a day > 12, which settles the
#: order. The two-digit-year variants were missing at first and silently
#: dropped HALF the filled launch dates -- 30 of 60 parsed -- which made
#: the register look far emptier than it is.
_FORMATS = ("%d-%b-%Y", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d",
            "%d-%b-%y", "%d.%m.%Y", "%d-%m-%Y", "%d-%m-%y",
            "%d %b %Y", "%b %d, %Y")


def parse_date(value: str) -> date | None:
    """A date only where the format is unambiguous; None otherwise."""
    v = (value or "").strip()
    if not v or not re.search(r"\d", v):
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def fetch_csv(sheet_id: str, gid: str) -> list[dict]:
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
           f"/export?format=csv&gid={gid}")
    req = urllib.request.Request(url, headers={"User-Agent": "saadaa-dashboard"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.status != 200:
            raise SystemExit(f"Sheet returned HTTP {resp.status}. Is it link-shared?")
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def split_names(cell: str) -> list[str]:
    """A cell may list several entities on separate lines."""
    return [p.strip() for p in (cell or "").split("\n") if p.strip()]


def resolve(conn, names: list[str]) -> tuple[str | None, str | None, str | None]:
    """(level, id, name) for the first name that resolves. Exact first,
    across BOTH levels, before falling back to a LIKE -- an exact ad-set
    hit beats a fuzzy campaign hit."""
    if not names:
        return None, None, None
    with conn.cursor() as cur:
        for sql, level in (
            ("SELECT campaign_id, campaign_name FROM public.meta_campaigns WHERE campaign_name = %s LIMIT 1", "campaign"),
            ("SELECT adset_id, adset_name FROM public.meta_adsets WHERE adset_name = %s LIMIT 1", "adset"),
        ):
            for name in names:
                cur.execute(sql, (name,))
                row = cur.fetchone()
                if row:
                    return level, row[0], row[1]
        for sql, level in (
            ("SELECT campaign_id, campaign_name FROM public.meta_campaigns WHERE campaign_name ILIKE %s LIMIT 1", "campaign~"),
            ("SELECT adset_id, adset_name FROM public.meta_adsets WHERE adset_name ILIKE %s LIMIT 1", "adset~"),
        ):
            for name in names:
                cur.execute(sql, (f"%{name}%",))
                row = cur.fetchone()
                if row:
                    return level, row[0], row[1]
    return None, None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sheet-id", default=os.environ.get("HYPOTHESIS_SHEET_ID", DEFAULT_SHEET_ID))
    ap.add_argument("--gid", default=os.environ.get("HYPOTHESIS_SHEET_GID", DEFAULT_GID))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = fetch_csv(args.sheet_id, args.gid)
    print(f"sheet: {len(rows)} rows, {len(COLUMNS)} mapped columns")

    missing = [h for h, _ in COLUMNS if rows and h not in rows[0]]
    if missing:
        # Loud, because a renamed header would otherwise import as NULL
        # and look like the team simply stopped filling that field in.
        raise SystemExit(f"These sheet headers are missing: {missing}. "
                         "Rename them back or update COLUMNS.")

    with connect(autocommit=False, statement_timeout="120s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute(MIGRATE)
        conn.commit()

        prepared, matched = [], 0
        for i, raw in enumerate(rows):
            rec = {col: (raw.get(hdr) or "").strip() or None for hdr, col in COLUMNS}
            # Drop rows that are entirely empty -- the sheet has trailing ones.
            if not any(rec.values()):
                continue
            names = split_names(rec.get("entity_raw") or "")
            level, mid, mname = resolve(conn, names)
            if level:
                matched += 1
            rec["row_index"] = i
            rec["entity_names"] = names or None
            rec["matched_level"] = level
            rec["matched_id"] = mid
            rec["matched_name"] = mname
            for f in DATE_FIELDS:
                rec[f + "_parsed"] = parse_date(rec.get(f) or "")
            prepared.append(rec)

        print(f"  {len(prepared)} non-empty rows, {matched} resolved to a Meta entity "
              f"({100.0 * matched / max(len(prepared), 1):.0f}%)")

        if args.dry_run:
            print("  --dry-run: nothing written")
            return 0

        cols = (["row_index"] + [c for _, c in COLUMNS]
                + [f + "_parsed" for f in DATE_FIELDS]
                + ["entity_names", "matched_level", "matched_id", "matched_name"])
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "row_index")
        sql = (f"INSERT INTO public.meta_hypothesis_tests ({', '.join(cols)}, source) "
               f"VALUES ({placeholders}, 'sheet') "
               f"ON CONFLICT (row_index) WHERE source = 'sheet' "
               f"DO UPDATE SET {updates}, ingested_at = now(), updated_at = now()")
        with conn.cursor() as cur:
            # Rows removed from the sheet must not linger as ghosts.
            # Sheet rows ONLY. A dashboard-entered hypothesis is not a
            # ghost of a deleted sheet row and must survive every sync.
            cur.execute("DELETE FROM public.meta_hypothesis_tests "
                        " WHERE source = 'sheet' AND row_index > %s",
                        (max(r["row_index"] for r in prepared),))
            for rec in prepared:
                cur.execute(sql, [rec.get(c) for c in cols])
        conn.commit()

    print(f"[OK] {len(prepared)} hypothesis rows written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
