"""Preview or insert missing, exact asset/ad-name matches in a bounded window.

The default is a read-only preview. Optional JSON snapshots of verified upstream
register rows are considered during preview; --apply imports only rows required
by unambiguous proposals. Existing register and mapping rows are never updated.

Example:
    python scripts/backfill_ad_asset_map.py --from-date 2026-08-18 \
        --to-date 2026-09-16 --source-rows /tmp/verified-assets.json \
        --output-dir exports/mapping_2026-09-16
    # Inspect proposal.csv/unresolved.csv, then repeat with:
    # --apply --expected-matches <reviewed count>
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, execute_values


TABLES = {
    "content_asset_register": ("video", "asset_id", "asset_id"),
    "content_graphic_register": ("graphic", "requisition_id", "requisition_id"),
    "content_influencer_posts": ("influencer", "post_id", "id"),
}
REFERENCED_CODE = re.compile(
    r"(?<![0-9A-Za-z])(?:C[A-Z]{2}[0-9]+-[0-9]+|GAD-[A-Za-z]+-[0-9]+|SIF-[0-9]+-P[0-9]+)(?![0-9])",
    re.I,
)
SOURCE_COLUMNS = {
    "content_asset_register": set("""
        seq asset_id source_parent asset_type category planning_nomenclature
        link_to_asset origin creative_effort_type type_of_content
        date_of_production date_testing_ads date_testing_posting_ig is_test
        created_at source source_ad_id source_ad_name source_testing_status
    """.split()),
    "content_graphic_register": set("""
        requisition_id asset_date nomenclature product priority creative
        audience_type graphic_type objective due_date status_of_completion
        date_of_completion status_of_testing test_results test_status status
        source_ad_id impressions cac link_1 link_2 link_3 ad_launch_date
        reference_links key_message things_to_note demographic who_is_this_for
        visuals count_9_16 count_4_5 count_16_9 count_1_1 total_count platform
        assignee catchphrase_main catchphrase_sub summary_status summary_result
    """.split()),
    "content_influencer_posts": set("""
        id post_id post_id_short username nomenclature content_type
        deliverable_type deliverable_role collab_type campaign_id post_date
        created_at updated_at workflow_status partnership_status ads_usage_rights
        post_link download_link post_thumbnail source_testing_status source_ad_result
    """.split()),
}

SCOPE_SQL = """
WITH delivery AS (
    SELECT ad_id, SUM(COALESCE(spend, 0)) AS period_spend,
           BOOL_OR(COALESCE(spend, 0) > 0 OR COALESCE(impressions, 0) > 0) AS delivered
    FROM public.insights_daily_by_ad
    WHERE day BETWEEN %(from_date)s AND %(to_date)s
    GROUP BY ad_id
)
SELECT al.ad_id, al.ad_name, al.ad_created_time::date AS ad_created_date,
       COALESCE(d.period_spend, 0) AS period_spend
FROM public.ad_lifecycle al
LEFT JOIN delivery d ON d.ad_id = al.ad_id
WHERE NOT EXISTS (SELECT 1 FROM public.ad_asset_map m WHERE m.ad_id = al.ad_id)
  AND (
      (%(basis)s IN ('delivered', 'either') AND COALESCE(d.delivered, false))
      OR (%(basis)s IN ('created', 'either')
          AND al.ad_created_time::date BETWEEN %(from_date)s AND %(to_date)s)
  )
ORDER BY COALESCE(d.period_spend, 0) DESC, al.ad_id
"""

# Match the denormalized metrics copied by refresh_ad_asset_map.py exactly.
INSERT_MAP_SQL = """
WITH proposed(ad_id, ad_name, asset_id, media) AS (VALUES %s)
INSERT INTO public.ad_asset_map (
    ad_id, ad_name, asset_id, media, match_source, match_rank,
    asset_in_register, name_conflict, ad_created_date, account_name, category,
    spend, impressions, purchases, conv_value, ncp_count, ftewv_count,
    link_clicks, thruplays, three_sec_plays, outbound_clicks, post_engagements
)
SELECT al.ad_id, al.ad_name, p.asset_id, p.media, 'asset_id', 1,
       true, false, al.ad_created_time::date, al.account_name, al.category,
       al.spend, al.impressions, al.purchases, al.conv_value,
       al.ncp_count, al.ftewv_count, al.inline_link_clicks,
       al.thruplays, al.three_sec_video_plays,
       ((al.outbound_clicks->0)->>'value')::numeric, al.post_engagements
FROM public.ad_lifecycle al
JOIN proposed p ON al.ad_id = p.ad_id AND al.ad_name = p.ad_name
WHERE NOT EXISTS (SELECT 1 FROM public.ad_asset_map m WHERE m.ad_id = al.ad_id)
ON CONFLICT (ad_id) DO NOTHING
RETURNING ad_id
"""


@dataclass(frozen=True)
class Asset:
    table: str
    asset_id: str
    pk: str | int
    source: str = "existing_register"
    row: dict[str, Any] | None = None

    @property
    def media(self) -> str:
        return TABLES[self.table][0]


def load_source_rows(paths: list[Path]) -> list[Asset]:
    """Reject malformed snapshots and conflicting canonical identifiers early."""
    assets: list[Asset] = []
    seen_ids: set[tuple[str, str]] = set()
    seen_pks: set[tuple[str, str | int]] = set()
    for path in paths:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict) or set(payload) - TABLES.keys():
            raise ValueError(f"{path}: expected an object keyed by known register tables")
        for table, rows in payload.items():
            if not isinstance(rows, list):
                raise ValueError(f"{path}: {table} must contain a list of row objects")
            _, identity, primary_key = TABLES[table]
            for row in rows:
                if not isinstance(row, dict) or set(row) - SOURCE_COLUMNS[table]:
                    raise ValueError(f"{path}: {table} contains unsupported columns or a non-object row")
                asset_id = row.get(identity)
                if (not isinstance(asset_id, str) or len(asset_id) < 6
                        or asset_id != asset_id.strip() or any(c.isspace() for c in asset_id)):
                    raise ValueError(f"{path}: invalid canonical {identity}")
                pk = row.get(primary_key)
                if table == "content_influencer_posts":
                    if not isinstance(pk, int) or isinstance(pk, bool):
                        raise ValueError(f"{path}: influencer id must be an integer")
                    if row.get("post_id_short") not in (None, asset_id):
                        raise ValueError(f"{path}: influencer post_id/post_id_short disagree")
                if any(isinstance(value, (dict, list)) for value in row.values()):
                    raise ValueError(f"{path}: register values must be scalar")
                key = (table, asset_id.casefold())
                pk_key = (table, pk)
                if key in seen_ids or pk_key in seen_pks:
                    raise ValueError(f"{path}: duplicate canonical identifier or primary key: {asset_id}")
                seen_ids.add(key)
                seen_pks.add(pk_key)
                assets.append(Asset(table, asset_id, pk, str(path), row))
    return assets


def merge_assets(existing: list[Asset], sources: list[Asset]) -> list[Asset]:
    """Preserve existing rows; forbid a source snapshot from changing identity."""
    by_id: dict[tuple[str, str], list[Asset]] = defaultdict(list)
    by_pk = {(a.table, a.pk): a for a in existing}
    for asset in existing:
        by_id[(asset.table, asset.asset_id.casefold())].append(asset)
    additions: list[Asset] = []
    for asset in sources:
        same_pk = by_pk.get((asset.table, asset.pk))
        if same_pk and same_pk.asset_id != asset.asset_id:
            raise ValueError(f"Source identity conflicts with existing primary key: {asset.asset_id}")
        matches = by_id.get((asset.table, asset.asset_id.casefold()), [])
        if matches:
            if len(matches) != 1 or matches[0].pk != asset.pk:
                raise ValueError(f"Source identifier conflicts with existing register: {asset.asset_id}")
            continue
        additions.append(asset)
    return existing + additions


def plan_matches(ads: list[dict[str, Any]], assets: list[Asset], *,
                 from_date: date, to_date: date, basis: str) -> tuple[list[dict], list[dict]]:
    patterns = [(a, re.compile(r"(^|[^0-9A-Za-z])" + re.escape(a.asset_id) + r"([^0-9]|$)", re.I))
                for a in assets if len(a.asset_id) >= 6]
    proposed, unresolved = [], []
    for ad in ads:
        name = ad.get("ad_name") or ""
        candidates = [a for a, pattern in patterns if pattern.search(name)]
        codes = sorted(set(REFERENCED_CODE.findall(name)), key=str.casefold)
        report = {**ad, "from_date": from_date, "to_date": to_date, "basis": basis,
                  "referenced_codes": " | ".join(codes)}
        if len(candidates) == 1:
            asset = candidates[0]
            proposed.append({**report, "asset_id": asset.asset_id, "media": asset.media,
                             "source": asset.source, "reason": "unique_exact_registered_identifier",
                             "_asset": asset})
        else:
            reason = ("ambiguous_registered_identifiers" if candidates
                      else "identifier_absent_from_registers" if codes
                      else "no_recognizable_asset_identifier")
            unresolved.append({**report, "reason": reason,
                               "asset_id": " | ".join(a.asset_id for a in candidates),
                               "media": " | ".join(a.media for a in candidates),
                               "source": " | ".join(a.source for a in candidates)})
    return proposed, unresolved


def read_assets(cur) -> list[Asset]:
    assets = []
    for table, (_, identity, primary_key) in TABLES.items():
        cur.execute(sql.SQL("SELECT {identity} AS asset_id, {pk} AS pk FROM public.{table}").format(
            identity=sql.Identifier(identity), pk=sql.Identifier(primary_key), table=sql.Identifier(table)))
        assets.extend(Asset(table, r["asset_id"] or "", r["pk"]) for r in cur.fetchall())
    return assets


def source_target_columns(cur, sources: list[Asset]) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """Older mirrors need not have optional source reconciliation columns."""
    columns, omitted = {}, {}
    for table in sorted({a.table for a in sources}):
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s", (table,))
        columns[table] = {r["column_name"] for r in cur.fetchall()}
        required = {TABLES[table][1], TABLES[table][2], "mirrored_at"}
        if not required <= columns[table]:
            raise ValueError(f"Target register is missing required columns: {table}")
        skipped = set().union(*(set(a.row or {}) - columns[table] for a in sources if a.table == table))
        if skipped:
            omitted[table] = sorted(skipped)
    return columns, omitted


def insert_proposals(cur, proposals: list[dict], target_columns: dict[str, set[str]]) -> dict[str, int]:
    """Call inside a transaction after locking registers and recomputing the plan."""
    imports: dict[tuple[str, str | int], Asset] = {}
    for proposal in proposals:
        asset = proposal["_asset"]
        if asset.row is not None:
            imports[(asset.table, asset.pk)] = asset
    imported = Counter()
    batches: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for asset in imports.values():
        row = {k: v for k, v in asset.row.items() if k in target_columns[asset.table]}
        row["mirrored_at"] = datetime.now(timezone.utc)
        batches[(asset.table, tuple(sorted(row)))].append(row)
    for (table, columns), rows in batches.items():
        statement = sql.SQL(
            "INSERT INTO public.{table} ({columns}) VALUES %s "
            "ON CONFLICT DO NOTHING RETURNING {pk}"
        ).format(table=sql.Identifier(table),
                 columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
                 pk=sql.Identifier(TABLES[table][2]))
        inserted = execute_values(cur, statement, [tuple(row[c] for c in columns) for row in rows],
                                  page_size=250, fetch=True)
        if len(inserted) != len(rows):
            raise RuntimeError(f"Register changed during apply; rolling back: {table}")
        imported[TABLES[table][0]] += len(inserted)
    if proposals:
        values = [(p["ad_id"], p["ad_name"], p["asset_id"], p["media"]) for p in proposals]
        inserted = execute_values(cur, INSERT_MAP_SQL, values, page_size=250, fetch=True)
        if len(inserted) != len(proposals):
            raise RuntimeError("Ad changed or was mapped during apply; rolling back the complete batch")
    return dict(imported)


REPORT_COLUMNS = ["ad_id", "ad_name", "ad_created_date", "asset_id", "media", "period_spend",
                  "reason", "referenced_codes", "from_date", "to_date", "basis", "source"]


def write_reports(output_dir: Path, proposals: list[dict], unresolved: list[dict], summary: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("proposal.csv", proposals), ("unresolved.csv", unresolved)):
        with (output_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, REPORT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--from-date", required=True, type=date.fromisoformat)
    parser.add_argument("--to-date", required=True, type=date.fromisoformat)
    parser.add_argument("--basis", choices=("delivered", "created", "either"), default="delivered")
    parser.add_argument("--source-rows", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected-matches", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.from_date > args.to_date:
        parser.error("--from-date must not follow --to-date")
    if args.expected_matches is not None and args.expected_matches < 0:
        parser.error("--expected-matches must be non-negative")
    sources = load_source_rows(args.source_rows)
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    dsn = os.environ.get("DATABASE_URL_SYNC")
    if not dsn:
        parser.error("DATABASE_URL_SYNC is required")
    dsn = dsn.replace("postgresql+psycopg2://", "postgresql://", 1)
    conn = psycopg2.connect(dsn, connect_timeout=30)
    imported = {}
    try:
        conn.set_session(readonly=not args.apply, isolation_level="REPEATABLE READ")
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout = '120s'")
                cur.execute("SET LOCAL lock_timeout = '5s'")
                if args.apply:
                    # Ordinary dashboard SELECTs remain permitted. Prevent register
                    # upserts and nightly map rebuilds from racing this short batch.
                    cur.execute("LOCK TABLE public.content_asset_register, "
                                "public.content_graphic_register, public.content_influencer_posts, "
                                "public.ad_asset_map IN SHARE ROW EXCLUSIVE MODE")
                assets = merge_assets(read_assets(cur), sources)
                target_columns, omitted_columns = source_target_columns(cur, sources)
                params = {"from_date": args.from_date, "to_date": args.to_date, "basis": args.basis}
                # Lock only the selected lifecycle rows during apply so an ad
                # rename cannot invalidate the inspected name before insertion.
                cur.execute(SCOPE_SQL + (" FOR SHARE OF al" if args.apply else ""), params)
                ads = list(cur.fetchall())
                proposals, unresolved = plan_matches(ads, assets, **params)
                if args.expected_matches is not None and len(proposals) != args.expected_matches:
                    raise RuntimeError(f"Expected {args.expected_matches} matches; found {len(proposals)}. "
                                       "No changes committed; run a fresh preview.")
                if args.apply:
                    imported = insert_proposals(cur, proposals, target_columns)
    finally:
        conn.close()
    summary = {"status": "applied" if args.apply else "preview_read_only", **params,
               "generated_at": datetime.now(timezone.utc), "missing_ads_in_scope": len(ads),
               "proposed_matches": len(proposals), "inserted_mappings": len(proposals) if args.apply else 0,
               "unresolved_ads": len(unresolved), "imported_register_rows": imported,
               "omitted_source_columns": omitted_columns,
               "proposed_by_media": dict(Counter(p["media"] for p in proposals)),
               "unresolved_by_reason": dict(Counter(p["reason"] for p in unresolved)),
               "proposed_period_spend": sum((Decimal(str(p["period_spend"])) for p in proposals), Decimal(0)),
               "source_files": [str(p) for p in args.source_rows]}
    write_reports(args.output_dir, proposals, unresolved, summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
