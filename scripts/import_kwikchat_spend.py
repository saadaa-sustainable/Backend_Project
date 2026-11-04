"""Load real Kwikchat spend from the console's daily-spend CSV export.

WHY THIS EXISTS
---------------
`seed_kwikchat_spend.py` writes a flat placeholder because Kwikchat has
no feed into this warehouse. That placeholder is wrong in both
directions and not by a little: measured against the October export,
the real figure ran from Rs 66 on a quiet day to Rs 80,717 on a busy
one, against a placeholder of Rs 30,000 every single day. Any ratio
with spend in it -- MER, AMER, cost per session, the Live P&L's
contribution margin -- inherited that error.

The export is a manual download, so this is a manual import. It writes
`is_estimate = false`, which is what separates a measured day from a
seeded one; `seed_kwikchat_spend.py` only fills days that have no row,
so a re-seed cannot overwrite what this loads.

THE FILE
--------
Kwikchat console -> daily spend view -> export. One row per day of a
month, with a `Total Price` column that already sums WhatsApp, SMS,
RCS, email and AI calling.

Dates are DD-MM-YYYY. Amounts carry a rupee sign and Indian digit
grouping, and the grouped ones are quoted, so "1,00,000" is ONE field
and not three -- csv.reader handles that, a split on comma does not.

SEVERAL ACCOUNTS, ONE DAY
-------------------------
Kwikchat is billed per workspace and the console exports one at a
time, so a month arrives as several files covering the SAME dates with
different traffic -- one carrying marketing and SMS, another utility
messages, another almost nothing. Pass them all: the day's spend is
their SUM.

This matters because the write REPLACES the day. Importing three files
one after another would leave only the last one's figure and silently
drop the rest, which on a real month was most of the money.

Usage:
    ./.venv/bin/python scripts/import_kwikchat_spend.py export.csv
    ./.venv/bin/python scripts/import_kwikchat_spend.py a.csv b.csv c.csv
    ./.venv/bin/python scripts/import_kwikchat_spend.py *.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

SOURCE = "kwikchat daily-spend export"

UPSERT = """
INSERT INTO public.kwikchat_spend_daily (day, spend, is_estimate, source, fetched_at)
VALUES %s
ON CONFLICT (day) DO UPDATE SET
  spend = EXCLUDED.spend,
  is_estimate = EXCLUDED.is_estimate,
  source = EXCLUDED.source,
  fetched_at = EXCLUDED.fetched_at
"""


def parse_amount(raw: str) -> float:
    """"₹1,00,000.50" -> 100000.5

    Indian grouping is not every three digits, so no assumption about
    group width survives -- the separators are simply removed.
    """
    cleaned = (raw or "").strip().replace("₹", "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return 0.0
    return float(cleaned)


def parse_day(raw: str) -> date:
    """DD-MM-YYYY, as the console writes it.

    Parsed strictly rather than with dateutil: 03-10-2026 is the third
    of October here and the tenth of March in the American reading, and
    a silent month/day swap would move a month of spend.
    """
    return datetime.strptime((raw or "").strip(), "%d-%m-%Y").date()


def read_rows(path: Path) -> list[tuple[date, float]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if "Date" not in (reader.fieldnames or []):
            raise SystemExit(
                f"No `Date` column in {path.name}. Columns: {reader.fieldnames}")
        if "Total Price" not in (reader.fieldnames or []):
            raise SystemExit(
                f"No `Total Price` column in {path.name}. Columns: {reader.fieldnames}")
        out = []
        for i, row in enumerate(reader, start=2):
            if not (row.get("Date") or "").strip():
                continue
            try:
                out.append((parse_day(row["Date"]), parse_amount(row["Total Price"])))
            except ValueError as exc:
                raise SystemExit(f"{path.name} line {i}: {exc}") from exc
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv_path", type=Path, nargs="+",
                    help="One or more exports. Same-day rows are SUMMED: "
                         "each file is a separate Kwikchat workspace.")
    ap.add_argument("--until", type=date.fromisoformat, default=None,
                    help="Last day to write (YYYY-MM-DD). Use it to leave "
                         "TODAY out: the console exports the day so far, and "
                         "writing that marks a part-finished day as measured, "
                         "where a later re-import would have corrected it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be written and exit.")
    args = ap.parse_args()

    for path in args.csv_path:
        if not path.exists():
            raise SystemExit(f"No such file: {path}")

    # Summed per day across the files, never replaced: each file is a
    # separate workspace and they all billed on the same dates.
    merged: dict[date, float] = {}
    for path in args.csv_path:
        file_rows = read_rows(path)
        if not file_rows:
            raise SystemExit(f"No dated rows in {path.name}.")
        sub = sum(s for _, s in file_rows)
        print(f"File:    {path.name}  ({len(file_rows)} days, Rs {sub:,.2f})")
        for d, amount in file_rows:
            merged[d] = merged.get(d, 0.0) + amount

    rows = sorted(merged.items())
    if args.until:
        dropped = [d for d, _ in rows if d > args.until]
        rows = [(d, v) for d, v in rows if d <= args.until]
        if dropped:
            print(f"Skipped: {len(dropped)} day(s) after {args.until} "
                  f"({', '.join(str(d) for d in dropped)})")
        if not rows:
            raise SystemExit(f"Nothing on or before {args.until}.")
    total = sum(s for _, s in rows)
    days = [d for d, _ in rows]
    if len(args.csv_path) > 1:
        print(f"\nSummed {len(args.csv_path)} files into {len(rows)} days.")
    print(f"Range:   {min(days)} .. {max(days)}  ({len(rows)} days)")
    print(f"Total:   Rs {total:,.2f}")
    print(f"Per day: min Rs {min(s for _, s in rows):,.2f}  "
          f"max Rs {max(s for _, s in rows):,.2f}  "
          f"mean Rs {total / len(rows):,.2f}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    import psycopg2.extras  # noqa: PLC0415
    with connect(autocommit=False) as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur, UPSERT, [(d, s, False, SOURCE) for d, s in rows],
                template="(%s,%s,%s,%s,now())", page_size=200)
        conn.commit()

    print(f"\n[OK] {len(rows)} days written, is_estimate = false")
    print("     Re-run scripts/fetch_hourly_tracker.py for those days so the "
          "tracker picks them up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
