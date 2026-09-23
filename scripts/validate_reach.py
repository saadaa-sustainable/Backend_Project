"""Validate stored reach against the properties a unique count must obey.

Reach is a COUNT OF DISTINCT PEOPLE, and that constrains it in ways a sum
of events is not constrained. Each check below is falsifiable: if reach
were being summed, spread, or fetched over the wrong window, at least one
of them breaks. Passing all of them is not proof, but every realistic way
of getting reach wrong fails at least one.

  1. reach <= impressions
     A reached person saw at least one impression. Violation means the
     two came from different windows, or reach was summed.

  2. monotone in window length
     reach[a,c] >= reach[a,b] when b < c. Adding days can only add
     people. Violation means the windows were not really nested, i.e.
     something was fetched for the wrong range.

  3. subadditive across a split
     reach[a,c] <= reach[a,b] + reach[b+1,c]. The union of two periods
     cannot exceed the sum of their parts; equality only if nobody
     appears in both. THIS IS THE TEST THAT CATCHES SUMMED DAILY REACH,
     which typically exceeds the true figure by 2-5x.

  4. hierarchy
     campaign reach <= SUM(its ad sets' reach), and >= MAX(any one of
     them). Same argument one level up.

  5. frequency >= 1
     impressions / reach cannot be below 1.

  6. live re-fetch
     Ask Meta again for a stored window and compare. This is the only
     check that can catch a systematically wrong-but-self-consistent
     store, because it does not reuse anything we already hold.

Read-only apart from the optional live call.

Usage:
    ./.venv/bin/python scripts/validate_reach.py
    ./.venv/bin/python scripts/validate_reach.py --level adset --no-live
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402

DSN = (os.environ["DATABASE_URL_SYNC"]
       .replace("postgresql+psycopg2://", "postgresql://").split("?")[0])

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str, soft: bool = False) -> None:
    status = PASS if ok else (WARN if soft else FAIL)
    results.append((status, name, detail))
    print(f"  [{status}] {name}\n         {detail}", flush=True)


def check_sql(cur, level: str) -> None:
    daily = {"adset": "insights_daily_by_adset",
             "campaign": "insights_daily_by_campaign"}[level]
    id_col = {"adset": "adset_id", "campaign": "campaign_id"}[level]

    # 1. reach <= impressions, over the window each row actually describes.
    cur.execute(f"""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE r.cumulative_reach > i.impressions)
          FROM public.ad_reach_cumulative r
          JOIN LATERAL (SELECT COALESCE(SUM(impressions), 0) AS impressions
                          FROM public.{daily} d
                         WHERE d.{id_col} = r.entity_id
                           AND d.day BETWEEN r.epoch_date AND r.as_of_date) i ON TRUE
         WHERE r.level = %s AND i.impressions > 0
    """, (level,))
    n, bad = cur.fetchone()
    record("reach <= impressions", bad == 0,
           f"{n:,} rows compared, {bad:,} violations")

    # 2. Monotone in window length, same `since`.
    cur.execute("""
        WITH s AS (
          SELECT entity_id, epoch_date, as_of_date, cumulative_reach,
                 LAG(cumulative_reach) OVER (PARTITION BY entity_id, epoch_date
                                             ORDER BY as_of_date) AS prev
            FROM public.ad_reach_cumulative WHERE level = %s)
        SELECT COUNT(*) FILTER (WHERE prev IS NOT NULL),
               COUNT(*) FILTER (WHERE prev IS NOT NULL AND cumulative_reach < prev)
          FROM s
    """, (level,))
    n, bad = cur.fetchone()
    record("monotone as the window grows", bad == 0,
           f"{n:,} nested pairs, {bad:,} where a longer window had LESS reach")

    # 3. Subadditivity across a split of one window into two.
    #    Uses whatever adjacent windows happen to be stored.
    cur.execute("""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE whole.cumulative_reach
                                              > part1.cumulative_reach + part2.cumulative_reach)
          FROM public.ad_reach_cumulative whole
          JOIN public.ad_reach_cumulative part1
            ON part1.level = whole.level AND part1.entity_id = whole.entity_id
           AND part1.epoch_date = whole.epoch_date
           AND part1.as_of_date < whole.as_of_date
          JOIN public.ad_reach_cumulative part2
            ON part2.level = whole.level AND part2.entity_id = whole.entity_id
           AND part2.epoch_date = part1.as_of_date + 1
           AND part2.as_of_date = whole.as_of_date
         WHERE whole.level = %s
    """, (level,))
    n, bad = cur.fetchone()
    record("subadditive across a split", bad == 0,
           f"{n:,} splits found, {bad:,} where the whole exceeded its parts"
           + ("  (no adjacent windows stored to compare)" if n == 0 else ""),
           soft=(n == 0))

    # 5. frequency >= 1
    cur.execute(f"""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE i.impressions < r.cumulative_reach)
          FROM public.ad_reach_cumulative r
          JOIN LATERAL (SELECT COALESCE(SUM(impressions), 0) AS impressions
                          FROM public.{daily} d
                         WHERE d.{id_col} = r.entity_id
                           AND d.day BETWEEN r.epoch_date AND r.as_of_date) i ON TRUE
         WHERE r.level = %s AND r.cumulative_reach > 0 AND i.impressions > 0
    """, (level,))
    n, bad = cur.fetchone()
    record("frequency >= 1", bad == 0, f"{n:,} rows, {bad:,} with frequency below 1")


def check_hierarchy(cur) -> None:
    """Campaign reach must sit between MAX and SUM of its ad sets."""
    cur.execute("""
        WITH pair AS (
          SELECT c.entity_id AS campaign_id, c.epoch_date, c.as_of_date,
                 c.cumulative_reach AS camp_reach,
                 SUM(a.cumulative_reach) AS sum_adsets,
                 MAX(a.cumulative_reach) AS max_adset
            FROM public.ad_reach_cumulative c
            JOIN public.meta_adsets s ON s.campaign_id = c.entity_id
            JOIN public.ad_reach_cumulative a
              ON a.level = 'adset' AND a.entity_id = s.adset_id
             AND a.epoch_date = c.epoch_date AND a.as_of_date = c.as_of_date
           WHERE c.level = 'campaign'
           GROUP BY 1,2,3,4)
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE camp_reach > sum_adsets),
               COUNT(*) FILTER (WHERE camp_reach < max_adset)
          FROM pair
    """)
    n, over, under = cur.fetchone()
    record("campaign reach <= SUM(ad sets)", over == 0,
           f"{n:,} campaign-windows, {over:,} exceeding the sum of their ad sets")
    record("campaign reach >= MAX(ad set)", under == 0,
           f"{n:,} campaign-windows, {under:,} below their largest ad set")


async def check_live(cur, level: str, sample: int) -> None:
    """Re-ask Meta for stored windows. The only check that cannot be
    fooled by a store that is wrong but internally consistent."""
    try:
        import httpx
    except ImportError:
        record("live re-fetch", True, "httpx missing, skipped", soft=True)
        return
    token = os.getenv("META_ACCESS_TOKEN")
    if not token:
        record("live re-fetch", True, "META_ACCESS_TOKEN unset, skipped", soft=True)
        return
    ver = os.getenv("META_API_VERSION", "v21.0")
    cur.execute("""
        SELECT entity_id, epoch_date, as_of_date, cumulative_reach
          FROM public.ad_reach_cumulative
         WHERE level = %s AND cumulative_reach > 1000
         ORDER BY random() LIMIT %s
    """, (level, sample))
    rows = cur.fetchall()
    worst, checked = 0.0, 0
    async with httpx.AsyncClient(timeout=90) as client:
        for entity_id, since, until, stored in rows:
            r = await client.get(
                f"https://graph.facebook.com/{ver}/{entity_id}/insights",
                params={"access_token": token, "fields": "reach",
                        "time_range": json.dumps({"since": since.isoformat(),
                                                  "until": until.isoformat()})})
            data = (r.json() or {}).get("data") or []
            if not data:
                continue
            live = int(float(data[0].get("reach", 0)))
            checked += 1
            drift = abs(live - stored) / max(stored, 1) * 100
            worst = max(worst, drift)
            flag = "" if drift < 1 else f"   <- {drift:.1f}% drift"
            print(f"         {entity_id}  {since}..{until}  "
                  f"stored {stored:>10,}  live {live:>10,}{flag}", flush=True)
    # Meta restates recent days, so small drift is expected, not a fault.
    record("live re-fetch matches", worst < 5.0,
           f"{checked} sampled, worst drift {worst:.2f}% (tolerance 5%)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--level", choices=["adset", "campaign", "all"], default="all")
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--no-live", action="store_true")
    args = ap.parse_args()
    levels = ["adset", "campaign"] if args.level == "all" else [args.level]

    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = '600s'")
        for lv in levels:
            print(f"\n=== {lv} ===")
            check_sql(cur, lv)
            if not args.no_live:
                asyncio.run(check_live(cur, lv, args.sample))
        if set(levels) == {"adset", "campaign"}:
            print("\n=== hierarchy ===")
            check_hierarchy(cur)

    fails = [r for r in results if r[0] == FAIL]
    print(f"\n{'=' * 58}\n{len(results) - len(fails)} passed, {len(fails)} FAILED")
    for _s, name, detail in fails:
        print(f"  FAIL  {name}: {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
