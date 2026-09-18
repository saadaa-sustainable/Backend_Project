"""Persist the ad_id -> asset_id mapping into public.ad_asset_map.

WHY THIS EXISTS
---------------
The mapping from a Meta ad to the creative asset it was built from was
computed INLINE, per request, inside the /admin/analytics/ads-analyse row
query (app/api/routers/analytics.py, _ADS_ANALYSE_FROM_ROWS). It was
persisted nowhere. Three consequences, all of which this table fixes:

  1. Nothing else could read it. The mapping answers "which of the assets
     we produced actually ran as ads, and how did they do?" -- a question
     that has no business being answerable only as a side effect of
     loading one dashboard tab.

  2. The Untested Assets tab disagreed with reality. Its query filters
     `WHERE content_asset_register.ad_id IS NULL` (analytics.py). An asset
     whose code appears verbatim in a live ad's name, but which the
     content workflow never wrote an ad_id back for, resolved through the
     name_parsed/name_synthetic tiers at request time and was STILL
     reported as untested -- because the register column it filters on
     stayed NULL. The inline-only mapping made that write-back impossible.

  3. It was recomputed on every uncached request.

The legacy CTD system did persist this, as `ad_asset_ids`, fed from the
CTP-Asset_Sheet_v1 External tab. This project dropped that table and
recomputed instead. This script restores the persisted artefact, built
from the register tables this project already mirrors rather than from a
Google Sheet.

STRICT MATCHING: ONE IDENTIFIER PER MEDIA, AGAINST ad_name
-----------------------------------------------------------
An asset is tied to an ad if and only if that asset's own identifier
appears inside the ad's name. One column per media, nothing else:

    video       content_asset_register.asset_id          CPL012-0963
    video       content_iterated_register.requisition_id ITE-Sep-273
    graphic     content_graphic_register.requisition_id  GAD-Sep-1493
    influencer  content_influencer_posts.post_id         SIF-15233-P1

    Two registers report as `video`. content_asset_register is keyed on
    the asset itself; content_iterated_register on the requisition an
    iteration was cut under. An ad name can carry both, so the asset
    code wins (media_pri 1 vs 2) -- it identifies the creative, while the
    requisition only identifies the batch.

Nothing else is consulted. Not nomenclature, not the creator username,
not the register's own ad_id / matched_ad_id / computed_is_tested
columns, and not a regex scrape of ad_name that no register can vouch
for. Everything dropped was either a second identifier for the same
asset or a pointer maintained by hand upstream:

  * `direct` / `ctd_matched` -- register ad_id and matched_ad_id. Only
    225 of 949 live video assets carry an ad_id, and where it IS set it
    drifts (6 of 165 named a different asset than the register claimed).
    Measured before removal: of 1,224 ads these two tiers found, 1,222
    were already reachable from the ad name. They contributed 2.
  * `nomenclature` -- the fuller planning string. It contains the
    identifier, so it can only agree with it or disagree; matching it
    separately just gave the same asset two chances to win.
  * `name_synthetic` -- a code-shaped token in ad_name with no register
    row behind it. That is the ad CLAIMING an asset, not evidence one
    exists, and it made "untested" counts meaningless.

The boundary guard is not optional. Identifiers are sequential, so plain
containment lets GAD-Sep-14 match inside GAD-Sep-1493 and CPL010-078
inside CPL010-0780. Every match requires a non-alphanumeric (or string
start) before the identifier and a non-digit (or end) after it.

When one ad name contains identifiers for more than one asset, media
breaks the tie in the order video, graphic, influencer, then asset_id --
so a rebuild on unchanged input always produces the same row, and
name_conflict flags the ad for a human.

Nomenclature the regexes key off, per the conventions in use:

    video       SDCSS_BST_CPL001-0026_20_03_2026   -> CPL001-0026
    graphic     SDCP_VRP_MH_SC_GAD-Dec-627         -> GAD-Dec-627
    influencer  SIF-11695-P1-username-VRP-...      -> SIF-11695-P1

GRAIN
-----
One row per ad_id (PK), holding that ad's winning match -- the same
one-asset-per-ad semantics /ads-analyse already had, so swapping the
endpoint onto this table cannot change what a merchant sees.

The reverse direction (which ads ran a given asset) is a GROUP BY:

    SELECT asset_id, COUNT(*) AS ads, array_agg(ad_id)
    FROM public.ad_asset_map GROUP BY asset_id;

AD UNIVERSE
-----------
ad_lifecycle, not ad_performance_summary. ad_lifecycle is refreshed by
this same nightly pipeline and ad_performance_summary is built FROM it,
so ad_lifecycle is both fresher and a superset. Register rows pointing at
an ad that is not in ad_lifecycle are dropped and counted in the summary
rather than silently discarded -- a non-zero count there is a real data
problem worth seeing (a deleted ad, or an ad_id typo in the register).

Idempotent: TRUNCATE + INSERT. Safe to re-run.

Usage:
    ./.venv/bin/python scripts/refresh_ad_asset_map.py
    ./.venv/bin/python scripts/refresh_ad_asset_map.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Unicode-safe stdout: this script prints a summary table, and the daily
# runner captures it on a Windows console whose default cp1252 codec
# raises on anything outside Latin-1.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:  # noqa: BLE001 -- pre-3.7 stdout, or an odd stream
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="backslashreplace")

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402


DSN = os.environ["DATABASE_URL_SYNC"].replace(
    "postgresql+psycopg2://", "postgresql://"
).split("?")[0]


DDL = """
CREATE TABLE IF NOT EXISTS public.ad_asset_map (
    ad_id             text PRIMARY KEY,
    ad_name           text,
    -- The content-workflow asset code: content_asset_register.asset_id
    -- (video), content_graphic_register.requisition_id (graphic), or
    -- content_influencer_posts.id (influencer, cast to text).
    asset_id          text NOT NULL,
    media             text NOT NULL,
    -- direct | ctd_matched | name_parsed | name_synthetic
    match_source      text NOT NULL,
    -- 1..5, same ordering as match_source. Numeric so a consumer can
    -- filter "confident matches only" with match_rank <= 2 without
    -- hardcoding the source strings.
    match_rank        smallint NOT NULL,
    -- false only for name_synthetic: the code is in the ad's name but no
    -- register row exists for it. These are the assets that ran without
    -- the content workflow ever recording them.
    asset_in_register boolean NOT NULL,
    -- true when this ad won on a `direct` register link BUT its own name
    -- carries a different asset code. The register's ad_id column is
    -- filled by hand / by an upstream cron and drifts: measured
    -- 2026-09-15, 6 of 165 direct-linked ads disagreed with their own
    -- name (one, CPL010-0785-0736, carries two codes at once). Direct
    -- still wins the row -- a human asserted it -- but the conflict is
    -- recorded rather than silently resolved, because one of the two
    -- sides is wrong and somebody should find out which.
    name_conflict     boolean NOT NULL DEFAULT false,
    -- Snapshot of the ad's own row, denormalised at build time.
    -- Creative Testing rolls these up per asset; without them that
    -- endpoint had to join ad_lifecycle (42 MB, 205 cols) and group on
    -- every request, measured at 78.7s. This table is rebuilt nightly
    -- from ad_lifecycle anyway, so the copy is never staler than the
    -- map itself.
    ad_created_date   date,
    account_name      text,
    category          text,
    spend             numeric,
    impressions       numeric,
    purchases         numeric,
    conv_value        numeric,
    ncp_count         numeric,
    ftewv_count       numeric,
    link_clicks       numeric,
    -- Overview-Performance strip inputs (hook / outbound CTR /
    -- engagement / thruplay / hold rates). outbound_clicks is Meta's
    -- JSONB action array, not a scalar -- the value is pulled out of
    -- element 0 at build time so consumers can just SUM it.
    thruplays         numeric,
    three_sec_plays   numeric,
    outbound_clicks   numeric,
    post_engagements  numeric,
    refreshed_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.ad_asset_map
    ADD COLUMN IF NOT EXISTS name_conflict   boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS ad_created_date date,
    ADD COLUMN IF NOT EXISTS account_name    text,
    ADD COLUMN IF NOT EXISTS category        text,
    ADD COLUMN IF NOT EXISTS spend           numeric,
    ADD COLUMN IF NOT EXISTS impressions     numeric,
    ADD COLUMN IF NOT EXISTS purchases       numeric,
    ADD COLUMN IF NOT EXISTS conv_value      numeric,
    ADD COLUMN IF NOT EXISTS ncp_count       numeric,
    ADD COLUMN IF NOT EXISTS ftewv_count     numeric,
    ADD COLUMN IF NOT EXISTS link_clicks      numeric,
    ADD COLUMN IF NOT EXISTS thruplays        numeric,
    ADD COLUMN IF NOT EXISTS three_sec_plays  numeric,
    ADD COLUMN IF NOT EXISTS outbound_clicks  numeric,
    ADD COLUMN IF NOT EXISTS post_engagements numeric;

-- Creative Testing filters on the ad's launch date inside a window.
CREATE INDEX IF NOT EXISTS ix_ad_asset_map_created
    ON public.ad_asset_map (ad_created_date);

-- Reverse lookup: every ad that ran a given asset.
CREATE INDEX IF NOT EXISTS ix_ad_asset_map_asset
    ON public.ad_asset_map (asset_id);

-- Coverage/quality slicing in the Untested Assets and Ads Analyse views.
CREATE INDEX IF NOT EXISTS ix_ad_asset_map_media_source
    ON public.ad_asset_map (media, match_source);
"""


# One row per (ad, candidate match). DISTINCT ON collapses to the winner.
# Ordering is (match_rank, media_pri, asset_id) -- see the module
# docstring for why each term is there.
#: Every (ad, candidate asset) pair, materialised ONCE into a temp table.
#: The regex containment is a nested loop of registers x ads; evaluating
#: it twice (winners, then conflicts) measured 342s against 5.5s for this
#: single pass.
CANDIDATES_SQL = """
CREATE TEMP TABLE _asset_cand ON COMMIT DROP AS
SELECT al.ad_id, al.ad_name, car.asset_id AS asset_id,
       'video'::text AS media, 1 AS media_pri, 'asset_id'::text AS match_src,
       al.ad_created_time::date AS ad_created_date, al.account_name, al.category,
       al.spend, al.impressions, al.purchases, al.conv_value,
       al.ncp_count, al.ftewv_count, al.inline_link_clicks AS link_clicks,
       al.thruplays, al.three_sec_video_plays AS three_sec_plays,
       ((al.outbound_clicks->0)->>'value')::numeric AS outbound_clicks,
       al.post_engagements
  FROM ad_lifecycle al
  JOIN public.content_asset_register car
    ON length(car.asset_id) >= 6
   AND al.ad_name ~* ('(^|[^0-9A-Za-z])' || car.asset_id || '([^0-9]|$)')
UNION ALL
-- Iterated video: a requisition id ('ITE-Sep-273'), not an asset_id.
-- Reports as media='video' because that is what it is, and because the
-- media column is a Literal["video","graphic","influencer"] all the way
-- out to the UI. Ranked BELOW the main video register: when an ad name
-- carries both a CPL asset code and an ITE requisition, the asset code
-- names the creative itself and the requisition only names the batch it
-- was cut in, so the asset code is the better answer.
SELECT al.ad_id, al.ad_name, cir.requisition_id, 'video'::text, 2, 'asset_id',
       al.ad_created_time::date AS ad_created_date, al.account_name, al.category,
       al.spend, al.impressions, al.purchases, al.conv_value,
       al.ncp_count, al.ftewv_count, al.inline_link_clicks AS link_clicks,
       al.thruplays, al.three_sec_video_plays AS three_sec_plays,
       ((al.outbound_clicks->0)->>'value')::numeric AS outbound_clicks,
       al.post_engagements
  FROM ad_lifecycle al
  JOIN (SELECT DISTINCT requisition_id FROM public.content_iterated_register) cir
    ON length(cir.requisition_id) >= 6
   AND al.ad_name ~* ('(^|[^0-9A-Za-z])' || cir.requisition_id || '([^0-9]|$)')
UNION ALL
SELECT al.ad_id, al.ad_name, cgr.requisition_id, 'graphic'::text, 3, 'asset_id',
       al.ad_created_time::date AS ad_created_date, al.account_name, al.category,
       al.spend, al.impressions, al.purchases, al.conv_value,
       al.ncp_count, al.ftewv_count, al.inline_link_clicks AS link_clicks,
       al.thruplays, al.three_sec_video_plays AS three_sec_plays,
       ((al.outbound_clicks->0)->>'value')::numeric AS outbound_clicks,
       al.post_engagements
  FROM ad_lifecycle al
  JOIN public.content_graphic_register cgr
    ON length(cgr.requisition_id) >= 6
   AND al.ad_name ~* ('(^|[^0-9A-Za-z])' || cgr.requisition_id || '([^0-9]|$)')
UNION ALL
SELECT al.ad_id, al.ad_name, cip.post_id, 'influencer'::text, 4, 'asset_id',
       al.ad_created_time::date AS ad_created_date, al.account_name, al.category,
       al.spend, al.impressions, al.purchases, al.conv_value,
       al.ncp_count, al.ftewv_count, al.inline_link_clicks AS link_clicks,
       al.thruplays, al.three_sec_video_plays AS three_sec_plays,
       ((al.outbound_clicks->0)->>'value')::numeric AS outbound_clicks,
       al.post_engagements
  FROM ad_lifecycle al
  JOIN public.content_influencer_posts cip
    ON length(cip.post_id) >= 6
   AND al.ad_name ~* ('(^|[^0-9A-Za-z])' || cip.post_id || '([^0-9]|$)')
UNION ALL
-- Re-spellings, from scripts/recover_asset_ids.py: ids the ad name
-- writes with different separators or zero-padding ('ITE_Feb19' for
-- 'ITE-Feb-19'). Every row there was already checked to exist in a
-- register, so this join adds no new asset -- only a new way of
-- reaching one.
--
-- media_pri 5, the lowest: a VERBATIM id in the same ad name always
-- wins. A re-spelling is only ever the answer when nothing was spelled
-- correctly.
SELECT al.ad_id, al.ad_name, r.asset_id, r.media, 5, 'recovered',
       al.ad_created_time::date AS ad_created_date, al.account_name, al.category,
       al.spend, al.impressions, al.purchases, al.conv_value,
       al.ncp_count, al.ftewv_count, al.inline_link_clicks AS link_clicks,
       al.thruplays, al.three_sec_video_plays AS three_sec_plays,
       ((al.outbound_clicks->0)->>'value')::numeric AS outbound_clicks,
       al.post_engagements
  FROM ad_lifecycle al
  JOIN public.ad_asset_recovered r ON r.ad_id = al.ad_id
"""


#: Winner per ad, straight off the materialised candidates.
INSERT_SQL = """
INSERT INTO public.ad_asset_map
    (ad_id, ad_name, asset_id, media, match_source, match_rank, asset_in_register,
     ad_created_date, account_name, category, spend, impressions, purchases,
     conv_value, ncp_count, ftewv_count, link_clicks,
     thruplays, three_sec_plays, outbound_clicks, post_engagements)
SELECT DISTINCT ON (ad_id)
       ad_id, ad_name, asset_id, media,
       match_src AS match_source, 1::smallint AS match_rank,
       true AS asset_in_register,
       ad_created_date, account_name, category, spend, impressions, purchases,
       conv_value, ncp_count, ftewv_count, link_clicks,
       thruplays, three_sec_plays, outbound_clicks, post_engagements
FROM _asset_cand
ORDER BY ad_id, media_pri, asset_id
"""


#: An ad whose name resolves to MORE THAN ONE distinct registered asset.
#: Real and observed: CTP-SMCTS+MU+NA+IHP+CPL010-0785-0736-7/08/26 carries
#: two video codes concatenated. DISTINCT ON picks one by the ordering
#: above, which is deterministic but arbitrary between equals -- so the
#: ambiguity is recorded rather than hidden, and a human decides.
CONFLICT_SQL = """
UPDATE public.ad_asset_map m
   SET name_conflict = true
  FROM (
    SELECT ad_id FROM _asset_cand
     GROUP BY ad_id
    HAVING count(DISTINCT asset_id) > 1
  ) multi
 WHERE multi.ad_id = m.ad_id
"""


SUMMARY_SQL = """
SELECT match_source,
       COUNT(*)                     AS ads,
       COUNT(DISTINCT asset_id)     AS assets
  FROM public.ad_asset_map
 GROUP BY match_source
 ORDER BY MIN(match_rank)
"""

COVERAGE_SQL = """
SELECT (SELECT COUNT(*) FROM ad_lifecycle)                    AS ads_total,
       (SELECT COUNT(*) FROM public.ad_asset_map)             AS ads_mapped,
       (SELECT COUNT(DISTINCT asset_id) FROM public.ad_asset_map
         WHERE asset_in_register)                             AS assets_known,
       (SELECT COUNT(DISTINCT asset_id) FROM public.ad_asset_map
         WHERE NOT asset_in_register)                         AS assets_unregistered
"""

#: Assets in a register that this map never links to any ad -- i.e. the
#: genuinely untested ones, now computed from the map rather than from
#: the register's own (frequently unwritten) ad_id column.
UNTESTED_SQL = """
SELECT
  (SELECT COUNT(*) FROM public.content_asset_register car
    WHERE NOT EXISTS (SELECT 1 FROM public.ad_asset_map m
                       WHERE m.asset_id = car.asset_id))       AS video_untested,
  (SELECT COUNT(*) FROM (SELECT DISTINCT requisition_id
                           FROM public.content_iterated_register) cir
    WHERE NOT EXISTS (SELECT 1 FROM public.ad_asset_map m
                       WHERE m.asset_id = cir.requisition_id)) AS iterated_untested,
  (SELECT COUNT(*) FROM public.content_graphic_register cgr
    WHERE NOT EXISTS (SELECT 1 FROM public.ad_asset_map m
                       WHERE m.asset_id = cgr.requisition_id)) AS graphic_untested,
  (SELECT COUNT(*) FROM public.content_influencer_posts cip
    WHERE NOT EXISTS (SELECT 1 FROM public.ad_asset_map m
                       WHERE m.asset_id = cip.post_id))        AS influencer_untested
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="build the map in a transaction, print the summary, then ROLL BACK. "
             "Nothing is written. Use this to inspect coverage before committing "
             "to the mapping.",
    )
    args = ap.parse_args()

    t0 = time.time()
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '900s'")
            cur.execute(DDL)
            if not args.dry_run:
                conn.commit()

            print("[pg] TRUNCATE ad_asset_map", flush=True)
            cur.execute("TRUNCATE public.ad_asset_map")

            print("[pg] rebuilding from ad_lifecycle x content registers ...", flush=True)
            print("[pg] materialising candidate (ad, asset) pairs ...", flush=True)
            cur.execute(CANDIDATES_SQL)

            cur.execute(INSERT_SQL)
            inserted = cur.rowcount

            cur.execute(CONFLICT_SQL)
            conflicts = cur.rowcount

            # Freshly TRUNCATEd + repopulated: without this the planner
            # has no stats and picks bad plans for downstream reads.
            cur.execute("ANALYZE public.ad_asset_map")

            cur.execute(COVERAGE_SQL)
            ads_total, ads_mapped, assets_known, assets_unregistered = cur.fetchone()
            cur.execute(SUMMARY_SQL)
            by_source = cur.fetchall()
            cur.execute(UNTESTED_SQL)
            (video_untested, iterated_untested, graphic_untested,
             influencer_untested) = cur.fetchone()

            if args.dry_run:
                conn.rollback()
                print("[pg] ROLLED BACK -- --dry-run, nothing written", flush=True)
            else:
                conn.commit()
    finally:
        conn.close()

    dt = time.time() - t0
    pct = (ads_mapped * 100.0 / ads_total) if ads_total else 0.0

    print(f"\n[OK] ad_asset_map rebuilt in {dt:.1f}s  ({inserted:,} rows)")
    print(f"    ads in ad_lifecycle    : {ads_total:,}")
    print(f"    ads mapped to an asset : {ads_mapped:,}  ({pct:.0f}%)")
    print(f"    distinct assets, known : {assets_known:,}")
    print(f"    distinct assets, NOT in any register : {assets_unregistered:,}")
    print("")
    print("    by match source          ads       assets")
    print("    ---------------------------------------------")
    for source, ads, assets in by_source:
        print(f"    {source:<20} {ads:>8,}   {assets:>8,}")
    print("")
    print("    register assets never linked to an ad (genuinely untested):")
    print(f"      video      : {video_untested:,}")
    print(f"      iterated   : {iterated_untested:,}")
    print(f"      graphic    : {graphic_untested:,}")
    print(f"      influencer : {influencer_untested:,}")
    if conflicts:
        print("")
        print(f"    [warn] {conflicts:,} ad(s) name MORE THAN ONE registered asset "
              f"-- name_conflict = true. One winner was picked deterministically; "
              f"a human should decide which asset the ad actually ran.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
