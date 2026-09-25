"""Excluding a new ad set must hide exactly the rows wearing the badge.

The rollup marks entities Meta created in the last _NEW_ENTITY_DAYS
with a NEW badge, because a pause on something three days old is a
decision to stop a test, not a verdict on performance. The filter that
hides them has to be built from the SAME expression the badge is: if
the two drift, "exclude new" hides rows that are not badged new, and
nothing on screen explains why they went.

Measured 2026-09-25: 36 of 3,030 ad sets and 10 of 530 campaigns sit
inside the window.
"""

import inspect
import re

import pytest

from app.api.routers.analytics import (
    _NEW_ENTITY_DAYS,
    _is_new_entity_sql,
    get_ads_analyse_rollup,
)


def _source() -> str:
    src = inspect.getsource(get_ads_analyse_rollup)
    return "\n".join(
        re.sub(r"#.*$", "", ln) for ln in src.splitlines()
    )


@pytest.mark.parametrize("level,table,key", [
    ("adset", "public.meta_adsets", "adset_id"),
    ("campaign", "public.meta_campaigns", "campaign_id"),
])
def test_expression_reads_the_right_entity_table(level, table, key):
    sql = _is_new_entity_sql(level, key)
    assert table in sql
    assert f"n.{key} = i.{key}" in sql
    assert f"- {_NEW_ENTITY_DAYS}" in sql


def test_expression_is_correlated_not_joined():
    """The count and summary queries build their own FROM. A joined
    alias would be out of scope there and the filter would 500."""
    sql = _is_new_entity_sql("adset", "adset_id")
    assert sql.strip().startswith("COALESCE((SELECT")
    assert " JOIN " not in sql.upper()


def test_expression_never_returns_null():
    """An entity Meta has no created_time for must be treated as NOT
    new, so it survives an exclude and is reachable. NULL would drop it
    from both 'exclude' and 'only' and it would be unreachable."""
    assert _is_new_entity_sql("adset", "adset_id").startswith("COALESCE(")
    assert ", false)" in _is_new_entity_sql("adset", "adset_id")


def test_badge_and_filter_use_one_expression():
    """Both call the helper -- neither spells the predicate inline."""
    src = _source()
    assert "_is_new_entity_sql(level, id_col)" in src
    assert src.count("_is_new_entity_sql(level, id_col)") >= 2, (
        "the badge and the filter must both read the helper")
    # the old inline form must be gone
    assert "AS is_new_entity" in src
    assert "s3.created_time" not in src and "c3.created_time" not in src


def test_only_is_the_predicate_and_exclude_is_its_negation():
    src = _source()
    assert 'where.append(expr if new_entities == "only" else f"NOT {expr}")' in src


def test_filter_is_rejected_when_it_is_not_one_of_the_two_values():
    """A typo must 422 rather than silently returning everything."""
    ann = get_ads_analyse_rollup.__annotations__["new_entities"]
    assert "exclude" in str(ann) and "only" in str(ann)


def test_filter_defaults_to_showing_everything():
    sig = inspect.signature(get_ads_analyse_rollup)
    assert sig.parameters["new_entities"].default.default is None
