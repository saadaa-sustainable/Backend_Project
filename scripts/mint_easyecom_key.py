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

READ THIS BEFORE USING IT (2026-09-25).

This project has migrated to ASYMMETRIC JWT signing. Its JWKS
publishes exactly one key, an EC P-256 / ES256, and Supabase holds the
private half -- so a token for the current key cannot be minted here
at all.

The HS256 shared secrets still exist, but only as PREVIOUS keys.
Supabase keeps those to verify tokens that have not yet expired and
says plainly: "Revoke once all tokens have expired." A token signed
here is therefore valid only until that revocation, and a long-lived
one makes rotating the key a breaking change for the webhook.

So this mints a token against a key that is already on its way out.
Use it only as a short-lived stopgap, with an expiry you are happy to
re-issue before, and never set it and forget it.

The durable route is supabase/functions/easyecom-webhook/, which needs
no Supabase-signed token: deployed --no-verify-jwt, it checks a plain
shared secret of our own, so the signing-key migration does not touch
it.

The JWT secret comes from the Supabase dashboard:
  Settings > API > JWT Keys > Legacy JWT Secret
It is NOT the anon or service_role key, and it is NOT stored here --
pass it on stdin so it never lands in shell history or a file.

Usage:
    ./.venv/bin/python scripts/mint_easyecom_key.py
    # paste the JWT secret when prompted
"""
from __future__ import annotations

import datetime as dt
import getpass
import re
import sys

try:
    import jwt
except ImportError:                                   # pragma: no cover
    sys.exit("PyJWT is required:  ./.venv/bin/pip install PyJWT")

ROLE = "easyecom_webhook"
#: Deliberately short. The signing key this uses is a PREVIOUS key
#: that Supabase expects to be revoked, so a long expiry only buys a
#: silent failure later.
DAYS = 90


def main() -> int:
    print(
        "Supabase dashboard > Settings > API > JWT Keys > 'Legacy JWT Secret' tab.\n"
        "Copy the long random string there -- NOT the URL, NOT a Key ID UUID,\n"
        "NOT the anon or service_role key.\n"
    )
    secret = getpass.getpass("Legacy JWT Secret: ").strip()

    # Each of these is a thing someone actually reaches for first. Say
    # which one it is rather than failing later with a bad signature.
    if not secret:
        return print("Nothing entered.") or 1
    if secret.lower().startswith(("http://", "https://")):
        return print(
            "That is a URL. The secret is a value inside the dashboard page,\n"
            "under Settings > API > JWT Keys > Legacy JWT Secret."
        ) or 1
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", secret):
        return print(
            "That is a Key ID (the UUID in the JWT Signing Keys table).\n"
            "It identifies a key; it is not the key. Open the\n"
            "'Legacy JWT Secret' tab instead."
        ) or 1
    if secret.count(".") == 2:
        return print(
            "That is a JWT -- an anon or service_role KEY, not the SECRET\n"
            "they are signed with. The secret has no dots."
        ) or 1
    if secret.startswith(("sb_publishable_", "sb_secret_")):
        return print(
            "That is one of the new-style API keys. Those cannot sign a\n"
            "token; use the Legacy JWT Secret."
        ) or 1
    if len(secret) < 32:
        return print(
            f"That is only {len(secret)} characters. The legacy secret is a long\n"
            "random string, normally 40 or more."
        ) or 1

    now = dt.datetime.now(tz=dt.timezone.utc)
    token = jwt.encode(
        {
            "role": ROLE,
            "iss": "supabase",
            "iat": int(now.timestamp()),
            "exp": int((now + dt.timedelta(days=DAYS)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )
    print("\n" + "=" * 62)
    print(f"API key for EasyEcom (role={ROLE}, valid {DAYS} days):\n")
    print(token)
    print("=" * 62)
    print(
        "\nPaste it into EasyEcom's Webhook Settings token field.\n"
        "The worst it can do is add rows to webhook_events -- it cannot\n"
        "read anything back.\n\n"
        "It is signed with a PREVIOUS key. It stops working the moment\n"
        "that key is revoked in Settings > API > JWT Keys."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
