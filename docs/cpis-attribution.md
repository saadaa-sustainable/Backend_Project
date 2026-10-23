# CPIS attribution: every type, how it works, and what it is worth

## Value-Weighted revision — 2026-10-23

The current Value-Weighted mode uses **daily product revenue share**, replacing
the window-level weighting described in the historical audit below. Equal /
Order retains its existing rules and source tables.

For each IST day and resolved UTM ad (`utm_content`) or ad set (`utm_term`):

```
SKU revenue = sum(quantity × original unit price) from its matched order lines
SKU spend   = entity's spend that day × SKU revenue / entity's product revenue that day
SKU CPIS    = sum(SKU daily spend) / sum(SKU units in the selected dates)
```

₹10,000 spend with X revenue ₹10,000 (10 units) and Y revenue ₹3,500 (5 units)
allocates ₹7,407.41 to X and ₹2,592.59 to Y. Their CPIS values are ₹740.74
and ₹518.52 respectively. Percentages are never rounded before allocation.

An eligible order without a resolvable ad triggers **ad-set fallback for that
ad set on that day**. Its resolved child-ad orders join the same pool, and
child-ad spend is not also charged. Other days remain independent. Different
ad sets, days and accounts' entity IDs never share a denominator. Unmapped
orders and VOIDED orders remain excluded. Revenue retains the existing gross
line-item definition; discounts, tax and shipping do not change the weights.
Zero-revenue pools remain unallocated; there is no equal-order fallback.

`app/services/gold/cpis_value_weighted.py` owns the calculation.
`scripts/refresh_cpis_value_weighted.py` materializes
`public.cpis_value_weighted_daily`, keyed by day/entity/master SKU. Both
preset and custom date ranges aggregate this same table. Units, orders,
revenue, halo, sorting, filters, exports, KPI allocated spend and the daily
order chart use this mode's population. The API selects it with
`attribution_mode=value_weighted`; its normal attribution columns and `_vw`
aliases describe this selected population. Equal-mode responses leave the
superseded `_vw` aliases null instead of returning the old formula.

Apply `supabase/migrations/20261023101754_cpis_daily_revenue_weighting.sql`,
then run `.venv/bin/python scripts/refresh_cpis_value_weighted.py` once.
The daily refresh chain includes `cpis_value_weighted` after Meta/Shopify and
the existing CPIS refreshes. This takes effect in scheduled runs after merge
to `master`. `--since` / `--until` support scoped rebuilds; rows outside the
requested interval are preserved. A failed refresh rolls back the entire
replacement and leaves the prior snapshot intact.

The source table has RLS enabled and no browser/Data API read policies. The
existing backend database connection serves the analytics API. API and browser
cache keys include attribution mode, dates and filters.

### Historical audit (before the revision)

Validated against live data on **2026-10-22**. Every number below was
measured, not assumed. The reference window is the 30 days to
2026-10-21.

CPIS answers "what did it cost in ad spend to sell one unit of this
SKU". Getting there needs three independent decisions, and the project
answers each of them more than one way:

| layer | question | types |
|---|---|---|
| **A. Entity resolution** | which ad or ad set paid for this order? | 3 |
| **B. Spend attribution** | **how much spend does this SKU get charged?** | **4** |
| **C. SKU derivation** | which master SKU is this line item? | 2 parses |
| **D. Legacy correlation** | *(separate endpoint)* which ads mention this SKU? | 1 |

> **Section B is the one to read.** The `/cpis-utm` row model
> (`CpisUtmRow`, `app/api/routers/analytics.py:4851`) carries **four
> different spend-attributed figures per SKU**, computed by four
> different rules. Two are stored by `scripts/refresh_cpis_utm.py`; the
> other two are computed **in the endpoint** and exist in no table.
> Summed across SKUs they come to 49.7%, 206.2%, 99.8% and 99.8% of the
> same Meta spend.

---

## 0. The six tables, and which are alive

| table | rows | last built | served by |
|---|---|---|---|
| `cpis_by_sku_utm` | 254 | 2026-10-21 04:24 | `/cpis-utm` (7d/30d/90d) |
| `cpis_by_sku_daily` | 9,184 | 2026-10-21 04:24 | `/cpis-utm` custom ranges |
| `cpis_sku_ad_daily` | 64,944 | 2026-10-21 04:24 | `/cpis-utm` per-SKU ad list |
| `cpis_sku_context` | 100 | 2026-10-21 04:17 | `/cpis-utm` stock & velocity |
| `cpis_by_sku` | 318 | 2026-10-21 20:06 | `/cpis` |
| `master_sku_inventory_current` | 107 | — | inventory joins |

> **FIXED 2026-10-22 — `cpis_by_sku` was 55 days stale.** It had a
> `FlattenJob` entry in `app/services/silver/registry.py` and **no step
> in `scripts/refresh_all_daily.py`**, so only the in-process scheduler
> could refresh it — and that scheduler is off in production. Fourth
> instance of this bug here, after `meta_entities`, `ad_lifecycle` and
> `refresh_insights_tables`. A registry entry is not a schedule.
>
> `scripts/refresh_cpis_by_sku.py` now exists and runs nightly as
> `silver_cpis_by_sku`, last of the CPIS steps. Both inputs had been
> current the whole time — `ad_lifecycle` 2026-10-21 03:30,
> `shopify_inventory` through 2026-10-20 — so nothing was wrong with the
> data; nothing was running the job.
>
> **The refresh moved the numbers 17x, and that is the story.** 30d
> `SUM(ad_spend)` went from Rs 2,01,77,470 to Rs 34,53,62,313, because
> `ad_spend` is a LIFETIME total that grows every day an ad keeps
> spending. It reconciles exactly:
>
> ```
> lifetime spend of ads matched at least once   295,526,406
> + double-counted by multi-SKU match            49,835,906
> = table total                                 345,362,312
>   actual SUM(ad_spend), window_key='30d'      345,362,313
> ```
>
> Divided by 68,433 units sold in the window that is **Rs 5,047 of ad
> spend per unit** across the catalogue — on products priced Rs 599 to
> Rs 1,299. The table is now current and still not usable as a rate.

### Two writers, one table

`cpis_by_sku_utm` is written by **two** different implementations with
**different attribution semantics**:

* `app/services/gold/cpis_utm.py` — registry job `cpis_by_sku_utm`.
  Sums each ad's **whole** spend into **every** SKU it touched. No
  split. Does not know about the ad-set fallback or the `_vw` columns.
* `scripts/refresh_cpis_utm.py` — nightly step `silver_cpis_utm`.
  The real allocator described in section B.

Both `TRUNCATE` and rewrite the table. The nightly runs the second, so
today the good one wins — `computed_at` confirms it.

But the first is **reachable over HTTP right now**:

```
POST /admin/flatten/jobs/cpis_by_sku_utm/run
```

`app/api/routers/flatten.py:76` looks the key up in `FLATTEN_REGISTRY`
and runs it with `force=True`. One click on that admin control replaces
correct, split spend with unsplit spend and blanks the `_vw` columns,
until the next nightly puts it back. The same endpoint is the only thing
that can refresh `cpis_by_sku` at all.

---

## A. Entity resolution — which ad pays for the order

Source: `scripts/refresh_cpis_utm.py`, CTEs `matched` → `fallback_adsets`
→ `resolved`.

### A1. `ad:<id>` — ad direct

`shopify_orders.utm_content` is a 10–20 digit ad id **and** that id
exists in `ad_lifecycle`. Spend comes from `insights_daily_by_ad`.

### A2. `adset:<id>` — ad-set fallback

`utm_content` did not resolve, but `utm_term` is a real
`meta_adsets.adset_id`. Spend comes from `insights_daily_by_adset`.

**The fallback is decided per AD SET, not per order.** If *any* order in
an ad set cannot name an ad, the **whole ad set** switches to ad-set
allocation — including the orders that *did* name an ad.

> Why it has to work that way: allocating some of an ad set's orders
> from per-ad spend and the rest from the ad-set total would count the
> overlap twice, and the reconciliation `allocated + unattributed =
> total` would stop holding.

The existence check on `meta_adsets` is not decoration. Without it any
numeric `utm_term` becomes an entity with **no spend**, which would add
orders to a SKU at zero cost and quietly *improve* its CPIS.

### A3. `UNMAPPED` — excluded from CPIS

Neither resolves. The order is dropped from CPIS entirely.

### Measured split, 30 days to 2026-10-21

| tier | orders | revenue | share |
|---|---|---|---|
| A1 ad direct | 10,904 | ₹1,36,34,200 | 30.4% |
| A2 ad-set fallback | 5,394 | ₹65,78,818 | 15.0% |
| **A3 UNMAPPED** | **19,600** | **₹2,41,12,344** | **54.6%** |

**54.6% of orders never reach CPIS.** What they are:

| utm_source | orders | revenue | verdict |
|---|---|---|---|
| `direct` | 5,678 | ₹97,15,142 | correctly excluded — not ad-driven |
| `kwikengage` | 2,756 | ₹43,35,740 | correctly excluded |
| *(empty)* | 6,111 | ₹23,62,005 | correctly excluded |
| **`google`** | **2,719** | **₹43,05,537** | **excluded, but now attributable** |
| `affiliate` | 745 | ₹13,01,616 | correctly excluded |
| `kwikchat` | 742 | ₹10,71,295 | correctly excluded |
| meta, unresolved | 318 | ₹4,19,164 | deleted ad / CBO shuffle |

Most of the 54.6% *should* be excluded. The exception is Google.

### CPIS is Meta-only

The only spend sources in any CPIS producer are
`insights_daily_by_ad` and `insights_daily_by_adset`. **No Google
spend enters CPIS.** `google_ads_spend_daily` is never read, and
`shopify_order_attribution`'s Google tiers are never consulted.

So every Google rupee is missing from the numerator *and* every Google
order from the denominator. For the 30d window that is 2,719 orders and
₹43.1 L of revenue invisible to CPIS, against Google spend of roughly
₹11.6 L a month that no SKU is ever charged for.

### Cancellations

`financial_status = 'VOIDED'` is excluded. `PENDING` is kept — it is COD
awaiting payment and 16,245 of 16,409 are fulfilled. `REFUNDED` is kept,
because the spec keeps gross units and returns land long after the sale.

---

## B. Spend attribution — the four figures per SKU

All four appear on the same `/cpis-utm` row. 30 days to 2026-10-21,
summed across every SKU, against Meta spend of **Rs 1,12,37,961**:

| # | field | where computed | summed across SKUs | of Meta spend |
|---|---|---|---|---|
| 1 | `name_matched_spend` | endpoint, CTE `name_ads` | Rs 55,79,891 | **49.7%** |
| 2 | `utm_matched_spend` | endpoint, CTEs `utm_sku_ads` → `utm_ads` | Rs 2,31,72,061 | **206.2%** |
| 3 | `ad_spend` | `refresh_cpis_utm.py`, stored | Rs 1,12,18,821 | 99.8% |
| 4 | `ad_spend_vw` | `refresh_cpis_utm.py`, stored | Rs 1,12,18,821 | 99.8% |

Per SKU, 30d window — the same SKU gets four different spend figures:

| master | 1 name | 2 utm | 3 equal | 4 value-wtd | units |
|---|---|---|---|---|---|
| SMCP | 11,84,747 | 36,40,460 | 34,94,667 | 33,36,982 | 8,757 |
| SDCP | 14,69,034 | 26,43,818 | 16,77,197 | 15,83,075 | 4,126 |
| SDVPL | 1,48,839 | 14,75,842 | 8,55,478 | 7,94,110 | 2,007 |
| SDAWP | 1,53,867 | 18,17,445 | 6,58,626 | 6,83,218 | 1,414 |
| SDFSK | 4,56,349 | 13,56,381 | 6,01,129 | 5,98,624 | 1,685 |
| SDCSP | 1,13,361 | 13,19,807 | 5,12,548 | 4,75,523 | 1,240 |

### B1. `name_matched_spend` — the ad's NAME mentions the SKU

```sql
LEFT JOIN ad_lifecycle al ON al.ad_name ~* ('\y' || p.master_sku || '\y')
LEFT JOIN insights_windowed iw ON iw.ad_id = al.ad_id
```

A **word-boundary** regex, not a bare substring — so this does NOT have
the collision that `cpis_by_sku` has (section D). `\ySDFS\y` will not
match an ad named `SDFSK...`, because `K` is a word character.

> **FIXED 2026-10-22, in two passes.** The text below is the diagnosis
> that led to it.
>
> **Pass 1** replaced `\y` with `[^A-Za-z0-9]` bounds at all five sites
> that match an ad name to a SKU. Coverage 52.5% → 81.4% of Meta spend
> (+₹33,45,795 over the 30 days to 2026-10-21).
>
> **Pass 2** added a 0–2 letter **colour code** after the SKU, plus a
> **longest-match** rule. Pass 1 still read SMFSK at ₹93,924 against
> Meta's ₹2,04,081 — 46% — because its largest ads are
> `PDP-SMFSKEC_...` and `SMFSKRT/...`. Colour tolerance alone would have
> been worse than the bug: `SDFS` + `K` is a legal colour, so SDFS would
> have absorbed all ₹6,20,266 of SDFSK's spend, ₹12.8 L misattributed
> across the seven nested families. So when several SKUs match one ad,
> only the longest of a nested family is credited; unrelated SKUs on a
> genuine multi-SKU ad all survive.
>
> Built as a CTE (`name_cand` → `name_match`), **not** a correlated
> `NOT EXISTS` in the join: the correlated form re-runs the regex per
> candidate row and measured **83,661 blocks** against this shape's
> **14,034** (10,026 before colour codes).
>
> Verified against the running endpoint, not just unit tests: SMFSK
> reads ₹2,04,081, SDFS ₹0, SDCPT ₹63,461. Pinned by
> `tests/test_cpis_ad_name_match.py`.

**`_` is also a word character in Postgres**, and that broke it in
the other direction. Verified:

| ad name | SKU | `\y..\y` | bare substring |
|---|---|---|---|
| `SDFSK_GRWM_DEC23` | SDFSK | **no** | yes |
| `SDCP_OFF_FL_916_ITE-Feb-25` | SDCP | **no** | yes |
| `SMCPBL-Reel-Oct` | SMCP | **no** | yes |
| `SDFSK+SDFLK` | SDFSK | yes | yes |
| `SDFSK_GRWM_DEC23` | SDFS | no *(correct)* | yes *(collision)* |

`SDFSK_GRWM_DEC23` is plainly an ad for SDFSK and this rule skips it,
because the SKU is followed by an underscore. Measured over distinct ads
in the window:

| matching rule | spend matched | of Meta spend |
|---|---|---|
| `\y..\y` — **what the section uses** | Rs 59,03,432 | 52.5% |
| separator-bounded `(^|[^A-Za-z0-9])sku([^A-Za-z0-9]|$)` | Rs 91,38,284 | 81.3% |
| **missed by the section** | **Rs 32,34,852** | **28.8 pp** |

So `name_matched_spend` under-reports by about **Rs 32.3 L in 30 days**
— roughly a third of the spend on ads that genuinely name their SKU.
Anything derived from it inherits the error: `name_matched_roas_lifetime`,
`name_matched_nc_roas`, `active_spend_per_day`, `weekly_ad_spend` and
`required_creatives_per_week` (which is
`FLOOR(name_matched_spend * 7 / n_days / 100000)`, so it under-prescribes
creative tests).

### B2. `utm_matched_spend` — ads that reached buyers of the SKU

```sql
FROM cpis_sku_ad_daily usa            -- (day, master_sku, ad_id)
LEFT JOIN insights_daily_by_ad idba
       ON idba.ad_id = usa.ad_id AND idba.day = usa.day
```

Day-scoped: an ad's Tuesday spend counts for SMCP only if Tuesday's SMCP
orders named that ad. Days it ran but drove no SKU order are excluded.

**It deliberately double-counts across SKUs.** An ad driving both SMCP
and SDCP orders contributes 100% of its spend to *both*. The code says
so explicitly — it is an **affinity** metric ("how much did I spend on
ads that reached buyers of this SKU?"), not a portfolio share. Hence
206.2%: summing this column across SKUs is meaningless by design.

`ad_spend` and `ad_spend_vw` are the allocation-aware pair, computed in
the same pass by `scripts/refresh_cpis_utm.py` and stored. They are the
only two of the four that reconcile. Worked through below.

### Worked example — a real order

Order `gid://shopify/Order/7331797139702`, driven by ad
`120251750022110431`, in the 30d window:

```
ad_spend (30d)        63,692.07
orders for that ad           78
ad total revenue        108,555
per_order_share          816.56      = 63,692.07 / 78
average basket         1,391.73      = 108,555 / 78
THIS basket            2,696.00      = 1.94x the average
```

The basket holds four line items collapsing to two master SKUs:

| variant SKU | master | qty | unit price | line revenue | share |
|---|---|---|---|---|---|
| `SMCPBL_M` | SMCP | 1 | 899 | 899 | 33.3% |
| `SMJRTWH_M` | SMJRT | 1 | 599 | 599 | 22.2% |
| `SMJRTBL_M` | SMJRT | 1 | 599 | 599 | 22.2% |
| `SMJRTGG_M` | SMJRT | 1 | 599 | 599 | 22.2% |

### B3. `ad_spend` — equal per order, then revenue share within it

```
per_order_share   = ad_spend / n_orders_for_ad
within_order      = line_revenue / basket_revenue
contribution      = per_order_share × within_order
```

| master | share | allocation |
|---|---|---|
| SMCP | 33.3% | **272.29** |
| SMJRT | 66.7% | **544.28** |
| | | 816.56 = exactly one order's share |

Every conversion event counts equally regardless of value. A ₹500 order
and a ₹5,000 order each absorb `ad_spend / n_orders`.

If the basket has no revenue to share, it falls back to `qty /
order_total_qty`; if there is no quantity either, the contribution is 0.

### B4. `ad_spend_vw` — value-weighted across the ad's whole revenue

```
contribution = ad_spend × (line_revenue / ad_total_revenue)
```

| master | line revenue / 108,555 | allocation |
|---|---|---|
| SMCP | 0.83% | **527.47** |
| SMJRT | 1.66% | **1,054.35** |
| | | 1,581.81 |

This order absorbs **1,581.81**, not 816.56, because its basket is 1.94×
the ad's average. Big baskets pull more spend; small ones less.

When an ad drove zero revenue there is nothing to weight by, so B2 falls
back to B1 for that ad.

### Both give identical ROAS per SKU — by construction

Because spend follows revenue share, every SKU in a basket gets the same
ROAS; only the absolute cost differs:

```
equal split   SMCP 3.30   SMJRT 3.30
value weighted SMCP 1.70  SMJRT 1.70
```

CPIS is where the SKUs actually diverge, because units differ:

```
SMCP  272.29 / 1 unit  = 272.29 per unit
SMJRT 544.28 / 3 units = 181.43 per unit
```

### They sum to the same total, and neither double-counts

Identical totals are **correct** — both distribute the same pool, just
differently across SKUs. Per SKU they differ by −9.3% to +1.7%:

| master | equal | value-weighted | diff |
|---|---|---|---|
| SMCP | 30,84,429 | 29,94,080 | −2.9% |
| SDCP | 11,77,453 | 11,45,926 | −2.7% |
| SDASK | 2,95,535 | 2,68,110 | −9.3% |
| SDAWP | 4,91,813 | 5,00,327 | +1.7% |

### The preset window and a custom date range use DIFFERENT models

This is not a date-bounds difference. `app/api/routers/analytics.py:5413`
switches table on `from_date and to_date`:

| path | table | same 30 days |
|---|---|---|
| preset `30d` button | `cpis_by_sku_utm` | **Rs 1,12,18,821** |
| typed 2026-09-22 → 2026-10-21 | `cpis_by_sku_daily` | **Rs 85,04,867** |

A **24% smaller** spend figure for the identical period, because the two
tables scope spend differently:

* `cpis_by_sku_utm` allocates an ad's **whole window** spend if it drove
  any attributed order anywhere in the window — 99.8% of Meta spend.
* `cpis_by_sku_daily` allocates an ad's **day D** spend only if it drove
  an attributed order **on day D** — 75.7%. Days it ran but converted
  nothing go to a portfolio-wide unattributed bucket, deliberately not
  pushed onto any SKU.

Both are defensible. Showing them under the same column name in the same
UI, switched by whether the user clicked a button or typed dates, is not.
The two ad-level and ad-set-level spend pools are the same size
(Rs 1,12,37,961 vs Rs 1,12,38,001, Rs 40 apart), so the gap is entirely
the day-scoping rule.

### halo_spend is always 0, and primary_weight is never set

`halo_orders` / `halo_units` / `halo_revenue` **are** populated — 10,879
halo units and Rs 1,04,21,721 halo revenue in the 30d window, non-zero
on 85 of 87 SKUs. But `halo_spend` is `0` on every row, by design:
`ad_spend` already distributes every rupee, so charging halo spend on
top would double-count. The custom-range path hardcodes
`0::numeric AS halo_spend`.

`primary_weight` is NULL on all 254 rows — the column exists and nothing
writes it.

Note that `refresh_cpis_utm.py`'s own docstring says the halo columns
"remain in the schema as placeholders ... halo has no natural definition
yet". That is now out of date: three of the four are populated.

---

## C. SKU derivation — variant to master

```
SDCPBL_L   variant SKU
SDCPBL     colour SKU   (strip the trailing _<size>)
SDCP       master SKU   (strip the 2-char colour code)
```

Validated against `^(SD|SM|SU)[A-Z]{1,4}$` — SD women, SM men, SU
unisex — and anything shorter than 4 characters is rejected.

### Two different parses are in use

| implementation | expression |
|---|---|
| `cpis.py`, `cpis_utm.py`, `refresh_cpis_utm.py`, `refresh_cpis_by_sku_daily.py` | `regexp_replace(sku,'_[A-Za-z0-9]+$','')` — strip the **last** `_` segment |
| `refresh_cpis_sku_ad_daily.py` | `split_part(sku,'_',1)` — take everything before the **first** `_` |

`refresh_cpis_sku_ad_daily.py`'s docstring says the parse is "copied
verbatim from the endpoint so the two cannot disagree." **It is not
verbatim.** The two differ for any SKU with two or more underscores:

```
SDCPBL_L_XL   strip-last  -> SDCPBL_L -> SDCPB     }  different
              before-first -> SDCPBL   -> SDCP     }  master SKUs
```

**Measured: harmless today.** Of 3,933 distinct variant SKUs on orders
since 2026-07-01, 3,929 have exactly one underscore and 4 have none.
None has two. The two parses agree on **100%** of real SKUs. This is a
latent hazard, not a live error — but the docstring's claim is false
and the next naming convention could break it silently.

### Missing validation in one place

Every producer filters on `^(SD|SM|SU)[A-Z]{1,4}$` **except**
`refresh_cpis_sku_ad_daily.py`, which has no pattern filter. Result:
10 rows of 64,944 (0.015%) carry a master SKU the rest reject —
`SDAFD-CCS` (9 rows) and `SD` (1 row). Negligible in effect, wrong in
principle.

---

## D. Legacy correlation — `cpis_by_sku` (NOT attribution)

`app/services/gold/cpis.py` predates the attribution work and does
something fundamentally different: it **correlates** ads to SKUs by
**case-insensitive substring match on the ad name**, then totals
store-wide inventory sales.

```python
needle = master_sku.lower()
return [ad_id for ad_id, name in ad_names.items() if needle in name.lower()]
```

It never looks at an order. Nothing ties the spend to a sale.

### It also mixes window scopes

| column | scope |
|---|---|
| `units_sold` | genuinely windowed (1d/7d/30d) |
| `ad_spend`, `ncp_count` | **lifetime totals**, not windowed |
| `cost_per_unit_sold` | lifetime spend ÷ windowed units |

`cost_per_unit_sold` divides a lifetime numerator by a 30-day
denominator. The module docstring admits this. It is not a rate.

### The substring matcher double-counts ₹4.98 Cr

Measured against 22,657 named ads in `ad_lifecycle` and 106 master SKUs
parsed from `shopify_inventory`:

| ads matching | count | spend |
|---|---|---|
| 1 master SKU | 11,668 | ₹24.91 Cr |
| 2 master SKUs | 2,806 | ₹4.31 Cr |
| 3 master SKUs | 220 | ₹33.6 L |
| 4 master SKUs | 20 | ₹4,099 |

An ad matching *n* SKUs has its **full spend charged to all *n***.
Total over-counted: **₹4,98,35,906**. And it splits into two very
different causes:

| cause | spend |
|---|---|
| **substring collision (a bug)** | **₹4,36,06,585 — 87.5%** |
| genuine multi-SKU ads | ₹62,29,322 |

**The collision.** Seven master SKUs are substrings of other master
SKUs: `SDAS`, `SDCP`, `SDCS`, `SDFP`, `SDFS`, `SDSK`, `SMLS`.

```
ad name "SDFSK_GRWM_DEC23"
  matches SDFSK   correct
  matches SDFS    WRONG - "SDFS" is a prefix of "SDFSK"
```

That ad's entire spend is charged to `SDFS`, a SKU whose code never
appeared in the ad name. 2,710 ads are affected.

**The genuine case** is different and arguably defensible:

```
ad name "SDFSK+SDFLK"                     a real bundle ad
ad name "CLP-SDAMK+MU+NA+IHP+SDVSK_..."   a real multi-product ad
```

Charging full spend to both is still wrong — it should be split, as
section B does — but at least both SKUs were really advertised.

### The collision, now visible on the live dashboard

After the 2026-10-22 refresh, `/cpis` shows this for the 30d window:

| master SKU | matched ads | ad_spend (lifetime) | units 30d | cost/unit |
|---|---|---|---|---|
| SDCP | 1,965 | 13,21,30,353 | 9,940 | 13,293 |
| SDFSK | 1,477 | 2,94,35,702 | 4,283 | 6,873 |
| **SDFS** | **1,541** | **2,99,76,301** | **68** | **4,39,357** |
| SDFLK | 1,114 | 2,44,42,990 | 2,300 | 10,627 |
| SMCP | 467 | 2,36,86,953 | 18,454 | 1,284 |
| **SDTJ** | 475 | 75,68,336 | 28 | **2,70,298** |

`SDFS` and `SDFSK` carry almost the same spend — Rs 2.99 Cr against
Rs 2.94 Cr — and `SDFS` is credited with *more* ads than `SDFSK` while
selling 68 units to its 4,283. That is the nested-substring collision
in plain sight: nearly every ad named for `SDFSK` also matches `SDFS`,
so `SDFS` inherits a Rs 3 Cr spend figure and a cost of Rs 4,39,357 per
unit on a garment that retails under Rs 1,300.

---

## Summary of validation findings

| # | finding | severity |
|---|---|---|
| 1 | ~~`cpis_by_sku` 55 days stale~~ — **FIXED 2026-10-22**: `scripts/refresh_cpis_by_sku.py` added, runs nightly as `silver_cpis_by_sku`. Refreshing moved 30d spend 17x (Rs 2.02 Cr → Rs 34.54 Cr) because `ad_spend` is a lifetime total | resolved |
| 2 | **`/cpis` only** — `cpis_by_sku`'s bare-substring matcher charges ₹4.36 Cr to SKUs never named, via 7 nested SKU codes. Does NOT affect the `/cpis-utm` section, which uses a word-boundary regex | **high** |
| 2b | ~~`name_matched_spend`'s `\y..\y` regex treats `_` as a word char~~ — **FIXED 2026-10-22**: bounded on `[^A-Za-z0-9]` at all five match sites. Recovers ₹33.5 L of 30d spend (52.5% → 81.4% coverage); 53 of 100 SKUs gained, 0 lost | resolved |
| 2c | Preset window and custom date range use **different spend models** for the same period — ₹1.12 Cr vs ₹85.0 L over the same 30 days, under the same column name | **high** |
| 2d | `utm_matched_spend` sums to **206.2%** of Meta spend across SKUs — by design (affinity metric), but nothing in the UI says it must not be totalled | **medium** |
| 3 | Google entirely absent from CPIS — 2,719 orders / ₹43.1 L excluded, Google spend never charged | **high** |
| 4 | Two writers for `cpis_by_sku_utm` with different semantics; the unsplit one is reachable via `POST /admin/flatten/jobs/cpis_by_sku_utm/run` with `force=True` | **high** |
| 5 | `cpis_by_sku.cost_per_unit_sold` divides lifetime spend by windowed units — now Rs 5,047/unit catalogue-wide on Rs 599–1,299 products; raised from medium after the refresh made it current and visible | **high** |
| 6 | Two SKU parses diverge on 2+ underscore SKUs; agree on 100% of current data | **low (latent)** |
| 7 | `cpis_sku_ad_daily` lacks the SKU pattern filter — 10 of 64,944 rows | **low** |

### What is actually sound

The main path — `/cpis-utm` off `cpis_by_sku_utm` and
`cpis_by_sku_daily` — holds up:

* `ad_spend` / `ad_spend_vw` reconcile — 99.8% of Meta spend on the
  windowed path, 75.7% on the day-scoped path with the remainder in an
  honest unattributed bucket, and neither exceeds 100%;
* the two allocations distribute the same pool and differ per SKU as
  intended;
* the ad-set fallback is correctly decided per ad set, so no spend is
  counted twice;
* the `meta_adsets` existence check stops zero-spend entities from
  flattering a SKU's CPIS;
* cancelled orders are handled with a documented, evidence-backed rule.

The problems are concentrated in the **legacy correlation table**, in
the **stale refresh wiring**, and in **Google being absent**.
