# `virtual_inventory_current`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~280 rows (planner estimate) · 80 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `variant_sku` | `text` | no |  |
| 2 | `size` | `text` | yes |  |
| 3 | `virtual_units` | `integer` | no |  |
| 4 | `source_file` | `text` | yes |  |
| 5 | `imported_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `virtual_inventory_current_pkey`
  - `CREATE UNIQUE INDEX virtual_inventory_current_pkey ON public.virtual_inventory_current USING btree (variant_sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `variant_sku` → `inventory_variant_current`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

**One variant SKU** from the manually-maintained "Virtual stock
details - Sourcing" workbook, loaded by
`scripts/import_virtual_inventory.py`.

Virtual stock is **promised, not held**. It is not on a shelf.

## Traps

- **Never add `virtual_units` to Shopify's count.** Anything that sums
  them is telling you that you have stock you cannot ship. Every
  surface keeps them in separate columns for this reason.
- **No automatic refresh, by design** — nobody generates this file,
  someone edits it. `source_file` and `imported_at` say which version
  produced the figures; without them a stale load is indistinguishable
  from a fresh one.
- Replaced whole on each import, so a SKU dropped from the file stops
  promising stock.
- A SKU matching no row in [[inventory_variant_current]] is stored but
  invisible on the inventory page. The importer reports the count.
