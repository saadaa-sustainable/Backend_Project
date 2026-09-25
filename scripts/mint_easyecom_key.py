"""Mint the Supabase API key EasyEcom will post with.

Supabase's anon and service_role keys are just JWTs signed with the
project's JWT secret, carrying a `role` claim. PostgREST switches into
whatever role that claim names, so a token minted with
role=easyecom_webhook lands in the least-privilege role created by
sql/easyecom_webhook_role.sql -- which can INSERT one kind of row into
one table and nothing else.

This exists so EasyEcom can be pointed straight at
  https://<ref>.supabase.co/rest/v1/webhook_events
without giving it service_role, which would grant read and write on
every table in the project and bypass row-level security.

The JWT secret comes from the Supabase dashboard:
  Settings > API > JWT Settings > JWT Secret
It is NOT the anon or service_role key, and it is NOT stored here --
pass it on stdin so it never lands in shell history or a file.

Usage:
    ./.venv/bin/python scripts/mint_easyecom_key.py
    # paste the JWT secret when prompted
"""
from __future__ import annotations

import datetime as dt
import getpass
import sys

try:
    import jwt
except ImportError:                                   # pragma: no cover
    sys.exit("PyJWT is required:  ./.venv/bin/pip install PyJWT")

ROLE = "easyecom_webhook"
YEARS = 5


def main() -> int:
    secret = getpass.getpass("Supabase JWT Secret (Settings > API): ").strip()
    if not secret:
        return print("No secret given.") or 1
    if secret.count(".") == 2:
        return print(
            "That looks like an anon/service_role KEY, not the JWT SECRET.\n"
            "The secret is the long random string under JWT Settings, with no dots."
        ) or 1

    now = dt.datetime.now(tz=dt.timezone.utc)
    token = jwt.encode(
        {
            "role": ROLE,
            "iss": "supabase",
            "iat": int(now.timestamp()),
            # Long-lived on purpose: rotating it means editing the
            # webhook config in EasyEcom by hand. The blast radius is
            # one INSERT on one table, which is what makes that
            # acceptable.
            "exp": int((now + dt.timedelta(days=365 * YEARS)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )
    print("\n" + "=" * 62)
    print(f"API key for EasyEcom (role={ROLE}, valid {YEARS} years):\n")
    print(token)
    print("=" * 62)
    print(
        "\nPaste it into EasyEcom's Webhook Settings token field.\n"
        "Treat it as a credential, but note the worst it can do is add\n"
        "rows to webhook_events -- it cannot read anything back."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
