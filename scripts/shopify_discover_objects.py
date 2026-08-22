"""One-time discovery: introspect Shopify's live GraphQL schema (ground
truth, not docs -- shopify.dev's query reference pages are client-rendered
and don't expose the full field list to static scraping) to find EVERY
QueryRoot field that's genuinely top-level-fetchable (no dependency on an
ID/value obtained from another query first), then introspect each
candidate's return type to auto-build a safe query (every directly
available scalar/enum field -- nested object/list sub-fields are skipped
since they'd need their own recursive field-selection logic).

Writes scripts/shopify_object_manifest.json: one entry per fetchable
object type, either a paginated connection or a singleton, with a ready-
to-use GraphQL query string. scripts/ingest_shopify.py's --all-objects
mode reads this manifest instead of hardcoding a handful of queries.

This only needs to be re-run if Shopify's schema changes meaningfully
(e.g. after an API version bump) -- the manifest is checked in like any
other generated registry artifact.

Usage:
    python3 scripts/shopify_discover_objects.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print("Missing dependency: pip install httpx", file=sys.stderr)
    raise SystemExit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shopify_client import DEFAULT_API_VERSION, ShopifyStore, discover_stores, graphql_request  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "scripts" / "shopify_object_manifest.json"

#: A REQUIRED arg (type.kind == NON_NULL at the top level) is only
#: acceptable if it's pure pagination -- anything else (even a
#: filter-looking name like `ownerType` or `type`) means the field can't
#: actually be called without a value this script has no way to supply,
#: so it's excluded. Discovered live: metafieldDefinitions.ownerType,
#: metaobjects.type, and metaobjectDefinitionByType.type all looked like
#: safe filter args by name but are REQUIRED -- name-based allowlisting
#: alone was wrong; nullability (from introspection) is the real signal.
SAFE_REQUIRED_ARGS = {"first", "after", "last", "before"}

QUERYROOT_INTROSPECTION = """
{
  __type(name: "QueryRoot") {
    fields {
      name
      args { name type { kind ofType { kind } } }
      type {
        kind
        name
        ofType { kind name }
      }
    }
  }
}
"""

#: GraphQL type refs can nest NON_NULL/LIST wrappers several deep before
#: reaching the actual named type (e.g. `nodes: [Product!]!` is
#: NON_NULL(LIST(NON_NULL(Product))) -- 3 wrapper levels). This fragment
#: unwraps 5 levels, comfortably more than Shopify's schema ever nests.
TYPE_REF_FRAGMENT = """
fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType { kind name }
        }
      }
    }
  }
}
"""

TYPE_FIELDS_INTROSPECTION = (
    TYPE_REF_FRAGMENT
    + """
query TypeFields($typeName: String!) {
  __type(name: $typeName) {
    kind
    fields {
      name
      args { name type { kind } }
      type { ...TypeRef }
    }
  }
}
"""
)


def _has_unsatisfiable_required_arg(field: dict[str, Any]) -> bool:
    """True if `field` has a required (NON_NULL) argument this script
    can't supply -- e.g. Product.inCollection(id: ID!). A field can look
    like a plain scalar (Boolean, String, ...) and still be unselectable
    without an argument; type kind alone doesn't catch this."""
    for arg in field.get("args", []):
        if arg["type"]["kind"] == "NON_NULL" and arg["name"] not in SAFE_REQUIRED_ARGS:
            return True
    return False


def _unwrap_type(type_obj: dict[str, Any]) -> tuple[str, str]:
    """Return (kind, name) after stripping NON_NULL/LIST wrappers."""
    kind = type_obj.get("kind")
    name = type_obj.get("name")
    of_type = type_obj.get("ofType")
    if kind in ("NON_NULL", "LIST") and of_type:
        return _unwrap_type(of_type)
    return kind, name


async def _get_connection_node_type(client: httpx.AsyncClient, store: ShopifyStore, connection_type_name: str) -> str | None:
    """A Connection type has an `edges { node }` or `nodes` field -- find
    the underlying node type name by introspecting the connection's own
    fields, then the Edge type's `node` field."""
    data = await graphql_request(
        client, store, TYPE_FIELDS_INTROSPECTION, {"typeName": connection_type_name}
    )
    type_info = data.get("__type")
    if not type_info:
        return None
    for f in type_info["fields"]:
        if f["name"] == "nodes":
            kind, name = _unwrap_type(f["type"])
            return name
    return None


async def _get_scalar_fields(client: httpx.AsyncClient, store: ShopifyStore, type_name: str) -> list[str]:
    """Every field on `type_name` whose type is a bare SCALAR or ENUM
    (after unwrapping NON_NULL/LIST) AND has no unsatisfiable required
    argument -- i.e. genuinely selectable with zero further input.
    Always includes `id` first if present."""
    data = await graphql_request(client, store, TYPE_FIELDS_INTROSPECTION, {"typeName": type_name})
    type_info = data.get("__type")
    if not type_info or not type_info.get("fields"):
        return []
    scalar_fields = []
    has_id = False
    for f in type_info["fields"]:
        if _has_unsatisfiable_required_arg(f):
            continue
        kind, name = _unwrap_type(f["type"])
        if f["name"] == "id":
            has_id = True
            continue
        if kind in ("SCALAR", "ENUM"):
            scalar_fields.append(f["name"])
    fields = (["id"] if has_id else []) + sorted(scalar_fields)
    return fields


def _is_safe_candidate(field: dict[str, Any]) -> bool:
    return not _has_unsatisfiable_required_arg(field)


async def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    if load_dotenv is not None:
        load_dotenv()

    stores_by_key = discover_stores()
    if not stores_by_key:
        print("No Shopify store configured (need SHOP_DOMAIN + ADMIN_ACCESS_TOKEN or SHOPIFY_STORE_1_*).", file=sys.stderr)
        return 1
    store = stores_by_key[sorted(stores_by_key, key=int)[0]]

    t0 = time.monotonic()
    async with httpx.AsyncClient() as client:
        data = await graphql_request(client, store, QUERYROOT_INTROSPECTION)
        all_fields = data["__type"]["fields"]
        print(f"QueryRoot fields discovered: {len(all_fields)}")

        candidates = []
        for f in all_fields:
            if not _is_safe_candidate(f):
                continue
            kind, type_name = _unwrap_type(f["type"])
            if not type_name:
                continue
            candidates.append({"name": f["name"], "kind": kind, "type_name": type_name})

        print(f"Top-level-enumerable candidates (no foreign-ID dependency): {len(candidates)}")

        manifest: dict[str, Any] = {}
        for i, c in enumerate(candidates, start=1):
            root_name, kind, type_name = c["name"], c["kind"], c["type_name"]
            is_connection = type_name.endswith("Connection")
            try:
                if is_connection:
                    node_type = await _get_connection_node_type(client, store, type_name)
                    if not node_type:
                        print(f"  [{i}/{len(candidates)}] {root_name}: SKIP -- couldn't resolve node type for {type_name}")
                        continue
                    scalar_fields = await _get_scalar_fields(client, store, node_type)
                    if not scalar_fields:
                        print(f"  [{i}/{len(candidates)}] {root_name}: SKIP -- {node_type} has no plain scalar/enum fields")
                        continue
                    query = (
                        f"query {root_name.capitalize()}($first: Int!, $after: String) {{\n"
                        f"  {root_name}(first: $first, after: $after) {{\n"
                        f"    edges {{ node {{ {' '.join(scalar_fields)} }} cursor }}\n"
                        f"    pageInfo {{ hasNextPage endCursor }}\n"
                        f"  }}\n}}"
                    )
                    manifest[root_name] = {
                        "kind": "connection", "node_type": node_type,
                        "path": [root_name], "query": query, "fields": scalar_fields,
                    }
                    print(f"  [{i}/{len(candidates)}] {root_name}: OK ({node_type}, {len(scalar_fields)} fields)")
                else:
                    # SINGLE, zero-required-arg singleton (e.g. `shop`).
                    scalar_fields = await _get_scalar_fields(client, store, type_name)
                    if not scalar_fields:
                        print(f"  [{i}/{len(candidates)}] {root_name}: SKIP -- {type_name} has no plain scalar/enum fields")
                        continue
                    query = f"query {root_name.capitalize()} {{\n  {root_name} {{ {' '.join(scalar_fields)} }}\n}}"
                    manifest[root_name] = {
                        "kind": "singleton", "node_type": type_name,
                        "path": [root_name], "query": query, "fields": scalar_fields,
                    }
                    print(f"  [{i}/{len(candidates)}] {root_name}: OK ({type_name}, {len(scalar_fields)} fields)")
            except RuntimeError as exc:
                print(f"  [{i}/{len(candidates)}] {root_name}: FAILED -- {str(exc)[:150]}")
                continue

    elapsed = time.monotonic() - t0
    print(f"\nManifest built: {len(manifest)} fetchable object types in {elapsed:.1f}s")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"Written to {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
