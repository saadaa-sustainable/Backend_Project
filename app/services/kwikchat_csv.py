"""Parse the Kwikchat console's daily-spend CSV export.

Lifted out of `scripts/import_kwikchat_spend.py` so the command line
and the upload endpoint read a file the same way. Two parsers for one
format is two chances to disagree about what a day cost, and the
disagreement would be invisible: both produce a plausible number.

THE FILE
--------
Kwikchat console -> daily spend view -> export. One row per day of a
month, with a `Total Price` column that already sums WhatsApp, SMS,
RCS, email and AI calling.

Dates are DD-MM-YYYY. Amounts carry a rupee sign and Indian digit
grouping, and the grouped ones are quoted, so "1,00,000" is ONE field
and not three -- csv.reader handles that, a split on comma does not.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime


class KwikchatCsvError(ValueError):
    """The file is not a daily-spend export, or a row will not parse."""


def parse_amount(raw: str) -> float:
    """"₹1,00,000.50" -> 100000.5

    Indian grouping is not every three digits, so no assumption about
    group width survives -- the separators are simply removed.
    """
    cleaned = (raw or "").strip().replace("₹", "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError as exc:
        raise KwikchatCsvError(f"not an amount: {raw!r}") from exc


def parse_day(raw: str) -> date:
    """DD-MM-YYYY, as the console writes it.

    Parsed strictly rather than with dateutil: 03-10-2026 is the third
    of October here and the tenth of March in the American reading, and
    a silent month/day swap would move a month of spend.
    """
    try:
        return datetime.strptime((raw or "").strip(), "%d-%m-%Y").date()
    except ValueError as exc:
        raise KwikchatCsvError(f"not a DD-MM-YYYY date: {raw!r}") from exc


def read_rows(text: str, name: str = "upload") -> list[tuple[date, float]]:
    """(day, spend) per row, in file order.

    Takes the file's TEXT rather than a path, because the endpoint has
    an upload in memory and the script has a file: text is the thing
    they share. The caller strips the BOM by decoding utf-8-sig.
    """
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    # Named explicitly rather than taken by position. The console has
    # twenty-two columns and has added some before; a positional read
    # would silently start reporting a different one.
    for need in ("Date", "Total Price"):
        if need not in cols:
            raise KwikchatCsvError(
                f"No `{need}` column in {name}. Columns: {cols}")
    out: list[tuple[date, float]] = []
    for i, row in enumerate(reader, start=2):
        if not (row.get("Date") or "").strip():
            continue
        try:
            out.append((parse_day(row["Date"]), parse_amount(row["Total Price"])))
        except KwikchatCsvError as exc:
            raise KwikchatCsvError(f"{name} line {i}: {exc}") from exc
    if not out:
        raise KwikchatCsvError(f"{name} has a header but no dated rows.")
    return out


#: The workspaces this business bills under. Kwikchat exports one at a
#: time, so a month arrives as one file per account covering the same
#: dates with different traffic.
#:
#: Spelled exactly as the console shows them, including `Backedn731` --
#: an identifier is not something to tidy up on the owner's behalf,
#: and a corrected one would not match what they upload against.
ACCOUNTS = (
    "Backedn731",
    "Backend732",
    "Backend734",
    "Backend735",
    "Backend736",
    "Backend999",
    "Backend_ebo",
    "Backend_Saadaa",
)
