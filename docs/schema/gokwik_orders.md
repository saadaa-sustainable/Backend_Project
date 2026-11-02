# `gokwik_orders`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~328,040 rows (planner estimate) · 154 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `order_id` | `text` | no |  |
| 2 | `order_gid` | `text` | yes |  |
| 3 | `order_name` | `text` | yes |  |
| 4 | `order_date` | `date` | yes |  |
| 5 | `utm_source` | `text` | yes |  |
| 6 | `utm_medium` | `text` | yes |  |
| 7 | `utm_campaign` | `text` | yes |  |
| 8 | `utm_term` | `text` | yes |  |
| 9 | `utm_content` | `text` | yes |  |
| 10 | `grand_total` | `double precision` | yes |  |
| 11 | `total_discount` | `double precision` | yes |  |
| 12 | `cod_charges` | `numeric` | yes |  |
| 13 | `mrp_total` | `numeric` | yes |  |
| 14 | `payment_method` | `text` | yes |  |
| 15 | `payment_status` | `text` | yes |  |
| 16 | `merchant_order_status` | `text` | yes |  |
| 17 | `order_shipment_status` | `text` | yes |  |
| 18 | `rto_risk` | `text` | yes |  |
| 19 | `rto_score` | `text` | yes |  |
| 20 | `rto_remark` | `text` | yes |  |
| 21 | `awb_number` | `text` | yes |  |
| 22 | `customer_type_gokwik` | `text` | yes |  |
| 23 | `customer_type_merchant` | `text` | yes |  |
| 24 | `billing_city` | `text` | yes |  |
| 25 | `billing_state` | `text` | yes |  |
| 26 | `coupon_code` | `text` | yes |  |
| 27 | `landing_page` | `text` | yes |  |
| 28 | `ingested_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `gokwik_orders_pkey`
  - `CREATE UNIQUE INDEX gokwik_orders_pkey ON public.gokwik_orders USING btree (order_id)`
- Index — `ix_gokwik_date_old`: `CREATE INDEX ix_gokwik_date_old ON public.gokwik_orders USING btree (order_date)`
- Index — `ix_gokwik_gid_old`: `CREATE INDEX ix_gokwik_gid_old ON public.gokwik_orders USING btree (order_gid)`
- Index — `ix_gokwik_name_old`: `CREATE INDEX ix_gokwik_name_old ON public.gokwik_orders USING btree (order_name)`
- Index — `ix_gokwik_term_old`: `CREATE INDEX ix_gokwik_term_old ON public.gokwik_orders USING btree (utm_term)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `order_date` → `easyecom_delivery_attributed`, `easyecom_returns`, `easyecom_shipments`
- `order_id` → `easyecom_returns`, `easyecom_shipments`, `order_customer_type`, `shopify_discounts`, `shopify_fulfillments`, `shopify_order_attribution`, `shopify_orders`, `shopify_sales`
- `order_name` → `easyecom_delivery_attributed`, `easyecom_returns`, `easyecom_shipments`, `shopify_fulfillments`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
