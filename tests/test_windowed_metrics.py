"""A windowed metric must describe its window, or be zero.

The rollup used to read COALESCE(w.spend, i.spend): the window's daily
sum, falling back to the entity's LIFETIME figure. The fallback was
justified as covering "entities the daily table has not seen", but the
daily tables start 2025-12-31, before the 2026-01-01 data floor, so no
window the picker can produce is uncovered.

What it actually caught was entities with no activity IN THE WINDOW,
and for those it printed their whole lifetime under the window's own
date_start and date_stop. Measured 2026-09-24 on a 7-day window: 114 ad
sets and 20 campaigns reported lifetime as window, inflating 7-day ad
set spend by 82%. One paused ad set reported Rs 2.95L of spend and
1.36M impressions for a week Meta charged nothing for.

The error grew as the window shrank -- worst on the 3 and 7 day views
the pause and scale rules read, invisible on the lifetime preset where
the window covers everything and the fallback never fires.
"""

import re

from app.api.routers.analytics import get_ads_analyse_rollup


def _source() -> str:
    """The function's CODE, with comments stripped.

    The comment explaining this bug quotes the broken shape verbatim,
    so a scan over raw source matches the prose describing the fix and
    fails on the very text that documents it.
    """
    import inspect
    lines = []
    for line in inspect.getsource(get_ads_analyse_rollup).splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def test_no_windowed_metric_falls_back_to_lifetime():
    src = _source()
    # COALESCE(w.<metric>, i.<anything>) is the shape of the bug: the
    # window's value with the lifetime row standing in behind it.
    offenders = re.findall(r"COALESCE\(w\.\w+,\s*i\.\w+\)", src)
    assert not offenders, (
        "a windowed metric falls back to its lifetime value: "
        f"{sorted(set(offenders))}. An entity that did not run in the "
        "window spent nothing in it -- the fallback is 0."
    )


def test_the_jsonb_derived_metrics_do_not_fall_back_either():
    src = _source()
    # purchases and conv_value are extracted from the lifetime insights
    # row's JSONB, so their fallback is an interpolated expression
    # rather than a plain column and the regex above cannot see it.
    for metric in ("purchases", "conv_value"):
        bad = re.findall(rf"COALESCE\(w\.{metric},\s*\{{{metric}\}}\)", src)
        assert not bad, f"w.{metric} still falls back to the lifetime figure"
        assert f"COALESCE(w.{metric}, 0)" in src, (
            f"w.{metric} should fall back to 0"
        )


def test_reach_never_fell_back_and_still_does_not():
    # Reach was already correct: i.reach describes the insights row's
    # own window, so mixing it into a different one is the same defect.
    assert "COALESCE(w.reach" not in _source()
