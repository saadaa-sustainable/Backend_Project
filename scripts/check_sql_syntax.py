"""Parse every SQL constant in this repo with a real PostgreSQL parser.

Why this exists
---------------
scripts/refresh_cpis_sku_context.py shipped with a dangling comma between
its last CTE and its INSERT:

    ...
    GROUP BY master_sku
),                          <-- this comma
INSERT INTO public.cpis_sku_context (

It failed instantly on every daily run for two days --
"syntax error at or near INTO" -- and nothing caught it earlier because:

  * ruff and py_compile only check the PYTHON. A broken SQL string is a
    perfectly valid str literal.
  * the SQL had been parsed with pglast when first written, then a CTE
    was removed and it was never re-parsed.
  * the live smoke test ran a hand-edited COPY of the query pasted into
    a database console, not the constant the script actually executes.
    That copy did not have the comma, so it passed while the shipped
    code was broken.

The last point is the real lesson: verifying a transcription proves
nothing about the artefact. This script imports the modules and parses
the exact objects they will execute.

Add new SQL constants to SQL_SOURCES below. Exits non-zero on the first
parse failure, so it works as a CI gate.

Usage:
    python scripts/check_sql_syntax.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Importing a refresh script reads its DSN at module scope. Give it
# something syntactically valid so the import succeeds; nothing here
# ever opens a connection.
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://user@localhost/db")

#: module path -> the names of the SQL constants it executes.
SQL_SOURCES: dict[str, tuple[str, ...]] = {
    "scripts/refresh_cpis_sku_context.py":      ("DDL", "REFRESH"),
    "scripts/refresh_ad_history_milestones.py": ("DDL", "REFRESH"),
    "scripts/refresh_insights_daily_by_ad.py":  ("DDL", "REBUILD_SQL"),
    "app/services/silver/ad_lifecycle.py":      ("_INSERT", "_EXTERNAL_OVERLAY_UPDATE",
                                                "_EXTERNAL_OVERLAY_INSERT",
                                                "_EXTERNAL_TABLE_EXISTS"),
    "app/services/gold/ad_performance.py":      ("_INSERT_WITH_EXTERNAL", "_INSERT_LOCAL_ONLY",
                                                "_EXTERNAL_TABLE_EXISTS"),
    "scripts/sync_ad_metrics_external.py":      ("DDL", "SELECT_SQL"),
}


def _load(path: str):
    spec = importlib.util.spec_from_file_location(f"_sqlcheck_{Path(path).stem}", ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        # Some scripts exit on a missing DSN at import; the constants are
        # already bound by then.
        pass
    return module


def main() -> int:
    try:
        import pglast
    except ImportError:
        print("pglast is not installed -- pip install pglast", file=sys.stderr)
        return 2

    failures = 0
    checked = 0
    for path, names in SQL_SOURCES.items():
        module = _load(path)
        for name in names:
            sql = getattr(module, name, None)
            if not isinstance(sql, str):
                print(f"MISSING  {path}:{name} -- not a string constant", file=sys.stderr)
                failures += 1
                continue
            checked += 1
            try:
                pglast.parse_sql(sql)
            except Exception as exc:
                failures += 1
                print(f"FAIL     {path}:{name}\n         {exc}", file=sys.stderr)
            else:
                print(f"ok       {path}:{name}")

    print(f"\n{checked} SQL constant(s) parsed, {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
