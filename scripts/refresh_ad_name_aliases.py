"""Build `ad_name_alias`: every name an ad has ever answered to.

THE PROBLEM
-----------
Meta writes the ad's name into the UTM tag AT CLICK TIME. Rename the ad
later and the order keeps the old name forever, while our ad universe
only knows the current one. The order then cannot be matched to its ad:
the cascade can see which ad set the click came from, but nothing in
that ad set is called what the order says it was called, so it lands in
`adset_name_miss`.

Measured on the last 30 days, that bucket held 752 orders and Rs 8.3L,
and 86% of them named an ad that exists nowhere in the universe under
any current name.

THE SOURCES
-----------
1. `update_ad_friendly_name` activity events. Meta's change log records
   the rename explicitly -- object_id plus an extra_data blob carrying
   old_value and new_value:

       object_id  120251448926970431
       old_value  CTP-SMCFP+MU+NA+IHP+NO-ID-14/08/26
       new_value  CTP-SMCFP+MU+NA+IHP+CPL010-0783-14/08/26

   This is the authoritative source: it names the ad id outright, so
   the alias is a fact rather than an inference. Note extra_data is
   stored as a JSON *string*, not an object, so it needs an explicit
   ::jsonb cast -- reading it as an object silently yields zero rows.

2. Distinct (ad_id, name) pairs across Bronze `ad` snapshots. Weaker and
   much narrower -- Bronze keeps current state, so it only catches a
   rename that happened to straddle two fetches -- but free.

AMBIGUITY IS REFUSED
--------------------
A name that has belonged to more than one ad is NOT an alias: resolving
it would be a coin flip between two real ads, and the whole point of
this table is to stop the cascade guessing. Such names are written with
`ambiguous = true` and the matcher skips them, rather than being dropped
silently -- keeping them makes the refusal auditable.

A name that is already an ad's CURRENT name is also skipped: the normal
path handles those, and an alias row would only shadow it.

Usage:
    ./.venv/bin/python scripts/refresh_ad_name_aliases.py --dry-run
    ./.venv/bin/python scripts/refresh_ad_name_aliases.py
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
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
CREATE TABLE IF NOT EXISTS public.ad_name_alias (
    ad_name_lower text NOT NULL,
    ad_id         text NOT NULL,
    -- 'activity' (a recorded rename) or 'snapshot' (two Bronze fetches
    -- disagreed). Kept so a surprising match can be traced to the
    -- evidence that produced it.
    source        text NOT NULL,
    -- True when this name has belonged to more than one ad. Such rows
    -- are kept but never matched: see the module docstring.
    ambiguous     boolean NOT NULL DEFAULT false,
    refreshed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ad_name_lower, ad_id)
);
CREATE INDEX IF NOT EXISTS ix_ad_name_alias_ad_id ON public.ad_name_alias (ad_id);
"""

#: Both sides of a rename. new_value matters as much as old_value: a
#: second rename makes today's name yesterday's alias.
ACTIVITY_SQL = """
SELECT raw_payload ->> 'object_id'                            AS ad_id,
       (raw_payload ->> 'extra_data')::jsonb ->> 'old_value'  AS old_value,
       (raw_payload ->> 'extra_data')::jsonb ->> 'new_value'  AS new_value
  FROM raw_dump_meta
 WHERE object_type = 'activity'
   AND raw_payload ->> 'event_type' = 'update_ad_friendly_name'
   AND raw_payload ->> 'object_id' IS NOT NULL
"""

SNAPSHOT_SQL = """
SELECT DISTINCT meta_id, raw_payload ->> 'name'
  FROM raw_dump_meta
 WHERE object_type = 'ad' AND meta_id IS NOT NULL AND raw_payload ? 'name'
"""

#: Names the universe already resolves. An alias row for one of these
#: could only shadow the live name, never add reach.
CURRENT_SQL = """
SELECT DISTINCT lower(btrim(ad_name)) FROM (
    SELECT ad_name FROM ad_lifecycle WHERE ad_name IS NOT NULL
    UNION ALL
    SELECT ad_name FROM meta_ads     WHERE ad_name IS NOT NULL
) x WHERE btrim(ad_name) <> ''
"""

#: Aliases are only useful for an ad the cascade can actually resolve.
KNOWN_ADS_SQL = """
SELECT ad_id FROM ad_lifecycle WHERE ad_id IS NOT NULL
UNION
SELECT ad_id FROM meta_ads     WHERE ad_id IS NOT NULL
"""

INSERT = """
INSERT INTO public.ad_name_alias (ad_name_lower, ad_id, source, ambiguous)
VALUES %s
ON CONFLICT (ad_name_lower, ad_id) DO UPDATE SET
    source = EXCLUDED.source,
    ambiguous = EXCLUDED.ambiguous,
    refreshed_at = now()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written, then ROLL BACK.")
    ap.add_argument("--show", type=int, default=10, help="example rows to print.")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '900s'")
            cur.execute(DDL)

            cur.execute(KNOWN_ADS_SQL)
            known = {r[0] for r in cur}
            cur.execute(CURRENT_SQL)
            current = {r[0] for r in cur}
            print(f"universe: {len(known):,} ad ids, {len(current):,} current names")

            #: name -> {ad_id}, and the best source seen for each pair.
            by_name: dict[str, set[str]] = defaultdict(set)
            src: dict[tuple[str, str], str] = {}

            cur.execute(ACTIVITY_SQL)
            act_events = 0
            for ad_id, old, new in cur:
                act_events += 1
                for val in (old, new):
                    nm = (val or "").strip().lower()
                    if nm:
                        by_name[nm].add(ad_id)
                        src[(nm, ad_id)] = "activity"
            print(f"rename events: {act_events:,}")

            cur.execute(SNAPSHOT_SQL)
            for ad_id, nm in cur:
                nm = (nm or "").strip().lower()
                if nm:
                    by_name[nm].add(ad_id)
                    src.setdefault((nm, ad_id), "snapshot")

            rows: list[tuple] = []
            stats = defaultdict(int)
            examples: list[tuple[str, str]] = []
            for nm, ids in by_name.items():
                ids = {i for i in ids if i in known}
                if not ids:
                    stats["names whose ad is not in the universe"] += 1
                    continue
                if nm in current:
                    stats["already a current name -- no alias needed"] += 1
                    continue
                ambiguous = len(ids) > 1
                stats["ambiguous -- kept but never matched" if ambiguous
                      else "usable alias"] += 1
                for ad_id in ids:
                    rows.append((nm, ad_id, src.get((nm, ad_id), "snapshot"), ambiguous))
                if not ambiguous and len(examples) < args.show:
                    examples.append((nm, next(iter(ids))))

            print()
            for k, n in sorted(stats.items(), key=lambda kv: -kv[1]):
                print(f"  {k:46}{n:>8,}")

            if examples:
                print(f"\n{'historical name':<62}resolves to")
                for nm, ad_id in examples:
                    print(f"  {nm[:60]:<62}{ad_id}")

            if rows:
                psycopg2.extras.execute_values(cur, INSERT, rows, page_size=500)
            cur.execute("SELECT COUNT(*) FROM public.ad_name_alias WHERE NOT ambiguous")
            usable = cur.fetchone()[0]

            if args.dry_run:
                conn.rollback()
                print(f"\n[pg] ROLLED BACK -- would hold {usable:,} usable alias rows")
            else:
                conn.commit()
                print(f"\n[OK] ad_name_alias: {len(rows):,} rows written, "
                      f"{usable:,} usable")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
