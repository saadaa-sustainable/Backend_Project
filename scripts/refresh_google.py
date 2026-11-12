"""Everything that comes from Google, in one run.

WHY THIS EXISTS
---------------
The nightly runs in CI, where there are no Google credentials, so every
Google-fed step fails there and the tables only move when somebody runs
them from a machine that has the credentials. That used to mean nine
commands in the right order. This is those nine, in that order.

    ./.venv/bin/python scripts/refresh_google.py

WHAT IT RUNS
------------
    ads_spend       Google Ads spend per campaign per day, from the Ads API
    ads_roster      campaigns, ad groups and ads (bronze)
    ads_silver      the google_* tables built from that roster
    ga4_landing     GA4 sessions by landing page
    ga4_arpu        GA4 ARPU by day and by window
    ga4_attribution first click per order, from the GA4 BigQuery export
    returns         SKU returns, from the MapleMonk BigQuery table
    landing_gold    the three landing-page tables built on ga4_landing
    snapshots       the materialized views behind the founder sheet

The order matters in two places: `ads_silver` reads what `ads_roster`
wrote, and `landing_gold` reads what `ga4_landing` wrote. A step whose
source failed is skipped rather than rebuilt from stale input.

WHAT IT DOES NOT RUN
--------------------
The bq_inventory pull. It scans millions of rows for one column and was
dropped from the nightly for that reason; nothing here reads it.

Google Ads spend is read from the Ads API only. The MapleMonk copy of
the same table is the nightly's fallback, and a manual run of it can
replace fresher API rows with its own frozen conversions.

COST
----
Only `ga4_attribution` costs anything worth knowing: it scans the GA4
export with a 90-day session lookback, roughly half a US dollar for the
default three days of orders and more for a longer window. Leave it out
with `--skip ga4_attribution` when only spend or sessions are wanted.

Usage:
    ./.venv/bin/python scripts/refresh_google.py                    # all of it
    ./.venv/bin/python scripts/refresh_google.py --list             # show the steps
    ./.venv/bin/python scripts/refresh_google.py --only ads         # just Google Ads
    ./.venv/bin/python scripts/refresh_google.py --only ga4_landing landing_gold
    ./.venv/bin/python scripts/refresh_google.py --skip ga4_attribution
    ./.venv/bin/python scripts/refresh_google.py --attribution-days 7
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

#: Lines of a step's output kept for the summary when it fails.
TAIL = 15


def build_steps(args: argparse.Namespace) -> list[tuple[str, list[str], int, str | None]]:
    """(name, command, timeout seconds, the step it depends on)."""
    return [
        ("ads_spend", ["scripts/fetch_google_ads_api.py", "--days", str(args.ads_days)],
         900, None),
        ("ads_roster", ["scripts/fetch_google_ads_entities.py"], 600, None),
        ("ads_silver", ["scripts/refresh_google_entities.py"], 600, "ads_roster"),
        ("ga4_landing", ["scripts/fetch_ga4_daily.py", "--days", str(args.ga4_days)],
         1200, None),
        ("ga4_arpu", ["scripts/fetch_ga4_arpu.py", "--days", str(args.arpu_days)],
         900, None),
        ("ga4_attribution", ["scripts/fetch_ga4_order_attribution.py",
                             "--days", str(args.attribution_days)], 1800, None),
        ("returns", ["scripts/refresh_master_sku_returns.py"], 900, None),
        ("landing_gold", ["scripts/refresh_landing_page_gold.py"], 1800, "ga4_landing"),
        ("snapshots", ["scripts/refresh_snapshot_views.py"], 900, None),
    ]


def pick(names: list[str], wanted: list[str]) -> set[str]:
    """Step names matching any of `wanted`, exactly or by prefix.

    A prefix so `--only ads` means the three Google Ads steps and
    `--only ga4` the three GA4 ones, without a second vocabulary of
    group names to remember. A word that matches nothing is an error:
    silently running everything, or nothing, on a typo is worse.
    """
    chosen: set[str] = set()
    for w in wanted:
        hit = {n for n in names if n == w or n.startswith(w)}
        if not hit:
            raise SystemExit(f"No step matches {w!r}. Steps: {', '.join(names)}")
        chosen |= hit
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", metavar="STEP", default=None,
                    help="Run just these steps. A prefix selects a group: 'ads', 'ga4'.")
    ap.add_argument("--skip", nargs="+", metavar="STEP", default=[],
                    help="Leave these steps out. Same matching as --only.")
    ap.add_argument("--list", action="store_true", help="Show the steps and exit.")
    ap.add_argument("--ads-days", type=int, default=35,
                    help="Days of Google Ads spend to re-read (default 35: Google "
                         "restates recent days as conversions land).")
    ap.add_argument("--ga4-days", type=int, default=10,
                    help="Days of GA4 landing sessions (default 10).")
    ap.add_argument("--arpu-days", type=int, default=35,
                    help="Days of GA4 ARPU (default 35).")
    ap.add_argument("--attribution-days", type=int, default=3,
                    help="Days of orders to attribute (default 3). This is the one "
                         "step with a BigQuery bill; it grows with the window.")
    args = ap.parse_args()

    steps = build_steps(args)
    names = [s[0] for s in steps]
    chosen = pick(names, args.only) if args.only else set(names)
    chosen -= pick(names, args.skip) if args.skip else set()
    steps = [s for s in steps if s[0] in chosen]

    if args.list or not steps:
        for name, cmd, _, needs in build_steps(args):
            mark = "x" if name in chosen else " "
            print(f"  [{mark}] {name:<16} {' '.join(cmd)}"
                  + (f"   (after {needs})" if needs else ""))
        return 0

    print(f"Google refresh: {len(steps)} step(s)\n")
    results: dict[str, tuple[str, float, str]] = {}
    started = time.monotonic()
    for name, cmd, timeout, needs in steps:
        # Only a dependency that RAN and failed blocks its reader. One
        # left out on purpose leaves yesterday's input in place, which
        # is exactly what `--only landing_gold` is asking for.
        if needs in results and results[needs][0] != "ok":
            results[name] = ("skipped", 0.0, f"{needs} did not finish")
            print(f"  --   {name:<16} skipped: {needs} did not finish")
            continue
        print(f"  ..   {name:<16} running", flush=True)
        t0 = time.monotonic()
        try:
            proc = subprocess.run([PY, str(ROOT / cmd[0]), *cmd[1:]], cwd=str(ROOT),
                                  capture_output=True, text=True, timeout=timeout)
            out = (proc.stdout or "") + (proc.stderr or "")
            status = "ok" if proc.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            out, status = f"timed out after {timeout}s", "failed"
        took = time.monotonic() - t0
        tail = "\n".join(out.strip().splitlines()[-TAIL:])
        results[name] = (status, took, tail)
        print(f"  {'ok  ' if status == 'ok' else 'FAIL'} {name:<16} {took:6.0f}s", flush=True)

    total = time.monotonic() - started
    failed = [n for n, r in results.items() if r[0] == "failed"]
    skipped = [n for n, r in results.items() if r[0] == "skipped"]
    print(f"\n{len(results) - len(failed) - len(skipped)} ok, {len(failed)} failed, "
          f"{len(skipped)} skipped in {total / 60:.1f} min")
    for name in failed:
        print(f"\n--- {name} ---\n{results[name][2]}")
    return 1 if failed or skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
