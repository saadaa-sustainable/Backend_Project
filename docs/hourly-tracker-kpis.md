# Hourly Tracker: what every number means

Definitions for the campaign tracker — the admin section at
`/user/analytics#hourly-tracker` and the standalone deploy in
`tracker/`. Both read one endpoint, `GET /admin/analytics/hourly-tracker`,
so they cannot disagree.

Everything here is definitions. This repo is public; keep spend, order
and revenue figures out of it.

**Where each number is produced**

| | |
|---|---|
| ingest | `scripts/fetch_hourly_tracker.py` → `hourly_campaign_tracker` |
| ratios | `_derive_hourly` and `_totals` in `app/api/routers/analytics.py` |
| tests | `tests/test_hourly_tracker_rollups.py` |

**One rule that governs the lot.** Only counts are stored. Every ratio
is derived — per hour from that hour's counts, and for the day from the
day's *summed* counts. A day figure is never the average of the hourly
ones: averaging would weight a dead 04:00 the same as a 21:00 peak. On
30 Oct that is the difference between an AOV of ₹1,391 and ₹1,237.

A zero denominator yields NULL, not 0. An hour with no paid sessions
has no cost per paid session, and a 0 would sort it below an hour that
genuinely performed badly.

---

## 1. The three populations

Almost every KPI is one of these divided by another, so they come first.

### Sessions

`FROM sessions SHOW sessions GROUP BY hour, utm_source` — ShopifyQL,
bucketed into the IST hour. ShopifyQL returns UTC instants, so IST
midnight arrives as `18:30Z` the day before; `ist_hour()` normalises it.

Each session is sorted by its `utm_source`:

| bucket | rule |
|---|---|
| **direct** | no `utm_source`, or one that literally says `direct`, `none`, `(direct)`, `(none)` |
| **paid** | everything else — the complement of direct |
| **meta** | `meta*`, `facebook`, `fb`, `ig`, `instagram`, `igshopping`, `an`, `msg`, `messenger`, `fb.me`, `*.facebook.com`, `*.instagram.com`, `{{site_source_name}}` |
| **google** | contains `google` or `adwords`, or is `gads`, `yt_ads`, `youtube` |

**"Paid" means attributed, not bought.** A session tagged
`utm_source=newsletter` is "paid" by this rule and cost nothing. Meta
and Google are *not* subsets that add up to paid — they overlap it and
each other is not guaranteed. Only paid + direct is a true partition.

The raw split survives in `sessions_by_source` and is what the donut
draws. The buckets above are lossy; that column is what they were
bucketed *from*.

### Orders and revenue

Read from the orders themselves, not from ShopifyQL — ShopifyQL refuses
to split sales by `utm_source` ("Attribution Syntax Required"). Revenue
is the sum of `totalPriceSet.shopMoney.amount`, which is why the
per-channel columns add up against it exactly.

**What is excluded** (`is_excluded_order`):

```
cancelled_at is set          -> excluded
tagged Return, no Exchange   -> excluded
tagged Exchange              -> KEPT
tagged Return AND Exchange   -> KEPT  (the exchange leg of a swap)
```

An exchange swaps for an item of equal value, so the money stayed and
this tracker counts it. The dashboard uses a **deliberately different**
rule and drops exchanges too, because it answers "what did we end up
keeping" rather than "what did this campaign hour bring in". Over
October: ₹4.21Cr on the tracker's basis against ₹3.89Cr on the
dashboard's, from the same 36,796 orders. Both rules are pinned by
tests, including one asserting they disagree.

Excluded orders are not dropped silently — they are counted into
`orders_excluded` / `revenue_excluded`, so a gap against Shopify's own
admin can be explained rather than argued about.

> **Returns arrive late.** Return Prime settles returns *outside*
> Shopify's native returns API, so `returnStatus` is useless and tags
> are the only signal — and tags land days after the order. Today shows
> almost none; a day a week old has most of them. **A past day's revenue
> here will read lower than it did live.** That is the data arriving,
> not a bug.

Orders split on the same denominators as the sessions: `orders_paid` and
`orders_direct` sum to `orders`.

### Spend

`meta_spend + google_spend + kwikchat_spend`. The three are not the same
kind of number:

| | grain | how it lands on an hour |
|---|---|---|
| **Meta** | hourly | measured — `breakdowns=hourly_stats_aggregated_by_advertiser_time_zone` (advertiser TZ is IST) |
| **Google** | daily | the day's total, shared out by each hour's share of *Google-driven sessions* |
| **Kwikchat** | flat ₹30,000/day | ₹1,250 an hour |

The Google allocator is not arbitrary: on 29 Oct the Google session
share and the Meta spend share tracked each other within ~1.5 points at
every hour, troughing together at 03:00 and peaking together in the
evening. An even 24th would put as much spend at 4am as at 8pm. **The
total is measured; the shape is inferred.**

Google's daily figure comes from a BigQuery export that syncs each
morning, so on a day still running it covers only up to that sync.
`google_spend_as_of` carries the sync time (from `_airbyte_emitted_at`,
*not* our fetch time, which moves whenever the fetcher re-runs). Hours
past it store NULL and show a dash — "not told yet" and "Google spent
nothing" are different claims. Those hours still carry their Meta and
Kwikchat spend, so the cost curve keeps no hole.

Kwikchat is a **placeholder**, not a measurement. Any ratio with spend
in it inherits that.

---

## 2. The KPIs

Fourteen, in the order they appear.

| # | KPI | Definition | Read it as |
|---|---|---|---|
| 1 | **Sessions** | all sessions | traffic |
| 2 | **Spend** | Meta + Google + Kwikchat | what the day cost |
| 3 | **Revenue** | Σ order totals, exclusions applied | what it brought in |
| 4 | **Cost / session** | spend ÷ sessions | what a visit cost |
| 5 | **Rev / session** | revenue ÷ sessions | what a visit returned |
| 6 | **AOV** | revenue ÷ **orders** | basket size |
| 7 | **Cost / paid session** | spend ÷ paid sessions | what a *bought* visit cost |
| 8 | **Rev / paid session** | revenue from orders with a `utm_source` ÷ paid sessions | what a bought visit returned |
| 9 | **AMER** | new-customer revenue ÷ spend | acquisition efficiency |
| 10 | **Conversion rate** | orders ÷ sessions | how much traffic buys |
| 11 | **CR / paid** | paid orders ÷ paid sessions | how well bought traffic buys |
| 12 | **CR / direct** | direct orders ÷ direct sessions | how well returning traffic buys |
| 13 | **% paid sessions** | paid ÷ all sessions | the traffic mix |
| 14 | **% direct sessions** | direct ÷ all sessions | the complement of 13 |

### Notes that matter when reading them

**AOV is the only revenue KPI whose denominator is orders.** Rev /
session moves when *either* conversion or basket size moves and cannot
tell you which. AOV and CR read together can.

**The paid pair moves opposite to the all-traffic pair.** On 30 Oct
cost was *higher* on paid (₹6.76 vs ₹6.10) because the denominator drops
the ~10% of sessions that arrived direct, while revenue was *lower*
(₹15.84 vs ₹20.38) because direct converts at 5.02% against paid's
1.04%. Either figure alone misleads. This is normal — direct traffic is
largely returning customers.

**AMER's numerator is new-customer revenue only**, where "new" is
`customer.numberOfOrders == 1` at order time — their lifetime first.
Its denominator is total spend, including the Kwikchat placeholder.

**CR excludes cancelled and returned orders but counts exchanges**, like
every revenue figure here. So CR drifts down on past days as return tags
land.

---

## 3. Table-only columns

The table carries the hourly breakdown plus four things not promoted to
KPIs.

| column | definition |
|---|---|
| **Impressions** | Meta only. Google has no hourly feed and Kwikchat has none at all, so this is *not* total impressions. |
| **Orders** | the numerator of both CR and AOV |
| **ARPU (GA4)** | GA4 revenue ÷ GA4 **active users** — a different tool, a different denominator, and *not* comparable to Rev / session. Best effort: GA4 lags, and its `(other)` cardinality bucket is skipped. |
| **Google** | the allocated hourly slice of Google spend; a dash means the hour is past the daily capture |

`revenue_shopifyql` is stored but not shown: ShopifyQL's own total for
the hour, kept as a cross-check against a different measure. Drift
against it grows with a day's age as returns are tagged — ~3% today,
~14% a week back — which is the return lag made visible, not an error.

---

## 4. Comparison

Every figure shows the chosen day over a baseline (the previous day
unless one is named), with the change beneath.

**The baseline is clamped to the hours the chosen day has reached.** A
part-finished today against a complete yesterday flatters yesterday
every time. `compare_full` carries the unclamped day for when it stops
mattering.

**The live hour shows its pair but withholds the percentage.** Its
figures are real; its change against a *complete* hour is not. Before
this was suppressed, 18:10 read sessions −59.9% and spend −79.8% with
nothing wrong at all.

**Shares move in points, not per cent.** "90.2% is 2% up on 88.4%" is a
different and much smaller claim than "up 1.8 points". The share KPIs
and all three conversion rates report points.

**A missing baseline is not a missing day.** If the day before was never
ingested, the chosen day's figures still render and each comparison
shows a dash. A day outside the table says which span the tracker holds.

---

## 5. Freshness

| source | cadence | note |
|---|---|---|
| Shopify sessions, orders | hourly, live | the cron runs at `5 * * * *` |
| Meta spend, impressions | hourly, live | |
| Google spend | daily, morning sync | partial on a day still running |
| Kwikchat | never | flat placeholder |
| GA4 | hourly, best effort | lags; may be absent |

Backfill a range with
`scripts/fetch_hourly_tracker.py --date <day> --days <n>`. It is
idempotent — re-running a day replaces it, which is how a past day picks
up returns tagged since.
