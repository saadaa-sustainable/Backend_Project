"""Expensive, low-converting ads, grouped by the SKU they advertise.

WHAT IT SELECTS
---------------
An ad is listed when, over the window, ALL of these hold:

    cost per FTEWV  <  --cost-per-ftewv   (default 12)
    CPC             <  --cpc              (default 12)
    conversion rate <  --cvr              (default 5%)
    add-to-cart %   <  --atc              (default 0.1%)

i.e. the traffic is CHEAP -- under Rs 12 a click and under Rs 12 a
first-time engaged visitor -- and still does not convert or add to cart
at the Shopify averages. Cheap traffic that does not buy.

This is deliberately NOT a "most expensive ads" list. The two cost gates
look GOOD and the two funnel gates look BAD, and the interesting ads are
the ones where both are true at once: the media buying is working and
the landing experience, the audience quality or the product match is
not. An ad that is merely expensive is a bidding problem; an ad that is
cheap and still dead is a different problem, and this finds those.

Because the cost gates now read "below", an ad that spent with ZERO
FTEWV is EXCLUDED rather than included -- its cost per first-time
engaged visitor is unbounded, which is the opposite of the cheap
traffic this selects. NULL fails the comparison, which is the behaviour
wanted here, so there is no COALESCE around it.

WHICH DENOMINATOR -- THIS IS THE PART TO READ
---------------------------------------------
`clicks` is NULL for every row of `insights_daily_by_ad` in the recent
window (30,258 of 30,258 on 2026-10-21), so CPC and CVR here are built
on `outbound_clicks`, which is the populated link-click column.

The add-to-cart rate is deliberately on a DIFFERENT denominator:
impressions, not clicks. Measured over the 30 days to 2026-10-21:

    CVR  = purchases / link clicks        1.603%
    CVR  = purchases / all clicks         1.333%
    CVR  = purchases / impressions        0.025%
    ATC% = add_to_cart / link clicks     12.408%
    ATC% = add_to_cart / all clicks      10.316%
    ATC% = add_to_cart / impressions      0.196%   <-- the only ~0.1%
    GA4   purchases / sessions            1.727%
    GA4   add_to_carts / sessions        16.429%

A 0.1% threshold is only meaningful against that last ATC basis. On
every click or session basis the fleet's ATC rate is 10-16%, far ABOVE
its conversion rate -- people add to cart far more often than they buy
-- so "ATC below 0.1% while CVR is below 5%" cannot both be read on the
same denominator. Both `atc_pct_of_clicks` and `atc_pct_of_impressions`
are therefore written to the sheet, and `--atc-basis` switches which one
the filter uses, so the assumption is visible and cheap to overturn.

AD TO SKU: THE NAME IS THE BETTER SOURCE
----------------------------------------
Two sources exist and they are not equally useful. Measured over the 30
days to 2026-10-21, against the 2,897 ads that spent:

    cpis_sku_ad_daily        1,037 ads (36%),  2-3 SKUs each, one on 76
    parsed from ad_name      2,245 ads (78%),  1.02 SKUs each
    either                   2,472 ads (85%)

`cpis_sku_ad_daily` is many-to-many: it records every SKU an ad touched,
so an ad comes back with a handful and a cell cannot say "the SKU for
this ad". The ad NAME carries the hero SKU in its own token --
`CLP-SDCP+MU+NA+IHP+SDCP_USP_...`, `CTP-BL+MU+OFF-BL+IHP+SDAWP_OFF_...`
-- which is one code per ad and twice the coverage.

Parsing is matched against the SKU vocabulary from cpis_sku_ad_daily
rather than by shape, so it can only ever emit a code that really
exists, and it reads EVERY token rather than the one after the prefix
(the SDAWP example above has a non-SKU prefix, `BL`).

Where both sources exist they agree on 609 of 810 ads (75%). The 201
that differ are mostly CPIS's breadth against the name's hero SKU.

WHY CPIS IS NOT A SOURCE
------------------------
It was one, as a fallback for ads whose name carried no SKU, and that
fallback wrecked the sheet. Measured 2026-10-21 on the cheap-traffic
gates: 28 ads matched, of which ONE -- `CTP-MSA+IFAD+NA+OSP+1PA-SIF-
7461-P1-...`, whose name has no SKU token -- fell back to CPIS and came
back with 28 SKUs. Its Rs 236,813 was then repeated under 28 separate
SKU banners, out of Rs 239,732 for the whole list. The summary read as
though 28 different SKUs had each wasted Rs 236k, when the other 27 ads
came to Rs 2,919 between them.

Fanning one ad's spend across every SKU it ever touched is not a weaker
answer than the name's single code, it is a different and misleading
one. So the ad name is now the ONLY source: an ad whose name carries no
SKU is reported honestly as `(no SKU mapped)` rather than smeared over
the catalogue. `cpis_skus` still carries the CPIS set per ad as an
audit trail, and `sku_source` is `ad_name` or `none`.

THE OUTPUT IS NOT COMMITTABLE
-----------------------------
Real ad names, campaign names, spend and SKUs. This repo is PUBLIC, so
`.gitignore` covers `docs/*.xlsx` and `exports/*.csv` for exactly this
reason. Write the workbook anywhere, but do not add it to the index.

Usage:
    ./.venv/bin/python scripts/export_underperforming_ads_by_sku.py
    ./.venv/bin/python scripts/export_underperforming_ads_by_sku.py --days 14
    ./.venv/bin/python scripts/export_underperforming_ads_by_sku.py --atc 1.0
    ./.venv/bin/python scripts/export_underperforming_ads_by_sku.py --atc-basis clicks
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

SQL = """
WITH vocab AS (
    SELECT DISTINCT master_sku FROM public.cpis_sku_ad_daily
), agg AS (
    SELECT d.ad_id,
           SUM(d.spend)            AS spend,
           SUM(d.impressions)      AS impressions,
           SUM(d.outbound_clicks)  AS link_clicks,
           SUM(d.ftewv_count)      AS ftewv,
           SUM(d.purchases)        AS purchases,
           SUM(d.add_to_cart)      AS atc,
           SUM(d.conv_value)       AS conv_value
      FROM public.insights_daily_by_ad d
     WHERE d.day > CURRENT_DATE - %(days)s
     GROUP BY d.ad_id
    HAVING SUM(d.spend) > 0
       AND SUM(d.outbound_clicks) > 0
       AND SUM(d.impressions) > 0
), m AS (
    SELECT a.*,
           a.spend / NULLIF(a.ftewv, 0)            AS cost_per_ftewv,
           a.spend / a.link_clicks                 AS cpc,
           a.purchases / a.link_clicks * 100       AS cvr_pct,
           a.atc / a.link_clicks * 100             AS atc_pct_of_clicks,
           a.atc / a.impressions * 100             AS atc_pct_of_impressions,
           a.conv_value / NULLIF(a.spend, 0)       AS roas
      FROM agg a
), picked AS (
    SELECT * FROM m
     WHERE cpc < %(cpc)s
       -- NULL (spend but zero FTEWV) is intentionally dropped here. The
       -- gate selects CHEAP cost per first-time engaged visitor, and an
       -- ad that bought none at all is the costliest case, not a cheap
       -- one. Leaving the comparison to fail on NULL is the whole fix.
       AND cost_per_ftewv < %(cpf)s
       AND cvr_pct < %(cvr)s
       AND {atc_column} < %(atc)s
), name_sku AS (
    SELECT DISTINCT p.ad_id, v.master_sku
      FROM picked p
      JOIN public.ad_lifecycle al ON al.ad_id = p.ad_id
      CROSS JOIN regexp_split_to_table(upper(COALESCE(al.ad_name, '')),
                                       '[^A-Z0-9]+') AS t(token)
      JOIN vocab v ON v.master_sku = t.token
), cpis_long AS (
    SELECT DISTINCT ad_id, master_sku
      FROM public.cpis_sku_ad_daily
     WHERE day > CURRENT_DATE - %(days)s
), cpis_agg AS (
    SELECT ad_id, string_agg(master_sku, ', ' ORDER BY master_sku) AS cpis_skus
      FROM cpis_long GROUP BY ad_id
), resolved AS (
    -- The ad NAME is the only SKU source. cpis_sku_ad_daily is still
    -- read, but only for the `cpis_skus` audit column -- never to
    -- resolve a row. See "WHY CPIS IS NOT A SOURCE" above.
    SELECT p.ad_id, n.master_sku AS master_sku, 'ad_name' AS sku_source
      FROM picked p JOIN name_sku n ON n.ad_id = p.ad_id
    UNION ALL
    SELECT p.ad_id, '(no SKU mapped)', 'none'
      FROM picked p
     WHERE NOT EXISTS (SELECT 1 FROM name_sku n WHERE n.ad_id = p.ad_id)
)
SELECT r.master_sku,
       r.sku_source,
       p.ad_id,
       al.ad_name,
       al.campaign_name,
       al.adset_name,
       al.account_name,
       ROUND(p.spend::numeric, 0)                   AS spend,
       p.impressions::bigint                        AS impressions,
       p.link_clicks::bigint                        AS link_clicks,
       p.ftewv::bigint                              AS ftewv,
       ROUND(p.cost_per_ftewv::numeric, 2)          AS cost_per_ftewv,
       ROUND(p.cpc::numeric, 2)                     AS cpc,
       p.purchases::bigint                          AS purchases,
       ROUND(p.cvr_pct::numeric, 3)                 AS cvr_pct,
       p.atc::bigint                                AS atc,
       ROUND(p.atc_pct_of_clicks::numeric, 3)       AS atc_pct_of_clicks,
       ROUND(p.atc_pct_of_impressions::numeric, 3)  AS atc_pct_of_impressions,
       ROUND(p.roas::numeric, 2)                    AS roas,
       ca.cpis_skus
  FROM resolved r
  JOIN picked p                       ON p.ad_id = r.ad_id
  LEFT JOIN public.ad_lifecycle al     ON al.ad_id = p.ad_id
  LEFT JOIN cpis_agg ca                ON ca.ad_id = p.ad_id
 ORDER BY r.master_sku, p.spend DESC
"""

_ATC_COLUMN = {
    "impressions": "atc_pct_of_impressions",
    "clicks": "atc_pct_of_clicks",
}

HEADERS = [
    "master_sku", "sku_source", "ad_id", "ad_name", "campaign_name",
    "adset_name", "account_name", "spend", "impressions", "link_clicks",
    "ftewv", "cost_per_ftewv", "cpc", "purchases", "cvr_pct", "atc",
    "atc_pct_of_clicks", "atc_pct_of_impressions", "roas", "cpis_skus",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--cpc", type=float, default=12.0,
                    help="Upper bound: keep ads CHEAPER than this per click.")
    ap.add_argument("--cost-per-ftewv", dest="cpf", type=float, default=12.0,
                    help="Upper bound: keep ads CHEAPER than this per FTEWV.")
    ap.add_argument("--cvr", type=float, default=5.0, help="Percent.")
    ap.add_argument("--atc", type=float, default=0.1, help="Percent.")
    ap.add_argument("--atc-basis", choices=sorted(_ATC_COLUMN), default="impressions")
    ap.add_argument("--out", default="underperforming_ads_by_sku.xlsx")
    args = ap.parse_args()

    params = {"days": args.days, "cpc": args.cpc, "cpf": args.cpf,
              "cvr": args.cvr, "atc": args.atc}
    sql = SQL.format(atc_column=_ATC_COLUMN[args.atc_basis])

    print(f"Window:     last {args.days} days")
    print(f"Gates:      CPC < {args.cpc}, cost/FTEWV < {args.cpf}, "
          f"CVR < {args.cvr}%, ATC < {args.atc}% of {args.atc_basis}")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        print("\nNothing matched. Loosen a gate and re-run.")
        return 1

    idx = {h: i for i, h in enumerate(HEADERS)}
    by_ad: dict[str, list] = {}
    for r in rows:
        by_ad.setdefault(r[idx["ad_id"]], []).append(r)

    skus = {r[idx["master_sku"]] for r in rows}
    unmapped = sum(1 for rs in by_ad.values()
                   if rs[0][idx["master_sku"]] == "(no SKU mapped)")
    spend = sum(float(rs[0][idx["spend"]] or 0) for rs in by_ad.values())
    print(f"\nMatched:    {len(by_ad):,} ads across {len(skus):,} SKUs")
    print(f"Spend:      Rs {spend:,.0f} (counted once per ad)")
    if unmapped:
        print(f"Unmapped:   {unmapped:,} ads resolved to no SKU at all")

    _write_workbook(args, rows, by_ad, idx)
    print(f"\n[OK] {Path(args.out).resolve()}")
    print("     Ad-level data -- do NOT commit it; .gitignore covers "
          "docs/*.xlsx and exports/*.csv.")
    return 0


def _write_workbook(args, rows, by_ad, idx) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="44546A")
    sku_font = Font(bold=True, size=12)
    sku_fill = PatternFill("solid", fgColor="D9E1F2")

    # ---- Sheet 1: by SKU, each SKU a banner row then its ads ----------
    ws = wb.active
    ws.title = "By SKU"
    cols = [h for h in HEADERS if h != "master_sku"]

    ws.append(["SKU / ad"] + cols)
    for c in range(1, len(cols) + 2):
        cell = ws.cell(row=1, column=c)
        cell.font, cell.fill = head_font, head_fill
        cell.alignment = Alignment(horizontal="center")

    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r[idx["master_sku"]], []).append(r)

    for sku in sorted(grouped, key=lambda s: (s == "(no SKU mapped)", s)):
        ads = grouped[sku]
        spend = sum(float(a[idx["spend"]] or 0) for a in ads)
        ws.append([sku] + [""] * len(cols))
        banner = ws.max_row
        for c in range(1, len(cols) + 2):
            ws.cell(row=banner, column=c).fill = sku_fill
        ws.cell(row=banner, column=1).font = sku_font
        # Positions derived from `cols`, never hardcoded: adding a column
        # to HEADERS would otherwise write the count and the subtotal
        # into whatever happened to be sitting there.
        count_col = cols.index("ad_id") + 2
        spend_col = cols.index("spend") + 2
        ws.cell(row=banner, column=count_col).value = f"{len(ads)} ads"
        ws.cell(row=banner, column=count_col).font = Font(italic=True)
        ws.cell(row=banner, column=spend_col).value = round(spend)
        ws.cell(row=banner, column=spend_col).font = Font(bold=True)
        for a in ads:
            ws.append([""] + [a[idx[h]] for h in cols])

    # ---- Sheet 2: one row per ad, SKUs collapsed ----------------------
    ws2 = wb.create_sheet("By ad")
    ad_cols = [h for h in HEADERS if h != "master_sku"]
    ws2.append(ad_cols + ["skus", "sku_count"])
    for c in range(1, len(ad_cols) + 3):
        cell = ws2.cell(row=1, column=c)
        cell.font, cell.fill = head_font, head_fill
        cell.alignment = Alignment(horizontal="center")

    for _ad_id, rs in sorted(by_ad.items(),
                             key=lambda kv: -float(kv[1][0][idx["spend"]] or 0)):
        sku_list = sorted({r[idx["master_sku"]] for r in rs})
        ws2.append([rs[0][idx[h]] for h in ad_cols]
                   + [", ".join(sku_list), len(sku_list)])

    # ---- Sheet 3: what this sheet means ------------------------------
    ws3 = wb.create_sheet("Method")
    for line in [
        ("Window", f"last {args.days} days, to {_today()}"),
        ("Gate: CPC", f"< Rs {args.cpc}  (spend / outbound_clicks)"),
        ("Gate: cost per FTEWV", f"< Rs {args.cpf}  (spend / ftewv_count)"),
        ("What this list is", "Cheap traffic that does not convert. The two "
                              "cost gates look GOOD and the two funnel gates "
                              "look BAD -- not a 'most expensive ads' list."),
        ("Gate: conversion rate", f"< {args.cvr}%  (purchases / outbound_clicks)"),
        ("Gate: add-to-cart rate", f"< {args.atc}%  (add_to_cart / {args.atc_basis})"),
        ("", ""),
        ("Why outbound_clicks", "insights_daily_by_ad.clicks is NULL for every "
                                "row in the recent window, so it cannot be a "
                                "denominator. outbound_clicks is the populated "
                                "link-click column."),
        ("Why ATC is on impressions", "Fleet ATC rate is 12.4% of link clicks "
                                      "and 16.4% of GA4 sessions, but 0.196% of "
                                      "impressions. A 0.1% threshold is only "
                                      "meaningful on the impressions basis. "
                                      "Both rates are in the sheets; "
                                      "--atc-basis switches the filter."),
        ("", ""),
        ("Where the SKU comes from", "Parsed from the ad name, matched against "
                                     "the SKU vocabulary in cpis_sku_ad_daily "
                                     "so only real codes can be emitted. That "
                                     "covers 78% of spending ads at ~1 SKU "
                                     "each; cpis_sku_ad_daily alone covers 36% "
                                     "at 2-3 SKUs each. See sku_source."),
        ("sku_source", "ad_name = parsed from the ad name. This is the ONLY "
                       "source. none = the name carried no SKU token, "
                       "reported as such rather than guessed."),
        ("Why CPIS is not a source", "It was, as a fallback, and one ad with "
                                     "no SKU in its name came back with 28 "
                                     "SKUs from CPIS -- repeating its Rs "
                                     "236,813 under 28 banners, out of Rs "
                                     "239,732 for the whole list. Spreading "
                                     "one ad across the catalogue is "
                                     "misleading, not approximate."),
        ("cpis_skus", "Every SKU cpis_sku_ad_daily records for the ad, kept as "
                      "an audit trail only. Never used to resolve a row."),
        ("", ""),
        ("DO NOT sum spend on 'By SKU'", "An ad advertising several SKUs is "
                                         "listed under each one, so spend "
                                         "repeats. Sum the 'By ad' sheet."),
        ("Zero-FTEWV ads excluded", "An ad that spent and bought no "
                                    "first-time engaged visitor has unbounded "
                                    "cost per FTEWV, so it cannot be cheap "
                                    "traffic and is dropped by the < gate."),
        ("Not committable", "Real ad names, campaigns, spend and SKUs, in a "
                            "PUBLIC repo. .gitignore covers docs/*.xlsx."),
    ]:
        ws3.append(list(line))
    ws3.column_dimensions["A"].width = 30
    ws3.column_dimensions["B"].width = 100
    for r in range(1, ws3.max_row + 1):
        ws3.cell(row=r, column=1).font = Font(bold=True)
        ws3.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")

    for sheet in (ws, ws2):
        sheet.freeze_panes = "A2"
        for c in range(1, sheet.max_column + 1):
            longest = max((len(str(sheet.cell(row=r, column=c).value or ""))
                           for r in range(1, min(sheet.max_row, 200) + 1)), default=10)
            sheet.column_dimensions[get_column_letter(c)].width = min(max(longest + 2, 10), 46)

    wb.save(args.out)


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
