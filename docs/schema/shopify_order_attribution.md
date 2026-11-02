# `shopify_order_attribution`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~433,046 rows (planner estimate) · 270 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `order_id` | `text` | no |  |
| 2 | `name` | `text` | yes |  |
| 3 | `total_price` | `numeric` | yes |  |
| 4 | `created_at` | `timestamp with time zone` | yes |  |
| 5 | `customer_id` | `text` | yes |  |
| 6 | `utm_source` | `text` | yes |  |
| 7 | `utm_medium` | `text` | yes |  |
| 8 | `utm_campaign` | `text` | yes |  |
| 9 | `utm_content` | `text` | yes |  |
| 10 | `tier` | `text` | yes |  |
| 11 | `matched_ad_id` | `text` | yes |  |
| 12 | `matched_ad_name` | `text` | yes |  |
| 13 | `matched_campaign_id` | `text` | yes |  |
| 14 | `matched_campaign_name` | `text` | yes |  |
| 15 | `flattened_at` | `timestamp with time zone` | yes |  |
| 16 | `utm_term` | `text` | yes |  |
| 17 | `matched_value` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_order_attribution_pkey`
  - `CREATE UNIQUE INDEX shopify_order_attribution_pkey ON public.shopify_order_attribution USING btree (order_id)`
- Index — `ix_shopify_order_attribution_ad_created`: `CREATE INDEX ix_shopify_order_attribution_ad_created ON public.shopify_order_attribution USING btree (matched_ad_id, created_at) INCLUDE (order_id, total_price)`
- Index — `ix_shopify_order_attribution_matched_ad_id`: `CREATE INDEX ix_shopify_order_attribution_matched_ad_id ON public.shopify_order_attribution USING btree (matched_ad_id)`
- Index — `ix_shopify_order_attribution_matched_campaign_id`: `CREATE INDEX ix_shopify_order_attribution_matched_campaign_id ON public.shopify_order_attribution USING btree (matched_campaign_id)`
- Index — `ix_shopify_order_attribution_tier`: `CREATE INDEX ix_shopify_order_attribution_tier ON public.shopify_order_attribution USING btree (tier)`
- Index — `ix_soa_ad_created_cover`: `CREATE INDEX ix_soa_ad_created_cover ON public.shopify_order_attribution USING btree (matched_ad_id, created_at) INCLUDE (total_price, order_id) WHERE (matched_ad_id IS NOT NULL)`
- Index — `ix_soa_created_at`: `CREATE INDEX ix_soa_created_at ON public.shopify_order_attribution USING btree (created_at)`
- Index — `ix_soa_created_desc_nulls_last`: `CREATE INDEX ix_soa_created_desc_nulls_last ON public.shopify_order_attribution USING btree (created_at DESC NULLS LAST)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `customer_id` → `order_customer_type`, `shopify_customer_analytics`, `shopify_customers`, `shopify_orders`
- `matched_ad_id` → `content_asset_register`, `content_graphic_register`, `content_influencer_posts`
- `matched_campaign_id` → `shopify_landing_page_analysis`
- `order_id` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`, `order_customer_type`, `shopify_discounts`, `shopify_fulfillments`, `shopify_orders`, `shopify_sales`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
