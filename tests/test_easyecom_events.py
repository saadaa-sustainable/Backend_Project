"""The webhook consumer, exercised against EasyEcom's own payloads.

No mark_return has arrived from the live account yet, so the return
path is proved here against the documented V1 and V2 bodies rather
than against production traffic. Fixtures are EasyEcom's published
examples with the customer block removed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = json.loads((ROOT / "tests/fixtures/easyecom_webhook_payloads.json").read_text())

spec = importlib.util.spec_from_file_location(
    "ree", ROOT / "scripts/refresh_easyecom_events.py")
ree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ree)

SHIP = {c: i for i, c in enumerate(ree.SHIP_COLS)}
RET = {c: i for i, c in enumerate(ree.RET_COLS)}
ITEM = {c: i for i, c in enumerate(ree.ITEM_COLS)}


# --- unwrapping: three shapes must all yield their records ----------

@pytest.mark.parametrize("key,expect_at_least", [
    ("tracking_v1", 1),        # [{...}]
    ("mark_return_v2", 1),     # [[{...}]]
    ("mark_return_v1", 1),     # {"credit_notes": [...]}
    ("create_order_v1", 1),    # {"orders": [...]}
    ("create_order_v2", 1),
    ("cancel_order_v2", 1),
])
def test_records_unwraps_every_shape(key, expect_at_least):
    got = list(ree.records(FIX[key]))
    assert len(got) >= expect_at_least
    assert all(isinstance(r, dict) for r in got)


def test_records_yields_all_not_just_first():
    """A V1 envelope with two orders must yield two, not one."""
    payload = {"orders": [{"invoice_id": 1}, {"invoice_id": 2}], "nextUrl": None}
    assert [r["invoice_id"] for r in ree.records(payload)] == [1, 2]


def test_records_does_not_descend_into_tracking_items():
    """tracking.items holds formatted strings; descending loses the record."""
    rec = {"invoiceId": 5, "currentShippingStatus": "Delivered",
           "items": ["Shirt (SKU1) X 1", "Pant (SKU2) X 2"]}
    got = list(ree.records([rec]))
    assert len(got) == 1 and got[0]["invoiceId"] == 5


# --- shipments ------------------------------------------------------

def test_tracking_maps_to_a_shipment_row():
    rec = list(ree.records(FIX["tracking_v1"]))[0]
    row = ree.shipment_row(rec, "2026-09-25T10:00:00+05:30")
    assert row[SHIP["invoice_id"]] == rec["invoiceId"]
    assert row[SHIP["awb_number"]] == str(rec["awbNumber"])
    assert row[SHIP["order_name"]] is not None


@pytest.mark.parametrize("ssid,state,delivered,rto,returned,terminal", [
    (19, "in_flight",     False, False, False, False),
    (2,  "in_flight",     False, False, False, False),
    (20, "in_flight",     False, False, False, False),
    (3,  "delivered",     True,  False, False, True),
    (16, "undelivered",   False, False, False, False),
    (17, "rto_initiated", False, True,  False, False),
    (9,  "rto_returned",  False, True,  True,  True),
])
def test_every_status_maps(ssid, state, delivered, rto, returned, terminal):
    row = ree.shipment_row({"invoiceId": 1, "shipping_status_id": ssid}, None)
    assert row[SHIP["delivery_state"]] == state
    assert row[SHIP["is_delivered"]] is delivered
    assert row[SHIP["is_rto"]] is rto
    assert row[SHIP["rto_returned"]] is returned
    assert row[SHIP["is_terminal"]] is terminal


def test_unknown_status_is_flagged_not_guessed():
    row = ree.shipment_row({"invoiceId": 1, "shipping_status_id": 999,
                            "currentShippingStatus": "Teleported"}, None)
    assert row[SHIP["delivery_state"]] == "unknown"
    assert row[SHIP["is_delivered"]] is False and row[SHIP["is_rto"]] is False


def test_reference_code_becomes_a_shopify_order_name():
    assert ree._name("1547416") == "#1547416"
    assert ree._name("Test_12_OR1") == "Test_12_OR1"   # not numeric, left alone
    assert ree._name(None) is None


# --- returns --------------------------------------------------------

@pytest.mark.parametrize("key", ["mark_return_v1", "mark_return_v2"])
def test_return_head_and_items(key):
    recs = [r for r in ree.records(FIX[key]) if "credit_note_id" in r]
    assert recs, f"{key} carried no credit note"
    head, items = ree.return_rows(recs[0])
    assert head[RET["credit_note_id"]] == recs[0]["credit_note_id"]
    assert head[RET["invoice_id"]] == recs[0]["invoice_id"]
    assert head[RET["credit_note_amount"]] is not None
    assert items, "no return lines extracted"
    assert all(i[ITEM["suborder_id"]] is not None for i in items)
    assert any(i[ITEM["return_reason"]] for i in items)


def test_replacement_order_drives_is_exchange():
    for flag, expect in ((1, True), (0, False), (None, False)):
        head, _ = ree.return_rows({"credit_note_id": 7, "replacement_order": flag})
        assert head[RET["is_exchange"]] is expect


def test_return_without_credit_note_id_is_dropped():
    head, items = ree.return_rows({"invoice_id": 1})
    assert head is None and items == []


# --- coercion -------------------------------------------------------

@pytest.mark.parametrize("raw", ["NA", "", None, "N/A", "-"])
def test_blank_markers_become_null(raw):
    assert ree._t(raw) is None and ree._n(raw) is None and ree._i(raw) is None


def test_numeric_strings_are_coerced():
    assert ree._n("434.91") == pytest.approx(434.91)
    assert ree._i("3") == 3 and ree._i(3.0) == 3


def test_empty_invoice_date_is_null_not_epoch():
    assert ree._ts("") is None
    assert ree._ts("0000-00-00 00:00:00") is None
    assert ree._ts("2023-09-18 00:00:00") == "2023-09-18 00:00:00"


def test_tracking_items_never_parsed_as_return_lines():
    """`items` means line objects on mark_return V1 and formatted
    strings on tracking. Reading fields off a string would throw."""
    head, items = ree.return_rows({
        "credit_note_id": 1, "invoice_id": 2,
        "items": ["Shirt (SKU1) X 1", "Pant (SKU2) X 2"]})
    assert head is not None
    assert items == []


def _ship(inv, ssid, upd, seen):
    row = ree.shipment_row({"invoiceId": inv, "shipping_status_id": ssid,
                            "last_status_update": upd}, seen)
    return row[:-1] + (1, seen, seen)


def test_collapse_keeps_newest_status_and_sums_the_count():
    rows = [_ship(1, 19, "2026-09-25 10:00:00", "a"),
            _ship(1, 3,  "2026-09-25 12:00:00", "c"),
            _ship(1, 20, "2026-09-25 11:00:00", "b"),
            _ship(2, 17, "2026-09-25 09:00:00", "a")]
    out = {r[0]: r for r in ree.collapse(rows)}
    assert len(out) == 2                       # one row per invoice_id
    assert out[1][SHIP["delivery_state"]] == "delivered"   # 12:00 wins
    assert out[1][25] == 3                     # event_count folded
    assert out[1][26] == "a" and out[1][27] == "c"         # first/last seen
    assert out[2][SHIP["delivery_state"]] == "rto_initiated"


def test_collapse_handles_a_missing_timestamp():
    rows = [_ship(1, 3, None, "a"), _ship(1, 17, "2026-09-25 10:00:00", "b")]
    out = ree.collapse(rows)
    assert len(out) == 1
    assert out[0][SHIP["delivery_state"]] == "rto_initiated"   # None sorts oldest
