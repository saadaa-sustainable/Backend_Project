"""verify_sku_inventory.py -- reconcile a master SKU's unit count.

Answers one question: "the dashboard says N units for SMCP -- is that
right, and if not, where did the rest go?"

It compares two numbers:

  GROUND TRUTH   every variant in the Shopify products dump whose SKU
                 starts with the master SKU, summed, with NO filtering
                 at all. This is "what is in the store".

  CPIS TOTAL     what the CPIS query's Units in Stock column computes,
                 reproducing its exact pipeline: bundle productType
                 exclusions -> variant SKU -> master-SKU parse ->
                 validate against ^(SD|SM|SU)[A-Z]{1,4}$ -> dedupe per
                 variant SKU with MAX -> sum. Price-test listings ARE
                 counted (same SKUs, same stock); the dedupe stops the
                 overlap being counted twice.

Any gap between them is itemised by CAUSE, with example SKUs, so the
fix is obvious rather than guessed at. The causes it can find:

  excluded_product_type  the product is a BUNDLE (combo / set /
                         "buy any 3") or another category, so its
                         inventory count is not this SKU's units
  unparseable_sku        the SKU doesn't yield a valid master SKU
                         (no colour code, lowercase, extra segment)
  misfiled_other_master  the SKU parses, but to a DIFFERENT master --
                         e.g. an underscore-less SMCPBLS parses to
                         SMCPB, so its units land on a row that isn't
                         this one
  truncated_variants     the product was stored with
                         variants.pageInfo.hasNextPage = true, so the
                         bronze row itself is missing variants. Ingests
                         before the 2026-09-04 pagination fix did this
                         for any product with >25 variants; re-run the
                         Shopify refresh to clear it.

Reads raw_dump_shopify directly, so it measures exactly what the API
would serve right now -- not a re-fetch that might disagree.

Usage:
    python scripts/verify_sku_inventory.py --sku SMCP
    python scripts/verify_sku_inventory.py --sku SMCP --expected 8000
    python scripts/verify_sku_inventory.py --all          # every master SKU
    python scripts/verify_sku_inventory.py --sku SMCP --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402


#: Kept byte-for-byte in step with the CPIS query's product_sku_map CTE
#: (app/api/routers/analytics.py). If you change one, change the other --
#: the whole point of this script is that it mirrors production exactly.
#:
#: NOTE "price test" is deliberately NOT here. A price-test listing is a
#: duplicate of the same product at a different price -- same variant
#: SKUs, same physical stock -- so as of 2026-09-04 it is counted for
#: stock and only excluded from the price ladder. Measured live: SMCP
#: holds 8,641 units under "Men Cotton Pant Price Test" whose 77 SKUs
#: are a superset of the 21 under "Men Cotton Pant"; excluding it was
#: what made the dashboard read 1,152. The per-SKU MAX dedupe below is
#: what makes counting both listings safe.
EXCLUDED_PRODUCT_TYPE_PATTERNS = [
    "combo", "bedsheet", "co-ord", "comforter", "buy any 3", " set",
]

MASTER_SKU_RE = re.compile(r"^(SD|SM|SU)[A-Z]{1,4}$")
SIZE_SUFFIX_RE = re.compile(r"_[A-Za-z0-9]+$")


def parse_master_sku(variant_sku: str | None) -> str | None:
    """Strip the trailing _<size>, strip the 2-char colour code, validate.

    Mirrors the SQL in product_variants exactly:
        SUBSTRING(regexp_replace(sku,'_[A-Za-z0-9]+$','')
                  FROM 1 FOR GREATEST(1, length(...) - 2))
    """
    if not variant_sku:
        return None
    base = SIZE_SUFFIX_RE.sub("", variant_sku)
    master = base[: max(1, len(base) - 2)]
    return master if MASTER_SKU_RE.match(master) else None


def product_type_excluded(product_type: str | None) -> str | None:
    """Return the matching exclusion pattern, or None if the product is kept."""
    lowered = (product_type or "").lower()
    for pattern in EXCLUDED_PRODUCT_TYPE_PATTERNS:
        if pattern in lowered:
            return pattern.strip()
    return None


FETCH_SQL = """
SELECT raw_payload, extracted_at
FROM raw_dump_shopify
WHERE object_type = 'products'
"""


def audit(rows: list[dict], target: str) -> dict:
    """Classify every variant whose SKU belongs to `target`'s family.

    Family membership for GROUND TRUTH is deliberately a plain prefix
    match on the raw SKU -- no parsing, no filtering. That is the only
    way to see units the production pipeline drops, since anything the
    pipeline can't parse is exactly what we're hunting for.
    """
    counted: dict[str, int] = {}      # variant_sku -> units (deduped, as CPIS does)
    losses: dict[str, list[dict]] = defaultdict(list)
    ground_truth: dict[str, int] = {}
    newest = None

    for row in rows:
        payload, extracted_at = row["raw_payload"], row["extracted_at"]
        if newest is None or (extracted_at and extracted_at > newest):
            newest = extracted_at
        product_type = payload.get("productType") or ""
        title = payload.get("title") or "(untitled)"
        excluded_by = product_type_excluded(product_type)
        variants_conn = payload.get("variants") or {}
        truncated = bool((variants_conn.get("pageInfo") or {}).get("hasNextPage"))

        for edge in variants_conn.get("edges") or []:
            node = edge.get("node") or {}
            sku = node.get("sku")
            if not sku or not sku.upper().startswith(target.upper()):
                continue
            units = max(int(node.get("inventoryQuantity") or 0), 0)

            # Ground truth: every unit in the store under this prefix.
            ground_truth[sku] = max(ground_truth.get(sku, 0), units)

            detail = {"sku": sku, "units": units, "product": title,
                      "product_type": product_type}
            if truncated:
                # Recorded as a warning even when the variant itself is
                # counted -- the product is missing OTHER variants whose
                # units can't be seen from here at all.
                losses["truncated_variants"].append(detail)
            if excluded_by:
                losses["excluded_product_type"].append({**detail, "matched": excluded_by})
                continue
            master = parse_master_sku(sku)
            if master is None:
                losses["unparseable_sku"].append(detail)
                continue
            if master != target.upper():
                losses["misfiled_other_master"].append({**detail, "filed_as": master})
                continue
            # CPIS dedupes per (master_sku, variant_sku) with MAX.
            counted[sku] = max(counted.get(sku, 0), units)

    return {
        "master_sku": target.upper(),
        "cpis_total": sum(counted.values()),
        "cpis_variant_count": len(counted),
        "ground_truth_total": sum(ground_truth.values()),
        "ground_truth_variant_count": len(ground_truth),
        "losses": dict(losses),
        "products_snapshot_at": newest.isoformat() if newest else None,
    }


def print_report(result: dict, expected: int | None) -> None:
    gt, cpis = result["ground_truth_total"], result["cpis_total"]
    print(f"\n=== {result['master_sku']} ===")
    print(f"Shopify products snapshot: {result['products_snapshot_at'] or 'unknown'}")
    print(f"  Ground truth (every SKU starting {result['master_sku']}, unfiltered):")
    print(f"      {gt:>8,} units across {result['ground_truth_variant_count']} variants")
    print("  CPIS 'Units in Stock' (what the dashboard shows):")
    print(f"      {cpis:>8,} units across {result['cpis_variant_count']} variants")
    gap = gt - cpis
    print(f"  Gap: {gap:,} units" + ("  <-- all accounted for below" if gap else "  (none)"))

    labels = {
        "excluded_product_type": "Excluded by productType filter",
        "unparseable_sku":       "SKU does not parse to a valid master SKU",
        "misfiled_other_master": "Parses to a DIFFERENT master (lands on another row)",
        "truncated_variants":    "Product stored truncated (>25 variants, pre-fix ingest)",
    }
    for cause, items in result["losses"].items():
        if not items:
            continue
        total = sum(i["units"] for i in items)
        print(f"\n  {labels.get(cause, cause)}: {total:,} units, {len(items)} variants")
        for item in sorted(items, key=lambda i: -i["units"])[:6]:
            extra = ""
            if "matched" in item:
                extra = f"  [productType {item['product_type']!r} matched {item['matched']!r}]"
            elif "filed_as" in item:
                extra = f"  [filed as {item['filed_as']}]"
            print(f"      {item['sku']:<18} {item['units']:>6,}  {item['product'][:40]}{extra}")
        if len(items) > 6:
            print(f"      ... and {len(items) - 6} more")

    if result["losses"].get("truncated_variants"):
        print("\n  NOTE: truncated products mean units exist that this report")
        print("        cannot even see. Re-run the Shopify refresh workflow")
        print("        (variant pagination landed 2026-09-04), then re-check.")

    if expected is not None:
        print(f"\n  You expected ~{expected:,}.")
        for label, value in (("Ground truth", gt), ("CPIS total", cpis)):
            delta = value - expected
            verdict = "matches" if abs(delta) <= max(1, expected * 0.02) else "DIFFERS"
            print(f"      {label:<14} {value:>8,}  {verdict} (delta {delta:+,})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sku", help="Master SKU to audit, e.g. SMCP")
    ap.add_argument("--all", action="store_true",
                    help="Audit every master SKU found, summary only")
    ap.add_argument("--expected", type=int, default=None,
                    help="Your own figure, to compare against")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    if not args.sku and not args.all:
        ap.error("pass --sku SMCP or --all")

    dsn = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL") or ""
    dsn = dsn.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://")
    if not dsn:
        print("Set DATABASE_URL_SYNC (or DATABASE_URL) first.", file=sys.stderr)
        return 2

    with psycopg2.connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(FETCH_SQL)
            rows = cur.fetchall()
    if not rows:
        print("raw_dump_shopify has no 'products' rows -- run the Shopify "
              "refresh workflow first.", file=sys.stderr)
        return 1

    if args.all:
        masters = sorted({
            m for r in rows
            for e in ((r["raw_payload"].get("variants") or {}).get("edges") or [])
            if (m := parse_master_sku(((e.get("node") or {}).get("sku"))))
        })
        results = [audit(rows, m) for m in masters]
        if args.json:
            print(json.dumps(results, indent=2))
            return 0
        print(f"{'master':<10} {'CPIS':>10} {'truth':>10} {'gap':>10}")
        for r in results:
            gap = r["ground_truth_total"] - r["cpis_total"]
            print(f"{r['master_sku']:<10} {r['cpis_total']:>10,} "
                  f"{r['ground_truth_total']:>10,} {gap:>10,}"
                  + ("   <-- units missing" if gap else ""))
        return 0

    result = audit(rows, args.sku)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result, args.expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
