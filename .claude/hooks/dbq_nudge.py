#!/usr/bin/env python3
"""PreToolUse(Bash): send hand-rolled DB connections to scripts/dbq.py.

831 of 8,097 Bash calls in this project's transcripts opened by
re-deriving the database DSN inline, and 720 of those rewrote
`postgresql+psycopg2://` to `postgresql://` from memory. Each one is
eight wasted lines and one more chance to print a live connection string
into a PUBLIC repository's transcript.

This denies only the specific thing that has a better answer: a command
that reads DATABASE_URL_SYNC and rewrites the scheme itself. Anything
that already imports scripts.dbq passes, and so does any command that
does not touch the DSN -- the hook is narrow on purpose, because a gate
that fires on work it cannot redirect just gets worked around.

stdin: the PreToolUse payload. stdout: a JSON permissionDecision.
Never blocks on its own failure -- see the bare except at the bottom.
"""
import json
import re
import sys

# The boilerplate, not merely "a command mentioning the database".
# Both halves must be present: reading the variable AND rewriting the
# scheme is what this hook can replace with one import.
READS_DSN = re.compile(r"DATABASE_URL_SYNC")
REWRITES_SCHEME = re.compile(r"postgresql\+psycopg2://")

# Already doing the right thing.
ALREADY_OK = re.compile(r"scripts[./]dbq|from scripts\.dbq|import dbq|dbq\.py")

REASON = """This command re-derives the database DSN by hand. Use scripts/dbq.py:

  one query      .venv/bin/python scripts/dbq.py "SELECT ..."
  machine-read   .venv/bin/python scripts/dbq.py --json "SELECT ..."
  query plan     .venv/bin/python scripts/dbq.py --explain "SELECT ..."
  a real script  from scripts.dbq import connect
                 with connect() as conn, conn.cursor() as cur: ...
  a write        add --write (dbq is read-only by default)

dbq owns the postgresql+psycopg2:// rewrite and scrubs credentials out
of every error, which matters because this repository is public."""


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:
        return 0  # Malformed input is not grounds to block a command.

    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "")
    if not command or ALREADY_OK.search(command):
        return 0
    if not (READS_DSN.search(command) and REWRITES_SCHEME.search(command)):
        return 0

    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # A broken hook must never stand between the user and their
        # shell. Exit 0 with no stdout = "no opinion".
        raise SystemExit(0)
