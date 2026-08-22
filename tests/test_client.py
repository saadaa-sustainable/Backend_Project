"""Unit tests for the generic Meta API client: success, retry/backoff,
rate-limit handling, permanent errors, and pagination — all against a
mocked transport via ``respx``, no network access required.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import MetaAPISettings
from app.core.exceptions import MetaPermanentError, MetaRateLimitError
from app.core.security import MetaCredentials
from app.services.meta.client import MetaAPIClient

pytestmark = pytest.mark.asyncio


def _fast_settings(**overrides: object) -> MetaAPISettings:
    """Settings tuned for tests: tiny backoff delays so retry tests run fast."""
    values: dict[str, object] = {
        "META_ACCESS_TOKEN": "test-token",
        "META_API_VERSION": "v21.0",
        "META_MAX_RETRIES": 2,
        "META_RETRY_BACKOFF_BASE_SECONDS": 0.01,
        "META_RETRY_BACKOFF_MAX_SECONDS": 0.02,
        "META_RATE_LIMIT_SLEEP_BUFFER_SECONDS": 0.01,
        "META_HTTP_TIMEOUT_SECONDS": 5,
        "META_HTTP_CONNECT_TIMEOUT_SECONDS": 2,
        "META_PAGE_SIZE": 25,
        "META_MAX_CONCURRENT_REQUESTS": 4,
    }
    values.update(overrides)
    return MetaAPISettings(**values)


@respx.mock
async def test_get_returns_parsed_json(credentials: MetaCredentials) -> None:
    respx.get("https://graph.facebook.com/v21.0/act_1234567890/campaigns").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "1", "name": "Campaign 1"}], "paging": {}}
        )
    )
    async with MetaAPIClient(credentials, settings=_fast_settings()) as client:
        result = await client.get("act_1234567890/campaigns")

    assert result["data"][0]["id"] == "1"


@respx.mock
async def test_transient_500_is_retried_then_succeeds(credentials: MetaCredentials) -> None:
    route = respx.get("https://graph.facebook.com/v21.0/act_1234567890/campaigns")
    route.side_effect = [
        httpx.Response(500, json={"error": {"message": "internal error"}}),
        httpx.Response(200, json={"data": [{"id": "1"}], "paging": {}}),
    ]
    async with MetaAPIClient(credentials, settings=_fast_settings()) as client:
        result = await client.get("act_1234567890/campaigns")

    assert result["data"][0]["id"] == "1"
    assert route.call_count == 2


@respx.mock
async def test_rate_limit_error_code_is_retried_then_succeeds(
    credentials: MetaCredentials,
) -> None:
    route = respx.get("https://graph.facebook.com/v21.0/act_1234567890/campaigns")
    route.side_effect = [
        httpx.Response(400, json={"error": {"code": 4, "message": "User request limit reached"}}),
        httpx.Response(200, json={"data": [{"id": "1"}], "paging": {}}),
    ]
    async with MetaAPIClient(credentials, settings=_fast_settings()) as client:
        result = await client.get("act_1234567890/campaigns")

    assert result["data"][0]["id"] == "1"
    assert route.call_count == 2


@respx.mock
async def test_rate_limit_exhausts_retries_raises_typed_error(
    credentials: MetaCredentials,
) -> None:
    respx.get("https://graph.facebook.com/v21.0/act_1234567890/campaigns").mock(
        return_value=httpx.Response(
            400, json={"error": {"code": 613, "message": "Calls have exceeded the rate limit"}}
        )
    )
    async with MetaAPIClient(credentials, settings=_fast_settings(META_MAX_RETRIES=1)) as client:
        with pytest.raises(MetaRateLimitError):
            await client.get("act_1234567890/campaigns")


@respx.mock
async def test_buc_ads_insights_rate_limit_code_is_recognized_and_retried(
    credentials: MetaCredentials,
) -> None:
    """80000 is Meta's Business Use Case error code for Ads Insights
    throttling (see developers.facebook.com/docs/graph-api/overview/
    rate-limiting#buc-rate-limits) — the endpoint this service calls most.
    Before this code was added to RATE_LIMIT_ERROR_CODES, a BUC throttle
    here would have fallen through to MetaPermanentError (non-retryable)
    instead of being retried with backoff."""
    route = respx.get("https://graph.facebook.com/v21.0/act_1234567890/insights")
    route.side_effect = [
        httpx.Response(
            400,
            json={
                "error": {
                    "code": 80000,
                    "error_subcode": 2446079,
                    "message": "Too many calls to this ads-insights endpoint",
                }
            },
        ),
        httpx.Response(200, json={"data": [{"id": "1"}], "paging": {}}),
    ]
    async with MetaAPIClient(credentials, settings=_fast_settings()) as client:
        result = await client.get("act_1234567890/insights")

    assert result["data"][0]["id"] == "1"
    assert route.call_count == 2


@respx.mock
async def test_rate_limit_prefers_estimated_time_to_regain_access_over_backoff(
    credentials: MetaCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the HTTP Retry-After header is absent but the
    X-Business-Use-Case-Usage header reports
    estimated_time_to_regain_access (in minutes per Meta's docs), that
    value should drive the backoff instead of the generic exponential
    fallback."""
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.meta.client.asyncio.sleep", _fake_sleep)

    respx.get("https://graph.facebook.com/v21.0/act_1234567890/insights").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": 80000, "message": "Too many calls"}},
            headers={
                "X-Business-Use-Case-Usage": json.dumps(
                    {
                        "1234567890": [
                            {
                                "type": "ads_insights",
                                "call_count": 100,
                                "estimated_time_to_regain_access": 2,
                            }
                        ]
                    }
                )
            },
        )
    )
    async with MetaAPIClient(credentials, settings=_fast_settings(META_MAX_RETRIES=1)) as client:
        with pytest.raises(MetaRateLimitError) as exc_info:
            await client.get("act_1234567890/insights")

    # estimated_time_to_regain_access=2 minutes -> 120 seconds exactly.
    assert exc_info.value.retry_after_seconds == 120.0
    # Every sleep triggered along the way (proactive usage-threshold wait
    # and/or reactive backoff) should be driven by that 120s, never by the
    # tiny synthetic exponential-backoff fallback this test's settings
    # would otherwise produce.
    assert sleep_calls
    assert all(seconds >= 120.0 for seconds in sleep_calls)


@respx.mock
async def test_permanent_error_raises_immediately_without_retry(
    credentials: MetaCredentials,
) -> None:
    route = respx.get("https://graph.facebook.com/v21.0/act_1234567890/campaigns").mock(
        return_value=httpx.Response(
            400, json={"error": {"code": 100, "message": "Invalid parameter"}}
        )
    )
    async with MetaAPIClient(credentials, settings=_fast_settings()) as client:
        with pytest.raises(MetaPermanentError):
            await client.get("act_1234567890/campaigns")

    assert route.call_count == 1


@respx.mock
async def test_paginate_follows_next_cursor_across_pages(credentials: MetaCredentials) -> None:
    page_one_url = "https://graph.facebook.com/v21.0/act_1234567890/campaigns"
    page_two_url = "https://graph.facebook.com/v21.0/act_1234567890/campaigns?after=CURSOR2"

    respx.get(page_one_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "1"}, {"id": "2"}],
                "paging": {"cursors": {"after": "CURSOR2"}, "next": page_two_url},
            },
        )
    )
    respx.get(page_two_url).mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "3"}], "paging": {"cursors": {"after": "CURSOR3"}}}
        )
    )

    async with MetaAPIClient(credentials, settings=_fast_settings()) as client:
        items = [item async for item in client.paginate("act_1234567890/campaigns", page_size=2)]

    assert [item["id"] for item in items] == ["1", "2", "3"]
