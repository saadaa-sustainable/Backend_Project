"""Install the small index set used by dashboard date and ad filters.

Default: print candidates without connecting. Apply to the configured DB:
    .venv/bin/python scripts/optimize_analytics_indexes.py --apply

Builds concurrently to allow normal reads/writes. Equivalent indexes under
other names are reused. A failed connection or statement ends the run;
invalid index remnants are reported, never dropped automatically.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import dispose_engine, get_engine  # noqa: E402


@dataclass(frozen=True)
class Index:
    name: str
    table: str
    keys: tuple[str, ...]
    include: tuple[str, ...] = ()

    @property
    def ddl(self) -> str:
        sql = f"CREATE INDEX CONCURRENTLY {self.name} ON public.{self.table} ({', '.join(self.keys)})"
        if self.include:
            sql += f" INCLUDE ({', '.join(self.include)})"
        return sql


INDEXES = (
    Index("ix_shopify_order_attribution_created_at", "shopify_order_attribution", ("created_at",)),
    Index("ix_shopify_order_attribution_ad_created", "shopify_order_attribution",
          ("matched_ad_id", "created_at"), ("order_id", "total_price")),
    Index("ix_shopify_orders_processed_at", "shopify_orders", ("processed_at",)),
)

_CATALOG = """
SELECT c.relname AS name, i.indisvalid AS valid, i.indisready AS ready,
       i.indpred IS NULL AS unrestricted, am.amname AS method,
       ARRAY(SELECT pg_get_indexdef(i.indexrelid, n, true)
             FROM generate_series(1, i.indnkeyatts) n) AS keys,
       ARRAY(SELECT pg_get_indexdef(i.indexrelid, n, true)
             FROM generate_series(i.indnkeyatts + 1, i.indnatts) n) AS included
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_am am ON am.oid = c.relam
WHERE i.indrelid = to_regclass(:table)
"""


def covers(existing: dict[str, Any], desired: Index) -> bool:
    keys = tuple(existing["keys"])
    return (
        existing["valid"] and existing["ready"] and existing["unrestricted"]
        and existing["method"] == "btree"
        and keys[:len(desired.keys)] == desired.keys
        and set(desired.include).issubset(set(keys) | set(existing["included"]))
    )


async def apply_indexes(connection) -> None:
    # Each statement keeps its own connection-level deadline; no retries.
    # CREATE INDEX CONCURRENTLY must run outside a transaction.
    for desired in INDEXES:
        async with asyncio.timeout(15):
            rows = (await connection.execute(
                text(_CATALOG), {"table": f"public.{desired.table}"},
            )).mappings().all()
        equivalent = next((row for row in rows if covers(row, desired)), None)
        if equivalent:
            print(f"Reuse {equivalent['name']} for {desired.name}", flush=True)
            continue
        if any(row["name"] == desired.name for row in rows):
            raise RuntimeError(f"{desired.name} exists but is invalid or has a different definition; inspect it before rebuilding")
        print(f"Building {desired.name} concurrently...", flush=True)
        async with asyncio.timeout(300):
            await connection.execute(text(desired.ddl))
        async with asyncio.timeout(15):
            rows = (await connection.execute(
                text(_CATALOG), {"table": f"public.{desired.table}"},
            )).mappings().all()
        if not any(covers(row, desired) for row in rows):
            raise RuntimeError(f"{desired.name} did not produce a usable index")
        print(f"Verified {desired.name}", flush=True)


async def main() -> None:
    try:
        async with asyncio.timeout(15):
            connection = await get_engine().connect()
        try:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await apply_indexes(connection)
        finally:
            await connection.close()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Inspect and build missing indexes")
    if parser.parse_args().apply:
        asyncio.run(main())
    else:
        for candidate in INDEXES:
            print(candidate.ddl + ";")
        print("Preview only; no database connection was opened.")
