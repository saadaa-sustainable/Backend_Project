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


def address_verdict(address1: str | None, address2: str | None) -> tuple[str, str | None]:
    """(verdict, reason). Verdict is "ok", "flag" or "bad".

    "flag" means deliverable but worth knowing about -- a shop or a
    hostel room -- and does NOT hold the order. Only "bad" holds it.

    Lines 1 and 2 are read together, because people split a single
    address across them arbitrarily. City and pincode are separate
    fields and are not judged here.
    """
    raw = _clean(" ".join(filter(None, (address1, address2))))
    if not raw:
        return "bad", "no address"
    low = raw.lower()
    words = raw.split()
    numbered = bool(_HAS_NUMBER.search(raw))
    rural = any(k in low for k in _RURAL)
    shoppy = any(k in low for k in _SHOP)

    # Junk and gibberish are decided first: they are wrong whatever
    # else the address contains.
    if any(re.search(rf"\b{re.escape(j)}\b", low) for j in _JUNK):
        return "bad", "junk word"
    if _GIBBERISH.search(raw):
        return "bad", "gibberish"

    if any(k in low for k in _HOSTEL) and not numbered:
        return "bad", "hostel/PG, no room number"

    if len({w.lower() for w in words}) < 3:
        return "bad", "fewer than 3 different words"

    # The same phrase typed twice with nothing else. Retyping a
    # locality INSIDE a fuller address is normal and is not caught,
    # because the halves must be the whole string.
    half = len(words) // 2
    if half and not numbered and [w.lower() for w in words[:half]] == \
            [w.lower() for w in words[half:half * 2]] and len(words) <= half * 2 + 1:
        return "bad", "one phrase repeated"

    # A workplace with no house number is still deliverable -- people
    # order to their office. Flag, never hold.
    if shoppy and not numbered:
        return "flag", "shop/office address"

    if not numbered and not rural:
        if len(words) < 5:
            return "bad", "landmark or area only"
        if len(raw) < 20:
            return "bad", "too short, no house number"

    if any(k in low for k in _HOSTEL):
        return "flag", "hostel/PG address"
    return "ok", None


# --- customers --------------------------------------------------------

def is_high_rto(prior_shipped: int, prior_rto: int) -> bool:
    """Return-to-origin is half or more of what shipped, or 3+ outright.

    Only RTO counts against a customer. A normal return or exchange
    after delivery does not: the parcel arrived, which is the thing
    this is trying to predict.
    """
    if prior_rto >= 3:
        return True
    return prior_shipped > 0 and prior_rto * 2 >= prior_shipped


# --- the decision -----------------------------------------------------

def is_watchlisted(order: dict, repeat_buyer: bool) -> str | None:
    """Why this order is on the watchlist, or None.

    An OVERLAY, not a bucket: a watchlisted order still sits in Ship
    now or the Call list and still has to be dispatched or called.
    This only says it is worth a second look, so it must never remove
    an order from the queue it belongs in.
    """
    if order.get("fake_order") and order.get("payment") == "COD" \
            and not order.get("is_returning"):
        return "Fake Order tag, new customer COD"
    if repeat_buyer:
        return "repeat buyer, same phone or address"
    return None


def classify(order: dict, hist: dict | None, dup_cod: bool) -> tuple[str, str | None]:
    """(bucket, reason). See the module docstring for the order.

    `order` carries payment, fulfillment, units, risk_tag, is_returning
    and the address verdict. `hist` is the customer's record before
    this campaign, or None when they have none.
    """
    # Not a coin order at all -- it is here because it LOOKS eligible
    # and went out without one. Outside the five-way partition.
    if order.get("coins", 1) == 0:
        return "bundle_no_coin", "2+ units, no coin"

    if (order.get("fulfillment") or "").lower() == "fulfilled":
        return "shipped", None

    # Held whatever the payment type, and listed nowhere else.
    if order.get("units", 0) == 0:
        return "coin_only", "coin and nothing else"

    if order.get("address_verdict") == "bad":
        return "address_bad", order.get("address_reason")

    payment = order.get("payment") or ""
    if payment != "COD":
        # Paid something, so refusal risk is low. The Fake Order tag is
        # deliberately ignored here: the money is already in.
        return "ship_now", None

    # --- COD from here down ---
    returning = bool(order.get("is_returning"))
    if not returning:
        if order.get("fake_order"):
            return "call_list", "Fake Order tag, new customer COD"
        return "call_list", "new customer COD"
    if order.get("risk_tag") is None:
        # GoKwik scores COD checkouts; no tag means it never saw this
        # one, so there is no score to trust.
        return "call_list", "untagged gateway COD"
    if dup_cod:
        return "call_list", "duplicate same-day COD"
    if hist is None or hist.get("delivered", 0) == 0:
        return "call_list", "no prior delivery"
    if is_high_rto(hist.get("shipped", 0), hist.get("rto", 0)):
        return "call_list", "high RTO history"
    return "ship_now", None
