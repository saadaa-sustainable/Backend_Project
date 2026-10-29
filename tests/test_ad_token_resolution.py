"""Resolving the tokens GA4 leaves in utm_content.

The field is whatever the ad's URL template produced, so the first-click
column holds ad ids, ad NAMES, third-party tokens and the occasional
unexpanded `{{ad.id}}`. Everything downstream joins ad_lifecycle on
ad_id, so a name never matched: those orders sat under a row labelled
with the raw name, carrying no spend and therefore no ROAS, while the
real ad's row was missing that revenue.

What must hold:

  * resolving moves revenue, it never creates or destroys any. Measured
    on 30 days of live data the first-click total is identical before
    and after -- Rs 2,88,09,186 both ways -- while the entity count
    drops from 1,979 to 1,968 and Rs 5.11 L lands on an ad that has
    spend and can therefore carry a ROAS.
  * an ambiguous name stays unresolved. One name here is shared by
    seventeen ads, and this codebase has already paid for a loose match
    once: colour tolerance in the CPIS SKU matcher would have moved
    Rs 12.8 L to the wrong SKU before longest-match was added.
  * a token that resolves to nothing survives the join. Those are real
    orders; dropping them would quietly shrink the section.
"""
import re

import pytest

from app.api.routers import analytics


def test_only_the_ad_grain_resolves_tokens():
    # utm_content is an AD field. Ad sets key on utm_term and sources on
    # a source string, neither of which carries this problem, so neither
    # pays for the join.
    assert "ad_token_resolution" in analytics._first_click_sql("ad", "order")
    assert "ad_token_resolution" not in analytics._first_click_sql("adset", "order")
    assert "ad_token_resolution" not in analytics._first_click_sql("source", "order")


@pytest.mark.parametrize("basis", ["order", "first_touch"])
def test_both_journey_ends_resolve_independently(basis):
    # Each side joins its own alias: a shared one would make the first
    # side's resolution decide the last side's entity.
    sql = analytics._first_click_sql("ad", basis)
    assert "ad_token_resolution rf ON rf.token = first_ad_id" in sql
    assert "ad_token_resolution rl ON rl.token = last_ad_id" in sql
    assert sql.count("ad_token_resolution") == 2


def test_an_unresolved_token_keeps_its_own_id():
    # COALESCE, not the resolved column alone. A third-party token
    # resolves to NULL, and taking that would drop the order instead of
    # showing it under the token somebody can still recognise.
    first, last = analytics._FIRST_CLICK_GRAINS["ad"]
    assert first == "COALESCE(rf.resolved_ad_id, first_ad_id)"
    assert last == "COALESCE(rl.resolved_ad_id, last_ad_id)"


def test_the_view_refuses_what_it_cannot_prove():
    from scripts.refresh_ad_token_resolution import VIEW

    # Only these two tiers produce a resolved id.
    assert "'name_unique'" in VIEW and "'name_spend'" in VIEW
    # An ambiguous name is labelled, never mapped.
    amb = VIEW.split("'name_ambiguous'")[0]
    assert "n_named = 1" in amb and "n_spent = 1" in amb
    # The CASE that picks resolved_ad_id must not have a branch for the
    # ambiguous case: reaching it means somebody guessed.
    picker = VIEW.split("END AS resolved_ad_id")[0]
    assert "name_ambiguous" not in picker
    assert "n_named = 1" in picker and "n_spent = 1" in picker


def test_the_match_is_window_free():
    from scripts.refresh_ad_token_resolution import VIEW

    # `name_spend` asks whether an ad EVER spent. Scoping it to a window
    # would make the same token resolve to different ads depending on
    # the date range a dashboard happened to request.
    spend_clause = VIEW.split("insights_daily_by_ad")[1].split(")")[0]
    assert "spend > 0" in spend_clause
    assert "day BETWEEN" not in spend_clause
    assert ":from_date" not in VIEW and ":to_date" not in VIEW


def test_both_journey_ends_are_collected():
    from scripts.refresh_ad_token_resolution import VIEW

    # A token can appear as a last click without ever being a first
    # click. Building the universe from first_ad_id alone would leave
    # the last-click column resolving against a shorter list.
    assert "SELECT first_ad_id AS token" in VIEW
    assert "SELECT last_ad_id FROM public.ga4_order_attribution" in VIEW
    assert re.search(r"UNION\s+SELECT last_ad_id", VIEW)


def test_the_unexpanded_macro_is_named_not_silently_dropped():
    from scripts.refresh_ad_token_resolution import VIEW

    # `{{ad.id}}` means the ad's URL template never expanded. It cannot
    # be fixed from data -- it needs correcting in Ads Manager -- so it
    # gets its own method rather than being lumped in with third-party
    # tokens where nobody would look for it.
    assert "'unexpanded_macro'" in VIEW
    assert "LIKE '{{%'" in VIEW
