"""Which bucket a silver-coin order belongs in, by the dispatch desk's rules.

WHY THIS IS ITS OWN MODULE
--------------------------
These are judgement calls -- what makes an address undeliverable, what
makes a customer a return-to-origin risk -- and they are the part most
likely to be argued with and changed. Keeping them out of the ingest
means they can be read, tested and corrected without touching the
pipeline that writes forty other columns.

The rules come from the Shagun dispatch desk's annexure. They are
reproduced here so the tracker and the desk agree; where the desk
changes, this has to change with it, and a disagreement between the
two is a bug in one of them rather than two valid opinions.

EXACTLY ONE BUCKET
------------------
Every counted coin order lands in one of these, in this order:

    shipped       already fulfilled in Shopify
    coin_only     the coin and nothing else, not yet shipped -- held
    address_bad   the address cannot be delivered to as written -- held
    call_list     COD that needs a confirmation call before dispatch
    ship_now      cleared

The order matters. A shipped order has already gone, so nothing later
can hold it. A coin-only order is held whatever else is true of it. A
bad address holds an order of any payment type, which is why it sits
above the COD rules rather than inside them.
"""
from __future__ import annotations

import re

# --- addresses --------------------------------------------------------

#: A house, flat or plot number. Any digit in the address line counts:
#: "15 Periyapatti Road", "B-12", "Flat 4", "#402" all pass, and the
#: spec's failing examples ("Near Jama Masjid", "Om krishi Kendra
#: Rampur") contain none.
_HAS_NUMBER = re.compile(r"\d")

#: A 10+ letter run with no vowel: keyboard mashing, not a word.
_GIBBERISH = re.compile(r"[bcdfghjklmnpqrstvwxyz]{10,}", re.I)

#: Rural addresses are written Village / Post / Tehsil / District and
#: legitimately carry no house number. They are deliverable, so the
#: "no number" checks are skipped for them.
_RURAL = ("village", "vill ", "vill.", "post ", "po ", "tehsil", "taluka",
          "district", "dist ", "dist.", "gram", "panchayat")

#: A parcel to a workplace is normal and deliverable. These are NOT
#: held; they carry a flag so the team knows it is a business.
_SHOP = ("store", "shop", "kirana", "medical", "bank", "office", "school",
         "hotel", "college office", "factory", "showroom", "clinic",
         "hospital", "restaurant", "cafe", "petrol")

_HOSTEL = ("hostel", "pg ", " pg", "paying guest", "boys hostel", "girls hostel")

#: Left behind by blank form fields. Stripped before anything is
#: judged, so they neither pass nor fail a check on their own.
_FILLER = ("null", "none", "n/a", "na", "-", ".")

#: A fake or test entry rather than a real place.
_JUNK = ("test", "xyz", "abc", "asdf", "qwerty", "asdfgh")


def _clean(address: str) -> str:
    words = [w for w in re.split(r"[\s,]+", (address or "").strip())
             if w and w.lower().strip(".") not in _FILLER]
    return " ".join(words)


#: Each address check, in the order the desk lists them. An address can
#: fail SEVERAL, and the desk shows them all -- "Too short (<20 chars),
#: no house no.; Fewer than 3 distinct words" -- so this returns every
#: issue rather than stopping at the first.
ISSUE_LABEL = {
    "landmark": "Landmark/area only, no house no.",
    "short": "Too short (<20 chars), no house no.",
    "fewwords": "Fewer than 3 distinct words",
    "repeated": "One phrase repeated, no house no.",
    "gibberish": "Gibberish word",
    "hostel": "Hostel/PG, no room no.",
    "junk": "Junk word",
    "empty": "No address",
}

#: The sub-filters the desk offers above the Address issues table, and
#: which raw issues roll into each.
ISSUE_GROUP = {
    "landmark": "landmark", "short": "short", "fewwords": "repeated",
    "repeated": "repeated", "gibberish": "junk", "hostel": "hostel",
    "junk": "junk", "empty": "short",
}
GROUP_LABEL = {
    "landmark": "Landmark only", "hostel": "Hostel / PG, no room no.",
    "junk": "Junk word", "short": "Too short",
    "repeated": "Repeated / too few words",
}


def address_issues(address1: str | None, address2: str | None) -> tuple[list[str], str | None]:
    """(issue keys, flag). Issues non-empty means the address is Bad.

    A flag is deliverable but worth knowing -- a shop or a hostel room
    -- and never holds the order.

    Lines 1 and 2 are read together, because people split one address
    across them arbitrarily. City and pincode are separate fields and
    are not judged here.
    """
    raw = _clean(" ".join(filter(None, (address1, address2))))
    if not raw:
        return ["empty"], None
    low = raw.lower()
    words = raw.split()
    numbered = bool(_HAS_NUMBER.search(raw))
    rural = any(k in low for k in _RURAL)
    shoppy = any(k in low for k in _SHOP)
    hostel = any(k in low for k in _HOSTEL)

    issues: list[str] = []
    # Junk only counts on an address with NO house number. A full
    # street address was being held because a nearby landmark's name
    # happens to contain one of these words -- a real place, a real
    # parcel, held for nothing. A genuine test entry carries no house
    # number, so requiring that loses none of them.
    if not numbered and any(re.search(rf"\b{re.escape(j)}\b", low) for j in _JUNK):
        issues.append("junk")
    if _GIBBERISH.search(raw):
        issues.append("gibberish")
    if hostel and not numbered:
        issues.append("hostel")
    if len({w.lower() for w in words}) < 3:
        issues.append("fewwords")

    # The same phrase typed twice and nothing else. Retyping a locality
    # INSIDE a fuller address is normal and is not caught, because the
    # halves have to be the whole string.
    half = len(words) // 2
    if half and not numbered and [w.lower() for w in words[:half]] == \
            [w.lower() for w in words[half:half * 2]] and len(words) <= half * 2 + 1:
        issues.append("repeated")

    if not numbered and not rural and not shoppy:
        # "Too short" and "landmark only" are mutually exclusive, and
        # the desk treats them so: its own rows file "Near Jama Masjid"
        # and "Bamhori Udaipura" under Too short alone, never also
        # under Landmark. Below 20 characters the address is simply too
        # short to judge as a landmark, so only the stronger of the two
        # fires and the sub-filter counts stay meaningful.
        if len(raw) < 20:
            issues.append("short")
        elif len(words) < 5:
            issues.append("landmark")

    if issues:
        return issues, None
    # Deliverable, but the team should know where the parcel is going.
    if shoppy and not numbered:
        return [], "Shop/office address"
    if hostel:
        return [], "Hostel/PG address"
    return [], None


def is_high_rto(prior_shipped: int, prior_rto: int) -> bool:
    """Return-to-origin is half or more of what shipped, or 3+ outright.

    Only RTO counts against a customer. A normal return or exchange
    after delivery does not: the parcel arrived, which is the thing
    this is trying to predict.
    """
    if prior_rto >= 3:
        return True
    return prior_shipped > 0 and prior_rto * 2 >= prior_shipped


#: Every reason a COD order can need a call. An order can trip several
#: and the desk shows them all as separate pills, so these accumulate.
CALL_LABEL = {
    "new": "New customer COD",
    "untagged": "Untagged gateway COD",
    "dup": "Duplicate same-day COD",
    "rto": "High RTO",
    "nodelivery": "No prior delivery",
    "fake": "Fake Order tag",
}


def call_reasons(order: dict, hist: dict | None, dup_cod: bool) -> list[str]:
    """Every reason this COD order needs a confirmation call."""
    out: list[str] = []
    returning = bool(order.get("is_returning"))
    if order.get("risk_tag") is None:
        out.append("untagged")
    if not returning:
        out.append("new")
        # The tag holds an order ONLY when it is COD from a new
        # customer. Already paid, or known to us, and it is ignored.
        if order.get("fake_order"):
            out.append("fake")
    else:
        if hist is None or hist.get("delivered", 0) == 0:
            out.append("nodelivery")
        if is_high_rto((hist or {}).get("shipped", 0), (hist or {}).get("rto", 0)):
            out.append("rto")
    if dup_cod:
        out.append("dup")
    return out


def is_watchlisted(order: dict, repeat_buyer: bool) -> str | None:
    """Why this order is on the watchlist, or None.

    An OVERLAY, not a bucket: a watchlisted order still sits in Ship
    now or the Call list and still has to be dispatched or called.
    """
    if order.get("fake_order") and order.get("payment") == "COD" \
            and not order.get("is_returning"):
        return "Fake Order tag, new customer COD"
    if repeat_buyer:
        return "Repeat buyer"
    return None


def classify(order: dict, hist: dict | None, dup_cod: bool) -> tuple[str, list[str]]:
    """(bucket, reason keys). See the module docstring for the order."""
    # Not a coin order at all -- it is here because it LOOKS eligible
    # and went out without one. Outside the five-way partition.
    if order.get("coins", 1) == 0:
        return "bundle_no_coin", []

    if (order.get("fulfillment") or "").lower() == "fulfilled":
        return "shipped", []

    # Held whatever the payment type, and listed nowhere else.
    if order.get("units", 0) == 0:
        return "coin_only", []

    if order.get("address_issues"):
        return "address_bad", list(order["address_issues"])

    if (order.get("payment") or "") != "COD":
        # Paid something, so refusal risk is low. The Fake Order tag is
        # deliberately ignored here: the money is already in.
        return "ship_now", []

    reasons = call_reasons(order, hist, dup_cod)
    return ("call_list", reasons) if reasons else ("ship_now", [])
