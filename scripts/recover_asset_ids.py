"""Recover asset ids that ad names spell differently from the registers.

WHY
---
refresh_ad_asset_map.py matches an asset only when its id appears in the
ad name VERBATIM. That is the right default -- it cannot invent a match.
But the same id gets typed several ways at launch:

    register        ad name           what happened
    ITE-Feb-19      ITE_Feb19         separators dropped
    ITE-Apr-84      ITE_Apr-84        one separator dropped
    GAD-May-90      GAD_May90         separators dropped
    SIF-791-P1      SIF-0791-P1       numeric part zero-padded

Those are the SAME asset, written differently. This script recovers them.

THE RULE THAT MAKES THIS SAFE
-----------------------------
A recovered id is only ever a RE-SPELLING of a string already in the ad
name, and it is kept ONLY IF that canonical form exists in a register.
Nothing is invented: if the canonical id is not in the database the
candidate is dropped, because a mapping to an asset that does not exist
is worse than no mapping -- it would put a real ad's spend behind a
creative nobody can open.

Ambiguity is also refused. If a canonicalised id could belong to more
than one register row, or one ad yields two different canonical ids, the
ad is skipped rather than assigned a coin-flip.

The recovered pairs land in public.ad_asset_recovered, which
refresh_ad_asset_map.py unions in at the LOWEST priority -- a verbatim
match always wins over a recovered one.

Usage:
    ./.venv/bin/python scripts/recover_asset_ids.py --dry-run
    ./.venv/bin/python scripts/recover_asset_ids.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

DSN = (
    os.environ["DATABASE_URL_SYNC"]
    .replace("postgresql+psycopg2://", "postgresql://")
    .split("?")[0]
)

DDL = """
CREATE TABLE IF NOT EXISTS public.ad_asset_recovered (
    ad_id          text PRIMARY KEY,
    asset_id       text NOT NULL,
    media          text NOT NULL,
    ad_name        text,
    -- The exact substring found in the ad name, and what it canonicalised
    -- to. Both are kept so any recovered row can be audited by eye
    -- without re-deriving it.
    matched_form   text NOT NULL,
    canonical_form text NOT NULL,
    recovered_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ad_asset_recovered_asset
    ON public.ad_asset_recovered (asset_id);
"""

#: Three-letter month tokens as the registers spell them.
_MONTHS = {
    "jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr",
    "may": "May", "jun": "Jun", "jul": "Jul", "aug": "Aug",
    "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec",
}

#: Separator between id segments: dash, underscore, space, or nothing.
_SEP = r"[-_ ]?"


def _strip_leading_zeros(num: str) -> str:
    """'0791' -> '791'. '1000' -> '1000'. '000' -> '0'."""
    stripped = num.lstrip("0")
    return stripped or "0"


#: (media, compiled pattern, canonicaliser). The patterns are TOLERANT --
#: they accept the separator variants seen in real ad names -- while the
#: canonicaliser emits exactly one spelling, which is then looked up in
#: the register. Tolerance in reading, strictness in accepting.
FAMILIES: list[tuple[str, re.Pattern[str], object]] = [
    (
        "influencer",
        re.compile(rf"(?<![0-9A-Za-z])SIF{_SEP}([0-9]{{1,6}}){_SEP}P([0-9]{{1,3}})(?![0-9])", re.I),
        lambda m: f"SIF-{_strip_leading_zeros(m.group(1))}-P{_strip_leading_zeros(m.group(2))}",
    ),
    (
        "graphic",
        re.compile(rf"(?<![0-9A-Za-z])GAD{_SEP}([A-Za-z]{{3}}){_SEP}([0-9]{{1,5}})(?![0-9])", re.I),
        lambda m: f"GAD-{_MONTHS[m.group(1).lower()]}-{_strip_leading_zeros(m.group(2))}",
    ),
    (
        "video",  # iterated content reports as video, like the map does
        re.compile(rf"(?<![0-9A-Za-z])ITE{_SEP}([A-Za-z]{{3}}){_SEP}([0-9]{{1,5}})(?![0-9])", re.I),
        lambda m: f"ITE-{_MONTHS[m.group(1).lower()]}-{_strip_leading_zeros(m.group(2))}",
    ),
    (
        "video",
        re.compile(rf"(?<![0-9A-Za-z])([A-Za-z]{{3}}[0-9]{{3}}){_SEP}([0-9]{{3,4}})(?![0-9])", re.I),
        lambda m: f"{m.group(1).upper()}-{m.group(2)}",
    ),
]

#: Every register id, uppercased, with the media it belongs to. Built from
#: the live tables -- this is the "cross-check against the database" that
#: decides whether a generated id is real.
REGISTERS = [
    ("video", "SELECT asset_id FROM public.content_asset_register WHERE asset_id IS NOT NULL"),
    ("video", "SELECT DISTINCT requisition_id FROM public.content_iterated_register "
              "WHERE requisition_id IS NOT NULL"),
    ("graphic", "SELECT requisition_id FROM public.content_graphic_register "
                "WHERE requisition_id IS NOT NULL"),
    ("influencer", "SELECT post_id FROM public.content_influencer_posts WHERE post_id IS NOT NULL"),
]

UNMAPPED_ADS = """
SELECT al.ad_id, al.ad_name, COALESCE(al.spend, 0) AS spend
  FROM ad_lifecycle al
 WHERE al.ad_name IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM public.ad_asset_map m WHERE m.ad_id = al.ad_id)
"""

INSERT = """
INSERT INTO public.ad_asset_recovered
    (ad_id, asset_id, media, ad_name, matched_form, canonical_form)
VALUES %s
ON CONFLICT (ad_id) DO UPDATE SET
    asset_id = EXCLUDED.asset_id, media = EXCLUDED.media,
    ad_name = EXCLUDED.ad_name, matched_form = EXCLUDED.matched_form,
    canonical_form = EXCLUDED.canonical_form, recovered_at = now()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be recovered, then ROLL BACK.")
    ap.add_argument("--show", type=int, default=15, help="example rows to print.")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            cur.execute(DDL)

            # ---- the cross-check set -------------------------------
            known: dict[str, set[str]] = defaultdict(set)
            for media, sql in REGISTERS:
                cur.execute(sql)
                for (rid,) in cur:
                    known[media].add(rid.strip().upper())
            total_known = sum(len(v) for v in known.values())
            print(f"register ids loaded: {total_known:,} "
                  + ", ".join(f"{k} {len(v):,}" for k, v in sorted(known.items())),
                  flush=True)

            # An id that exists in more than one media is ambiguous --
            # resolving it would be a guess about WHICH asset ran.
            seen_once: Counter[str] = Counter()
            for ids in known.values():
                seen_once.update(ids)
            cross_media = {i for i, n in seen_once.items() if n > 1}
            if cross_media:
                print(f"  {len(cross_media)} id(s) exist in >1 register -- refused as ambiguous")

            cur.execute(UNMAPPED_ADS)
            ads = cur.fetchall()
            print(f"unmapped ads scanned: {len(ads):,}\n", flush=True)

            rows: list[tuple] = []
            stats = Counter()
            spend_by = defaultdict(float)
            examples: list[tuple[str, str, str]] = []

            for ad_id, ad_name, spend in ads:
                found: dict[tuple[str, str], str] = {}   # (media, canon) -> raw
                for media, pattern, canon in FAMILIES:
                    for m in pattern.finditer(ad_name):
                        try:
                            cid = canon(m)
                        except KeyError:
                            continue          # month token that is not a month
                        found[(media, cid.upper())] = m.group(0)

                # Keep only ids the database actually holds.
                real = {
                    (media, cid): raw for (media, cid), raw in found.items()
                    if cid in known.get(media, ()) and cid not in cross_media
                }
                if not real:
                    stats["no valid id in name"] += 1
                    continue
                # Already-verbatim ids are not "recovered" -- the map
                # would have caught them. Only count a re-spelling.
                respelled = {
                    k: raw for k, raw in real.items()
                    if raw.upper() != k[1]
                }
                if not respelled:
                    stats["id present but map missed it (investigate)"] += 1
                    continue
                if len({cid for _, cid in respelled}) > 1:
                    stats["ambiguous: ad names two different assets"] += 1
                    continue

                (media, cid), raw = next(iter(respelled.items()))
                rows.append((ad_id, cid, media, ad_name, raw, cid))
                stats[f"recovered ({media})"] += 1
                spend_by[media] += float(spend or 0)
                if len(examples) < args.show:
                    examples.append((raw, cid, ad_name))

            print(f"{'outcome':<44}{'ads':>7}")
            for k, n in stats.most_common():
                print(f"{k:<44}{n:>7,}")
            print(f"\nRECOVERED: {len(rows):,} ads   "
                  + ", ".join(f"{k} Rs {v:,.0f}" for k, v in sorted(spend_by.items())))

            if examples:
                print(f"\n{'ad name says':<18}{'register holds':<18}ad")
                for raw, cid, name in examples:
                    print(f"{raw:<18}{cid:<18}{name[:64]}")

            if rows:
                psycopg2.extras.execute_values(cur, INSERT, rows, page_size=500)

            if args.dry_run:
                conn.rollback()
                print("\n[pg] ROLLED BACK -- --dry-run, nothing written")
            else:
                conn.commit()
                print(f"\n[OK] {len(rows):,} rows in public.ad_asset_recovered")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
