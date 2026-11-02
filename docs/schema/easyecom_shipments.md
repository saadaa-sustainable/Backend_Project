# `easyecom_shipments`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~1,528 rows (planner estimate) · 864 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `invoice_id` | `bigint` | no |  |
| 2 | `order_id` | `bigint` | yes |  |
| 3 | `suborder_id` | `bigint` | yes |  |
| 4 | `reference_code` | `text` | yes |  |
| 5 | `order_name` | `text` | yes |  |
| 6 | `awb_number` | `text` | yes |  |
| 7 | `carrier_name` | `text` | yes |  |
| 8 | `carrier_id` | `bigint` | yes |  |
| 9 | `shipping_status_id` | `integer` | yes |  |
| 10 | `shipping_status` | `text` | yes |  |
| 11 | `delivery_state` | `text` | yes |  |
| 12 | `is_delivered` | `boolean` | yes |  |
| 13 | `is_rto` | `boolean` | yes |  |
| 14 | `rto_returned` | `boolean` | yes |  |
| 15 | `is_terminal` | `boolean` | yes |  |
| 16 | `order_status` | `text` | yes |  |
| 17 | `order_date` | `timestamp with time zone` | yes |  |
| 18 | `invoice_date` | `timestamp with time zone` | yes |  |
| 19 | `expected_delivery` | `timestamp with time zone` | yes |  |
| 20 | `status_updated_at` | `timestamp with time zone` | yes |  |
| 21 | `invoice_amount` | `double precision` | yes |  |
| 22 | `tax` | `double precision` | yes |  |
| 23 | `city` | `text` | yes |  |
| 24 | `state` | `text` | yes |  |
| 25 | `location_key` | `text` | yes |  |
| 26 | `event_count` | `integer` | no | `1` |
| 27 | `first_seen_at` | `timestamp with time zone` | yes |  |
| 28 | `last_seen_at` | `timestamp with time zone` | yes |  |
| 29 | `updated_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `easyecom_shipments_pkey`
  - `CREATE UNIQUE INDEX easyecom_shipments_pkey ON public.easyecom_shipments USING btree (invoice_id)`
- Index — `ix_ees_awb2`: `CREATE INDEX ix_ees_awb2 ON public.easyecom_shipments USING btree (awb_number)`
- Index — `ix_ees_name`: `CREATE INDEX ix_ees_name ON public.easyecom_shipments USING btree (order_name)`
- Index — `ix_ees_ref`: `CREATE INDEX ix_ees_ref ON public.easyecom_shipments USING btree (reference_code)`
- Index — `ix_ees_state`: `CREATE INDEX ix_ees_state ON public.easyecom_shipments USING btree (delivery_state)`
- Index — `ix_ees_upd`: `CREATE INDEX ix_ees_upd ON public.easyecom_shipments USING btree (status_updated_at)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `invoice_id` → `easyecom_delivery_attributed`, `easyecom_return_items`, `easyecom_returns`
- `location_key` → `easyecom_returns`
- `order_date` → `easyecom_delivery_attributed`, `easyecom_returns`, `gokwik_orders`
- `order_id` → `easyecom_returns`, `gokwik_orders`, `order_customer_type`, `shopify_discounts`, `shopify_fulfillments`, `shopify_order_attribution`, `shopify_orders`, `shopify_sales`
- `order_name` → `easyecom_delivery_attributed`, `easyecom_returns`, `gokwik_orders`, `shopify_fulfillments`
- `suborder_id` → `easyecom_return_items`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
