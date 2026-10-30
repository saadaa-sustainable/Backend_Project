"""Rank the day's utm_sources for the donut.

The per-hour sessions_by_source maps are the only place the raw tags
survive -- every other session column in the tracker is a bucket a
classifier produced from them. Getting this wrong would not raise; it
would quietly draw a ring that does not add up to the day.
"""
import pytest

from app.api.routers.analytics import _TOP_SOURCES, HourlyRow, _rank_sources


def row(hour: int, by_source: dict[str, int] | None) -> HourlyRow:
    """An hour carrying nothing but its source split.

    Every other field is filled with None off the model itself rather
    than listed here, so adding a metric to HourlyRow does not break
    this file.
    """
    fields = {k: None for k in HourlyRow.model_fields}
    return HourlyRow(**{
        **fields,
        "hour": f"2026-10-30T{hour:02d}:00:00+00:00",
        "day_ist": "2026-10-30",
        "hour_of_day": hour,
        "sessions": sum((by_source or {}).values()) or None,
        "sessions_by_source": by_source,
    })


def test_sums_across_hours():
    out = _rank_sources([row(1, {"meta": 10, "google": 3}),
                         row(2, {"meta": 5, "google": 1})])
    assert [(s.source, s.sessions) for s in out] == [("meta", 15), ("google", 4)]


def test_folds_case_variants_into_one_slice():
    """META/Meta/meta are one hand-typed tag, not three sources."""
    out = _rank_sources([row(1, {"META": 10, "Meta": 5, "  meta ": 2})])
    assert [(s.source, s.sessions) for s in out] == [("meta", 17)]


def test_blank_source_counts_as_direct():
    out = _rank_sources([row(1, {"": 4, "(direct)": 6})])
    assert [(s.source, s.sessions) for s in out] == [("(direct)", 10)]


def test_tail_folds_into_one_other_slice():
    by_source = {f"src{i}": 100 - i for i in range(12)}
    out = _rank_sources([row(1, by_source)])
    # Six slices at most: five named plus the fold. Any more and the
    # six-colour categorical palette would have to repeat a hue.
    assert len(out) == _TOP_SOURCES + 1
    assert out[-1].source == "other"
    assert out[-1].sessions == sum(sorted(by_source.values())[:-_TOP_SOURCES])


def test_no_other_slice_when_nothing_is_left_over():
    out = _rank_sources([row(1, {"a": 3, "b": 2})])
    assert [s.source for s in out] == ["a", "b"]


def test_shares_are_fractions_of_the_day_and_sum_to_one():
    out = _rank_sources([row(1, {f"src{i}": i + 1 for i in range(9)})])
    assert sum(s.share for s in out) == pytest.approx(1.0)
    total = sum(s.sessions for s in out)
    assert all(s.share == pytest.approx(s.sessions / total) for s in out)


def test_ties_break_by_name_so_colours_do_not_shuffle():
    """Equal sources must rank in a stable order.

    The page assigns colours by position, so an unstable sort would
    repaint a source a different colour between two refreshes that
    found the same numbers.
    """
    first = _rank_sources([row(1, {"zeta": 5, "alpha": 5, "mid": 5})])
    assert [s.source for s in first] == ["alpha", "mid", "zeta"]


def test_hours_without_a_source_map_are_skipped():
    """Rows written before the column existed are null, not empty."""
    out = _rank_sources([row(1, None), row(2, {"meta": 7}), row(3, {})])
    assert [(s.source, s.sessions) for s in out] == [("meta", 7)]


def test_a_day_with_no_sessions_yields_no_slices():
    assert _rank_sources([]) == []
    assert _rank_sources([row(1, {"meta": 0})]) == []
