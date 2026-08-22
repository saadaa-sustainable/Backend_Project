"""Runs the 4 Bronze -> Silver flatten functions (scripts/sql/functions/
flatten_{account,campaign,adset,ad}_metrics.sql) via Supabase RPC.

Each function is pure SQL (option B: SQL does the join/cast/upsert
server-side, Python only triggers it and reports the result) -- see
docs/ctd_computation_logic_reference.md and the flow diagrams from this
session for why. This script does not touch raw_dump_meta directly; all
four flatten_*_metrics() functions must already exist in the target
Supabase project (run the .sql files in this directory's functions/
subfolder, and the silver_*.sql DDL, once each via the SQL Editor first).

Usage:
    python3 scripts/flatten_silver_metrics.py                # all 4 levels
    python3 scripts/flatten_silver_metrics.py --level ad      # just one
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

LEVELS = ["account", "campaign", "adset", "ad"]


def _resolve_supabase_creds() -> tuple[str, str] | None:
    supabase_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_URL")
    service_role_key = (
        os.environ.get("DATABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not supabase_url or not service_role_key:
        print(
            "A Supabase project URL (DATABASE_URL or SUPABASE_URL) and a service-role key "
            "(DATABASE_SERVICE_KEY, SUPABASE_KEY, or SUPABASE_SERVICE_ROLE_KEY) must both be set in .env.",
            file=sys.stderr,
        )
        return None
    return supabase_url, service_role_key


def _call_flatten_fn(client: httpx.Client, supabase_url: str, service_role_key: str, level: str) -> int:
    fn = f"flatten_{level}_metrics"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
    resp = client.post(f"{supabase_url.rstrip('/')}/rest/v1/rpc/{fn}", headers=headers, json={}, timeout=300.0)
    if resp.status_code >= 300:
        raise RuntimeError(f"{fn} failed ({resp.status_code}): {resp.text[:500]}")
    return int(resp.json())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--level", choices=LEVELS, default=None, help="Restrict to one level. Default: all 4.")
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

    creds = _resolve_supabase_creds()
    if creds is None:
        return 1
    supabase_url, service_role_key = creds

    levels = [args.level] if args.level else LEVELS
    print(f"Target Supabase project: {supabase_url}")
    print(f"Flattening levels: {', '.join(levels)}\n")

    any_error = False
    with httpx.Client() as client:
        for level in levels:
            t0 = time.monotonic()
            try:
                rows = _call_flatten_fn(client, supabase_url, service_role_key, level)
                dt = time.monotonic() - t0
                print(f"  [{level:<8}] flatten_{level}_metrics() -- {rows} rows upserted -- {dt:.2f}s")
            except RuntimeError as exc:
                any_error = True
                print(f"  [{level:<8}] FAILED -- {exc}", file=sys.stderr)

    return 1 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
