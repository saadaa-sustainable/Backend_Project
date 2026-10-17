#!/usr/bin/env python3
"""Warn when pipeline work exists only locally, before the cron erases it.

    "Push the chanages before the cron or the matching would be reverted
     for today"                                        -- session, 2026-10

The nightly builds from master. Anything the nightly EXECUTES that lives
only in a working tree or on an unmerged branch does not run: the job
checks out master, runs master's code, and the night's output reflects
master. That has cost this project a full day twice -- once when the
duplicate indexes came back, once when silver_shopify died.

Two modes:
  (default)      SessionStart hook -- prints JSON additionalContext
  --statusline   one line for the status bar, printed every refresh

Silent when nothing nightly-executed has drifted. A warden that speaks
every session is a warden nobody reads.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Paths the nightly actually runs. A change under admin/ is invisible to
#: the cron, so it must not raise this alarm -- that is the difference
#: between a warning and noise.
#:
#: Derived from .github/workflows/daily-refresh.yml, which invokes
#: scripts/refresh_all_daily.py, which imports from app/.
#:
#: sql/ is in the list because refresh_snapshot_views.py READS
#: sql/snapshot_views.sql at run time and re-applies it whenever a view
#: has drifted off its source table. A change there is executed by the
#: cron as surely as a change to a script -- and it was missed on the
#: first pass, which left sql/snapshot_views.sql drifting silently
#: while the warden reported everything around it.
NIGHTLY_PATHS = ("scripts/", "app/", "utils/", "sql/", ".github/workflows/")

#: 01:30 UTC in daily-refresh.yml. The real trigger is an external
#: workflow_dispatch a few minutes later; the cron time is the honest
#: floor and the one written down.
CRON_UTC_HOUR, CRON_UTC_MIN = 1, 30


def git(*args: str) -> str:
    try:
        return subprocess.run(("git", *args), cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def nightly_files(paths: list[str]) -> list[str]:
    return sorted({p for p in paths if p and p.startswith(NIGHTLY_PATHS)})


def drift() -> tuple[list[str], list[str], str]:
    """(tracked files whose content differs from origin/master, new files, branch).

    The question is NOT "what have I touched" -- it is "what would the
    cron run differently from what is in front of me". So this compares
    the WORKING TREE against origin/master directly, in one diff.

    That distinction is load-bearing. Running it the obvious way, with
    `git status` for dirty files plus `origin/master...HEAD` for commits,
    reported eight drifted files on a tree where four of them already
    matched origin/master byte for byte -- they were merged in a PR built
    from a worktree, so they read as "modified" against a branch head
    that predates the merge. Four false alarms out of eight is how a
    warning becomes background noise.
    """
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    # Working tree vs the commit the cron checks out. Covers uncommitted
    # edits and unmerged commits in a single comparison, and says nothing
    # about a file that merely differs from the local branch.
    changed = nightly_files(
        git("diff", "--name-only", "origin/master", "--").splitlines()
    )
    # Untracked files are invisible to that diff and equally invisible
    # to the cron.
    untracked = nightly_files(
        git("ls-files", "--others", "--exclude-standard").splitlines()
    )
    return changed, untracked, branch


def until_cron() -> str:
    now = datetime.now(timezone.utc)
    nxt = now.replace(hour=CRON_UTC_HOUR, minute=CRON_UTC_MIN,
                      second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    mins = int((nxt - now).total_seconds() // 60)
    return f"{mins // 60}h{mins % 60:02d}m"


def main() -> int:
    statusline = "--statusline" in sys.argv
    changed, untracked, branch = drift()
    if not changed and not untracked:
        return 0  # Silence is the normal state.

    n = len(set(changed) | set(untracked))
    if statusline:
        print(f"⚠ {n} pipeline file{'s' if n != 1 else ''} not on master · cron in {until_cron()}")
        return 0

    lines = [
        f"Nightly drift: {n} file(s) the nightly executes are not on origin/master. "
        f"The cron checks out master and runs master's code, so these will not "
        f"take effect tonight (next run in {until_cron()}; branch is {branch})."
    ]
    if changed:
        lines.append("  differs from master: " + ", ".join(changed[:8])
                     + (f" (+{len(changed) - 8} more)" if len(changed) > 8 else ""))
    if untracked:
        lines.append("  untracked (invisible to the cron): "
                     + ", ".join(untracked[:8])
                     + (f" (+{len(untracked) - 8} more)" if len(untracked) > 8 else ""))
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
