#!/usr/bin/env python3
"""PreToolUse(Bash): warn when a commit touches filter code unswept.

WARNS, does not block. Blocking was the other option and it is the wrong
one here: the person committing at 1am is usually racing the 01:30 cron,
and a gate that stands between them and that push costs more than the
regression it catches. Flip BLOCK to True to change that -- it is one
line, and the deny path below is already written.

Fires only when the commit touches a file that defines or serves
filters, and only when a baseline exists to compare against.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BLOCK = False  # True -> deny the commit instead of warning

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / ".claude" / "filter_sweep_baseline.json"

FILTER_CODE = re.compile(
    r"app/api/routers/analytics\.py"
    r"|app/services/analytics_cache\.py"
    r"|admin/src/app/user/analytics/.*\.tsx"
)


def staged() -> list[str]:
    try:
        out = subprocess.run(["git", "diff", "--cached", "--name-only"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
        return [f for f in out.stdout.split("\n") if f.strip()]
    except Exception:
        return []


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not re.search(r"\bgit\s+commit\b", cmd):
        return 0
    touched = [f for f in staged() if FILTER_CODE.search(f)]
    if not touched:
        return 0

    if not BASELINE.exists():
        note = ("This commit touches filter code and no filter-sweep baseline "
                "exists yet. Run `/sweep --save` once to record one, so later "
                "commits can be compared against it.")
    else:
        note = (f"This commit touches {len(touched)} file(s) that define or serve "
                f"analytics filters ({', '.join(touched[:3])}"
                f"{'...' if len(touched) > 3 else ''}). A filter-sweep baseline "
                f"exists; `/sweep --check` compares against it and reports dead "
                f"filters, scope violations and block-count regressions.")

    if BLOCK:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": note + " Run it before committing.",
        }}, sys.stdout)
    else:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": note,
        }}, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
