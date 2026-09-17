"""Read order-level UTM evidence without mixing contradictory visits.

Checkout attributes are the primary source for this store. Their ``full_url``
is captured beside the UTM fields, and can complete them when shared values
agree. Shopify's last visit is a fallback; first visit is deliberately excluded
because this extractor feeds last-click reporting. Values remain evidence, not
proof that the order belongs to a Meta ad: the attribution matcher decides that.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlsplit


UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


@dataclass(frozen=True)
class OrderUTM:
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    sources: tuple[str, ...] = ()
    # Diagnostics contain field/source names only, never URLs or customer data.
    conflicts: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str | None]:
        return {key: getattr(self, key) for key in UTM_FIELDS}


def _value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _attributes(value: object) -> tuple[dict[str, str], set[str]]:
    """Keep unique nonblank attributes; repeated contradictory keys are unusable."""
    values: dict[str, set[str]] = {}
    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            key, val = _value(item.get("key")), _value(item.get("value"))
            if key and val and key.lower() in (*UTM_FIELDS, "full_url"):
                values.setdefault(key.lower(), set()).add(val)
    ambiguous = {key for key, vals in values.items() if len(vals) > 1}
    return {key: next(iter(vals)) for key, vals in values.items() if len(vals) == 1}, ambiguous


def _url_parameters(value: object, source: str) -> tuple[dict[str, str], list[str]]:
    url = _value(value)
    if not url:
        return {}, []
    if len(url) > 65_536:
        return {}, [f"{source}:invalid_url"]
    try:
        # A URL is form encoded: '+' means space and '%2B' means literal plus.
        # Already-extracted checkout fields are NOT passed through this decoder.
        pairs = parse_qsl(urlsplit(url).query, max_num_fields=256)
    except ValueError:
        return {}, [f"{source}:invalid_url"]
    values: dict[str, set[str]] = {}
    for key, val in pairs:
        key, cleaned = key.strip().lower(), _value(val)
        if key in UTM_FIELDS and cleaned:
            values.setdefault(key, set()).add(cleaned)
    ambiguous = {key for key, vals in values.items() if len(vals) > 1}
    # A conflicting parameter makes this URL an unreliable tuple. Do not fill
    # other fields from it while silently discarding its contradictory identity.
    if ambiguous:
        return {}, [f"{source}:duplicate:{key}" for key in sorted(ambiguous)]
    return {key: next(iter(vals)) for key, vals in values.items()}, []


def extract_order_utm(order: Mapping[str, object]) -> OrderUTM:
    """Extract a checkout/last-visit tuple and explain rejected source merges.

    ``order`` contains the five raw ``utm_*`` columns, ``custom_attributes`` and
    ``customer_journey`` from ``shopify_orders``. Blank strings permit fallback.
    Nonempty source tuples can be combined only when at least one shared field
    agrees and none contradict. Complete existing values always remain primary.
    """
    attrs, ambiguous = _attributes(order.get("custom_attributes"))
    conflicts = [f"checkout:duplicate:{key}" for key in sorted(ambiguous)]
    values: dict[str, str] = {}
    for key in UTM_FIELDS:
        column, attribute = _value(order.get(key)), attrs.get(key)
        if key in ambiguous:
            continue
        if column and attribute and column != attribute:
            conflicts.append(f"checkout:column_conflict:{key}")
        if chosen := column or attribute:
            values[key] = chosen
    sources = ["checkout"] if values else []

    def merge_into(target: dict[str, str], candidate: dict[str, str], source: str) -> bool:
        if not candidate:
            return False
        if not target:
            target.update(candidate)
            return True
        shared = target.keys() & candidate.keys()
        # Percent escapes in already stored UTM fields can be compared to a URL
        # decoder's result without interpreting literal '+' as a space. Do not
        # rewrite stored fields: the matcher retains the original evidence.
        mismatches = [
            key for key in sorted(shared)
            if target[key] != candidate[key]
            and unquote(target[key]) != candidate[key]
        ]
        if mismatches:
            conflicts.extend(f"{source}:conflicting:{key}" for key in mismatches)
            return False
        missing = candidate.keys() - target.keys()
        if not missing:
            return False
        if not shared:
            conflicts.append(f"{source}:unlinked")
            return False
        for key in missing:
            target[key] = candidate[key]
        return True

    url_values, url_conflicts = _url_parameters(attrs.get("full_url"), "checkout_url")
    conflicts.extend(url_conflicts)
    if merge_into(values, url_values, "checkout_url"):
        sources.append("checkout_url")

    journey = order.get("customer_journey")
    last_visit = journey.get("lastVisit") if isinstance(journey, Mapping) else None
    if isinstance(last_visit, Mapping):
        parameters = last_visit.get("utmParameters")
        last_values: dict[str, str] = {}
        last_sources: list[str] = []
        if isinstance(parameters, Mapping):
            last_values = {
                key: cleaned for key in UTM_FIELDS
                if (cleaned := _value(parameters.get(key.removeprefix("utm_"))))
            }
            if last_values:
                last_sources.append("last_visit")
        landing_values, landing_conflicts = _url_parameters(
            last_visit.get("landingPage"), "last_visit_url",
        )
        conflicts.extend(landing_conflicts)
        # Validate this visit's URL against its own structured tuple first. A
        # URL must not bypass a conflicting structured visit merely because it
        # happens to agree with the checkout tuple.
        if merge_into(last_values, landing_values, "last_visit_url"):
            last_sources.append("last_visit_url")
        visit_source = "last_visit" if "last_visit" in last_sources else "last_visit_url"
        if merge_into(values, last_values, visit_source):
            sources.extend(last_sources)

    return OrderUTM(**values, sources=tuple(sources), conflicts=tuple(conflicts))
