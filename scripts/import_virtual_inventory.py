"""Load the manually-maintained virtual inventory sheet.

WHAT THIS IS
------------
"Virtual stock details - Sourcing.xlsx": Sku, Size, Dynamic Virtual
Inventory. One row per VARIANT SKU -- the same grain and the same
spelling as `inventory_variant_current.variant_sku`, underscore and
all, so it joins without a mapping table. Measured on the first load,
279 of 280 SKUs matched exactly; the one that did not was the gift coin.

Virtual inventory is stock that is promised rather than held: it is not
on a shelf, so it must never be added to Shopify's count. It is carried
as its own column and summed only where the page says it is summing it.

MAINTAINED BY HAND, SO INGESTED BY HAND
---------------------------------------
Nobody generates this file; someone edits it. That makes an automatic
pull impossible and a scheduled job a lie, so this is a command you run
when the file changes. `source_file` and `imported_at` record which
file produced the numbers on screen, because the second question after
"is this current?" is always "which version is this?".

Accepts .xlsx or .csv -- the sheet is exported both ways and refusing
one of them would just mean somebody converting it by hand first.

Usage:
    ./.venv/bin/python scripts/import_virtual_inventory.py ~/Downloads/'Virtual stock details - Sourcing.xlsx'
    ./.venv/bin/python scripts/import_virtual_inventory.py <file> --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

TABLE = "public.virtual_inventory_current"

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    variant_sku   text PRIMARY KEY,
    size          text,
    virtual_units integer NOT NULL,
    -- Which file these came from, and when it was loaded. This table
    -- has no automatic refresh by design, so without these there is no
    -- way to tell a figure loaded this morning from one loaded in
    -- August.
    source_file   text,
    imported_at   timestamptz NOT NULL DEFAULT now()
);
"""

#: Accepted spellings of the quantity header. The file is edited by
#: hand and the column has already been seen titled two ways.
QTY_HEADERS = {"dynamic virtual inventory", "virtual inventory", "virtual stock",
               "virtual units", "qty", "quantity"}
SKU_HEADERS = {"sku", "variant sku", "variant_sku"}
SIZE_HEADERS = {"size"}


def read_xlsx(path: Path) -> list[list]:
    try:
        import openpyxl
    except ImportError as exc:
        raise SystemExit("pip install openpyxl") from exc
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def read_csv(path: Path) -> list[list]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [list(r) for r in csv.reader(fh)]


def find_columns(header: list) -> tuple[int, int | None, int]:
    """Locate the three columns by NAME, not position.

    A hand-edited sheet gains and loses columns; pinning to position
    would silently read the wrong one after someone inserts a column at
    the front, and a silently wrong inventory figure is worse than a
    loud failure.
    """
    norm = [str(h or "").strip().lower() for h in header]
    sku = size = qty = None
    for i, h in enumerate(norm):
        if h in SKU_HEADERS and sku is None:
            sku = i
        elif h in SIZE_HEADERS and size is None:
            size = i
        elif h in QTY_HEADERS and qty is None:
            qty = i
    if sku is None or qty is None:
        raise SystemExit(
            f"Could not find the SKU and quantity columns.\nHeader was: {header}\n"
            f"Expected a SKU column from {sorted(SKU_HEADERS)} and a quantity "
            f"column from {sorted(QTY_HEADERS)}.")
    return sku, size, qty


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.path.exists():
        raise SystemExit(f"No such file: {args.path}")
    raw = (read_xlsx(args.path) if args.path.suffix.lower() in {".xlsx", ".xlsm"}
           else read_csv(args.path))
    raw = [r for r in raw if any(c not in (None, "") for c in r)]
    if len(raw) < 2:
        raise SystemExit("File has no data rows.")

    i_sku, i_size, i_qty = find_columns(raw[0])
    rows, skipped = {}, 0
    for r in raw[1:]:
        sku = str(r[i_sku] or "").strip().upper()
        if not sku:
            skipped += 1
            continue
        try:
            units = int(round(float(str(r[i_qty]).replace(",", "").strip())))
        except (TypeError, ValueError):
            skipped += 1
            continue
        size = str(r[i_size] or "").strip() if i_size is not None else None
        # Last wins on a duplicate SKU, and it is reported: a hand-kept
        # sheet grows duplicates, and silently keeping one of two
        # different numbers is how a wrong figure survives.
        if sku in rows and rows[sku][1] != units:
            print(f"  [warn] {sku} appears twice with different values "
                  f"({rows[sku][1]} then {units}); keeping the later")
        rows[sku] = (size, units)

    total = sum(u for _, u in rows.values())
    print(f"File:   {args.path.name}")
    print(f"Rows:   {len(rows)} SKUs  ({skipped} skipped)")
    print(f"Units:  {total:,}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    import psycopg2.extras  # noqa: PLC0415
    payload = [(sku, size, units, args.path.name) for sku, (size, units) in rows.items()]
    with connect(autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        # Replaced whole: a SKU dropped from the sheet has no virtual
        # stock any more, and leaving the old row would keep promising
        # stock nobody is sourcing.
        cur.execute(f"TRUNCATE {TABLE}")
        psycopg2.extras.execute_values(
            cur, f"INSERT INTO {TABLE} (variant_sku, size, virtual_units, source_file) "
                 f"VALUES %s", payload, page_size=500)
        cur.execute(f"""
            SELECT count(*) FILTER (WHERE i.variant_sku IS NULL) AS unmatched
              FROM {TABLE} v
              LEFT JOIN public.inventory_variant_current i
                     ON upper(i.variant_sku) = v.variant_sku
                    AND i.unparsed_reason IS NULL""")
        unmatched = cur.fetchone()[0]
        conn.commit()

    print(f"\n[OK] {len(rows)} SKUs written")
    if unmatched:
        print(f"     [warn] {unmatched} SKU(s) match nothing in inventory_variant_current; "
              f"they are stored but will not show on the inventory page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
