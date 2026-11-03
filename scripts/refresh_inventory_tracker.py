"""Rebuild public.inventory_variant_current from Shopify inventory alone.

WHY SHOPIFY ONLY
----------------
`bq_inventory_daily` carries tidy `Color` and `Size` columns, which makes
it the obvious source -- and it is twelve days stale. Shopify is loaded
daily and every product already carries the codes inside its variant
SKU, so the codes are parsed out of the SKU rather than joined in. One
source, one freshness story.

TWO SOURCES, AND WHY THE DEFAULT IS THE LIVE ONE
------------------------------------------------
    --source live    (default)  raw_dump_shopify, object_type='products'
    --source daily               public.shopify_inventory

`shopify_inventory` is a ShopifyQL export at DAY grain: one row per SKU
per day. Re-running against it every hour rewrites the same day's
numbers, so it cannot drive an hourly tracker no matter how often it is
scheduled. The product dump carries `variants { sku, inventoryQuantity }`
live, is what CPIS already reads for Units in Stock, and a full refetch
of every listing takes about ten seconds.

`daily` is kept because the two are independent readings of the same
stock and disagreement between them is worth being able to measure.

IMPORTANT: the live source must be fetched WITHOUT --incremental.
Incremental mode only re-pulls products whose updated_at moved, which
leaves most listings carrying whatever quantity they had when they last
changed -- stale rows wearing a fresh table. Rows older than the newest
fetch are therefore excluded outright, which is also how a product
deleted from Shopify stops reporting phantom stock.

THE HOURLY CHANGE LOG
---------------------
`inventory_variant_current` is replaced whole every run, so on its own
it answers "what is in stock now" and nothing about movement. Each run
diffs the incoming rows against the outgoing ones and appends only the
SKUs whose quantity MOVED to `inventory_variant_changes` -- a few
hundred rows an hour rather than all 4,400, while still covering every
SKU. Appearances and disappearances are logged too, with a NULL on the
side where the SKU was absent.

The diff is skipped on the first run after switching sources: the
outgoing rows came from the daily export and every SKU would look like
it moved.

THE SKU GRAMMAR
---------------
    SMCCPBE_2XL      ->  master SMCCP  · colour BE      · size 2XL
    WCFLKBL-CPWH_M   ->  master WCFLK  · colour BL-CPWH · size M

Everything before `_` is the colour SKU. Within it, everything before a
`-` is the garment; a set names a second garment after the dash and the
master is still the first. The last two characters of the garment part
are the colour code -- unless that would leave fewer than four, which is
how a five-character master with no colour code survives intact.

This is string surgery on a human-typed field and it will not be right
forever. `unparsed_reason` records every row it could not read rather
than dropping it silently, because a product that quietly vanishes from
an inventory tracker is worse than one that shows up flagged.

ONE QUANTITY PER SKU
--------------------
A variant SKU can appear under more than one listing -- the same
garment ACTIVE and ARCHIVED. Counting both double-counts the stock, so
exactly one row per SKU survives, the ACTIVE listing preferred. This is
the same rule CPIS uses for Units in Stock, and the two must agree.

Where SEVERAL listings are ACTIVE and disagree, the quantity is the
MEDIAN OF THE NON-ZERO ones, falling back to zero only when every
listing is zero. Two failure shapes exist and they want opposite
rules:

  SUPFHBE_M   Unisex 48, Men 0, Women 0
              -- the zeros are storefront duplicates holding no
              inventory. A plain median returns 0 and reports a
              stocked hoodie as out of stock.

  SDCPWH_XL   128, 559, 126, all ACTIVE and all real
              -- the maximum is the outlier and inflates the rate.

Ignoring zeros and then taking the median is right on both. Note that
it was NOT chosen by fitting to the production sheet: that sheet is a
separate source which legitimately differs, so tuning this rule to
agree with it would be circular.

WHICH PRODUCTS APPEAR
---------------------
Masters with at least one ACTIVE listing: 82 of them, against 111 if
drafts and archives were included. A draft is not merchandise anyone can
buy, so its empty sizes are not a stock-out.

Usage:
    ./.venv/bin/python scripts/refresh_inventory_tracker.py
    ./.venv/bin/python scripts/refresh_inventory_tracker.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

TABLE = "public.inventory_variant_current"
CHANGES = "public.inventory_variant_changes"

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    variant_sku     text PRIMARY KEY,
    colour_sku      text,
    master_sku      text,
    size            text,
    -- The size as written in the SKU suffix. Garments use XS..6XL;
    -- homeware uses its own vocabulary (KFIT, IN PCS), which is why this
    -- is text and not an enum, and why size_rank orders what it can.
    size_rank       smallint,
    units           integer,
    in_stock        boolean,
    -- Negative stock is real: Shopify lets an order oversell. It is NOT
    -- in stock (the rule is > 0), but it is also not the same as zero,
    -- and a buyer needs to see it.
    oversold        boolean,
    product_status  text,
    -- How many listings held this SKU at its best tier. Above 1 means
    -- the quantity is a median across listings that disagreed, which
    -- is worth knowing before trusting it to the unit.
    listing_ct      smallint,
    product_title   text,
    variant_title   text,
    -- NULL when the SKU parsed cleanly.
    unparsed_reason text,
    as_of_date      date NOT NULL,
    -- When the reading was TAKEN, to the second. as_of_date is kept
    -- beside it because the daily source can only state a date, and a
    -- date is all the dashboard's day-over-day comparison needs.
    -- Hourly tracking needs the instant: twelve rows a day all dated
    -- the same cannot be ordered.
    as_of_at        timestamptz,
    refreshed_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inv_master ON {TABLE} (master_sku);
CREATE INDEX IF NOT EXISTS ix_inv_colour ON {TABLE} (colour_sku);
ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS as_of_at timestamptz;

CREATE TABLE IF NOT EXISTS {CHANGES} (
    id             bigserial PRIMARY KEY,
    observed_at    timestamptz NOT NULL,
    variant_sku    text NOT NULL,
    master_sku     text,
    colour_sku     text,
    size           text,
    -- NULL means the SKU was absent on that side: units_from NULL is a
    -- SKU appearing for the first time, units_to NULL is one that left
    -- Shopify. Neither is a zero, and recording them as zero would
    -- invent a sale or a restock that never happened.
    units_from     integer,
    units_to       integer,
    delta          integer,
    product_status text
);
CREATE INDEX IF NOT EXISTS ix_invchg_at ON {CHANGES} (observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_invchg_sku ON {CHANGES} (variant_sku, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_invchg_master ON {CHANGES} (master_sku, observed_at DESC);
"""

#: Garment sizes, smallest first, so a size run reads in order rather
#: than alphabetically -- "2XL, 3XL, L, M, S, XL" is not a size run.
SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "6XL"]

#: The DAILY source: the ShopifyQL inventory export, one row per SKU per
#: day. `as_of` is a date, so every hour of a day reads identically.
SOURCE_DAILY = """
WITH latest AS (SELECT max(day) AS d FROM public.shopify_inventory),
raw AS (
    SELECT product_variant_sku AS variant_sku, product_status, product_title,
           product_variant_title, ending_inventory_units AS units,
           latest.d::timestamptz AS as_of
      FROM public.shopify_inventory, latest
     WHERE day = latest.d
       AND product_variant_sku IS NOT NULL
       AND product_variant_sku <> ''
       -- The em-dash is how a missing SKU arrives, not a product.
       AND product_variant_sku <> '—'
),"""

#: The LIVE source: the product dump, one row per listing, upserted in
#: place by every fetch. Variants are nested under
#: `variants -> edges -> node`, so they are unnested here rather than
#: flattened into a silver table first -- there is no intermediate step
#: to go stale.
SOURCE_LIVE = """
WITH fresh AS (
    SELECT max(extracted_at) AS t
      FROM public.raw_dump_shopify
     WHERE object_type = 'products'
),
raw AS (
    SELECT v->'node'->>'sku'                        AS variant_sku,
           p.raw_payload->>'status'                 AS product_status,
           p.raw_payload->>'title'                  AS product_title,
           v->'node'->>'title'                      AS product_variant_title,
           (v->'node'->>'inventoryQuantity')::int   AS units,
           p.extracted_at                           AS as_of
      FROM public.raw_dump_shopify p
      CROSS JOIN fresh
      CROSS JOIN LATERAL jsonb_array_elements(p.raw_payload->'variants'->'edges') AS v
     WHERE p.object_type = 'products'
       -- Only the newest fetch. Products are upserted one row each, so
       -- a row left behind at an older timestamp is a listing the last
       -- fetch did not return -- deleted from Shopify, or skipped by an
       -- --incremental run. Either way its quantity is not current, and
       -- carrying it forward is how a dead listing reports phantom
       -- stock indefinitely. The window is wide enough to tolerate a
       -- slow fetch and far narrower than the gap to a previous run.
       AND p.extracted_at >= fresh.t - interval '30 minutes'
       AND v->'node'->>'sku' IS NOT NULL
       AND v->'node'->>'sku' <> ''
       -- The em-dash is how a missing SKU arrives, not a product.
       AND v->'node'->>'sku' <> '—'
),"""

BUILD_TAIL = f"""
-- One quantity per SKU, ACTIVE preferred. Without this a garment listed
-- twice contributes its stock twice and the in-stock rate drifts up.
-- The best listing TIER present for each SKU: ACTIVE if it has one,
-- else DRAFT, else archived. Rank first so the median below is taken
-- within one tier rather than across a live listing and a dead one.
ranked AS (
    SELECT r.*,
           CASE product_status WHEN 'ACTIVE' THEN 0 WHEN 'DRAFT' THEN 1 ELSE 2 END AS tier,
           min(CASE product_status WHEN 'ACTIVE' THEN 0 WHEN 'DRAFT' THEN 1 ELSE 2 END)
               OVER (PARTITION BY variant_sku) AS best_tier
      FROM raw r
),
dedup AS (
    SELECT variant_sku,
           min(product_status)                                   AS product_status,
           min(product_title)                                    AS product_title,
           min(product_variant_title)                            AS product_variant_title,
           -- Median of the NON-ZERO listings, falling back to zero
           -- only when every listing is zero.
           --
           -- Two distinct failure shapes, and they want opposite
           -- rules. SUPFHBE_M is Unisex 48, Men 0, Women 0 -- the
           -- zeros are storefront duplicates carrying no inventory, so
           -- a plain median returns 0 and reports a stocked hoodie as
           -- out. SDCPWH_XL is 128, 559, 126, all real and all
           -- disagreeing, where the maximum is the outlier.
           --
           -- Ignoring zeros and then taking the median is the only one
           -- of the four strategies tried that is right on both: 48
           -- for the first, 128 for the second.
           COALESCE(
               percentile_cont(0.5) WITHIN GROUP (ORDER BY units)
                   FILTER (WHERE units <> 0),
               0)                                                AS units,
           min(as_of)                                            AS as_of,
           count(*)                                              AS listing_ct
      FROM ranked
     WHERE tier = best_tier
     GROUP BY variant_sku
),
parsed AS (
    SELECT d.*,
           split_part(variant_sku, '_', 1) AS colour_sku,
           NULLIF(split_part(variant_sku, '_', 2), '') AS size,
           split_part(split_part(variant_sku, '_', 1), '-', 1) AS garment
      FROM dedup d
),
keyed AS (
    SELECT p.*,
           CASE WHEN length(garment) > 5
                THEN left(garment, length(garment) - 2)
                ELSE garment END AS master_sku,
           CASE
             WHEN variant_sku !~ '^(SD|SM|SU|WC)' THEN 'sku does not start SD/SM/SU/WC'
             WHEN position('_' in variant_sku) = 0 THEN 'no _size suffix'
             WHEN length(garment) < 5 THEN 'garment code shorter than a master sku'
           END AS unparsed_reason
      FROM parsed p
),
-- A master earns a place by having something ACTIVE under it.
active_masters AS (
    SELECT DISTINCT master_sku FROM keyed
     WHERE product_status = 'ACTIVE' AND unparsed_reason IS NULL
)
-- Aliased explicitly: these column names are what the temp table the
-- diff reads is built with, so an unnamed expression here becomes an
-- unreadable column there.
SELECT k.variant_sku, k.colour_sku, k.master_sku, k.size,
       NULLIF(array_position(ARRAY[{','.join(f"'{s}'" for s in SIZE_ORDER)}], k.size), 0)::smallint
           AS size_rank,
       k.units::int                      AS units,
       (k.units > 0)                     AS in_stock,
       (k.units < 0)                     AS oversold,
       k.product_status,
       k.listing_ct::smallint            AS listing_ct,
       k.product_title,
       k.product_variant_title           AS variant_title,
       k.unparsed_reason,
       k.as_of::date                     AS as_of_date,
       k.as_of                           AS as_of_at
  FROM keyed k
  LEFT JOIN active_masters a USING (master_sku)
 WHERE a.master_sku IS NOT NULL OR k.unparsed_reason IS NOT NULL
"""


def build_sql(source: str) -> str:
    """The full SELECT for one source. Only the first CTE differs."""
    return (SOURCE_LIVE if source == "live" else SOURCE_DAILY) + BUILD_TAIL

SUMMARY = f"""
SELECT count(*) FILTER (WHERE unparsed_reason IS NULL)                      AS variants,
       count(DISTINCT master_sku) FILTER (WHERE unparsed_reason IS NULL)    AS masters,
       count(DISTINCT colour_sku) FILTER (WHERE unparsed_reason IS NULL)    AS colours,
       count(*) FILTER (WHERE in_stock)                                     AS in_stock,
       count(*) FILTER (WHERE oversold)                                     AS oversold,
       count(*) FILTER (WHERE unparsed_reason IS NOT NULL)                  AS unparsed,
       count(*) FILTER (WHERE listing_ct > 1)                               AS multi_listed,
       max(as_of_date)                                                      AS as_of,
       max(as_of_at)                                                        AS as_of_at
  FROM {TABLE}
"""

#: Rows whose quantity MOVED, plus arrivals and departures. A FULL JOIN
#: because the interesting cases live on both edges: `IS DISTINCT FROM`
#: rather than `<>` so a NULL on either side counts as a difference
#: instead of quietly dropping the row.
DIFF = f"""
INSERT INTO {CHANGES} (observed_at, variant_sku, master_sku, colour_sku, size,
                       units_from, units_to, delta, product_status)
SELECT %(at)s,
       COALESCE(n.variant_sku, o.variant_sku),
       COALESCE(n.master_sku, o.master_sku),
       COALESCE(n.colour_sku, o.colour_sku),
       COALESCE(n.size, o.size),
       o.units, n.units,
       CASE WHEN o.units IS NOT NULL AND n.units IS NOT NULL
            THEN n.units - o.units END,
       COALESCE(n.product_status, o.product_status)
  FROM incoming n
  FULL JOIN {TABLE} o USING (variant_sku)
 WHERE n.units IS DISTINCT FROM o.units
"""


COLS = ("variant_sku, colour_sku, master_sku, size, size_rank, units, "
        "in_stock, oversold, product_status, listing_ct, product_title, "
        "variant_title, unparsed_reason, as_of_date, as_of_at")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", choices=("live", "daily"), default="live",
                    help="live (default): the product dump, current to the "
                         "fetch. daily: the ShopifyQL export, day grain.")
    ap.add_argument("--no-changes", action="store_true",
                    help="Skip the change log for this run.")
    args = ap.parse_args()

    build = build_sql(args.source)

    with connect(autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        if args.dry_run:
            cur.execute(f"WITH b AS ({build}) SELECT count(*) FROM b")
            print(f"--dry-run: {cur.fetchone()[0]:,} rows would be written "
                  f"(source {args.source})")
            conn.rollback()
            return 0

        # Built into a temp table FIRST, so the incoming rows can be
        # diffed against the outgoing ones before anything is replaced.
        cur.execute(f"CREATE TEMP TABLE incoming ON COMMIT DROP AS {build}")
        cur.execute("SELECT count(*), max(as_of_at) FROM incoming")
        written, observed_at = cur.fetchone()
        if not written:
            # Never truncate on an empty build. A failed fetch would
            # otherwise empty the tracker and read as "everything is out
            # of stock", which is worse than showing the last reading.
            conn.rollback()
            print(f"[FAIL] source {args.source} produced no rows; "
                  f"{TABLE} left untouched")
            return 1

        # Every outgoing row predates as_of_at, so each would look like
        # it moved. That is a source switch, not stock movement.
        cur.execute(f"SELECT count(*), count(as_of_at) FROM {TABLE}")
        had, had_stamped = cur.fetchone()
        skip_why = None
        if args.no_changes:
            skip_why = "--no-changes"
        elif not had:
            skip_why = "nothing to compare against"
        elif not had_stamped:
            skip_why = "previous rows came from the daily source"

        changed = 0
        if not skip_why:
            cur.execute(DIFF, {"at": observed_at})
            changed = cur.rowcount

        # Replaced whole, not upserted: a SKU that leaves Shopify must
        # leave this table too, or it lingers as phantom stock.
        cur.execute(f"TRUNCATE {TABLE}")
        cur.execute(f"INSERT INTO {TABLE} ({COLS}) SELECT {COLS} FROM incoming")
        cur.execute(SUMMARY)
        cols = [d[0] for d in cur.description]
        s = dict(zip(cols, cur.fetchone()))
        conn.commit()

    stamp = s["as_of_at"] or s["as_of"]
    print(f"[OK] {written:,} rows  (source {args.source}, as of {stamp})")
    print(f"     {s['masters']} masters · {s['colours']} colours · {s['variants']:,} variants")
    rate = 100.0 * s["in_stock"] / s["variants"] if s["variants"] else 0
    print(f"     in stock {s['in_stock']:,} ({rate:.1f}%)")
    if s["oversold"]:
        print(f"     [warn] {s['oversold']} variant(s) oversold (negative units)")
    if s["multi_listed"]:
        print(f"     {s['multi_listed']} sku(s) on several listings; quantity is their median")
    if s["unparsed"]:
        print(f"     [warn] {s['unparsed']} sku(s) could not be parsed; kept and flagged")
    if skip_why:
        print(f"     change log skipped: {skip_why}")
    else:
        print(f"     {changed:,} sku(s) moved since the last run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
