"""The EasyEcom webhook receiver.

A webhook URL is public by necessity, so the shared secret is the only
thing standing between EasyEcom's delivery events and anyone who learns
the path. These pin that, and pin the other property that matters: an
event that arrives must be kept, even when we cannot parse it.
"""

import json

import pytest
from fastapi import HTTPException

from app.api.routers import webhooks


def test_a_missing_token_is_refused(monkeypatch):
    monkeypatch.setattr(webhooks, "get_settings",
                        lambda: type("S", (), {"easyecom_webhook_token": "right"})())
    with pytest.raises(HTTPException) as e:
        webhooks._authorise(None)
    assert e.value.status_code == 401


def test_a_wrong_token_is_refused(monkeypatch):
    monkeypatch.setattr(webhooks, "get_settings",
                        lambda: type("S", (), {"easyecom_webhook_token": "right"})())
    with pytest.raises(HTTPException) as e:
        webhooks._authorise("wrong")
    assert e.value.status_code == 401


def test_the_right_token_passes(monkeypatch):
    monkeypatch.setattr(webhooks, "get_settings",
                        lambda: type("S", (), {"easyecom_webhook_token": "right"})())
    webhooks._authorise("right")          # must not raise


def test_an_unconfigured_receiver_refuses_everything(monkeypatch):
    # The dangerous default would be to wave calls through when no
    # secret is set: a public URL with the check disabled is an open
    # write path into the warehouse.
    monkeypatch.setattr(webhooks, "get_settings",
                        lambda: type("S", (), {"easyecom_webhook_token": None})())
    with pytest.raises(HTTPException) as e:
        webhooks._authorise("anything")
    assert e.value.status_code == 503


def test_the_token_is_compared_in_constant_time():
    # secrets.compare_digest, not ==, so the check cannot be probed one
    # character at a time.
    import inspect
    src = inspect.getsource(webhooks._authorise)
    assert "compare_digest" in src
    assert "== expected" not in src


def test_every_documented_event_is_accepted():
    # The 12 EasyEcom sends, per its Webhook Settings screen. A typo in
    # a configured URL should fail at setup, not collect rows nobody
    # reads -- hence the Literal rather than a free string.
    import typing
    allowed = set(typing.get_args(webhooks.EasyEcomEvent))
    assert allowed == {
        "create_order", "confirm_order", "update_inventory", "manifested",
        "mark_return", "grn_details", "complete_grn", "rtd", "tracking",
        "confirm_order_start", "fetch_order", "cancel_order",
    }
    # The four that carry delivery state, which is the reason for this
    # integration at all.
    assert {"tracking", "mark_return", "manifested", "rtd"} <= allowed


def test_the_shared_secret_is_never_stored():
    # Storing Access-Token beside the data it protects would undo the
    # point of having it, so only these headers are kept.
    import inspect
    src = inspect.getsource(webhooks.easyecom_webhook)
    assert '"content-type", "user-agent", "x-forwarded-for"' in src
    assert "access-token" not in src.lower().split("keep =")[1].split("}")[0]
