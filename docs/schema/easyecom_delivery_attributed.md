# `easyecom_delivery_attributed`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**view** · unknown rows (planner estimate) · 0 bytes

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `invoice_id` | `bigint` | yes |  |
| 2 | `order_name` | `text` | yes |  |
| 3 | `reference_code` | `text` | yes |  |
| 4 | `awb_number` | `text` | yes |  |
| 5 | `carrier_name` | `text` | yes |  |
| 6 | `delivery_state` | `text` | yes |  |
| 7 | `shipping_status` | `text` | yes |  |
| 8 | `is_delivered` | `boolean` | yes |  |
| 9 | `is_rto` | `boolean` | yes |  |
| 10 | `rto_returned` | `boolean` | yes |  |
| 11 | `is_terminal` | `boolean` | yes |  |
| 12 | `order_date` | `timestamp with time zone` | yes |  |
| 13 | `status_updated_at` | `timestamp with time zone` | yes |  |
| 14 | `invoice_amount` | `double precision` | yes |  |
| 15 | `city` | `text` | yes |  |
| 16 | `state` | `text` | yes |  |
| 17 | `shopify_order_gid` | `text` | yes |  |
| 18 | `utm_source` | `text` | yes |  |
| 19 | `utm_medium` | `text` | yes |  |
| 20 | `utm_campaign` | `text` | yes |  |
| 21 | `utm_term` | `text` | yes |  |
| 22 | `utm_content` | `text` | yes |  |
| 23 | `matched_ad_name` | `text` | yes |  |
| 24 | `matched_campaign_name` | `text` | yes |  |
| 25 | `financial_status` | `text` | yes |  |
| 26 | `payment_type_inferred` | `text` | yes |  |
| 27 | `credit_note_id` | `bigint` | yes |  |
| 28 | `credit_note_amount` | `double precision` | yes |  |
| 29 | `return_date` | `date` | yes |  |
| 30 | `is_exchange` | `boolean` | yes |  |

## Keys and indexes

- **No primary key.**
- No indexes. Any filter on this table is a sequential scan.

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `credit_note_id` → `easyecom_return_items`, `easyecom_returns`
- `invoice_id` → `easyecom_return_items`, `easyecom_returns`, `easyecom_shipments`
- `order_date` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`
- `order_name` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`, `shopify_fulfillments`
- `return_date` → `easyecom_returns`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
