# `shopify_customer_analytics`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~253,876 rows (planner estimate) · 62 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `customer_id` | `text` | no |  |
| 2 | `first_order_date` | `date` | yes |  |
| 3 | `last_order_date` | `date` | yes |  |
| 4 | `customer_cohort_month` | `date` | yes |  |
| 5 | `customer_email` | `text` | yes |  |
| 6 | `customer_name` | `text` | yes |  |
| 7 | `customer_city` | `text` | yes |  |
| 8 | `customer_country` | `text` | yes |  |
| 9 | `customer_region` | `text` | yes |  |
| 10 | `rfm_group` | `text` | yes |  |
| 11 | `predicted_spend_tier` | `text` | yes |  |
| 12 | `customer_account_status` | `text` | yes |  |
| 13 | `customer_email_subscription_status` | `text` | yes |  |
| 14 | `customer_sms_subscription_status` | `text` | yes |  |
| 15 | `days_since_last_order` | `numeric` | yes |  |
| 16 | `new_customer_records` | `numeric` | yes |  |
| 17 | `total_amount_spent` | `numeric` | yes |  |
| 18 | `total_amount_spent_per_order` | `numeric` | yes |  |
| 19 | `total_number_of_orders` | `numeric` | yes |  |
| 20 | `extracted_at` | `timestamp with time zone` | yes |  |
| 21 | `flattened_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_customer_analytics_pkey`
  - `CREATE UNIQUE INDEX shopify_customer_analytics_pkey ON public.shopify_customer_analytics USING btree (customer_id)`
- Index — `ix_shopify_customer_analytics_rfm_group`: `CREATE INDEX ix_shopify_customer_analytics_rfm_group ON public.shopify_customer_analytics USING btree (rfm_group)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `customer_id` → `order_customer_type`, `shopify_customers`, `shopify_order_attribution`, `shopify_orders`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
