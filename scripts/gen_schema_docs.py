"""Write one markdown file per public table, for the assistant to read.

WHY THIS EXISTS
---------------
`get_table_info` already returns live column types, so a file that only
repeats `information_schema` would be worth nothing. What the database
cannot tell anyone is the part that matters:

  * **There are ZERO foreign keys in this database.** Not one. So no
    tool can derive how to join anything -- the relationships have to be
    written down or guessed at, and a chatbot guessing joins on a 15GB
    schema produces confident nonsense.
  * Only 8 of 88 relations carry a comment.
  * Which of several near-identical tables is the live one
    (`insights_daily_by_ad` vs `insights_daily_by_ad_old`), and which
    columns inside a table are trustworthy.

So each file has two halves. Everything above the NOTES marker is
generated and is overwritten on every run. Everything below it is
hand-written and is PRESERVED -- that is where the meaning lives.

Joins are *inferred* from shared column names and are labelled as
inferred. They are a starting point for a human to confirm, never a
claim that the join is valid.

Usage:
    ./.venv/bin/python scripts/gen_schema_docs.py              # all tables
    ./.venv/bin/python scripts/gen_schema_docs.py --only shopify_orders
    ./.venv/bin/python scripts/gen_schema_docs.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

OUT_DIR = ROOT / "docs" / "schema"

#: Everything after this line in an existing file is kept verbatim.
#: Without it the semantics would be destroyed by the next regeneration,
#: which would make anyone reasonably stop writing them.
NOTES_MARKER = "<!-- NOTES: hand-written below this line survives regeneration -->"

HEADER_WARNING = (
    "<!-- GENERATED above the NOTES marker. Edits there are lost.\n"
    "     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->"
)

#: A column name shared by several tables is a join candidate only if it
#: looks like a key. `name`, `status` and `created_at` are shared by
#: everything and join nothing.
JOINABLE = re.compile(r"(_id|_key|^id$|^day$|^date$|_date$|^sku$|_sku$|^order_name$)", re.I)

#: Shared by so many tables that listing every partner is noise rather
#: than guidance.
TOO_COMMON = {"day", "date", "created_at", "updated_at", "id"}

RELATIONS_SQL = """
SELECT c.relname AS name,
       CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view'
            WHEN 'p' THEN 'partitioned table' ELSE 'table' END AS kind,
       CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS est_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
       pg_total_relation_size(c.oid) AS size_bytes,
       obj_description(c.oid) AS comment
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m')
 ORDER BY c.relname
"""

COLUMNS_SQL = """
SELECT c.relname AS table_name, a.attname AS name,
       format_type(a.atttypid, a.atttypmod) AS type,
       NOT a.attnotnull AS nullable,
       pg_get_expr(d.adbin, d.adrelid) AS default_expr,
       col_description(c.oid, a.attnum) AS comment
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
 WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m')
   AND a.attnum > 0 AND NOT a.attisdropped
 ORDER BY c.relname, a.attnum
"""

INDEXES_SQL = """
SELECT c.relname AS table_name, i.relname AS index_name,
       pg_get_indexdef(x.indexrelid) AS definition,
       x.indisprimary AS is_primary, x.indisunique AS is_unique
  FROM pg_index x
  JOIN pg_class c ON c.oid = x.indrelid
  JOIN pg_class i ON i.oid = x.indexrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
 ORDER BY c.relname, i.relname
"""


def fetch_all(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "-", name.lower())


def md_escape(text: str | None) -> str:
    """A pipe in a comment would split the markdown table cell."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def build_join_index(columns: list[dict]) -> dict[str, list[str]]:
    """column name -> the tables carrying it, for joinable-looking names."""
    by_col: dict[str, list[str]] = {}
    for c in columns:
        n = c["name"].lower()
        if n in TOO_COMMON or not JOINABLE.search(n):
            continue
        by_col.setdefault(n, []).append(c["table_name"])
    # A name in only one table joins nothing.
    return {k: v for k, v in by_col.items() if len(v) > 1}


def existing_notes(path: Path) -> str | None:
    """The hand-written half, if this file has been written before."""
    if not path.exists():
        return None
    text = path.read_text()
    idx = text.find(NOTES_MARKER)
    return None if idx < 0 else text[idx + len(NOTES_MARKER):].lstrip("\n")


def render(rel: dict, cols: list[dict], idxs: list[dict],
           joins: dict[str, list[str]], notes: str | None) -> str:
    name = rel["name"]
    out: list[str] = [f"# `{name}`", "", HEADER_WARNING, ""]

    rows = "unknown" if rel["est_rows"] is None else f"~{rel['est_rows']:,}"
    out.append(f"**{rel['kind']}** · {rows} rows (planner estimate) · {rel['size']}")
    if rel["comment"]:
        out += ["", f"> {md_escape(rel['comment'])}"]
    out.append("")

    out += ["## Columns", "",
            "| # | column | type | null | default |",
            "|---|---|---|---|---|"]
    for i, c in enumerate(cols, 1):
        default = md_escape(c["default_expr"])
        default = f"`{default}`" if default else ""
        line = (f"| {i} | `{c['name']}` | `{c['type']}` | "
                f"{'yes' if c['nullable'] else 'no'} | {default} |")
        out.append(line)
        if c["comment"]:
            out.append(f"| | | | | {md_escape(c['comment'])} |")
    out.append("")

    pk = [i for i in idxs if i["is_primary"]]
    uniq = [i for i in idxs if i["is_unique"] and not i["is_primary"]]
    other = [i for i in idxs if not i["is_unique"]]
    out += ["## Keys and indexes", ""]
    if pk:
        out.append(f"- **Primary key** — `{pk[0]['index_name']}`")
        out.append(f"  - `{pk[0]['definition']}`")
    else:
        out.append("- **No primary key.**")
    for i in uniq:
        out.append(f"- Unique — `{i['index_name']}`: `{i['definition']}`")
    for i in other:
        out.append(f"- Index — `{i['index_name']}`: `{i['definition']}`")
    if not (pk or uniq or other):
        out.append("- No indexes. Any filter on this table is a sequential scan.")
    out.append("")

    colnames = {c["name"].lower() for c in cols}
    candidates = {k: [t for t in v if t != name]
                  for k, v in joins.items() if k in colnames}
    candidates = {k: v for k, v in candidates.items() if v}
    out += ["## Possible joins", ""]
    if candidates:
        out += ["This database defines **no foreign keys**, so the following are",
                "*inferred from shared column names only*. Confirm the grain before",
                "trusting one — a shared name does not prove a valid join.", ""]
        for col in sorted(candidates):
            partners = sorted(candidates[col])
            shown = ", ".join(f"`{p}`" for p in partners[:12])
            more = f" … and {len(partners) - 12} more" if len(partners) > 12 else ""
            out.append(f"- `{col}` → {shown}{more}")
    else:
        out.append("No shared key-like column names with other tables.")
    out.append("")

    out += [NOTES_MARKER, ""]
    if notes:
        out.append(notes.rstrip() + "\n")
    else:
        out += ["## What a row is", "",
                "_Not yet written._ One row = ?", "",
                "## Use it for", "", "_Not yet written._", "",
                "## Traps", "", "_Not yet written._", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", action="append", help="Table name; repeatable.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    with connect() as conn, conn.cursor() as cur:
        rels = fetch_all(cur, RELATIONS_SQL)
        cols = fetch_all(cur, COLUMNS_SQL)
        idxs = fetch_all(cur, INDEXES_SQL)

    joins = build_join_index(cols)
    by_table_cols: dict[str, list[dict]] = {}
    for c in cols:
        by_table_cols.setdefault(c["table_name"], []).append(c)
    by_table_idx: dict[str, list[dict]] = {}
    for i in idxs:
        by_table_idx.setdefault(i["table_name"], []).append(i)

    wanted = set(args.only) if args.only else None
    targets = [r for r in rels if not wanted or r["name"] in wanted]
    if wanted:
        missing = wanted - {r["name"] for r in targets}
        if missing:
            raise SystemExit(f"No such table(s): {', '.join(sorted(missing))}")

    args.out.mkdir(parents=True, exist_ok=True)
    written = kept = 0
    for rel in targets:
        path = args.out / f"{slug(rel['name'])}.md"
        notes = existing_notes(path)
        if notes:
            kept += 1
        body = render(rel, by_table_cols.get(rel["name"], []),
                      by_table_idx.get(rel["name"], []), joins, notes)
        if not args.dry_run:
            path.write_text(body)
        written += 1

    print(f"{'would write' if args.dry_run else 'wrote'} {written} file(s) to "
          f"{args.out.relative_to(ROOT)}")
    print(f"  hand-written notes preserved in {kept}")
    print(f"  {len(joins)} shared key-like column names across the schema")

    if not args.only:
        write_index(rels, by_table_cols, args.out, args.dry_run)
    return 0


def write_index(rels, by_table_cols, out: Path, dry: bool) -> None:
    """One page listing every relation, so the assistant can find a table
    without loading 88 files."""
    path = out / "README.md"
    notes = existing_notes(path)
    lines = ["# Database schema", "", HEADER_WARNING, "",
             f"{len(rels)} relations in `public`. One file each, generated by",
             "`scripts/gen_schema_docs.py` from the live database.", "",
             "**This database defines no foreign keys.** Joins listed in the",
             "per-table files are inferred from column names and must be",
             "confirmed, not assumed.", "",
             "| table | kind | rows (est.) | size | columns |",
             "|---|---|---|---|---|"]
    for r in sorted(rels, key=lambda x: -(x["size_bytes"] or 0)):
        rows = "?" if r["est_rows"] is None else f"{r['est_rows']:,}"
        n = len(by_table_cols.get(r["name"], []))
        lines.append(f"| [`{r['name']}`]({slug(r['name'])}.md) | {r['kind']} | "
                     f"{rows} | {r['size']} | {n} |")
    lines += ["", NOTES_MARKER, ""]
    lines.append(notes.rstrip() + "\n" if notes else "")
    if not dry:
        path.write_text("\n".join(lines))
    print(f"  index: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
