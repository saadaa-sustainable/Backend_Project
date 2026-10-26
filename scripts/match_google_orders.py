"""Last-click Google: map Shopify orders to campaign / ad group / ad.

WHAT IT MATCHES ON
------------------
Google auto-tagging writes ValueTrack IDs into the landing URL, and this
account's template puts them here -- confirmed against the Google Ads
API on 2026-10-21, not assumed from the parameter names:

    utm_campaign  = campaign id   19752547631  -> Search - Branded
    utm_term      = AD GROUP id   148136693402 -> सादा / SAADAA
    utm_content   = AD id         649815036937

Note the last two: `utm_term` is the AD GROUP and `utm_content` is the
AD. That is the opposite of what the names suggest and of how Meta's
own last-click reads them, so anything reusing this must not copy the
field order across.

WHY THERE IS NO TABLE
---------------------
Nothing is stored. The order rows are already in Postgres and the
entity names come from the Google Ads API at run time, so a table would
only be a stale copy of two live sources. Three GAQL queries resolve
every campaign, ad group and ad in the account -- the API bills nothing
and counts one operation per query against a 15,000/day quota, so there
is no saving to be had by caching it either.

No BigQuery. This path never touches MapleMonk.

WHAT IT IS WORTH
----------------
Measured over the 30 days to 2026-10-21, against orders that
`shopify_order_attribution` currently files as `unmatched`:

    google, numeric campaign id   1,913 orders   Rs 3,144,101  <- mappable
    google, sag_organic             905 orders   Rs 1,295,922  <- NOT ads
    google, no usable id            118 orders   Rs   191,185
    not google                   17,528 orders   Rs 20,768,456

`sag_organic` is the one to be careful about. It marks Google's FREE
product listings -- surfaces-across-Google, not a paid click -- and
crediting its Rs 13 L to Google Ads would overstate paid performance by
about 40% of what the paid orders are worth. It gets its own tier here
and is never counted as matched.

TIERS, mirroring shopify_order_attribution's vocabulary:

    ad_direct        ad id resolved -> campaign, ad group and ad known
    adgroup_scoped   ad group resolved, the ad did not (deleted, or the
                     template omitted {creative})
    campaign_only    only the campaign id resolved
    organic_surface  sag_organic: a free listing, deliberately not paid
    unmatched        from Google, nothing resolvable

WHAT THE TIERS LOOK LIKE HERE, AND WHY
--------------------------------------
Measured over the 30 days to 2026-10-21: ad_direct 1,145 / campaign_only
688 / organic_surface 870 / unmatched 112, i.e. 65.1% of Google orders
matched to a paid entity.

Two results look wrong at a glance and are not:

  * adgroup_scoped is EMPTY. There is no middle case in this account:
    Search and Demand Gen orders carry {creative} and land in ad_direct,
    while campaign_only is almost entirely PERFORMANCE MAX -- 677 of its
    688 orders. PMax has asset groups, not ad groups or ads, so it
    cannot emit {adgroupid} or {creative} and the campaign IS the
    deepest honest level for it. Do not go looking for the missing ad
    group; it does not exist. The tier stays in the vocabulary because a
    deleted ad on a Search campaign would land there.

  * unmatched is 112 orders, every one of them with an EMPTY
    utm_medium and no ids at all. That is the shape of an organic
    google.com referral that happens to carry utm_source=google, not a
    paid click this failed to resolve.

Usage:
    ./.venv/bin/python scripts/match_google_orders.py
    ./.venv/bin/python scripts/match_google_orders.py --days 90
    ./.venv/bin/python scripts/match_google_orders.py --out /tmp/google_last_click.csv
    ./.venv/bin/python scripts/match_google_orders.py --unmatched-only
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dbq import connect as db_connect  # noqa: E402
from scripts.google_ads_auth import GoogleAdsAuthError, connect as ads_connect  # noqa: E402

#: Google's marker for free product listings (surfaces across Google).
#: A click Google was never paid for, so it must not land in a paid tier.
ORGANIC_MARKER = "sag_organic"

ORDERS_SQL = """
SELECT o.order_id, o.name, o.created_at::date AS day, o.total_price,
       o.utm_source, o.utm_medium, o.utm_campaign, o.utm_term, o.utm_content
  FROM public.shopify_orders o
 WHERE o.created_at >= %(since)s AND o.created_at < %(until)s
   AND lower(COALESCE(o.utm_source, '')) LIKE '%%google%%'
 ORDER BY o.created_at
"""

#: Removed entities are included on purpose -- an order from three
#: months ago can point at an ad group since deleted, and dropping it
#: would file a perfectly matchable order as unmatched.
Q_CAMPAIGNS = "SELECT campaign.id, campaign.name, campaign.status FROM campaign"
Q_AD_GROUPS = ("SELECT ad_group.id, ad_group.name, ad_group.status, "
               "campaign.id, campaign.name FROM ad_group")
Q_ADS = ("SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.status, "
         "ad_group.id, ad_group.name, campaign.id, campaign.name "
         "FROM ad_group_ad")

FIELDS = ["order_id", "order_name", "day", "total_price", "tier",
          "utm_source", "utm_medium", "campaign_id", "campaign_name",
          "ad_group_id", "ad_group_name", "ad_id", "ad_name"]


def _resolve(ads) -> tuple[dict, dict, dict]:
    """Every campaign, ad group and ad in the account, by id."""
    campaigns = {}
    for r in ads.search_stream(Q_CAMPAIGNS):
        c = r["campaign"]
        campaigns[str(c["id"])] = c.get("name")

    ad_groups = {}
    for r in ads.search_stream(Q_AD_GROUPS):
        g, c = r["adGroup"], r.get("campaign", {})
        ad_groups[str(g["id"])] = (g.get("name"), str(c.get("id") or ""),
                                   c.get("name"))
    ads_by_id = {}
    for r in ads.search_stream(Q_ADS):
        a = r["adGroupAd"]["ad"]
        g, c = r.get("adGroup", {}), r.get("campaign", {})
        ads_by_id[str(a["id"])] = (a.get("name"), str(g.get("id") or ""),
                                   g.get("name"), str(c.get("id") or ""),
                                   c.get("name"))
    return campaigns, ad_groups, ads_by_id


def _classify(row, campaigns, ad_groups, ads_by_id) -> dict:
    """One order -> its tier and whatever entities resolved.

    Resolution runs most-specific first. The ad knows its own ad group
    and campaign, so a resolved ad fills all three even when the order's
    own utm_campaign is missing or stale.
    """
    camp_id = (row["utm_campaign"] or "").strip()
    ag_id = (row["utm_term"] or "").strip()
    ad_id = (row["utm_content"] or "").strip()

    out = {"order_id": row["order_id"], "order_name": row["name"],
           "day": row["day"], "total_price": float(row["total_price"] or 0),
           "utm_source": row["utm_source"], "utm_medium": row["utm_medium"],
           "campaign_id": None, "campaign_name": None,
           "ad_group_id": None, "ad_group_name": None,
           "ad_id": None, "ad_name": None, "tier": "unmatched"}

    if ORGANIC_MARKER in (camp_id, ad_id):
        out["tier"] = "organic_surface"
        return out

    if ad_id in ads_by_id:
        name, g_id, g_name, c_id, c_name = ads_by_id[ad_id]
        out.update(tier="ad_direct", ad_id=ad_id, ad_name=name,
                   ad_group_id=g_id or None, ad_group_name=g_name,
                   campaign_id=c_id or camp_id or None, campaign_name=c_name)
        return out

    if ag_id in ad_groups:
        name, c_id, c_name = ad_groups[ag_id]
        out.update(tier="adgroup_scoped", ad_group_id=ag_id, ad_group_name=name,
                   campaign_id=c_id or camp_id or None, campaign_name=c_name)
        return out

    if camp_id in campaigns:
        out.update(tier="campaign_only", campaign_id=camp_id,
                   campaign_name=campaigns[camp_id])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to", dest="to_date")
    ap.add_argument("--out", help="Write the matched rows to this CSV.")
    ap.add_argument("--unmatched-only", action="store_true",
                    help="Only list what could NOT be matched.")
    args = ap.parse_args()

    until = date.fromisoformat(args.to_date) if args.to_date else date.today()
    since = (date.fromisoformat(args.from_date) if args.from_date
             else until - timedelta(days=args.days - 1))

    try:
        ads = ads_connect()
    except GoogleAdsAuthError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"Window:    {since} .. {until}")
    campaigns, ad_groups, ads_by_id = _resolve(ads)
    print(f"Resolved:  {len(campaigns)} campaigns, {len(ad_groups)} ad groups, "
          f"{len(ads_by_id)} ads  (3 API operations, no cost)")

    with db_connect() as conn, conn.cursor() as cur:
        cur.execute(ORDERS_SQL, {"since": since, "until": until + timedelta(days=1)})
        cols = [c.name for c in cur.description]
        orders = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not orders:
        print("No Google-sourced orders in the window.")
        return 0

    rows = [_classify(o, campaigns, ad_groups, ads_by_id) for o in orders]

    tally: dict[str, list[int, float]] = defaultdict(lambda: [0, 0.0])
    for r in rows:
        t = tally[r["tier"]]
        t[0] += 1
        t[1] += r["total_price"]

    total_orders = len(rows)
    total_rev = sum(r["total_price"] for r in rows)
    paid = {"ad_direct", "adgroup_scoped", "campaign_only"}
    matched_n = sum(tally[t][0] for t in paid)
    matched_rev = sum(tally[t][1] for t in paid)

    print(f"\nGoogle-sourced orders: {total_orders:,}  Rs {total_rev:,.0f}\n")
    print(f"  {'tier':<17}{'orders':>9}{'revenue':>14}{'share':>8}")
    for tier in ("ad_direct", "adgroup_scoped", "campaign_only",
                 "organic_surface", "unmatched"):
        n, rev = tally[tier]
        if not n:
            continue
        print(f"  {tier:<17}{n:>9,}{rev:>14,.0f}{100.0 * n / total_orders:>7.1f}%")
    print(f"\n  matched to paid Google: {matched_n:,} orders "
          f"({100.0 * matched_n / total_orders:.1f}%), Rs {matched_rev:,.0f}")
    print(f"  organic (not ads):      {tally['organic_surface'][0]:,} orders, "
          f"Rs {tally['organic_surface'][1]:,.0f}")

    top = defaultdict(lambda: [0, 0.0])
    for r in rows:
        if r["tier"] in paid and r["campaign_name"]:
            e = top[r["campaign_name"]]
            e[0] += 1
            e[1] += r["total_price"]
    if top:
        print(f"\n  {'campaign':<46}{'orders':>8}{'revenue':>13}")
        for name, (n, rev) in sorted(top.items(), key=lambda kv: -kv[1][1])[:10]:
            print(f"  {name[:46]:<46}{n:>8,}{rev:>13,.0f}")

    if args.out:
        out_rows = [r for r in rows
                    if not args.unmatched_only or r["tier"] == "unmatched"]
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(out_rows)
        print(f"\n[OK] {len(out_rows):,} rows -> {Path(args.out).resolve()}")
        print("     Ad-level data: do NOT commit it. This repo is PUBLIC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
