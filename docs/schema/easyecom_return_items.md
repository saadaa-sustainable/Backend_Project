# `easyecom_return_items`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~63 rows (planner estimate) · 96 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `credit_note_id` | `bigint` | no |  |
| 2 | `suborder_id` | `bigint` | no |  |
| 3 | `invoice_id` | `bigint` | yes |  |
| 4 | `sku` | `text` | yes |  |
| 5 | `product_name` | `text` | yes |  |
| 6 | `category` | `text` | yes |  |
| 7 | `returned_quantity` | `integer` | yes |  |
| 8 | `return_reason` | `text` | yes |  |
| 9 | `inventory_status` | `text` | yes |  |
| 10 | `item_selling_price` | `double precision` | yes |  |
| 11 | `credit_note_item_ex_tax` | `double precision` | yes |  |
| 12 | `mrp` | `double precision` | yes |  |
| 13 | `cost` | `double precision` | yes |  |
| 14 | `updated_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `easyecom_return_items_pkey`
  - `CREATE UNIQUE INDEX easyecom_return_items_pkey ON public.easyecom_return_items USING btree (credit_note_id, suborder_id)`
- Index — `ix_eeri_reason`: `CREATE INDEX ix_eeri_reason ON public.easyecom_return_items USING btree (return_reason)`
- Index — `ix_eeri_sku`: `CREATE INDEX ix_eeri_sku ON public.easyecom_return_items USING btree (sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `credit_note_id` → `easyecom_delivery_attributed`, `easyecom_returns`
- `invoice_id` → `easyecom_delivery_attributed`, `easyecom_returns`, `easyecom_shipments`
- `sku` → `bq_inventory_daily`
- `suborder_id` → `easyecom_shipments`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
