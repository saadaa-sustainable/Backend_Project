"""Refresh daily revenue-weighted CPIS without changing Equal / Order data.

Default: full history since 2026-01-01, in bounded 7-day source reads. All
replacement rows commit together, so readers never see a partially refreshed
range. --since/--until can rebuild a smaller interval without deleting history.
Apply the cpis_daily_revenue_weighting migration before the first run.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg2.extras import execute_values  # noqa: E402

from app.services.gold.cpis_value_weighted import (  # noqa: E402
    COLUMNS, LINES_SQL, SPEND_SQL, ProductLine, allocate_daily,
)
from scripts.dbq import connect, scrub  # noqa: E402


def refresh(conn, since: date, until: date) -> int:
    if since > until:
        raise ValueError("--since must be on or before --until")
    total = 0
    with conn.cursor() as cur:
        # Guard against two refresh jobs replacing overlapping intervals.
        cur.execute("SELECT pg_try_advisory_xact_lock(724317, 1)")
        if not cur.fetchone()[0]:
            raise RuntimeError("A CPIS Value-Weighted refresh is already running")
        current = since
        while current <= until:
            end = min(current + timedelta(days=6), until)
            params = {"since": current, "until": end}
            print(f"[CPIS value-weighted] {current} to {end}", flush=True)
            cur.execute(LINES_SQL, params)
            lines = [ProductLine(*row) for row in cur.fetchall()]
            cur.execute(SPEND_SQL, params)
            spend = {(day, entity): amount for day, entity, amount in cur.fetchall()}
            rows = allocate_daily(lines, spend)
            cur.execute(
                "DELETE FROM public.cpis_value_weighted_daily WHERE day BETWEEN %s AND %s",
                (current, end),
            )
            if rows:
                execute_values(cur,
                    f"INSERT INTO public.cpis_value_weighted_daily ({', '.join(COLUMNS)}) VALUES %s",
                    [tuple(row[c] for c in COLUMNS) for row in rows], page_size=1000)
            total += len(rows)
            current = end + timedelta(days=1)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--until", type=date.fromisoformat)
    args = parser.parse_args()
    try:
        with connect(autocommit=False, statement_timeout="60s") as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SELECT MAX(day) FROM public.insights_daily_by_ad")
                until = args.until or cur.fetchone()[0]
            if until is None:
                raise ValueError("No Meta daily spend is available")
            count = refresh(conn, args.since, until)
            conn.commit()
            print(f"[OK] {count:,} entity/SKU/day rows committed", flush=True)
    except Exception as exc:
        raise SystemExit(scrub(exc)) from None


if __name__ == "__main__":
    main()
