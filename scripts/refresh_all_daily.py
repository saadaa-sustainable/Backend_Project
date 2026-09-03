"""refresh_all_daily.py -- Backend_Project daily orchestrator.

Runs the whole ingest + silver chain in dependency-correct order, wraps
each step in the cron_log helper, and returns a non-zero exit code if
any critical step failed so GitHub Actions marks the run red.

Called by .github/workflows/daily-refresh.yml at 05:00 IST daily.
Also runnable manually:

    ./.venv/Scripts/python.exe scripts/refresh_all_daily.py
    ./.venv/Scripts/python.exe scripts/refresh_all_daily.py --skip-meta
    ./.venv/Scripts/python.exe scripts/refresh_all_daily.py --only-silver

Phase layout mirrors CTD's _refresh_all_dashboard_data.py:

  PHASE 1 -- INGEST (external APIs, throttle-heavy, sequential)
     ingest_last_15_days.py                 Meta ads insights bronze
     fetch_ad_product_insights.py           Meta DPA product_id breakdown
     ingest_instagram_chronological.py      IG posts bronze
     ingest_shopify.py                      Shopify products/orders/customers bronze
     fetch_bq_inventory_daily.py            BigQuery inventory pull

  PHASE 2 -- SILVER (DB-only, depends on Phase 1)
     refresh_raw_dump_meta_daily.py         bronze meta -> daily flatten
     refresh_insights_daily_by_ad.py        dedup + range-expand -> ad x day
     refresh_shopify_silver.py              shopify bronze -> silver
     refresh_master_sku_inventory.py        BQ inventory -> master_sku silver
     refresh_master_sku_returns.py          BQ returns -> master_sku silver
     refresh_cpis_by_sku_daily.py           daily CPIS aggregate
     refresh_cpis_utm.py                    windowed CPIS (7/30/90d)
     refresh_ad_product_daily.py            DPA product silver
     refresh_ad_media.py                    ad-media joined silver

Wall time: ~35-60 min depending on Meta throttle.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys
from dotenv import load_dotenv

# UTF-8 for GH Actions (default is fine but be explicit).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="backslashreplace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)  # override=False so GH secrets win

from utils.cron_log import CronRun  # noqa: E402

PY = sys.executable

# (label, [script + args], timeout_seconds). Ordered by dependency.
PHASE_INGEST = [
    ("meta_insights_15d",     ["scripts/ingest_last_15_days.py"],           2700),
    ("meta_dpa_products",     ["scripts/fetch_ad_product_insights.py"],     1800),
    ("instagram_posts",       ["scripts/ingest_instagram_chronological.py"], 1800),
    ("shopify_daily",         ["scripts/ingest_shopify.py"],                1800),
    ("bq_inventory",          ["scripts/fetch_bq_inventory_daily.py"],       900),
]

PHASE_SILVER = [
    ("silver_raw_dump_meta",  ["scripts/refresh_raw_dump_meta_daily.py"],   1200),
    ("silver_insights_daily", ["scripts/refresh_insights_daily_by_ad.py"],   900),
    ("silver_shopify",        ["scripts/refresh_shopify_silver.py"],         900),
    ("silver_inventory",      ["scripts/refresh_master_sku_inventory.py"],   600),
    ("silver_returns",        ["scripts/refresh_master_sku_returns.py"],     900),
    ("silver_cpis_daily",     ["scripts/refresh_cpis_by_sku_daily.py"],      900),
    ("silver_cpis_utm",       ["scripts/refresh_cpis_utm.py"],              1200),
    ("silver_ad_product",     ["scripts/refresh_ad_product_daily.py"],       600),
    ("silver_ad_media",       ["scripts/refresh_ad_media.py"],               900),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-meta", action="store_true",
                    help="skip Phase 1 (use when Meta token is throttled)")
    ap.add_argument("--only-silver", action="store_true",
                    help="only Phase 2 (silver rebuild from existing bronze)")
    args = ap.parse_args()

    steps: list[tuple[str, list[str], int]] = []
    if not (args.skip_meta or args.only_silver):
        steps += PHASE_INGEST
    steps += PHASE_SILVER

    with CronRun(project="backend_project") as run:
        for name, cmd, timeout in steps:
            with run.step(name, timeout=timeout) as step:
                # Prepend the interpreter so the workflow doesn't need to
                # know each script's shebang; also lets us pin the venv.
                full_cmd = [PY, str(ROOT / cmd[0]), *cmd[1:]]
                step.run(full_cmd, cwd=str(ROOT))

    # Exit red if ANY step failed so GitHub marks the run failed and
    # sends a notification. Partial success still fails the job.
    return 0 if run.steps and all(s["status"] == "ok" for s in run.steps.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
