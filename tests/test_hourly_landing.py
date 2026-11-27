"""The three writers of hourly_landing_tracker must agree on the page key.

Sessions come from ShopifyQL's landing_page_path, orders from the order's
own full_url, spend from the ad creative's URL. All three go through
page_path(). If any one of them stopped, a page would be split in two
and every rate on the row would be computed against the wrong half.
"""
from datetime import date, timezone

import pytest

from app.services.gold.cpis import page_path
from scripts.refresh_hourly_landing import ist_hour_utc, to_ist_hour


def test_the_three_sources_land_on_one_key():
    ad = "https://saadaa.in/collections/the-formal-pants?utm_source=META&utm_id=1"
    order = ("https://saadaa.in/collections/the-formal-pants"
             "?utm_source=META&utm_medium=Facebook_Mobile_Reels&ad_id=120")
    session = "/collections/the-formal-pants"
    assert (page_path(ad) == page_path(order) == page_path(session)
            == "/collections/the-formal-pants")


def test_collection_product_url_collapses_the_same_way_everywhere():
    # Shopify serves a product under a collection at both URLs, so the
    # two must not become two rows.
    assert page_path("https://saadaa.in/collections/men/products/cotton-pant") \
        == page_path("/collections/men/products/cotton-pant") \
        == page_path("/products/cotton-pant") == "/products/cotton-pant"


def test_offsite_and_empty_are_dropped():
    for bad in ["https://wa.me/91999", "", None]:
        assert page_path(bad) in (None, "OFFSITE"), bad


def test_hour_is_the_ist_hour_as_a_utc_instant():
    # IST is UTC+5:30, so 00:00 IST is 18:30 UTC the day before. Getting
    # this wrong shifts every hour of the dashboard by 5h30m.
    assert ist_hour_utc(date(2026, 11, 27), 0).isoformat() == "2026-11-26T18:30:00+00:00"
    assert ist_hour_utc(date(2026, 11, 27), 14).isoformat() == "2026-11-27T08:30:00+00:00"
    assert ist_hour_utc(date(2026, 11, 27), 23).tzinfo is timezone.utc


def test_an_instant_floors_to_its_ist_hour():
    from datetime import datetime

    # 04:17 UTC is 09:47 IST, so it belongs to the 09:00 IST bucket --
    # which is stored as 03:30 UTC, NOT 04:00. An IST hour does not
    # start on a UTC hour, and rounding to one shifts half the day.
    got = to_ist_hour(datetime.fromisoformat("2026-11-27T04:17:03+00:00"))
    assert got.isoformat() == "2026-11-27T03:30:00+00:00"
    # An order placed at 00:12 IST belongs to that day's first bucket,
    # not to the previous UTC day.
    got2 = to_ist_hour(datetime.fromisoformat("2026-11-26T18:42:00+00:00"))
    assert got2.isoformat() == "2026-11-26T18:30:00+00:00"


# ---------------------------------------------------------------- spend by order
def test_an_ads_spend_is_conserved_when_split_over_pages():
    """The share arithmetic must not create or lose spend."""
    from refresh_hourly_landing import _shares

    shares = _shares({"/products/a": 3, "/collections/b": 1})
    assert shares == {"/products/a": 0.75, "/collections/b": 0.25}
    spend = 1000.0
    assert sum(spend * sh for sh in shares.values()) == pytest.approx(spend)


def test_an_ad_with_no_orders_gets_no_share():
    from refresh_hourly_landing import _shares

    assert _shares({}) == {}
    assert _shares({"/products/a": 0}) == {}


def test_only_a_plain_numeric_utm_content_is_taken_as_an_ad_id():
    """utm_content is frozen at click time and sometimes holds the ad
    NAME. It can also arrive padded, which a `!~ '[^0-9]'` test in SQL
    silently rejects -- the reason this gate is a Python regex."""
    from refresh_hourly_landing import AD_ID_RE

    assert AD_ID_RE.match("120253055134380431")
    assert AD_ID_RE.match("649815036937")
    assert not AD_ID_RE.match("sag_organic")
    assert not AD_ID_RE.match("AI_69d64fdaa45cd78a794717bf")
    assert not AD_ID_RE.match("12345")                      # too short
    assert not AD_ID_RE.match("120253055134380431 ")        # padded
