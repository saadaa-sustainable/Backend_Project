"""Exercise the workflow's actual shell guard against local run-history fixtures."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("event,schedule,runs,skip", [
    ("workflow_dispatch", "", [], False),
    ("schedule", "30 1 * * *", [{"conclusion": "success"}], False),
    ("schedule", "30 2 * * *", [{"conclusion": "failure"}], False),
    ("schedule", "30 2 * * *", [{"conclusion": "cancelled"}], False),
    ("schedule", "30 2 * * *", [{"conclusion": ""}], False),
    ("schedule", "30 2 * * *", [{"conclusion": "success"}], True),
    ("schedule", "30 2 * * *", [{"conclusion": "success", "databaseId": 99}], False),
    ("schedule", "30 2 * * *", [{"conclusion": "success", "createdAt": "2026-10-02T00:00:00Z"}], False),
])
def test_backup_recovers_after_failure_and_primary_never_skips(tmp_path, event, schedule, runs, skip):
    jq = shutil.which("jq")
    if not jq:
        pytest.skip("jq is required, as on the GitHub Ubuntu runner")
    workflow = (Path(__file__).parents[1] / ".github/workflows/daily-refresh.yml").read_text()
    guard = workflow.split("        id: guard\n", 1)[1].split("      - name: Checkout", 1)[0]
    script = textwrap.dedent(guard.split("        run: |\n", 1)[1])
    expressions = {"github.event_name": event, "github.event.schedule": schedule,
                   "github.repository": "example/test", "github.ref_name": "master",
                   "github.run_id": "99"}
    script = re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", lambda m: expressions[m[1]], script)
    fixtures = [{"databaseId": 1, "createdAt": "2026-10-03T01:30:00Z", **run} for run in runs]
    # Stub the network-facing executable; evaluate its actual --jq expression
    # against fixtures so a regression in success/self/time filters is caught.
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
    clock = tmp_path / "date"
    clock.write_text("#!/bin/sh\nprintf '%s\\n' '2026-10-03T00:00:00Z'\n")
    gh.chmod(0o755)
    clock.chmod(0o755)
    output = tmp_path / "output"
    called = tmp_path / "called"
    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=5,
        env={"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"], "GITHUB_OUTPUT": str(output),
             "JQ_BIN": jq, "RUNS": json.dumps(fixtures), "GH_CALLED": str(called)})
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == f"skip={str(skip).lower()}"
    assert called.exists() == (event == "schedule" and schedule == "30 2 * * *")
