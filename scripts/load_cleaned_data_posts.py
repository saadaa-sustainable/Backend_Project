"""Load influencer posts from a creatorhub `cleaned_data` export.

WHY THIS SOURCE IS A FILE AND NOT AN API CALL
---------------------------------------------
337+ influencer assets referenced by live ads exist in creatorhub ONLY in
`public.cleaned_data`. They are missing from `posts` and `historic_posts`
because their id extraction failed upstream -- both `sif_id` and
`post_id` hold the literal string 'SIF_ERROR', and the real id survives
only as the prefix of `nomenclature`:

    sif_id        SIF_ERROR
    post_id       SIF_ERROR
    nomenclature  SIF-1705-P1-drushti.ramrakhyani- VRP-12/20/2026

The other creatorhub tables are mirrored over PostgREST with the
publishable key, but `cleaned_data` cannot be: it has RLS enabled and
NO policy, so it default-denies and PostgREST returns 200 with zero rows
(`content-range: */0`) rather than an error. Adding an anon-read policy
would work but would expose that table's influencer contact details and
customer order/payment columns to anyone holding the publishable key, so
the file route was chosen instead.

WHERE THE ID COMES FROM
-----------------------
Strictly the canonical `SIF-<n>-P<n>` anchored at the START of
`nomenclature`, or a `sif_id`/`post_id` that is already canonical. A row
whose nomenclature does not begin with a canonical id is SKIPPED -- the
id is never guessed from elsewhere in the string, because the
nomenclature's own convention puts it first and a match found anywhere
else would be a coincidence.

Rows land with source_table='cleaned_data' so they stay distinguishable,
and the upsert is keyed on post_id, so a later real mirror of `posts`
overwrites them cleanly.

Usage:
    ./.venv/bin/python scripts/load_cleaned_data_posts.py
    ./.venv/bin/python scripts/load_cleaned_data_posts.py --file path/to/export.csv
    ./.venv/bin/python scripts/load_cleaned_data_posts.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

DSN = (os.environ["DATABASE_URL_SYNC"]
       .replace("postgresql+psycopg2://", "postgresql://").split("?")[0])

#: Looked for in order; the first that exists is used.
DEFAULT_FILES = (
    ROOT / "data" / "creatorhub_cleaned_data.csv",
    ROOT / "data" / "creatorhub_cleaned_data_posts.tsv",
)

#: Canonical influencer id, anchored to the start of the nomenclature.
_CANON = re.compile(r"^\s*(SIF-[0-9]{1,6}-P[0-9]{1,3})", re.I)
#: The same shape, for validating an id column that may hold 'SIF_ERROR'.
_IS_CANON = re.compile(r"^\s*SIF-[0-9]{1,6}-P[0-9]{1,3}\s*$", re.I)

#: Export header -> the column this script needs. Matched case- and
#: whitespace-insensitively; every other column in the export is ignored,
#: which is most of them (the table has ~87).
HEADER_MAP = {
    "nomenclature": "nomenclature",
    "username": "username",
    "ig_handle": "username",
    "content_type": "content_type",
    "post_date": "post_date",
    "sif_id": "sif_id",
    "post_id": "post_id",
    "link_to_post": "post_link",
    "content_downloaded_link": "download_link",
    "collab_type": "collab_type",
    "campaign_id": "campaign_id",
}

#: Date spellings seen in these exports. Anything else -> NULL: a post
#: with an unparseable date is still a real asset and must not be dropped
#: over a display field.
_FMTS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d %b %Y", "%d-%m-%Y", "%m/%d/%Y")

COLUMNS = ["post_id", "post_id_short", "nomenclature", "username", "content_type",
           "post_date", "collab_type", "campaign_id", "post_link", "download_link",
           "source_table", "mirrored_at"]

INSERT = f"""
INSERT INTO public.content_influencer_posts ({', '.join(COLUMNS)})
VALUES %s
ON CONFLICT (post_id) DO UPDATE SET
    nomenclature  = COALESCE(EXCLUDED.nomenclature,  content_influencer_posts.nomenclature),
    username      = COALESCE(EXCLUDED.username,      content_influencer_posts.username),
    content_type  = COALESCE(EXCLUDED.content_type,  content_influencer_posts.content_type),
    post_date     = COALESCE(EXCLUDED.post_date,     content_influencer_posts.post_date),
    collab_type   = COALESCE(EXCLUDED.collab_type,   content_influencer_posts.collab_type),
    campaign_id   = COALESCE(EXCLUDED.campaign_id,   content_influencer_posts.campaign_id),
    post_link     = COALESCE(EXCLUDED.post_link,     content_influencer_posts.post_link),
    download_link = COALESCE(EXCLUDED.download_link, content_influencer_posts.download_link),
    source_table  = EXCLUDED.source_table,
    mirrored_at   = now()
"""


def _date(raw: str | None) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for f in _FMTS:
        try:
            return datetime.strptime(raw, f).date().isoformat()
        except ValueError:
            continue
    return None


def _canonical_id(rec: dict[str, str]) -> str | None:
    """The asset id, from an id column if it is real, else the nomenclature."""
    for key in ("sif_id", "post_id"):
        val = (rec.get(key) or "").strip()
        if val and _IS_CANON.match(val):
            return val.upper()
    hit = _CANON.match(rec.get("nomenclature") or "")
    return hit.group(1).upper() if hit else None


def _read(path: Path) -> list[dict[str, str]]:
    """Read the export, whether it is the full CSV or the 5-column TSV."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    delim = "\t" if path.suffix.lower() == ".tsv" or "\t" in raw.split("\n")[0] else ","
    rows = list(csv.reader(raw.splitlines(), delimiter=delim))
    if not rows:
        return []

    header = [h.strip().lower() for h in rows[0]]
    known = {i: HEADER_MAP[h] for i, h in enumerate(header) if h in HEADER_MAP}
    if "nomenclature" in known.values():
        unmapped = sorted({h for i, h in enumerate(header) if h and i not in known})
        if unmapped:
            print(f"    ignoring {len(unmapped)} unmapped column(s)", flush=True)
        return [
            {known[i]: (r[i].strip() if i < len(r) else "") for i in known}
            for r in rows[1:]
        ]

    # Headerless 5-column TSV: id, nomenclature, username, content_type, post_date
    print("    no recognised header -- reading as the 5-column TSV", flush=True)
    out = []
    for r in rows:
        if not r or not r[0].strip():
            continue
        r = (r + [""] * 5)[:5]
        out.append({"sif_id": r[0], "nomenclature": r[1], "username": r[2],
                    "content_type": r[3], "post_date": r[4]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=None, help="export to load (csv or tsv).")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and report, then ROLL BACK.")
    args = ap.parse_args()

    path = Path(args.file) if args.file else next((p for p in DEFAULT_FILES if p.exists()), None)
    if path is None or not path.exists():
        raise SystemExit(
            "No export found. Put the cleaned_data export at "
            f"{DEFAULT_FILES[0].relative_to(ROOT)} or pass --file."
        )
    print(f"reading {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")

    recs = _read(path)
    seen: set[str] = set()
    rows: list[tuple] = []
    skipped = 0
    for rec in recs:
        pid = _canonical_id(rec)
        if not pid or pid in seen:
            skipped += 1 if not pid else 0
            continue
        seen.add(pid)
        rows.append((
            pid, pid, rec.get("nomenclature") or None, rec.get("username") or None,
            rec.get("content_type") or None, _date(rec.get("post_date")),
            rec.get("collab_type") or None, rec.get("campaign_id") or None,
            rec.get("post_link") or None, rec.get("download_link") or None,
            "cleaned_data", datetime.now(),
        ))
    print(f"    {len(recs):,} rows read, {len(rows):,} distinct canonical ids, "
          f"{skipped:,} without one")
    if not rows:
        raise SystemExit("Nothing to load -- no row had a canonical SIF id.")

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            cur.execute("SELECT COUNT(*) FROM public.content_influencer_posts")
            before = cur.fetchone()[0]
            psycopg2.extras.execute_values(cur, INSERT, rows, page_size=500)
            cur.execute("SELECT COUNT(*) FROM public.content_influencer_posts")
            after = cur.fetchone()[0]
            if args.dry_run:
                conn.rollback()
                print(f"\n[pg] ROLLED BACK -- would be {before:,} -> {after:,} "
                      f"(+{after - before:,} new)")
            else:
                conn.commit()
                print(f"\n[OK] content_influencer_posts {before:,} -> {after:,} "
                      f"(+{after - before:,} new)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
