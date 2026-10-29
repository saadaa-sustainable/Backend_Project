#!/usr/bin/env python
"""Per-ad attribution setting, from an Ads Manager export.

WHY A FILE AND NOT THE API
--------------------------
`attribution_setting` is already a column on ad_lifecycle, ad_insights,
adset_insights and campaign_insights, and it was populated until
2026-08-13. It is null for everything newer -- including all 1,140
currently ACTIVE ads -- because `_INSIGHTS_METRICS` in
scripts/ingest_last_15_days.py stopped asking Meta for the field:
462,726 insight rows fetched in the 20 days to 2026-10-29 carry no
`attribution_setting` key at all.

Putting the field back in that list is the durable fix and makes this
script redundant. Until then this loads the same values from an export.

EXPORT IT AS CSV, NOT XLSX
--------------------------
Meta's ad ids are 18 digits. Excel stores them as float64, which holds
~15-16 significant digits, so an .xlsx export silently rounds the last
three to zero: 120231901884260431 arrives as 120231901884260000. Every
one of the 2,905 ids in the .xlsx export of 2026-10-29 was corrupted
this way and NONE of them matched a real ad. The .csv of the same
report keeps them as text and all 2,905 match.

A correct id ends in the account suffix (431 for Fourth Ad Account),
never in 000; the loader refuses a file where that does not hold.

WHY ITS OWN TABLE
-----------------
ad_lifecycle is TRUNCATEd and rebuilt, so a value written into it
directly is gone on the next refresh. This mirrors `ad_metrics_external`
instead: a standalone table the rebuild overlays from, which is the
pattern that table already established.

Usage:
    .venv/bin/python scripts/ingest_ad_attribution.py path/to/export.csv
    .venv/bin/python scripts/ingest_ad_attribution.py export.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.dbq import connect  # noqa: E402

TABLE = "public.meta_ad_attribution"

#: Ads Manager writes the human label; every other table in this project
#: carries Meta's own code, because that is what the API returns. Both
#: are stored: the code to join on, the label to show.
#:
#: The six codes are exactly those `ad_insights` already holds from the
#: API, so a row loaded here and a row fetched before 2026-08-13 compare
#: without translating either.
SETTING_CODES = {
    "1-day click": "1d_click",
    "7-day click": "7d_click",
    "7-day click or 1-day view": "1d_view_7d_click",
    "7-day click or 1-day engaged view": "7d_click_1d_ev",
    "7-day click, 1-day view or 1-day engaged view": "1d_view_7d_click_1d_ev",
    "Incremental": "incrementality",
}

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    ad_id                 text PRIMARY KEY,
    adset_id              text,
    ad_name               text,
    adset_name            text,
    -- Meta's code, e.g. 7d_click. What everything joins on.
    attribution_setting   text NOT NULL,
    -- The label as Ads Manager wrote it, kept verbatim so a value this
    -- loader has no code for is still visible rather than discarded.
    attribution_label     text NOT NULL,
    source_file           text NOT NULL,
    loaded_at             timestamptz NOT NULL DEFAULT now()
)
"""

UPSERT = f"""
INSERT INTO {TABLE}
    (ad_id, adset_id, ad_name, adset_name,
     attribution_setting, attribution_label, source_file)
VALUES %s
ON CONFLICT (ad_id) DO UPDATE SET
    adset_id            = EXCLUDED.adset_id,
    ad_name             = EXCLUDED.ad_name,
    adset_name          = EXCLUDED.adset_name,
    attribution_setting = EXCLUDED.attribution_setting,
    attribution_label   = EXCLUDED.attribution_label,
    source_file         = EXCLUDED.source_file,
    loaded_at           = now()
"""


def read_rows(path: pathlib.Path) -> list[dict]:
    # utf-8-sig: Ads Manager writes a BOM, which otherwise lands in the
    # first header and makes "Reporting starts" unfindable by name.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [r for r in csv.DictReader(handle) if (r.get("Ad ID") or "").strip()]


def check_ids(ids: list[str]) -> None:
    """Refuse a file whose ids were rounded by a spreadsheet."""
    rounded = [i for i in ids if i.endswith("000")]
    if rounded:
        raise SystemExit(
            f"[ABORT] {len(rounded):,} of {len(ids):,} ad ids end in '000', which is "
            f"what a spreadsheet leaves behind when it stores an 18-digit id as a "
            f"float (120231901884260431 -> 120231901884260000).\n"
            f"        Example: {rounded[0]}\n"
            f"        Re-export the report as CSV, or import it with the id columns "
            f"typed as Text, and run this again.")
    bad = [i for i in ids if not i.isdigit() or len(i) < 15]
    if bad:
        raise SystemExit(f"[ABORT] {len(bad):,} ad ids are not 15+ digit numbers, "
                         f"e.g. {bad[0]!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv_path", type=pathlib.Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.csv_path)
    if not rows:
        raise SystemExit("[ABORT] no rows with an Ad ID")
    ids = [r["Ad ID"].strip() for r in rows]
    check_ids(ids)

    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        raise SystemExit(f"[ABORT] {len(dupes):,} ad ids appear more than once, "
                         f"e.g. {dupes[0]}. One row per ad is expected.")

    unknown = Counter()
    tuples = []
    for r in rows:
        label = (r.get("Attribution setting") or "").strip()
        code = SETTING_CODES.get(label)
        if code is None:
            unknown[label] += 1
            # Kept, not dropped: an unmapped label is still the truth
            # about that ad, and silently losing it would make the
            # section under-count without saying so.
            code = label or "(unset)"
        tuples.append((
            r["Ad ID"].strip(), (r.get("Ad set ID") or "").strip() or None,
            (r.get("Ad name") or "").strip() or None,
            (r.get("Ad set name") or "").strip() or None,
            code, label or "(unset)", args.csv_path.name,
        ))

    print(f"{args.csv_path.name}: {len(tuples):,} ads")
    for label, n in Counter(r[5] for r in tuples).most_common():
        print(f"   {n:>5}  {label}  ->  {SETTING_CODES.get(label, '(no code)')}")
    if unknown:
        print("  labels with no known code, stored verbatim:")
        for label, n in unknown.most_common():
            print(f"   {n:>5}  {label!r}")

    if args.dry_run:
        print("\n[DRY RUN] nothing written")
        return 0

    import psycopg2.extras  # noqa: PLC0415 -- only needed on the write path

    with connect() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        psycopg2.extras.execute_values(cur, UPSERT, tuples, page_size=500)
        conn.commit()
        cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT COUNT(*) FROM {TABLE} a
            WHERE NOT EXISTS (SELECT 1 FROM public.ad_lifecycle l WHERE l.ad_id = a.ad_id)
        """)
        orphans = cur.fetchone()[0]

    print(f"\n[OK] {len(tuples):,} rows written, {total:,} in {TABLE}")
    if orphans:
        # Not an error: the export is a different window from our ingest,
        # so it can name ads this project never pulled.
        print(f"     {orphans:,} carry an ad_id ad_lifecycle does not have")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
