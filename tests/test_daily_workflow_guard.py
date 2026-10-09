"""Exercise the workflow's actual shell guard against local run-history fixtures.

The guard's contract changed on 2026-10-09, and these cases encode the
new one. It used to skip only the 02:30 backup, and only after a
SUCCESSFUL run inside a rolling 5-hour window. GitHub then delayed the
schedules by six to seven hours, so by the time the backup fired the
primary had fallen outside the window it could see -- and a primary
that had itself been cancelled would not have counted as success
anyway. The backup went ahead every time, queued behind the concurrency
group for 2h19m, and ran through the working day.

It now allows ONE ATTEMPT per IST calendar day, whatever that attempt's
conclusion. A cancelled or failed run holds the slot; recovery is a
deliberate workflow_dispatch with force_refresh, not an automatic
retry.

The script is read out of the workflow file rather than copied here, so
a change to one without the other fails rather than drifting quietly.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

#: Midnight IST on the test's "today", expressed in UTC. The guard
#: computes exactly this, and every fixture timestamp is placed either
#: side of it.
IST_MIDNIGHT_UTC = "2026-10-02T18:30:00Z"

TODAY = {"createdAt": "2026-10-03T04:00:00Z"}          # after IST midnight
YESTERDAY = {"createdAt": "2026-10-02T04:00:00Z"}      # before it


@pytest.mark.parametrize("event,force,runs,skip", [
    # Nothing ran today: the scheduled run proceeds.
    ("schedule", "false", [], False),
    # An ATTEMPT holds the slot whatever it concluded as. These three
    # are the regression the old guard could not catch: it demanded
    # success, so a cancelled or failed primary let the backup through.
    ("schedule", "false", [{**TODAY, "conclusion": "success"}], True),
    ("schedule", "false", [{**TODAY, "conclusion": "failure"}], True),
    ("schedule", "false", [{**TODAY, "conclusion": "cancelled"}], True),
    ("schedule", "false", [{**TODAY, "conclusion": ""}], True),
    # Yesterday's run does not hold today's slot.
    ("schedule", "false", [{**YESTERDAY, "conclusion": "success"}], False),
    # This run must never count itself.
    ("schedule", "false", [{**TODAY, "databaseId": 99}], False),
    # A pull_request run of the same workflow is not a refresh.
    ("schedule", "false", [{**TODAY, "event": "pull_request"}], False),
    # A dispatch is subject to the same guard...
    ("workflow_dispatch", "false", [{**TODAY, "conclusion": "success"}], True),
    # ...unless it explicitly asks to override, which is the recovery path.
    ("workflow_dispatch", "true", [{**TODAY, "conclusion": "success"}], False),
    ("workflow_dispatch", "true", [], False),
])
def test_one_attempt_per_ist_day(tmp_path, event, force, runs, skip):
    jq = shutil.which("jq")
    if not jq:
        pytest.skip("jq is required, as on the GitHub Ubuntu runner")
    workflow = (Path(__file__).parents[1] / ".github/workflows/daily-refresh.yml").read_text()
    guard = workflow.split("        id: guard\n", 1)[1].split("      - name: Checkout", 1)[0]
    script = textwrap.dedent(guard.split("        run: |\n", 1)[1])
    expressions = {"github.repository": "example/test", "github.run_id": "99"}
    script = re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}",
                    lambda m: expressions.get(m[1], ""), script)

    fixtures = [{"databaseId": 1, "event": "schedule", "conclusion": "success", **run}
                for run in runs]

    # Stub the network-facing executable; evaluate its actual --jq
    # expression against the fixtures, so a regression in the self /
    # date / event filters is caught rather than mocked away.
    gh = tmp_path / "gh"
    gh.write_text(f"#!{sys.executable}\n" + "\n".join([
        "import os, subprocess, sys",
        "from pathlib import Path",
        "Path(os.environ['GH_CALLED']).touch()",
        "expression = sys.argv[sys.argv.index('--jq') + 1]",
        "result = subprocess.run([os.environ['JQ_BIN'], expression], input=os.environ['RUNS'],",
        "                        text=True, capture_output=True, check=True)",
        "sys.stdout.write(result.stdout)",
    ]) + "\n")

    # The guard calls date twice and wants different answers: the IST
    # calendar day, then midnight of that day in UTC. A stub that
    # ignored its arguments would make the cutoff meaningless and every
    # fixture would land on the same side of it.
    clock = tmp_path / "date"
    clock.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *%F*) printf '%s\\n' '2026-10-03' ;;\n"
        f"  *) printf '%s\\n' '{IST_MIDNIGHT_UTC}' ;;\n"
        "esac\n")
    gh.chmod(0o755)
    clock.chmod(0o755)

    output = tmp_path / "output"
    called = tmp_path / "called"
    result = subprocess.run(
        ["bash", "-c", script], text=True, capture_output=True, timeout=5,
        env={"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
             "GITHUB_OUTPUT": str(output), "JQ_BIN": jq,
             "RUNS": json.dumps(fixtures), "GH_CALLED": str(called),
             "REFRESH_EVENT": event, "FORCE_REFRESH": force})
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == f"skip={str(skip).lower()}"
    # A forced dispatch must short-circuit before asking GitHub anything.
    forced = event == "workflow_dispatch" and force == "true"
    assert called.exists() != forced


def test_workflow_has_exactly_one_schedule():
    """One cron, not two.

    The second cron is what put the pipeline in the middle of the
    working day, so its absence is part of the contract rather than an
    incidental edit.
    """
    workflow = (Path(__file__).parents[1] / ".github/workflows/daily-refresh.yml").read_text()
    crons = re.findall(r"^\s*- cron: ", workflow, re.M)
    assert len(crons) == 1, f"expected one schedule, found {len(crons)}"
