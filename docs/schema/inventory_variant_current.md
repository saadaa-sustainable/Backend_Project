# `inventory_variant_current`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~4,421 rows (planner estimate) · 912 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `variant_sku` | `text` | no |  |
| 2 | `colour_sku` | `text` | yes |  |
| 3 | `master_sku` | `text` | yes |  |
| 4 | `size` | `text` | yes |  |
| 5 | `size_rank` | `smallint` | yes |  |
| 6 | `units` | `integer` | yes |  |
| 7 | `in_stock` | `boolean` | yes |  |
| 8 | `oversold` | `boolean` | yes |  |
| 9 | `product_status` | `text` | yes |  |
| 10 | `listing_ct` | `smallint` | yes |  |
| 11 | `product_title` | `text` | yes |  |
| 12 | `variant_title` | `text` | yes |  |
| 13 | `unparsed_reason` | `text` | yes |  |
| 14 | `as_of_date` | `date` | no |  |
| 15 | `refreshed_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `inventory_variant_current_pkey`
  - `CREATE UNIQUE INDEX inventory_variant_current_pkey ON public.inventory_variant_current USING btree (variant_sku)`
- Index — `ix_inv_colour`: `CREATE INDEX ix_inv_colour ON public.inventory_variant_current USING btree (colour_sku)`
- Index — `ix_inv_master`: `CREATE INDEX ix_inv_master ON public.inventory_variant_current USING btree (master_sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `as_of_date` → `ad_reach_cumulative`, `master_sku_inventory_current`
- `colour_sku` → `production_sheet_oos`
- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more
- `variant_sku` → `virtual_inventory_current`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

**One Shopify variant SKU**, as of the latest `shopify_inventory` day.
Rebuilt whole by `scripts/refresh_inventory_tracker.py`; it is a
snapshot, not history.

The hierarchy is parsed out of the SKU, not joined in:

```
SMCCPBE_2XL     ->  master SMCCP  · colour BE      · size 2XL
WCFLKBL-CPWH_M  ->  master WCFLK  · colour BL-CPWH · size M
```

A set names a second garment after a dash; the master is still the
first. The last two characters of the garment part are the colour code
unless that leaves fewer than four.

## Use it for

In-stock rates at any tier. `variant in-stock` is rows with
`units > 0` over all rows; `size in-stock` is distinct sizes available
in ANY colour, which catches size-run gaps the variant rate hides — a
product can be a third on one and whole on the other.

## Traps

- **`units` is the MEDIAN of the non-zero listings**, not a simple
  read. A SKU can sit on several ACTIVE listings holding different
  quantities of the same garment. Taking the max inflated the rate by
  three points; taking a plain median reported stocked products as
  empty, because duplicate storefront listings carry zeros. Check
  `listing_ct > 1` before trusting a figure to the unit.
- **Only masters with an ACTIVE listing appear.** Drafts and archives
  are excluded, so this is smaller than Shopify's catalogue.
- `unparsed_reason IS NOT NULL` rows are kept but must be filtered out
  of every aggregate. They are archived homeware whose size lives in
  the variant title rather than a `_SIZE` suffix.
- **Negative units are real** — Shopify allows overselling. They are
  NOT in stock (`> 0`) but they are not zero either; `oversold` marks
  them.
- **Nothing refreshes this on a schedule.** It is as stale as the last
  manual run. Check `as_of_date`.

Joins to [[production_sheet_oos]] and [[virtual_inventory_current]].
