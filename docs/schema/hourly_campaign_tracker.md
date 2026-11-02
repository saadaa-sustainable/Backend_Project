# `hourly_campaign_tracker`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~1,143 rows (planner estimate) · 952 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `hour` | `timestamp with time zone` | no |  |
| 2 | `day_ist` | `date` | no |  |
| 3 | `hour_of_day` | `smallint` | no |  |
| 4 | `sessions` | `integer` | yes |  |
| 5 | `sessions_paid` | `integer` | yes |  |
| 6 | `sessions_direct` | `integer` | yes |  |
| 7 | `sessions_meta` | `integer` | yes |  |
| 8 | `sessions_google` | `integer` | yes |  |
| 9 | `revenue` | `numeric` | yes |  |
| 10 | `orders` | `integer` | yes |  |
| 11 | `revenue_shopifyql` | `numeric` | yes |  |
| 12 | `revenue_meta` | `numeric` | yes |  |
| 13 | `revenue_google` | `numeric` | yes |  |
| 14 | `revenue_paid` | `numeric` | yes |  |
| 15 | `orders_meta` | `integer` | yes |  |
| 16 | `new_customers` | `integer` | yes |  |
| 17 | `new_customer_revenue` | `numeric` | yes |  |
| 18 | `meta_spend` | `numeric` | yes |  |
| 19 | `meta_impressions` | `bigint` | yes |  |
| 20 | `kwikchat_spend` | `numeric` | yes |  |
| 21 | `ga4_sessions` | `integer` | yes |  |
| 22 | `ga4_revenue` | `numeric` | yes |  |
| 23 | `ga4_active_users` | `integer` | yes |  |
| 24 | `fetched_at` | `timestamp with time zone` | no | `now()` |
| 25 | `sessions_by_source` | `jsonb` | yes |  |
| 26 | `orders_paid` | `integer` | yes |  |
| 27 | `orders_direct` | `integer` | yes |  |
| 28 | `orders_excluded` | `integer` | yes |  |
| 29 | `revenue_excluded` | `numeric` | yes |  |
| 30 | `google_spend` | `numeric` | yes |  |
| 31 | `google_spend_as_of` | `timestamp with time zone` | yes |  |
| 32 | `pnl_sales` | `numeric` | yes |  |
| 33 | `pnl_orders` | `integer` | yes |  |
| 34 | `pnl_qty` | `integer` | yes |  |
| 35 | `silver_coin_orders` | `integer` | yes |  |
| 36 | `pnl_cancelled_orders` | `integer` | yes |  |
| 37 | `pnl_cancelled_sales` | `numeric` | yes |  |
| 38 | `pnl_cancelled_qty` | `integer` | yes |  |
| 39 | `pnl_refunds` | `numeric` | yes |  |
| 40 | `shopify_total_sales` | `numeric` | yes |  |
| 41 | `shopify_returns` | `numeric` | yes |  |
| 42 | `pnl_cancelled_refunded` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `hourly_campaign_tracker_pkey`
  - `CREATE UNIQUE INDEX hourly_campaign_tracker_pkey ON public.hourly_campaign_tracker USING btree (hour)`
- Index — `ix_hourly_tracker_day`: `CREATE INDEX ix_hourly_tracker_day ON public.hourly_campaign_tracker USING btree (day_ist)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

**One IST hour of one day.** `hour` is the UTC instant that *begins* the
IST hour, so the day a row belongs to is already decided and stored in
`day_ist` — never re-derive it. `hour_of_day` is 0–23 in IST.

Written by `scripts/fetch_hourly_tracker.py`, run hourly by the
`hourly-tracker.yml` GitHub workflow. 24 rows per complete day.

## Three different revenue figures, deliberately

This is the single biggest trap in this table. They are not variants of
one number and must never be substituted for each other.

| column | rule |
|---|---|
| `shopify_total_sales` | **Shopify's own Total sales**, stored verbatim: gross, less discounts, less returns, plus tax. Equals what the Shopify admin shows. This is the headline. |
| `revenue` | Order-derived: sum of each order's `totalPrice`, dropping cancelled, `Return`-without-`Exchange`, and `Return_Prime` orders. **Gross of returns.** This is what the per-channel splits are carved from. |
| `pnl_sales` | The P&L basis: drops `inf` and `Return_Prime`, and **keeps cancelled orders**, which are then deducted on their own line. |

`revenue_meta`, `revenue_google` and `revenue_paid` are carved from the
**order-derived** figure, so they do **not** sum to `shopify_total_sales`
— and cannot. Shopify dates a refund by the day it was *issued*, against
an order from any day, so a refund belongs to no campaign hour.

`revenue_shopifyql` is a deliberately different cross-check, typically
within half a per cent. It is not used in any calculation.

## Spend is one measurement and two allocations

- `meta_spend` — measured hourly, genuinely.
- `google_spend` — a DAILY total shared across hours by each hour's
  share of Google-driven sessions. `google_spend_as_of` carries when
  that daily total was captured; hours past it store NULL, not zero.
- `kwikchat_spend` — a daily total shared out **evenly**. Check
  `kwikchat_spend_daily.is_estimate` before trusting it: a flat
  placeholder is used for any day with no measured row, and real
  Kwikchat spend is spiky, so the placeholder is wrong on most days.

**The totals are real; the within-day shape of the last two is inferred.**

## Cancellations and refunds

`pnl_cancelled_*` are measured from `cancelledAt`, not assumed, and are
a SUBSET of `pnl_sales`/`pnl_orders`/`pnl_qty`. A cancellation is dated
by the order's own hour, not the hour it was cancelled in, so the hours
still sum to the day.

`pnl_cancelled_refunded` is how much of that Shopify has already
refunded — and therefore already removed from `shopify_total_sales`.
Deduct only `pnl_cancelled_sales - pnl_cancelled_refunded`, or the
refunded part comes out twice. Most cancelled value here is *not*
refunded (COD cancelled before payment).

`pnl_refunds` counts refunds on orders that were **not** cancelled. It
has been zero on every day observed.

## Traps

- **Ratios must be re-divided from the summed counts**, never averaged
  across hours — averaging weights a dead 4am hour the same as a 9pm
  peak.
- **NULL is not zero.** An hour past the Google capture has unknown
  Google spend, not none.
- **A past day's figures drift down for about a week** as `Return` tags
  land. Return Prime settles returns outside Shopify's returns API, so
  tags are the only signal and they arrive days late.
- `day_ist` is IST; the database's `CURRENT_DATE` is UTC. Use
  `(now() AT TIME ZONE 'Asia/Kolkata')::date`.
- `orders_excluded` / `revenue_excluded` hold what the revenue basis
  dropped, so a gap against Shopify's admin can be explained rather than
  argued about.

## See also

`docs/hourly-tracker-kpis.md` defines every KPI, the three populations
and the comparison rules in full.
