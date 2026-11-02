# `production_sheet_oos`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~623 rows (planner estimate) · 296 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `colour_sku` | `text` | no |  |
| 2 | `master_sku` | `text` | yes |  |
| 3 | `product_status` | `text` | yes |  |
| 4 | `category_type` | `text` | yes |  |
| 5 | `stock_by_size` | `jsonb` | yes |  |
| 6 | `total_stock` | `integer` | yes |  |
| 7 | `colour_instock_rate` | `numeric` | yes |  |
| 8 | `oos_sku_count` | `integer` | yes |  |
| 9 | `in_stock_sku_count` | `integer` | yes |  |
| 10 | `size_count` | `integer` | yes |  |
| 11 | `doq` | `numeric` | yes |  |
| 12 | `ip_doq` | `numeric` | yes |  |
| 13 | `pending_inv_qty` | `integer` | yes |  |
| 14 | `total_in_process` | `integer` | yes |  |
| 15 | `rop_30` | `integer` | yes |  |
| 16 | `rop_60` | `integer` | yes |  |
| 17 | `rop_90` | `integer` | yes |  |
| 18 | `total_doh` | `numeric` | yes |  |
| 19 | `priority_to_restock` | `text` | yes |  |
| 20 | `date_of_restocking` | `text` | yes |  |
| 21 | `colour_instock_status` | `text` | yes |  |
| 22 | `scm_comment` | `text` | yes |  |
| 23 | `sheet_as_of` | `timestamp with time zone` | yes |  |
| 24 | `fetched_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `production_sheet_oos_pkey`
  - `CREATE UNIQUE INDEX production_sheet_oos_pkey ON public.production_sheet_oos USING btree (colour_sku)`
- Index — `ix_pso_master`: `CREATE INDEX ix_pso_master ON public.production_sheet_oos USING btree (master_sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `colour_sku` → `inventory_variant_current`
- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

**One colour SKU** from the "OOS as per Production Plan" tab of the
FY26-27 Production Sheet, loaded by
`scripts/ingest_production_sheet.py`. A second, independent count of
the same stock [[inventory_variant_current]] holds.

## Use it for

Comparison, NOT reconciliation. The two sources are maintained by
different people from different systems and are expected to differ;
the gap is the product. Measured on 2026-11-02 the disagreement was
**symmetric** — Shopify higher on about half the colours, the sheet on
the other half, median ratio 1.00 — which is what rules out a concept
mismatch and leaves timing plus genuine error.

It also carries planning columns Shopify has no equivalent for: DOQ,
ROP 30/60/90, pending inventory, restock priority and SCM comments.

## Traps

- **`colour_instock_rate` is the SHEET's own arithmetic** and is never
  recomputed from the size columns here. A comparison is only honest
  if each side keeps its own; a difference in the rate is itself a
  finding.
- **`sheet_as_of` is when the sheet last recalculated**, not when we
  fetched it. It is usually hours newer than the Shopify snapshot, so
  a small gap is a day's trading rather than an error.
- `#N/A` is stored as NULL, not zero. A failed formula is unknown.
- Roughly a tenth of colours exist on only one side. That is a
  catalogue difference, not a stock discrepancy, and must not be
  ranked as a gap.
- Replaced whole on every load, so a colour dropped from the sheet
  disappears here too.
