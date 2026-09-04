"""refresh_all_daily.py -- Backend_Project daily orchestrator.

Runs the whole ingest + silver chain in dependency-correct order, wraps
each step in the cron_log helper, and returns a non-zero exit code if
any critical step failed so GitHub Actions marks the run red.

Called by .github/workflows/daily-refresh.yml at 05:00 IST daily.
Also runnable manually:

    ./.venv/Scripts/python.exe scripts/refresh_all_daily.py
    ./.venv/Scripts/python.exe scripts/refresh_all_daily.py --skip-meta
    ./.venv/Scripts/python.exe scripts/refresh_all_daily.py --only-silver
    ./.venv/Scripts/python.exe scripts/refresh_all_daily.py --only-shopify

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

# ----------------------------------------------------------------------
# Shopify ingest tuning -- shared by the daily run AND --only-shopify
# ----------------------------------------------------------------------
#
# A bare `ingest_shopify.py` walks ALL ten object types over full
# history: customers 984k, sessions 1.37M, inventory 1.28M, orders 347k
# and the rest -- ~4.8M bronze rows. It cannot finish in 1800s, and it
# didn't: measured 2026-09-04, raw_dump_shopify 'products' was 8 days
# stale (newest 2026-08-27) while cron_run_log showed
# shopify_daily = "timeout after 1800s" on EVERY recent run. The daily
# refresh has therefore not updated Shopify data since 27 August.
#
# So the daily step is scoped and re-timed, not just the manual one --
# an unscoped daily run is exactly what was failing.
SHOPIFY_INGEST_TIMEOUT_S = 5400

#: ORDER MATTERS and is cheapest-first on purpose. ingest_shopify.py runs
#: these sequentially in the order given (fixed 2026-09-04 -- it used to
#: group ShopifyQL tables ahead of everything else, so the 1.28M-row
#: `inventory` ran before the 635-row `products` regardless of what you
#: asked for). Writes are per page/chunk, so a run later killed has still
#: committed whatever finished -- which is what makes ordering pay:
#:
#:   products  ~1.3k rows, seconds  -> Units in Stock, in-stock rates,
#:                                     Selling Price and the cost model
#:   inventory ShopifyQL, 30 days   -> DoQ, Total DOH, OOS %
#:   orders    full history, ~347k  -> the UTM attribution behind CPIS
#:
#: Deliberately omits customers/sessions/fulfillments/sales/discounts/
#: customer_analytics: ~2.9M rows no CPIS column reads. Pass
#: --shopify-object-types (or 'all') to widen it.
DEFAULT_SHOPIFY_OBJECT_TYPES = "products,inventory,orders"

#: --incremental makes orders/customers/products resume from the newest
#: row already in bronze (minus a 1-day overlap) on updated_at, instead
#: of re-walking full history every run. Without it, run #7 (2026-09-04)
#: spent 1079s on a ~347k-order full walk and returned ZERO rows before
#: failing. Falls back to a full walk automatically when bronze is empty
#: or the watermark can't be read, so a fresh database still backfills.
SHOPIFY_INGEST_CMD = [
    "scripts/ingest_shopify.py",
    "--object-types", DEFAULT_SHOPIFY_OBJECT_TYPES,
    "--incremental",
]

# (label, [script + args], timeout_seconds). Ordered by dependency.
PHASE_INGEST = [
    ("meta_insights_15d",     ["scripts/ingest_last_15_days.py"],           2700),
    ("meta_dpa_products",     ["scripts/fetch_ad_product_insights.py"],     1800),
    ("instagram_posts",       ["scripts/ingest_instagram_chronological.py"], 1800),
    ("shopify_daily",         SHOPIFY_INGEST_CMD,        SHOPIFY_INGEST_TIMEOUT_S),
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


#: The Shopify-only path (--only-shopify), in dependency order. Listed
#: BY LABEL and resolved against PHASE_INGEST/PHASE_SILVER above rather
#: than redefined here, so a script path or timeout can never diverge
#: between the daily run and the manual Shopify refresh.
#:
#: The two CPIS steps are included because the dashboard's attribution
#: columns read the PRE-COMPUTED cpis_by_sku_utm / cpis_by_sku_daily
#: tables. (The inventory columns -- units in stock, in-stock rates, DoQ,
#: DOH, OOS -- read raw_dump_shopify and shopify_inventory live at query
#: time, so those are current the moment silver_shopify finishes.) Pass
#: --skip-cpis to stop after silver when you only care about inventory.
SHOPIFY_INGEST_STEPS = ["shopify_daily"]
SHOPIFY_SILVER_STEPS = ["silver_shopify"]
SHOPIFY_CPIS_STEPS = ["silver_cpis_daily", "silver_cpis_utm"]


def _steps_by_label(labels: list[str]) -> list[tuple[str, list[str], int]]:
    """Resolve step labels against the canonical phase lists.

    Raises on an unknown label rather than skipping it: a rename in
    PHASE_INGEST/PHASE_SILVER should break loudly here, not quietly
    produce a refresh that silently missed a step.
    """
    catalog = {label: (label, cmd, timeout)
               for label, cmd, timeout in PHASE_INGEST + PHASE_SILVER}
    missing = [label for label in labels if label not in catalog]
    if missing:
        raise SystemExit(
            f"Unknown step label(s) {missing}. Valid: {sorted(catalog)}. "
            "A step was probably renamed in PHASE_INGEST/PHASE_SILVER "
            "without updating the SHOPIFY_*_STEPS lists."
        )
    return [catalog[label] for label in labels]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-meta", action="store_true",
                    help="skip Phase 1 (use when Meta token is throttled)")
    ap.add_argument("--only-silver", action="store_true",
                    help="only Phase 2 (silver rebuild from existing bronze)")
    ap.add_argument("--only-shopify", action="store_true",
                    help="only the Shopify chain: ingest -> silver -> CPIS "
                         "aggregates. For refreshing store data (inventory, "
                         "prices, orders) without waiting on Meta.")
    ap.add_argument("--shopify-object-types", default=DEFAULT_SHOPIFY_OBJECT_TYPES,
                    help="With --only-shopify, the object types to fetch "
                         f"(default: {DEFAULT_SHOPIFY_OBJECT_TYPES}). Pass a "
                         "comma-separated list, or 'all' for every type.")
    ap.add_argument("--skip-cpis", action="store_true",
                    help="with --only-shopify, stop after the silver rebuild "
                         "and skip the CPIS aggregates.")
    args = ap.parse_args()

    if args.only_shopify and (args.skip_meta or args.only_silver):
        raise SystemExit(
            "--only-shopify cannot be combined with --skip-meta/--only-silver: "
            "they select different, overlapping step sets. Pick one."
        )
    if args.skip_cpis and not args.only_shopify:
        raise SystemExit("--skip-cpis only applies together with --only-shopify.")

    steps: list[tuple[str, list[str], int]] = []
    if args.only_shopify:
        labels = SHOPIFY_INGEST_STEPS + SHOPIFY_SILVER_STEPS
        if not args.skip_cpis:
            labels += SHOPIFY_CPIS_STEPS
        steps = _steps_by_label(labels)
    else:
        if not (args.skip_meta or args.only_silver):
            steps += PHASE_INGEST
        steps += PHASE_SILVER

    # Apply the --shopify-object-types override to WHICHEVER path was
    # selected. The daily run now carries the scoped command by default
    # (see SHOPIFY_INGEST_CMD), so this only rewrites it when the caller
    # asked for something different -- and it rewrites it for the daily
    # run too, not just --only-shopify, so `--shopify-object-types all`
    # means the same thing everywhere.
    if args.shopify_object_types != DEFAULT_SHOPIFY_OBJECT_TYPES:
        scoped = ([] if args.shopify_object_types.strip().lower() == "all"
                  else ["--object-types", args.shopify_object_types])
        steps = [
            (label,
             [SHOPIFY_INGEST_CMD[0], *scoped, "--incremental"]
             if label in SHOPIFY_INGEST_STEPS else cmd,
             timeout)
            for label, cmd, timeout in steps
        ]

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
