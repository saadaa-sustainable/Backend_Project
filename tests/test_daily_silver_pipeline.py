"""Run actual CLI selection against a fake runner; never launch ingest scripts."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys

import pytest

from scripts import refresh_all_daily as daily


class FakeRun:
    def __init__(self, failures=()):
        self.steps = {}
        self.commands = []
        self.failures = failures

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @contextmanager
    def step(self, name, timeout):
        def run(cmd, cwd):
            self.commands.append((name, cmd, timeout))
            self.steps[name] = {"status": "failed" if name in self.failures else "ok"}

        def skip(reason):
            self.steps[name] = {"status": "skipped", "reason": reason}

        yield SimpleNamespace(run=run, skip=skip)


@pytest.mark.parametrize("flags,ingests", [([], True), (["--only-silver"], False),
    (["--only-shopify"], True), (["--only-shopify-silver"], False)])
def test_every_refresh_path_rebuilds_attribution_after_flatten(monkeypatch, flags, ingests):
    run = FakeRun()
    monkeypatch.setattr(daily, "CronRun", lambda **kwargs: run)
    monkeypatch.setattr(sys, "argv", ["refresh_all_daily.py", *flags])
    assert daily.main() == 0
    names = list(run.steps)
    assert ("shopify_daily" in names) == ingests
    assert names.index("silver_shopify") < names.index("silver_shopify_attribution")
    commands = {name: (cmd, timeout) for name, cmd, timeout in run.commands}
    assert commands["silver_shopify"][0][-1] == "--skip-attribution"
    assert commands["silver_shopify_attribution"][0][-1] == "--only-attribution"
    assert commands["silver_shopify_attribution"][1] == 3600
    if "--only-shopify-silver" in flags:
        assert not set(names).intersection(label for label, _, _ in daily.PHASE_INGEST)
    if "gold_ad_performance" in names:
        assert names.index("silver_shopify_attribution") < names.index("gold_ad_performance")


@pytest.mark.parametrize("failure", ["silver_shopify", "silver_shopify_attribution"])
def test_failed_source_preserves_dependent_tables_and_fails_run(monkeypatch, failure):
    run = FakeRun(failures={failure})
    monkeypatch.setattr(daily, "CronRun", lambda **kwargs: run)
    monkeypatch.setattr(sys, "argv", ["refresh_all_daily.py", "--only-silver"])
    assert daily.main() == 1
    assert run.steps["gold_ad_performance"]["status"] == "skipped"
    if failure == "silver_shopify":
        assert run.steps["silver_shopify_attribution"]["status"] == "skipped"


def test_force_and_skip_cpis_work_in_bronze_only_recovery(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(daily, "CronRun", lambda **kwargs: run)
    monkeypatch.setattr(sys, "argv", ["refresh_all_daily.py", "--only-shopify-silver",
                                     "--force-silver", "--skip-cpis"])
    assert daily.main() == 0
    for name, cmd, _ in run.commands:
        assert ("--force" in cmd) == (name == "silver_shopify")
    assert not set(run.steps).intersection(daily.SHOPIFY_CPIS_STEPS)


@pytest.mark.parametrize("flags", [["--only-shopify", "--only-shopify-silver"],
    ["--only-shopify-silver", "--only-silver"], ["--only-shopify-silver", "--skip-meta"],
    ["--skip-cpis"]])
def test_conflicting_modes_fail_before_any_work(monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["refresh_all_daily.py", *flags])
    with pytest.raises(SystemExit):
        daily.main()
