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

Usage:
    ./.venv/bin/python scripts/import_kwikchat_spend.py path/to/export.csv
    ./.venv/bin/python scripts/import_kwikchat_spend.py export.csv --dry-run
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
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be written and exit.")
    args = ap.parse_args()

    if not args.csv_path.exists():
        raise SystemExit(f"No such file: {args.csv_path}")

    rows = read_rows(args.csv_path)
    if not rows:
        raise SystemExit("No dated rows in the file.")

    total = sum(s for _, s in rows)
    days = [d for d, _ in rows]
    print(f"File:    {args.csv_path.name}")
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
