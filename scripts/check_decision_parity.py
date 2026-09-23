"""Does the SQL mirror of the verdict rule agree with the Python one?

`_decide` runs in Python to build the tiles; `_decision_sql` is the same
rule in SQL so the table can be filtered over every entity rather than
the page that was fetched. Two bodies of one rule drift, and this one
has: leaving last-click revenue NULL once made an entity that spent and
earned nothing read UNRATED in SQL and PAUSE in Python, so the verdict
filter returned 27 rows against a tile saying 150.

This evaluates both against the live database, per entity, and reports
any entity the two disagree about. The unit tests pin the Python rule;
only a database can evaluate the SQL one.

Usage:
    ./.venv/bin/python scripts/check_decision_parity.py
    ./.venv/bin/python scripts/check_decision_parity.py --level campaign
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402

from app.api.routers.analytics import (  # noqa: E402
    _ROLLUP_DAILY,
    _decide,
    _decision_sql,
    _rolling_lc_sql,
    _rolling_metrics_sql,
)

DSN = (os.environ["DATABASE_URL_SYNC"]
       .replace("postgresql+psycopg2://", "postgresql://").split("?")[0])

_BASE = {"adset": ("adset_insights", "adset_id"),
         "campaign": ("campaign_insights", "campaign_id")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--level", choices=["adset", "campaign"], default="adset")
    args = ap.parse_args()

    table, id_col = _BASE[args.level]
    daily_table, daily_id = _ROLLUP_DAILY[args.level]

    con = psycopg2.connect(DSN)
    cur = con.cursor()
    cur.execute("SET statement_timeout = '900s'")
    cur.execute(f"SELECT MAX(day) FROM public.{daily_table}")
    last_date = cur.fetchone()[0] or date.today()

    # The SQL verdict alongside the raw inputs the Python one reads, so
    # both are evaluated over exactly the same rows.
    sql = (
        f"SELECT i.{id_col}, COALESCE(i.account_name, acct.account_name) AS account_name, "
        f"       rm.d3_spend, rm.d3_ftewv, rm.d7_spend, rm.d7_ftewv, "
        f"       rl.d3_lc_revenue, rl.d7_lc_revenue, "
        f"       {_decision_sql(args.level)} AS sql_verdict "
        f"  FROM public.{table} i "
        "  LEFT JOIN (SELECT account_id, MIN(account_name) AS account_name "
        "               FROM ad_lifecycle "
        "              WHERE account_id IS NOT NULL AND account_name IS NOT NULL "
        "              GROUP BY account_id) acct ON acct.account_id = i.account_id "
        f"  LEFT JOIN ({_rolling_metrics_sql(daily_table, daily_id)}) rm "
        f"         ON rm.entity_id = i.{id_col} "
        f"  LEFT JOIN ({_rolling_lc_sql(args.level)}) rl ON rl.entity_id = i.{id_col} "
    ).replace(":last_date", "%(last_date)s")

    cur.execute(sql, {"last_date": last_date})

    agree: Counter[str] = Counter()
    disagree: list[tuple] = []
    for (eid, account, s3, f3, s7, f7, r3, r7, sql_verdict) in cur:
        d3 = (float(r3 or 0) / float(s3)) if s3 else None
        d7 = (float(r7 or 0) / float(s7)) if s7 else None
        py, _why = _decide(d3, d7, account,
                           d3_spend=s3, d3_ftewv=f3, d7_spend=s7, d7_ftewv=f7)
        py = py or "UNRATED"
        if py == sql_verdict:
            agree[py] += 1
        else:
            disagree.append((eid, account, py, sql_verdict, d3, d7))

    total = sum(agree.values()) + len(disagree)
    print(f"level={args.level}  anchored on {last_date}  {total:,} entities\n")
    for verdict, n in sorted(agree.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:<9}{n:>7,}")

    if not disagree:
        print(f"\nPASS -- Python and SQL agree on all {total:,}.")
        return 0

    print(f"\nFAIL -- {len(disagree):,} disagreements:\n")
    for eid, account, py, sq, d3, d7 in disagree[:25]:
        print(f"  {eid}  {str(account)[:22]:<22} python={py:<8} sql={sq:<8} "
              f"3D={'-' if d3 is None else f'{d3:.2f}'} "
              f"7D={'-' if d7 is None else f'{d7:.2f}'}")
    if len(disagree) > 25:
        print(f"  ... and {len(disagree) - 25:,} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
