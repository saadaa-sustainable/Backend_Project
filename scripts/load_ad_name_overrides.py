"""Load hand-supplied utm_content -> ad_name mappings.

WHY A MANUAL TABLE EXISTS AT ALL
--------------------------------
The cascade refuses to guess, and that refusal is correct: measured on a
30-day window, `TW_onseventhsky_IFAD_230425` names seven different ads
across seven ad sets, none of them the ad set the click came from, and
`ADB_SDTJ_240924_W+ - Copy` names four. No rule can pick one of those
without inventing evidence.

A person can. Someone who knows which ad actually ran can say so, and
that is real evidence the data does not carry. This table is where that
knowledge goes -- explicit, reviewable, and attributable to a human
rather than smuggled in as a looser matching rule that would also fire
on cases nobody checked.

SCOPING -- adset_id IS THE ORDER'S AD SET, NOT THE AD'S
-------------------------------------------------------
A mapping is keyed on (utm_content, adset_id), where adset_id is the
ad set the ORDER came from -- the value in its utm_term. It is NOT
where the named ad currently lives.

The distinction matters because it is the whole reason this table
exists. In the ambiguous cases the named ad is deliberately somewhere
else: orders clicked through ad set A carry a name whose ad sits in ad
set B, and the mapping being expressed is "orders from A naming this
mean that ad in B". Requiring the ad to be in A would reject exactly
the rows worth writing.

Leaving adset_id out (or passing '*') applies the mapping wherever the
utm_content appears, which is right when the name means one thing
account-wide.

WHAT IS REFUSED
---------------
An override still has to name something real. A row is rejected, loudly
and individually, when:

  * neither ad_name nor ad_id is given;
  * the ad_name matches no ad in the account;
  * the ad_name matches several ads and no ad_id was given to say which
    -- the report prints the candidates so the choice can be made;
  * an ad_id is given that the account does not have.

Rejections do not fail the run -- the accepted rows still load, and the
report names every rejected row and why, so a typo is obvious.

INPUT FORMAT
------------
CSV or TSV, header optional. Recognised columns, matched
case-insensitively (any others are ignored):

    utm_content   required -- the value the order carried
    ad_name       the ad it should resolve to (or give ad_id instead)
    ad_id         optional -- settles an ambiguous ad_name outright
    adset_id      optional -- the ORDER's ad set; also accepted as utm_term
    adset_name    optional -- ignored, kept for readability
    note          optional -- why, for whoever reads this later

Without a header, two columns are read as utm_content, ad_name and
three as utm_content, ad_name, adset_id.

Usage:
    ./.venv/bin/python scripts/load_ad_name_overrides.py --file data/overrides.tsv --dry-run
    ./.venv/bin/python scripts/load_ad_name_overrides.py --file data/overrides.tsv
    ./.venv/bin/python scripts/load_ad_name_overrides.py --list
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

DSN = (
    os.environ["DATABASE_URL_SYNC"]
    .replace("postgresql+psycopg2://", "postgresql://")
    .split("?")[0]
)

ANY_ADSET = "*"

DDL = """
CREATE TABLE IF NOT EXISTS public.ad_name_override (
    utm_content_lower text NOT NULL,
    -- '*' means "any ad set". A real id scopes the mapping to that ad
    -- set, which is the whole point when a name is ambiguous.
    adset_id          text NOT NULL DEFAULT '*',
    ad_id             text NOT NULL,
    ad_name           text,
    note              text,
    -- NULL = this row is the sole mapping for its key. A number makes
    -- the key a WEIGHTED SPLIT: several ads share one utm_content and
    -- each takes a share of its orders proportional to weight.
    --
    -- Needed when two ads in one ad set carry the SAME name, which no
    -- matching rule can ever separate -- e.g. two Sep-682 ads both
    -- named SMCP_VRP_UB_US_916_Sep-682_03/10/2025_H0. The orders are
    -- real and belong to one of them; nothing in the data says which.
    weight            numeric,
    added_at          timestamptz NOT NULL DEFAULT now(),
    -- ad_id is part of the key so one utm_content can carry several
    -- weighted rows. Previously (utm_content_lower, adset_id) alone,
    -- which allowed exactly one ad per key.
    PRIMARY KEY (utm_content_lower, adset_id, ad_id)
);
CREATE INDEX IF NOT EXISTS ix_ad_name_override_ad_id
    ON public.ad_name_override (ad_id);
"""

#: Migrates the first shipped shape. Idempotent, no-op on a fresh table.
MIGRATIONS = ["""
ALTER TABLE public.ad_name_override ADD COLUMN IF NOT EXISTS weight numeric;
""", """
DO $$
DECLARE cols text;
BEGIN
    SELECT string_agg(a.attname, ',' ORDER BY k.ord) INTO cols
      FROM pg_constraint c
      JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
     WHERE c.conrelid = 'public.ad_name_override'::regclass AND c.contype = 'p';
    IF cols = 'utm_content_lower,adset_id' THEN
        ALTER TABLE public.ad_name_override DROP CONSTRAINT ad_name_override_pkey,
            ADD PRIMARY KEY (utm_content_lower, adset_id, ad_id);
    END IF;
END $$;
"""]

#: Ad id -> name -> adset, straight from the same two tables the
#: attribution universe is built from, so an override can only name an
#: ad the cascade could actually resolve.
UNIVERSE_SQL = """
SELECT COALESCE(al.ad_id, a.ad_id)                                        AS ad_id,
       COALESCE(NULLIF(BTRIM(al.ad_name), ''), NULLIF(BTRIM(a.ad_name), '')) AS ad_name,
       COALESCE(al.adset_id, a.adset_id)                                  AS adset_id
  FROM ad_lifecycle al
  FULL OUTER JOIN meta_ads a ON a.ad_id = al.ad_id
"""

INSERT = """
INSERT INTO public.ad_name_override
    (utm_content_lower, adset_id, ad_id, ad_name, note, weight)
VALUES %s
ON CONFLICT (utm_content_lower, adset_id, ad_id) DO UPDATE SET
    ad_name = EXCLUDED.ad_name, note = EXCLUDED.note,
    weight = EXCLUDED.weight, added_at = now()
"""

def _weight(rec: dict) -> float | None:
    """Parse an optional weight. Absent/blank means "sole mapping"."""
    raw = (rec.get("weight") or "").strip()
    if not raw:
        return None
    try:
        w = float(raw)
    except ValueError:
        return None
    # A non-positive share would silently take no orders while still
    # looking like a mapping someone wrote on purpose.
    return w if w > 0 else None


HEADER_MAP = {
    "utm_content": "utm_content", "utm content": "utm_content", "content": "utm_content",
    "ad_name": "ad_name", "ad name": "ad_name", "adname": "ad_name",
    "adset_id": "adset_id", "ad_set_id": "adset_id", "utm_term": "adset_id",
    "ad_id": "ad_id", "ad id": "ad_id",
    "adset_name": "adset_name", "ad set": "adset_name",
    "note": "note", "reason": "note",
    "weight": "weight", "share": "weight", "spend_weight": "weight",
}

#: Names are compared after the same normalisation live matching uses, so
#: a "- Copy" / "– Copy" difference in the sheet does not defeat a row.
_DASHES = r"\-‐‑‒–—―−"
_SUFFIX_RE = re.compile(
    rf"(?:[\s_{_DASHES}]+(?:copy(?:\s*\d+)?|[hc]\d+))+[\s_{_DASHES}]*$", re.IGNORECASE
)


def _norm(name: str) -> str:
    n = (name or "").strip()
    while True:
        new = _SUFFIX_RE.sub("", n).strip()
        if new == n:
            break
        n = new
    return re.sub(r"\s+", " ", n).strip().lower()


def _read(path: Path) -> list[dict[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []
    delim = "\t" if "\t" in lines[0] else ","
    rows = list(csv.reader(lines, delimiter=delim))
    header = [h.strip().lower() for h in rows[0]]
    known = {i: HEADER_MAP[h] for i, h in enumerate(header) if h in HEADER_MAP}

    # ad_id alone is a complete mapping -- the docstring above offers it
    # as an alternative to ad_name, and it is the STRONGER of the two
    # (an id cannot be ambiguous). Requiring ad_name here meant an
    # id-keyed file silently fell through to positional reading, which
    # then tried to resolve the id column as a name and rejected every
    # row with "no ad in the account has that name".
    if "utm_content" in known.values() and (
        "ad_name" in known.values() or "ad_id" in known.values()
    ):
        return [
            {known[i]: (r[i].strip() if i < len(r) else "") for i in known}
            for r in rows[1:]
        ]

    print("    no recognised header -- reading positionally", flush=True)
    out = []
    for r in rows:
        r = [c.strip() for c in r]
        if len(r) < 2 or not r[0] or not r[1]:
            continue
        rec = {"utm_content": r[0], "ad_name": r[1]}
        if len(r) > 2 and r[2]:
            rec["adset_id"] = r[2]
        out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=None, help="CSV/TSV of mappings.")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate and report, then ROLL BACK.")
    ap.add_argument("--list", action="store_true",
                    help="print the overrides currently loaded, then exit.")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            cur.execute(DDL)
            for _m in MIGRATIONS:
                cur.execute(_m)

            if args.list:
                cur.execute(
                    "SELECT utm_content_lower, adset_id, ad_id, ad_name, note "
                    "FROM public.ad_name_override ORDER BY added_at DESC"
                )
                rows = cur.fetchall()
                print(f"{len(rows):,} override(s) loaded\n")
                for uc, aset, aid, an, note in rows:
                    scope = "any adset" if aset == ANY_ADSET else f"adset {aset}"
                    print(f"  {uc[:52]:54} -> {an or aid} [{scope}]"
                          + (f"  ({note})" if note else ""))
                conn.rollback()
                return 0

            if not args.file:
                raise SystemExit("--file is required (or use --list).")
            path = Path(args.file)
            if not path.exists():
                raise SystemExit(f"No such file: {path}")

            # --- the universe an override is allowed to name ----------
            cur.execute(UNIVERSE_SQL)
            by_norm: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
            by_exact: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
            by_id: dict[str, str] = {}
            for ad_id, ad_name, adset_id in cur:
                if not ad_id or not ad_name:
                    continue
                by_id[ad_id] = ad_name
                by_exact[ad_name.strip().lower()].append((ad_id, ad_name, adset_id))
                by_norm[_norm(ad_name)].append((ad_id, ad_name, adset_id))
            print(f"universe: {len(by_exact):,} distinct ad names")

            recs = _read(path)
            print(f"read {len(recs):,} row(s) from {path.name}\n")

            accepted: list[tuple] = []
            rejected: list[tuple[str, str]] = []
            for rec in recs:
                uc = (rec.get("utm_content") or "").strip()
                an = (rec.get("ad_name") or "").strip()
                given_id = (rec.get("ad_id") or "").strip()
                aset = (rec.get("adset_id") or "").strip() or ANY_ADSET
                label = f"{uc[:40]} -> {(an or given_id)[:40]}"
                if not uc or not (an or given_id):
                    rejected.append((label, "utm_content and one of ad_name / ad_id are required"))
                    continue

                # An explicit ad_id settles it -- that is what it is for.
                if given_id:
                    if given_id not in by_id:
                        rejected.append((label, f"no ad in the account has id {given_id}"))
                        continue
                    accepted.append((uc.lower(), aset, given_id, by_id[given_id],
                                     (rec.get("note") or "").strip() or None,
                                     _weight(rec)))
                    continue

                cands = by_exact.get(an.lower()) or by_norm.get(_norm(an)) or []
                if not cands:
                    rejected.append((label, "no ad in the account has that name"))
                    continue
                ids = {c[0]: c[1] for c in cands}
                if len(ids) != 1:
                    # Print the choices rather than just refusing -- the
                    # next run only needs an ad_id pasted in.
                    shown = ", ".join(f"{i} ({n[:34]})" for i, n in list(ids.items())[:4])
                    more = f" +{len(ids) - 4} more" if len(ids) > 4 else ""
                    rejected.append((
                        label,
                        f"{len(ids)} ads share that name -- add an ad_id: {shown}{more}"))
                    continue
                ad_id, real_name = next(iter(ids.items()))
                accepted.append((uc.lower(), aset, ad_id, real_name,
                                 (rec.get("note") or "").strip() or None,
                                 _weight(rec)))

            print(f"{'outcome':<12}{'rows':>6}")
            print(f"{'accepted':<12}{len(accepted):>6}")
            print(f"{'rejected':<12}{len(rejected):>6}")
            if rejected:
                print("\nREJECTED -- nothing was written for these:")
                for what, why in rejected:
                    print(f"  {what:<84} {why}")
            if accepted:
                print("\nACCEPTED:")
                for uc, aset, ad_id, real_name, _note, weight in accepted[:40]:
                    scope = "any adset" if aset == ANY_ADSET else f"from adset {aset}"
                    share = "" if weight is None else f" weight={weight:g}"
                    print(f"  {uc[:50]:52} -> {real_name[:46]:48} [{scope}]{share}")
                if len(accepted) > 40:
                    print(f"  ... and {len(accepted) - 40:,} more")
                psycopg2.extras.execute_values(cur, INSERT, accepted, page_size=500)

            if args.dry_run:
                conn.rollback()
                print(f"\n[pg] ROLLED BACK -- --dry-run, nothing written")
            else:
                conn.commit()
                print(f"\n[OK] {len(accepted):,} override(s) written to ad_name_override")
                if accepted:
                    print("     Re-run attribution to apply them:")
                    print("       ./.venv/bin/python scripts/refresh_shopify_silver.py "
                          "--only-attribution")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
