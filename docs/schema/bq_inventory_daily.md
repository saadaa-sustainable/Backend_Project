# `bq_inventory_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~3,801,954 rows (planner estimate) · 2067 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `date_day` | `date` | yes |  |
| 2 | `sku` | `text` | yes |  |
| 3 | `warehouse` | `text` | yes |  |
| 4 | `RM_code` | `text` | yes |  |
| 5 | `Dyed_Fabric_SKU` | `text` | yes |  |
| 6 | `product_name` | `text` | yes |  |
| 7 | `Product_Variant` | `text` | yes |  |
| 8 | `Color` | `text` | yes |  |
| 9 | `Size` | `text` | yes |  |
| 10 | `Category` | `text` | yes |  |
| 11 | `Sub_Category` | `text` | yes |  |
| 12 | `Fabric_Consumption_Average` | `numeric` | yes |  |
| 13 | `CategoryType` | `text` | yes |  |
| 14 | `cost` | `numeric` | yes |  |
| 15 | `item_category` | `text` | yes |  |
| 16 | `Gender` | `text` | yes |  |
| 17 | `FitType` | `text` | yes |  |
| 18 | `Age_Group` | `text` | yes |  |
| 19 | `demographic_price_range` | `text` | yes |  |
| 20 | `WEAVE_TYPE` | `text` | yes |  |
| 21 | `FABRIC_NAME` | `text` | yes |  |
| 22 | `FABRIC_COMPOSITION` | `text` | yes |  |
| 23 | `FABRIC_GSM` | `text` | yes |  |
| 24 | `Garment_Length_Type` | `text` | yes |  |
| 25 | `Sleeve_Type` | `text` | yes |  |
| 26 | `Neck_Collar_Type` | `text` | yes |  |
| 27 | `Replenishment_Type` | `text` | yes |  |
| 28 | `Washcare_SKU` | `text` | yes |  |
| 29 | `Season` | `text` | yes |  |
| 30 | `GST` | `text` | yes |  |
| 31 | `Related_Ongoing_Product` | `text` | yes |  |
| 32 | `Qty_in_metres` | `text` | yes |  |
| 33 | `product_state` | `text` | yes |  |
| 34 | `daily_quantity` | `numeric` | yes |  |
| 35 | `has_inventory_today` | `bigint` | yes |  |
| 36 | `t7_quantity` | `numeric` | yes |  |
| 37 | `t730_quantity` | `numeric` | yes |  |
| 38 | `t73015_quantity` | `numeric` | yes |  |
| 39 | `t45_quantity` | `numeric` | yes |  |
| 40 | `doq_7` | `numeric` | yes |  |
| 41 | `doq_15` | `numeric` | yes |  |
| 42 | `doq_7_30` | `numeric` | yes |  |
| 43 | `doq_30_45` | `numeric` | yes |  |
| 44 | `doq_90` | `numeric` | yes |  |
| 45 | `doq_30` | `numeric` | yes |  |
| 46 | `doq_45` | `numeric` | yes |  |
| 47 | `doq_365` | `numeric` | yes |  |
| 48 | `oos_days_7` | `bigint` | yes |  |
| 49 | `oos_days_15` | `bigint` | yes |  |
| 50 | `oos_days_30` | `bigint` | yes |  |
| 51 | `oos_days_45` | `bigint` | yes |  |
| 52 | `oos_days_90` | `bigint` | yes |  |
| 53 | `oos_days_365` | `bigint` | yes |  |
| 54 | `total_sales_in_last_45_inventory_days` | `numeric` | yes |  |
| 55 | `weighted_doq_45` | `numeric` | yes |  |
| 56 | `weightage_doq` | `numeric` | yes |  |
| 57 | `monthly_doq` | `numeric` | yes |  |
| 58 | `yearly_doq` | `numeric` | yes |  |
| 59 | `Lead_Time` | `bigint` | yes |  |
| 60 | `Buffer_Days` | `bigint` | yes |  |
| 61 | `current_stock` | `bigint` | yes |  |
| 62 | `total_inprogress` | `bigint` | yes |  |
| 63 | `shopify_sp` | `numeric` | yes |  |
| 64 | `current_virtual_inventory` | `bigint` | yes |  |
| 65 | `v_doq` | `numeric` | yes |  |
| 66 | `synced_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **No primary key.**
- Index — `ix_bqinv_date_day`: `CREATE INDEX ix_bqinv_date_day ON public.bq_inventory_daily USING btree (date_day)`
- Index — `ix_bqinv_sku`: `CREATE INDEX ix_bqinv_sku ON public.bq_inventory_daily USING btree (sku)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `sku` → `easyecom_return_items`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
