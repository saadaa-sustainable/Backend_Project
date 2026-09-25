"""Watch webhook_events and print each new row as it lands.

For the moment a real EasyEcom delivery arrives: the payload shape is
what nothing in this project knows yet, and it is what the consumer
has to be built against.

Rows sent by curl are marked as tests, so a real delivery is
unmistakable -- EasyEcom sends its own user-agent.

Usage:
    ./.venv/bin/python scripts/watch_webhooks.py
    ./.venv/bin/python scripts/watch_webhooks.py --since 0   # show history too
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402

DSN = os.environ["DATABASE_URL_SYNC"].replace(
    "postgresql+psycopg2://", "postgresql://").split("?")[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", type=int, default=None,
                    help="Start from this row id. Default: only new rows.")
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM public.webhook_events")
        last = args.since if args.since is not None else cur.fetchone()[0]

    print(f"watching webhook_events from id > {last}   (ctrl-c to stop)\n")
    try:
        while True:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, event, received_at, headers->>'user-agent', payload "
                        "  FROM public.webhook_events WHERE id > %s ORDER BY id", (last,))
                    rows = cur.fetchall()
            except psycopg2.Error:
                # The pooler drops idle connections; reconnect rather
                # than die halfway through a wait for the one event
                # this script exists to catch.
                conn = psycopg2.connect(DSN)
                conn.autocommit = True
                continue

            for rid, event, at, ua, payload in rows:
                last = rid
                is_test = bool(ua and "curl" in ua.lower())
                mark = "test" if is_test else ">>> FROM EASYECOM"
                print(f"#{rid}  {event}  {str(at)[:19]}  {mark}")
                print(json.dumps(payload, indent=2)[:2000])
                if not is_test:
                    print("\n  Top-level keys, which is what the consumer maps:")
                    if isinstance(payload, dict):
                        for k in payload:
                            print(f"    {k}")
                print()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
