"""Prove the minted key works BEFORE configuring EasyEcom.

Two things can be wrong and only one is obvious. The key may be
rejected (easy to spot). Or the key may be fine and the PAYLOAD SHAPE
rejected -- because PostgREST inserts the JSON body as a table row, so
every top-level key in EasyEcom's payload has to be a column of
webhook_events. It will not be: EasyEcom sends its own order shape and
this table has source / event / payload / headers.

This sends both a correctly-shaped row and an EasyEcom-shaped one, so
the difference is visible here rather than in EasyEcom's delivery log.

The key is read from a prompt, never stored.

Usage:
    ./.venv/bin/python scripts/check_easyecom_key.py
"""
from __future__ import annotations

import getpass
import json
import sys
import urllib.error
import urllib.request

REST = "https://gtcdyfmlvglzpiwzklhx.supabase.co/rest/v1/webhook_events"


def post(key: str, body: dict, *, both_headers: bool) -> tuple[int, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    # Supabase's gateway normally wants `apikey` as well. EasyEcom's UI
    # offers one token field, so the single-header case is the one that
    # actually matters.
    if both_headers:
        headers["apikey"] = key
    req = urllib.request.Request(REST, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, (r.read().decode() or "(empty)")[:200]
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() or "")[:220]
    except Exception as e:                                  # noqa: BLE001
        return 0, str(e)[:200]


def main() -> int:
    key = getpass.getpass("Minted EasyEcom key (from mint_easyecom_key.py): ").strip()
    if not key or key.count(".") != 2:
        return print("That is not a JWT. Run mint_easyecom_key.py first.") or 1

    correct = {"source": "easyecom", "event": "tracking",
               "payload": {"probe": True}, "headers": {}}
    # Roughly what EasyEcom actually sends: its own fields, at the top
    # level, none of which are columns here.
    easyecom_like = {"order_id": 12345, "status": "delivered",
                     "awb": "TEST123", "invoice_id": "INV-1"}

    print("\n1. correct shape, both headers")
    c, b = post(key, correct, both_headers=True)
    print(f"   HTTP {c}  {b}")
    key_ok = c in (200, 201)

    print("\n2. correct shape, Authorization only (what EasyEcom can send)")
    c2, b2 = post(key, correct, both_headers=False)
    print(f"   HTTP {c2}  {b2}")

    print("\n3. EasyEcom-shaped payload, both headers")
    c3, b3 = post(key, easyecom_like, both_headers=True)
    print(f"   HTTP {c3}  {b3}")

    print("\n" + "=" * 60)
    if not key_ok:
        print("The KEY is being rejected. Check it was minted from the")
        print("Legacy JWT Secret, and that that key is not revoked.")
    else:
        print("Key works.")
        print(f"  single Authorization header alone: "
              f"{'works' if c2 in (200, 201) else f'REJECTED ({c2}) -- EasyEcom cannot send two headers'}")
        print(f"  EasyEcom-shaped payload:           "
              f"{'accepted' if c3 in (200, 201) else f'REJECTED ({c3}) -- PostgREST needs the body to match columns'}")
        if c3 not in (200, 201):
            print("\nThat third result is the blocker. PostgREST writes the body")
            print("as a row, so an arbitrary third-party payload cannot land in")
            print("a fixed table. The Edge Function wraps the payload instead:")
            print("  supabase/functions/easyecom-webhook/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
