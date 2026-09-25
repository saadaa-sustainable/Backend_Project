"""Mint the EasyEcom JWT and record which locations the account can see.

EasyEcom needs BOTH headers on every call:

    x-api-key:     long lived, from Settings -> API, primary account only
    Authorization: Bearer <jwt_token>, valid 90 days

The JWT comes from:

    POST https://api.easyecom.io/access/token
    x-api-key: <api key>
    {"email": "...", "password": "...", "location_key": "..."}
      -> data.token.jwt_token

THE TOKEN IS SCOPED TO ONE location_key, AND THAT IS WHY A CHANNEL CAN
LOOK MISSING. A location is a physical warehouse. getAllOrders in V2.1
takes only start_date, end_date and the cursor -- there is no
marketplace parameter -- so the only thing deciding which orders come
back is the window and the location the token was minted against. If
Amazon ships out of one warehouse and the Shopify D2C stock out of
another, a token minted on the Amazon location returns Amazon orders
and nothing else, with no error to tell you so.

So after minting, this calls

    GET /account/v1/api/locations

and prints every location the account owns. If more than one comes
back, the ingest has to run once per location_key, not once.

The password is read with getpass: not echoed, not stored, not logged.
The minted token is written straight into .env and never printed -- only
a short fingerprint, because this repo is public.

Usage:
    ./.venv/bin/python scripts/mint_easyecom_jwt.py
"""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
load_dotenv(ENV, override=True)

BASE = "https://api.easyecom.io"


def post(url: str, key: str, body: dict) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-api-key": key,
                 "Accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:400]
    except Exception as e:                                   # noqa: BLE001
        return 0, str(e)[:300]


def get(url: str, key: str, jwt: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        url, headers={"x-api-key": key, "Authorization": f"Bearer {jwt}",
                      "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:400]
    except Exception as e:                                   # noqa: BLE001
        return 0, str(e)[:300]


def put_env(name: str, value: str) -> None:
    """Replace NAME=... in .env, or append it. Never prints the value."""
    text = ENV.read_text() if ENV.exists() else ""
    line = f"{name}={value}"
    if re.search(rf"(?m)^{re.escape(name)}=", text):
        text = re.sub(rf"(?m)^{re.escape(name)}=.*$", line, text)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    ENV.write_text(text)


def main() -> int:
    key = os.environ.get("EASYECOM_API_KEY", "").strip()
    if not key:
        key = getpass.getpass("x-api-key (Settings -> API): ").strip()
    if not key:
        return print("No API key, nothing to do.") or 2

    print("\nEasyEcom login. The password is not echoed, stored or logged.")
    email = input("  email        : ").strip()
    password = getpass.getpass("  password     : ")
    loc = input("  location_key : ").strip()
    if not (email and password and loc):
        return print("\nAll three are required.") or 2

    code, body = post(f"{BASE}/access/token", key,
                      {"email": email, "password": password,
                       "location_key": loc})

    if not isinstance(body, dict):
        print(f"\n[{code}] unexpected response:\n  {body}")
        return 1

    jwt = ((body.get("data") or {}).get("token") or {}).get("jwt_token")
    if not jwt:
        msg = body.get("message") or body
        print(f"\n[{code}] no token issued: {msg}")
        print("\n  'Invalid user credentials provided' -> email/password.")
        print("  'Invalid location key provided'      -> the location_key,")
        print("     which you can read off EasyEcom's UI, or from another")
        print("     location's token via /account/v1/api/locations.")
        return 1

    data = body["data"]
    put_env("EASYECOM_JWT", jwt)
    print(f"\n[OK] token issued and written to .env as EASYECOM_JWT")
    print(f"     fingerprint  : {jwt[:6]}...{jwt[-4:]}  (len {len(jwt)})")
    print(f"     company      : {data.get('companyname')!r}")
    print(f"     user         : {data.get('userName')!r}")
    print(f"     all_location : {data.get('all_location')!r}")
    print(f"     time_zone    : {data.get('time_zone')!r}")
    print("     valid        : 90 days -- re-run this when it expires")

    # The point of the exercise: how many warehouses are there, and is
    # the one we just authenticated against the only one with orders?
    code, locs = get(f"{BASE}/account/v1/api/locations", key, jwt)
    rows = (locs or {}).get("data") if isinstance(locs, dict) else None
    if not rows:
        print(f"\n[locations] HTTP {code}, could not list: {locs}")
        return 0

    print(f"\n[locations] {len(rows)} on this account:")
    for r in rows:
        lk = r.get("location_key")
        here = "  <- token minted here" if lk == loc else ""
        print(f"     {str(r.get('companyname')):<28} {lk}{here}")

    if len(rows) > 1:
        print("\n  More than one location. getAllOrders returns orders for")
        print("  the location the token was minted against, and there is no")
        print("  marketplace parameter to widen it -- so if a channel looks")
        print("  missing, mint a token per location_key and probe each:")
        print("\n    ./.venv/bin/python scripts/ingest_easyecom_orders.py \\")
        print("        --probe --since 2026-08-01 --until 2026-09-25")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
