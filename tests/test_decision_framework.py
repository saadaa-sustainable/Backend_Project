"""The audit framework's kill gate, and the agreement of its two bodies.

`_decide` and `_decision_sql` are the same rule written twice -- once in
Python for the verdict tiles, once in SQL so the table can be filtered
server-side. They have silently disagreed before: leaving last-click
revenue NULL made an ad set that spent and earned nothing read as
UNRATED in SQL and PAUSE in Python, and the verdict filter returned 27
rows against a tile saying 150.

These pin the rule itself. The cross-check that the SQL says the same
thing runs against the live database in
scripts/check_decision_parity.py, because the SQL cannot be evaluated
without one.
"""

import pytest

from app.api.routers.analytics import (
    _KILL_ROAS,
    _SCALE_ROAS,
    _decide,
    _ftewv_benchmark,
    _ftewv_expensive,
)

RAHO = "Raho Saadaa"        # benchmark Rs15
FOURTH = "Fourth Ad Account - SD"  # benchmark Rs12


def verdict(d3_roas, d7_roas, account, *, cpf3, cpf7, spend=1000.0):
    """Drive `_decide` by the cost per FTEWV we want each window to have.

    cpf None means the window spent and produced no FTEWV at all;
    cpf 0 means it did not spend.
    """
    def window(cpf):
        if cpf == 0:
            return 0.0, 0.0          # no spend -- window is silent
        if cpf is None:
            return spend, 0.0        # spent, zero FTEWV
        return spend, spend / cpf

    s3, f3 = window(cpf3)
    s7, f7 = window(cpf7)
    return _decide(d3_roas, d7_roas, account,
                   d3_spend=s3, d3_ftewv=f3, d7_spend=s7, d7_ftewv=f7)[0]


def test_benchmark_is_per_account():
    assert _ftewv_benchmark(RAHO) == 15.0
    assert _ftewv_benchmark(FOURTH) == 12.0
    # An account the document does not name gets the looser of the two,
    # so it is never pause-recommended on a stricter rule than exists.
    assert _ftewv_benchmark("Third Ad Account - SD") == 15.0
    assert _ftewv_benchmark(None) == 15.0


@pytest.mark.parametrize("spend, ftewv, expected", [
    (1000.0, 50.0, False),   # Rs20 ... under a Rs25 benchmark
    (1000.0, 20.0, True),    # Rs50 ... over it
    (1000.0, 0.0, True),     # spent, bought no FTEWV at all -- the worst case
    (0.0, 0.0, None),        # did not spend -- the window says nothing
    (None, None, None),
])
def test_expensive_reads_a_window(spend, ftewv, expected):
    assert _ftewv_expensive(spend, ftewv, 25.0) is expected


class TestKillGate:
    """A pause needs BOTH windows over the account's benchmark."""

    def test_pause_when_both_windows_are_over(self):
        assert verdict(0.5, 0.5, RAHO, cpf3=20.0, cpf7=25.0) == "PAUSE"

    def test_report_when_both_windows_are_under(self):
        assert verdict(0.5, 0.5, RAHO, cpf3=9.0, cpf7=11.0) == "REPORT"

    def test_monitor_when_only_the_7d_window_is_over(self):
        # The case the change exists for: 7D still expensive, but the
        # last three days have already come back under the benchmark.
        assert verdict(0.5, 0.5, RAHO, cpf3=13.0, cpf7=16.0) == "MONITOR"

    def test_monitor_when_only_the_3d_window_is_over(self):
        assert verdict(0.5, 0.5, RAHO, cpf3=16.0, cpf7=13.0) == "MONITOR"

    def test_the_benchmark_that_applies_is_the_account_s_own(self):
        # Rs13 on both windows: over Fourth's Rs12, under Raho's Rs15.
        assert verdict(0.5, 0.5, FOURTH, cpf3=13.0, cpf7=13.0) == "PAUSE"
        assert verdict(0.5, 0.5, RAHO, cpf3=13.0, cpf7=13.0) == "REPORT"

    def test_spending_with_no_ftewv_counts_as_over(self):
        assert verdict(0.5, 0.5, RAHO, cpf3=None, cpf7=None) == "PAUSE"

    def test_a_silent_window_is_not_a_kill(self):
        # Spent nothing in the last 3 days: nothing to be over or under,
        # so the windows cannot agree and it holds.
        assert verdict(0.5, 0.5, RAHO, cpf3=0, cpf7=25.0) == "MONITOR"


class TestOtherVerdicts:
    def test_scale_is_independent_of_the_ftewv_gate(self):
        # Over the benchmark on both windows and still a SCALE: the
        # framework says kill criteria must not be applied to it.
        assert verdict(3.0, 3.0, RAHO, cpf3=99.0, cpf7=99.0) == "SCALE"

    def test_monitor_when_the_3d_roas_has_recovered(self):
        assert verdict(2.0, 0.5, RAHO, cpf3=99.0, cpf7=99.0) == "MONITOR"

    def test_ok_between_the_thresholds(self):
        assert verdict(2.0, 2.0, RAHO, cpf3=99.0, cpf7=99.0) == "OK"

    def test_unrated_without_a_roas_window(self):
        # Not a default verdict: an ad set that did not run in the last
        # three days must not be pause-recommended for being new.
        assert verdict(None, 0.5, RAHO, cpf3=99.0, cpf7=99.0) is None
        assert verdict(0.5, None, RAHO, cpf3=99.0, cpf7=99.0) is None

    def test_the_thresholds_are_the_documented_ones(self):
        assert (_SCALE_ROAS, _KILL_ROAS) == (2.5, 1.5)


def test_every_branch_states_a_reason():
    for args in [(3.0, 3.0), (0.5, 0.5), (2.0, 0.5), (2.0, 2.0)]:
        _v, why = _decide(*args, RAHO, d3_spend=1000.0, d3_ftewv=50.0,
                          d7_spend=1000.0, d7_ftewv=50.0)
        assert why and len(why) > 10
