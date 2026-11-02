# `easyecom_returns`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~52 rows (planner estimate) · 112 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `credit_note_id` | `bigint` | no |  |
| 2 | `invoice_id` | `bigint` | yes |  |
| 3 | `order_id` | `bigint` | yes |  |
| 4 | `reference_code` | `text` | yes |  |
| 5 | `order_name` | `text` | yes |  |
| 6 | `credit_note_number` | `text` | yes |  |
| 7 | `credit_note_date` | `timestamp with time zone` | yes |  |
| 8 | `return_date` | `date` | yes |  |
| 9 | `return_type` | `text` | yes |  |
| 10 | `replacement_order` | `integer` | yes |  |
| 11 | `is_exchange` | `boolean` | yes |  |
| 12 | `credit_note_amount` | `double precision` | yes |  |
| 13 | `credit_note_tax` | `double precision` | yes |  |
| 14 | `total_invoice_amount` | `double precision` | yes |  |
| 15 | `payment_mode` | `text` | yes |  |
| 16 | `marketplace` | `text` | yes |  |
| 17 | `return_awb_number` | `text` | yes |  |
| 18 | `reverse_carrier_name` | `text` | yes |  |
| 19 | `order_date` | `timestamp with time zone` | yes |  |
| 20 | `location_key` | `text` | yes |  |
| 21 | `updated_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `easyecom_returns_pkey`
  - `CREATE UNIQUE INDEX easyecom_returns_pkey ON public.easyecom_returns USING btree (credit_note_id)`
- Index — `ix_eer_date`: `CREATE INDEX ix_eer_date ON public.easyecom_returns USING btree (return_date)`
- Index — `ix_eer_inv`: `CREATE INDEX ix_eer_inv ON public.easyecom_returns USING btree (invoice_id)`
- Index — `ix_eer_name`: `CREATE INDEX ix_eer_name ON public.easyecom_returns USING btree (order_name)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `credit_note_id` → `easyecom_delivery_attributed`, `easyecom_return_items`
- `invoice_id` → `easyecom_delivery_attributed`, `easyecom_return_items`, `easyecom_shipments`
- `location_key` → `easyecom_shipments`
- `order_date` → `easyecom_delivery_attributed`, `easyecom_shipments`, `gokwik_orders`
- `order_id` → `easyecom_shipments`, `gokwik_orders`, `order_customer_type`, `shopify_discounts`, `shopify_fulfillments`, `shopify_order_attribution`, `shopify_orders`, `shopify_sales`
- `order_name` → `easyecom_delivery_attributed`, `easyecom_shipments`, `gokwik_orders`, `shopify_fulfillments`
- `return_date` → `easyecom_delivery_attributed`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
