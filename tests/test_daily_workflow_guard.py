"""Execute the workflow's real guard with run history and a fixed clock."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import pytest


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/daily-refresh.yml"


def run_guard(tmp_path, *, event="schedule", force=False, runs=(), now="2026-10-05T07:00:00+00:00", fail=False):
    jq = shutil.which("jq")
    if not jq:
        pytest.skip("jq is required, as on the GitHub Ubuntu runner")
    workflow = WORKFLOW.read_text()
    guard = workflow.split("        id: guard\n", 1)[1].split("      - name: Checkout", 1)[0]
    script = textwrap.dedent(guard.split("        run: |\n", 1)[1])
    expressions = {"github.repository": "example/test", "github.run_id": "99"}
    script = re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", lambda m: expressions[m[1]], script)
    fixtures = [{"databaseId": 1, "createdAt": "2026-10-05T01:39:00Z",
                 "status": "completed", **run} for run in runs]
    gh = tmp_path / "gh"
    gh.write_text(f"#!{sys.executable}\n" + "\n".join([
        "import os, subprocess, sys",
        "from pathlib import Path",
        "Path(os.environ['GH_CALLED']).touch()",
        "if os.environ['GH_FAIL'] == 'true': sys.exit(1)",
        "expression = sys.argv[sys.argv.index('--jq') + 1]",
        "result = subprocess.run([os.environ['JQ_BIN'], expression], input=os.environ['RUNS'],",
        "                        text=True, capture_output=True, check=True)",
        "sys.stdout.write(result.stdout)",
    ]) + "\n")
    # macOS date lacks GNU -d. Interpret the actual workflow arguments
    # against a frozen clock, including its TZ=Asia/Kolkata environment.
    clock = tmp_path / "date"
    clock.write_text(f"#!{sys.executable}\n" + "\n".join([
        "import os, sys",
        "from datetime import datetime, timezone",
        "from zoneinfo import ZoneInfo",
        "if sys.argv[1:] == ['+%F']:",
        "    now = datetime.fromisoformat(os.environ['NOW'])",
        "    print(now.astimezone(ZoneInfo(os.environ.get('TZ', 'UTC'))).date())",
        "else:",
        "    raw = sys.argv[sys.argv.index('-d') + 1]",
        "    cutoff = datetime.strptime(raw, '%Y-%m-%d %H:%M:%S %z')",
        "    print(cutoff.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))",
    ]) + "\n")
    gh.chmod(0o755)
    clock.chmod(0o755)
    output, called, summary = (tmp_path / name for name in ("output", "called", "summary"))
    result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=5,
        env={"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"], "GITHUB_OUTPUT": str(output),
             "GITHUB_STEP_SUMMARY": str(summary), "REFRESH_EVENT": event,
             "FORCE_REFRESH": str(force).lower(), "NOW": now, "GH_FAIL": str(fail).lower(),
             "JQ_BIN": jq, "RUNS": json.dumps(fixtures), "GH_CALLED": str(called)})
    return result, output, called, summary


@pytest.mark.parametrize("event,force,runs,skip", [
    ("schedule", False, [], False),
    ("workflow_dispatch", False, [], False),
    ("schedule", False, [{"conclusion": "success"}], True),
    ("schedule", False, [{"conclusion": "failure"}], True),
    ("schedule", False, [{"conclusion": "cancelled"}], True),
    ("schedule", False, [{"status": "in_progress"}], True),
    ("schedule", False, [{"status": "queued"}], False),
    ("schedule", False, [{"status": "pending"}], False),
    ("schedule", False, [{"status": "waiting"}], False),
    ("schedule", False, [{"databaseId": 99, "status": "in_progress"}], False),
    ("workflow_dispatch", False, [{"conclusion": "failure"}], True),
    ("workflow_dispatch", True, [{"conclusion": "failure"}], False),
    ("schedule", True, [{"conclusion": "success"}], True),
    # The same IST day extends into the previous UTC date.
    ("schedule", False, [{"createdAt": "2026-10-04T18:30:00Z"}], True),
    ("schedule", False, [{"createdAt": "2026-10-04T18:29:59Z"}], False),
])
def test_single_attempt_with_explicit_manual_override(tmp_path, event, force, runs, skip):
    result, output, called, summary = run_guard(tmp_path, event=event, force=force, runs=runs)
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == f"skip={str(skip).lower()}"
    assert called.exists() == (not (event == "workflow_dispatch" and force))
    assert summary.exists() == skip


def test_new_ist_day_allows_the_next_refresh_before_utc_midnight(tmp_path):
    result, output, _, _ = run_guard(tmp_path, now="2026-10-05T18:31:00+00:00",
                                   runs=[{"createdAt": "2026-10-05T18:29:59Z"}])
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == "skip=false"


def test_history_lookup_failure_never_authorizes_another_refresh(tmp_path):
    result, output, called, _ = run_guard(tmp_path, fail=True)
    assert result.returncode != 0
    assert called.exists()
    assert not output.exists()


def test_only_7am_ist_cron_and_manual_override_is_opt_in():
    workflow = WORKFLOW.read_text()
    assert re.findall(r'^\s+- cron: "([^"]+)"', workflow, re.MULTILINE) == ["30 1 * * *"]
    force_input = workflow.split("      force_refresh:\n", 1)[1].split("  schedule:", 1)[0]
    assert "type: boolean" in force_input and "default: false" in force_input
    assert "group: bp-daily-refresh" in workflow
    assert "cancel-in-progress: false" in workflow
