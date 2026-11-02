"""Load the production sheet's OOS tab into Postgres, for comparison.

WHY A SECOND SOURCE AT ALL
--------------------------
Shopify and this sheet are maintained by different people from
different systems, and they disagree. That is the point: the comparison
is the product, not a reconciliation bug to be fixed.

Measured on 2026-11-02, the disagreement is SYMMETRIC -- Shopify reads
higher on about half the colours and the sheet on the other half, with
a median ratio of 1.00. A concept difference (sellable vs on hand, one
warehouse vs all) would push one way. This does not. The two are
counting the same stock at different moments, so the gap is drift plus
whatever genuine error either side carries, and a buyer wants to see
where it is large.

THE TAB
-------
"OOS as per Production Plan" in the FY26-27 Production Sheet, at the
COLOUR grain -- one row per `PRODUCT VARIENT`, which is our colour SKU,
with a column per size.

Row 1 is a totals/timestamp strip and row 2 the header; data starts at
row 3. The timestamp in the first cell is when the sheet last
recalculated, and it is stored, because comparing a daily Shopify
snapshot against a sheet that recalculated minutes ago will always show
churn and the reader has to be able to see which moments are being
compared.

Usage:
    ./.venv/bin/python scripts/ingest_production_sheet.py
    ./.venv/bin/python scripts/ingest_production_sheet.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402
from scripts.read_sheet import service  # noqa: E402

SHEET_ID = "1goe5XW1FUdgSFfKZEalHvqI2TMxNY0IN5qq4Gs2xR-g"
TAB = "OOS as per Production Plan"
RANGE = "C:AW"
TABLE = "public.production_sheet_oos"

#: The size columns, in the order the sheet lays them out. The header
#: writes them as "(1) XS" .. "(5) 5XL" -- note the sheet repeats "(5)",
#: so the ORDINAL in the header is not reliable and position is.
SIZES = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]

#: Offsets within the C:AW slice, so column C is 0.
COL = {
    "master_sku": 0,       # C  Product Code
    "rm_fabric_code": 1,   # D
    "dyed_fabric_sku": 2,  # E
    "category_type": 3,    # F
    "colour_sku": 4,       # G  PRODUCT VARIENT
    "product_status": 5,   # H
    "size0": 6,            # I..Q
    "total_stock": 15,     # R
    "doq": 16,             # S
    "ip_doq": 17,          # T
    "class": 18,           # U
    "noos": 19,            # V
    "size_count": 20,      # W
    "oos_sku_count": 21,   # X
    "in_stock_sku_count": 22,  # Y
    "colour_instock_rate": 23,  # Z
    "pending_inv_qty": 24,  # AA
    "total_in_process": 25,  # AB
    "rop_30": 29, "rop_60": 30, "rop_90": 31,   # AG AH AI
    "total_doh": 37,       # AO
    "priority_to_restock": 39,  # AQ
    "date_of_restocking": 40,   # AR
    "colour_instock_status": 43,  # AU
    "scm_comment": 44,     # AV
}

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    colour_sku      text PRIMARY KEY,
    master_sku      text,
    product_status  text,
    category_type   text,
    -- Per-size quantities, keyed by our size vocabulary so they line up
    -- with inventory_variant_current without a mapping table.
    stock_by_size   jsonb,
    total_stock     integer,
    -- The sheet's OWN rate, kept as it writes it. Deliberately NOT
    -- recomputed: the comparison is only honest if each side keeps its
    -- own arithmetic, and a difference in the rate is itself a finding.
    colour_instock_rate numeric,
    oos_sku_count       integer,
    in_stock_sku_count  integer,
    size_count          integer,
    doq             numeric,
    ip_doq          numeric,
    pending_inv_qty integer,
    total_in_process integer,
    rop_30          integer,
    rop_60          integer,
    rop_90          integer,
    total_doh       numeric,
    priority_to_restock text,
    date_of_restocking  text,
    colour_instock_status text,
    scm_comment     text,
    -- When the SHEET last recalculated, from its own header cell. Not
    -- our fetch time: comparing a daily snapshot against a sheet that
    -- recalculated minutes ago always shows churn, and the reader needs
    -- to see which two moments are being compared.
    sheet_as_of     timestamptz,
    fetched_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pso_master ON {TABLE} (master_sku);
"""


def num(raw: str | None) -> float | None:
    """A sheet cell to a number, or None.

    These cells carry thousands separators, stray percent signs and
    Excel error strings. `#N/A` is not zero -- a formula that failed is
    unknown, and storing it as zero would make a missing figure look
    like an absent one.
    """
    s = (raw or "").strip().replace(",", "").replace("%", "").replace("₹", "")
    if not s or s.startswith("#") or s in {"-", "—", "NA", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def as_int(raw: str | None) -> int | None:
    v = num(raw)
    return None if v is None else int(round(v))


def pct(raw: str | None) -> float | None:
    """'50.00%' -> 0.5. Stored as a fraction, like every other rate in
    this database, so the two sides can be compared without one of them
    being out by a factor of a hundred."""
    v = num(raw)
    return None if v is None else v / 100.0


def cell(row: list[str], idx: int) -> str:
    return row[idx] if len(row) > idx else ""


def parse_sheet_timestamp(first_row: list[str]) -> datetime | None:
    """The recalculation stamp in the strip above the header.

    Day-first: this sheet is written in India, and read the American way
    '02-11-2026' is February, which would silently date every comparison
    nine months wrong.
    """
    for c in first_row[:3]:
        m = re.match(r"(\d{2})-(\d{2})-(\d{4})[ T]+(\d{1,2}):(\d{2})", (c or "").strip())
        if m:
            d, mo, y, h, mi = (int(x) for x in m.groups())
            try:
                return datetime(y, mo, d, h, mi)
            except ValueError:
                return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    api = service()
    values = (api.spreadsheets().values()
              .get(spreadsheetId=SHEET_ID, range=f"'{TAB}'!{RANGE}",
                   valueRenderOption="FORMATTED_VALUE")
              .execute().get("values", []))
    if len(values) < 3:
        raise SystemExit(f"'{TAB}' returned {len(values)} row(s); expected a header and data.")

    sheet_as_of = parse_sheet_timestamp(values[0])

    rows, skipped = [], 0
    for r in values[2:]:
        colour = cell(r, COL["colour_sku"]).strip().upper()
        if not colour:
            skipped += 1
            continue
        by_size = {}
        for i, size in enumerate(SIZES):
            v = as_int(cell(r, COL["size0"] + i))
            if v is not None:
                by_size[size] = v
        rows.append((
            colour, cell(r, COL["master_sku"]).strip().upper() or None,
            cell(r, COL["product_status"]).strip() or None,
            cell(r, COL["category_type"]).strip() or None,
            by_size,
            as_int(cell(r, COL["total_stock"])),
            pct(cell(r, COL["colour_instock_rate"])),
            as_int(cell(r, COL["oos_sku_count"])),
            as_int(cell(r, COL["in_stock_sku_count"])),
            as_int(cell(r, COL["size_count"])),
            num(cell(r, COL["doq"])), num(cell(r, COL["ip_doq"])),
            as_int(cell(r, COL["pending_inv_qty"])),
            as_int(cell(r, COL["total_in_process"])),
            as_int(cell(r, COL["rop_30"])), as_int(cell(r, COL["rop_60"])),
            as_int(cell(r, COL["rop_90"])), num(cell(r, COL["total_doh"])),
            cell(r, COL["priority_to_restock"]).strip() or None,
            cell(r, COL["date_of_restocking"]).strip() or None,
            cell(r, COL["colour_instock_status"]).strip() or None,
            cell(r, COL["scm_comment"]).strip() or None,
            sheet_as_of,
        ))

    print(f"Tab:      {TAB}")
    print(f"Sheet as of: {sheet_as_of or 'unknown'}")
    print(f"Rows:     {len(rows)} colour SKUs  ({skipped} blank row(s) skipped)")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    import json
    import psycopg2.extras  # noqa: PLC0415
    payload = [(r[0], r[1], r[2], r[3], json.dumps(r[4]), *r[5:]) for r in rows]
    with connect(autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        # Replaced whole: a colour dropped from the sheet must leave
        # here too, or it lingers and the comparison invents a gap.
        cur.execute(f"TRUNCATE {TABLE}")
        psycopg2.extras.execute_values(cur, f"""
            INSERT INTO {TABLE} (
              colour_sku, master_sku, product_status, category_type, stock_by_size,
              total_stock, colour_instock_rate, oos_sku_count, in_stock_sku_count,
              size_count, doq, ip_doq, pending_inv_qty, total_in_process,
              rop_30, rop_60, rop_90, total_doh, priority_to_restock,
              date_of_restocking, colour_instock_status, scm_comment, sheet_as_of)
            VALUES %s""", payload, page_size=200)
        conn.commit()

    print(f"\n[OK] {len(rows)} colour SKUs written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
