#!/usr/bin/env python
"""Exercise every filter on the analytics API, and measure what it costs.

    "the filter is not working for recent dated whereas we have all the
     data updated till the recent date, So check and fix"
    "it is taking too much time to load. check and fix"
    "again there are two search filters"          -- sessions, 2026-09/10

177 filter parameters live across 41 analytics endpoints and nothing has
ever exercised them. This does, one filter at a time against a fixed
baseline -- 177 probes, not 2**177, because the cross product is both
unmeasurable and not where the bugs are.

WHAT IT ASSERTS, per filter
---------------------------
  effect     a filter whose result is identical to the baseline is dead
             (this is what "two search filters" looks like in data)
  narrowing  row counts and totals must not GROW when a filter is added
  scope      a filter must move only what it is supposed to -- the
             landing-page `source` filter moves last_click_* and must
             leave every session and funnel column untouched
  liveness   a 4xx/5xx on a documented parameter value

WHAT IT MEASURES
----------------
Wall time, and the database blocks the request actually touched, read
from pg_stat_database around each call. Buffers over seconds on purpose:
this instance has 256MB of shared_buffers against ~32GB of data, so
wall-clock swings 10-25x with load while block counts stay put.

A filter that touches a million blocks to return fifty rows is the
finding -- that is a predicate the database is applying after the work
instead of before it.

USE
---
    scripts/filter_sweep.py                       # every endpoint
    scripts/filter_sweep.py --only landing-pages  # one
    scripts/filter_sweep.py --save                # write the baseline
    scripts/filter_sweep.py --check               # compare, exit 1 on regress

The response cache keys on the whole parameter set, so every probe is a
distinct key and does real database work. A SECOND run inside the TTL
measures the cache instead -- pass --restart-api to bounce uvicorn first.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8002"
PREFIX = "/admin/analytics"
CONFIG = ROOT / ".claude" / "filter_sweep.json"
BASELINE = ROOT / ".claude" / "filter_sweep_baseline.json"

#: Parameters that select a page rather than filter a population. They
#: change the answer legitimately and are swept for liveness only.
PAGINATION = {"limit", "offset", "page"}

#: A filter that grows the result is usually a bug, but these widen by
#: definition and are exempt from the narrowing rule.
WIDENS_BY_DESIGN = {"include_", "show_", "with_", "all_"}


def api(path: str, params: dict) -> tuple[int, object, float]:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{PREFIX}{path}" + (f"?{q}" if q else "")
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=300) as r:
            body = json.loads(r.read())
            return r.status, body, (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, None, (time.time() - t0) * 1000
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)[:160]}, (time.time() - t0) * 1000


def shape(body: object) -> tuple[int, int | None]:
    """(rows returned, total matched). Endpoints return several shapes."""
    if isinstance(body, list):
        return len(body), len(body)
    if isinstance(body, dict):
        for key in ("rows", "points", "items", "data", "assets"):
            if isinstance(body.get(key), list):
                total = body.get("total")
                return len(body[key]), total if isinstance(total, int) else None
        return 1, body.get("total") if isinstance(body.get("total"), int) else None
    return 0, None


def numeric_leaves(body: object, prefix: str = "") -> dict[str, float]:
    """Every numeric field in a response, flattened, summed over rows.

    Scope checks compare these: a filter that must not touch sessions
    must leave `rows[].ga4_sessions` summing to the same figure.
    """
    out: dict[str, float] = {}
    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for item in node:
                walk(item, path)
        elif isinstance(node, bool) or node is None:
            return
        elif isinstance(node, (int, float)):
            out[path] = out.get(path, 0) + node
    walk(body, prefix)
    return out


class DbCost:
    """Blocks and tuples this database touched, around one request.

    pg_stat_database is cumulative and instance-wide, so this is only
    attributable while nothing else is querying. The sweep says so in
    its header rather than pretending otherwise.
    """

    SQL = ("SELECT blks_read + blks_hit, tup_returned, tup_fetched "
           "FROM pg_stat_database WHERE datname = current_database()")

    def __init__(self) -> None:
        self.ok = False
        try:
            from scripts.dbq import connect
            self._connect = connect
            with self._connect() as c, c.cursor() as cur:
                cur.execute(self.SQL)
                cur.fetchone()
            self.ok = True
        except Exception:
            pass

    def read(self) -> tuple[int, int, int]:
        if not self.ok:
            return (0, 0, 0)
        try:
            with self._connect(statement_timeout="10s") as c, c.cursor() as cur:
                cur.execute(self.SQL)
                return tuple(cur.fetchone())
        except Exception:
            return (0, 0, 0)


def probe_values(param: dict, cfg: dict, window: tuple[str, str]) -> list:
    """Values worth trying for one parameter."""
    name = param["name"]
    if name in cfg.get("values", {}):
        return cfg["values"][name]
    schema = param.get("schema", {}) or {}
    for key in ("enum", "anyOf"):
        if key == "enum" and schema.get("enum"):
            return [v for v in schema["enum"] if v is not None]
        if key == "anyOf":
            for alt in schema.get("anyOf", []):
                if alt.get("enum"):
                    return [v for v in alt["enum"] if v is not None]
    desc = param.get("description") or ""
    # "One of a, b, c" / "Restrict to one section: a, b, c."
    if ":" in desc or "One of" in desc:
        tail = desc.split("One of")[-1].split(":")[-1]
        parts = [p.strip(" .`'\"") for p in tail.split(",")]
        parts = [p for p in parts if p and " " not in p and len(p) < 32]
        if len(parts) >= 2:
            return parts[:12]
    kind = schema.get("type") or ""
    fmt = schema.get("format") or ""
    if fmt == "date" or name.endswith(("_date", "date_from", "date_to")):
        return []  # swept via the window, not probed individually
    if kind == "integer":
        return [1]
    if kind == "boolean":
        return [True]
    if name in ("search", "q"):
        return [cfg.get("search_probe", "a")]
    return []


def sweep_endpoint(path: str, params: list[dict], cfg: dict,
                   window: tuple[str, str], cost: DbCost) -> dict:
    base_params = dict(cfg.get("base", {}))
    names = {p["name"] for p in params}
    if "from_date" in names:
        base_params.setdefault("from_date", window[0])
        base_params.setdefault("to_date", window[1])
    if "date_from" in names:
        base_params.setdefault("date_from", window[0])
        base_params.setdefault("date_to", window[1])
    if "limit" in names:
        base_params.setdefault("limit", cfg.get("limit", 50))

    before = cost.read()
    status, body, ms = api(path, base_params)
    after = cost.read()
    if status != 200:
        return {"path": path, "error": f"baseline returned HTTP {status}", "probes": []}
    b_rows, b_total = shape(body)
    b_leaves = numeric_leaves(body)
    baseline = {
        "rows": b_rows, "total": b_total, "ms": round(ms),
        "blocks": after[0] - before[0], "tuples": after[2] - before[2],
    }

    probes = []
    for p in sorted(params, key=lambda x: x["name"]):
        name = p["name"]
        if name in base_params and name not in PAGINATION:
            continue
        # A probe equal to the parameter's own default reproduces the
        # baseline exactly, which the effect check then reports as a
        # dead filter. `sort=ga4_sessions` is the default sort and read
        # as DEAD on the first run of this sweep -- the filter was fine,
        # the probe was meaningless.
        default = ((p.get("schema") or {}).get("default"))
        for value in probe_values(p, cfg, window):
            if default is not None and value == default:
                continue
            q = dict(base_params)
            q[name] = value
            before = cost.read()
            status, body, ms = api(path, q)
            after = cost.read()
            rec = {
                "param": name, "value": value, "status": status,
                "ms": round(ms), "blocks": after[0] - before[0],
                "tuples": after[2] - before[2],
            }
            if status != 200 or body is None:
                rec["verdict"] = "ERROR"
                probes.append(rec)
                continue
            rows, total = shape(body)
            rec["rows"], rec["total"] = rows, total
            leaves = numeric_leaves(body)
            if leaves == b_leaves and rows == b_rows:
                rec["verdict"] = "DEAD"
            elif (not any(name.startswith(w) for w in WIDENS_BY_DESIGN)
                  and name not in PAGINATION
                  and b_total is not None and total is not None and total > b_total):
                rec["verdict"] = "WIDENS"
            else:
                rec["verdict"] = "ok"
            # Scope: fields this filter must not move.
            frozen = (cfg.get("scope", {}) or {}).get(name, [])
            broke = [f for f in frozen
                     if any(k == f or k.endswith("." + f) for k in set(b_leaves) | set(leaves))
                     and {k: v for k, v in b_leaves.items() if k == f or k.endswith("." + f)}
                       != {k: v for k, v in leaves.items() if k == f or k.endswith("." + f)}]
            if broke:
                rec["verdict"] = "SCOPE"
                rec["moved"] = broke[:6]
            probes.append(rec)
    return {"path": path, "baseline": baseline, "probes": probes}


def discover(only: str | None) -> dict[str, list[dict]]:
    with urllib.request.urlopen(f"{BASE}/openapi.json", timeout=60) as r:
        spec = json.loads(r.read())
    out = {}
    for full, methods in spec.get("paths", {}).items():
        if not full.startswith(PREFIX) or "get" not in methods:
            continue
        path = full[len(PREFIX):]
        if "{" in path:
            continue  # needs a real id; out of scope for a blind sweep
        if only and only.strip("/") not in path.strip("/"):
            continue
        params = [p for p in methods["get"].get("parameters", [])
                  if p.get("in") == "query"]
        if params:
            out[path] = params
    return out


def report(results: list[dict]) -> tuple[str, int]:
    lines, bad = [], 0
    for r in results:
        if r.get("error"):
            lines.append(f"\n{r['path']}  !! {r['error']}")
            bad += 1
            continue
        b = r["baseline"]
        lines.append(
            f"\n{r['path']}   baseline {b['rows']} rows"
            + (f" of {b['total']:,}" if b["total"] is not None else "")
            + f" · {b['ms']}ms · {b['blocks']:,} blocks")
        flagged = [p for p in r["probes"] if p["verdict"] != "ok"]
        for p in r["probes"]:
            mark = {"ok": "  ", "DEAD": "✗ ", "WIDENS": "✗ ",
                    "SCOPE": "✗ ", "ERROR": "✗ "}[p["verdict"]]
            detail = ""
            if p["verdict"] == "DEAD":
                detail = "  no effect — filter does nothing"
            elif p["verdict"] == "WIDENS":
                detail = f"  total grew {b['total']:,} → {p['total']:,}"
            elif p["verdict"] == "SCOPE":
                detail = "  moved " + ", ".join(p.get("moved", []))
            elif p["verdict"] == "ERROR":
                detail = f"  HTTP {p['status']}"
            ratio = (p["blocks"] / b["blocks"]) if b["blocks"] else 0
            heavy = "  ⚠ no cheaper than unfiltered" if (
                p["verdict"] == "ok" and b["blocks"] > 1000
                and p.get("total") is not None and b["total"]
                and p["total"] < b["total"] * 0.5 and ratio > 0.9) else ""
            lines.append(
                f"   {mark}{p['param']}={str(p['value'])[:22]:<22} "
                f"{str(p.get('rows','-')):>5} rows  {p['ms']:>6}ms  "
                f"{p['blocks']:>9,} blocks{detail}{heavy}")
        bad += len(flagged)
    lines.append(f"\n{bad} finding(s)")
    return "\n".join(lines), bad


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(prog="filter_sweep")
    ap.add_argument("--only", help="substring of one endpoint path")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--save", action="store_true", help="write the baseline file")
    ap.add_argument("--check", action="store_true",
                    help="compare against the baseline; exit 1 if worse")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    BASE = args.base
    to_d = date.today()
    window = ((to_d - timedelta(days=args.days - 1)).isoformat(), to_d.isoformat())

    try:
        endpoints = discover(args.only)
    except Exception as exc:  # noqa: BLE001
        print(f"could not read {BASE}/openapi.json — is the API running?\n  {exc}",
              file=sys.stderr)
        return 2

    cfg_all = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    cost = DbCost()
    print(f"FILTER SWEEP · {len(endpoints)} endpoint(s) · window {window[0]}..{window[1]}")
    print("  block counts come from pg_stat_database and are attributable only "
          "while nothing else queries this database." if cost.ok else
          "  (no database connection — timing only, no block counts)")

    results = []
    for path, params in endpoints.items():
        cfg = cfg_all.get(path.strip("/"), {})
        results.append(sweep_endpoint(path, params, cfg, window, cost))

    text, bad = report(results)
    print(text)
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    if args.save:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(results, indent=2, default=str))
        print(f"\nbaseline written to {BASELINE.relative_to(ROOT)}")
    if args.check and BASELINE.exists():
        prev = {r["path"]: r for r in json.loads(BASELINE.read_text())}
        regressions = []
        for r in results:
            old = prev.get(r["path"])
            if not old or r.get("error") or old.get("error"):
                continue
            ob, nb = old["baseline"].get("blocks", 0), r["baseline"].get("blocks", 0)
            if ob and nb > ob * 1.5:
                regressions.append(f"{r['path']} baseline {ob:,} → {nb:,} blocks")
            for p in r["probes"]:
                o = next((q for q in old["probes"]
                          if q["param"] == p["param"] and q["value"] == p["value"]), None)
                if o and o["verdict"] == "ok" and p["verdict"] != "ok":
                    regressions.append(f"{r['path']}?{p['param']}={p['value']} → {p['verdict']}")
                elif o and o.get("blocks") and p["blocks"] > o["blocks"] * 1.5:
                    regressions.append(
                        f"{r['path']}?{p['param']}={p['value']} "
                        f"{o['blocks']:,} → {p['blocks']:,} blocks")
        if regressions:
            print("\nREGRESSIONS vs baseline:")
            for g in regressions:
                print("  ✗ " + g)
            return 1
        print("\nno regression against the baseline")
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
