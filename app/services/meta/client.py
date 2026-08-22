"""Generic, reusable async client for the Meta Marketing (Graph) API.

Every ingestion service goes through this single client rather than calling
``httpx`` directly, so pagination, retries, backoff, rate-limit handling,
timeouts, and structured logging/tracing are implemented exactly once and
apply uniformly to every endpoint.

Design notes
------------
* :meth:`get` performs a single request and returns the parsed JSON body.
* :meth:`paginate` follows Meta's cursor-based ``paging.next`` links and
  yields individual ``data`` items lazily, so callers can stream arbitrarily
  large result sets into the database without holding them all in memory.
* :meth:`batch` uses the Graph API Batch endpoint to fold up to 50 requests
  into a single HTTP round trip.
* Rate limiting is handled two ways: proactively, by inspecting Meta's
  ``X-App-Usage`` / ``X-Ad-Account-Usage`` / ``X-Business-Use-Case-Usage``
  response headers and sleeping before we get throttled, and reactively, by
  catching Meta's rate-limit error codes/HTTP 429 and backing off.

Rate-limit references
----------------------
Meta enforces two independent kinds of limit, and documents that Business
Use Case (BUC) limits are applied in preference to platform/app-level
limits whenever both could apply to a request:
https://developers.facebook.com/docs/graph-api/overview/rate-limiting#buc-rate-limits

* **Platform (app-level)**: reported via ``X-App-Usage``
  (``call_count`` / ``total_time`` / ``total_cputime``, each a percentage
  of a rolling 1-hour window), signaled by the legacy error codes in
  :data:`PLATFORM_RATE_LIMIT_ERROR_CODES`.
* **Business Use Case (per ad account / page / business)**: reported via
  ``X-Business-Use-Case-Usage`` — one entry per BUC ``type`` touched by the
  request (``ads_insights``, ``ads_management``, ``instagram``, ...), each
  with the same three percentage fields *plus*
  ``estimated_time_to_regain_access`` (minutes until throttling ends —
  Meta's own recommended value for backoff timing, used here in preference
  to a synthetic exponential backoff whenever it's present) and
  ``ads_api_access_tier``. Signaled by :data:`BUC_RATE_LIMIT_ERROR_CODES` —
  ``80000`` (Ads Insights) is the one this service is most likely to hit,
  since Insights is the highest-volume endpoint it calls.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx

from app.config import MetaAPISettings, get_settings
from app.core.exceptions import (
    MetaAuthenticationError,
    MetaPaginationError,
    MetaPermanentError,
    MetaPermissionError,
    MetaRateLimitError,
    MetaTransientError,
)
from app.core.security import MetaCredentials, get_meta_credentials
from app.logging.setup import get_logger

logger = get_logger(__name__)

#: Legacy/platform-level throttling codes (X-App-Usage territory) — predate
#: Business Use Case limits but still apply. 32 covers "Page (User access
#: token)" BUC throttling specifically per Meta's rate-limiting docs, so it
#: is deliberately listed here even though it overlaps conceptually with
#: BUC_RATE_LIMIT_ERROR_CODES below.
PLATFORM_RATE_LIMIT_ERROR_CODES: frozenset[int] = frozenset({4, 17, 32, 613})

#: Business Use Case (BUC) rate-limit codes, from Meta's Business Use Case
#: rate limiting reference (see module docstring for the URL). These are
#: what a Marketing API client actually hits in practice — 80000 (Ads
#: Insights) especially — and were previously NOT recognized as rate-limit
#: errors by this client, meaning a BUC throttle on Insights would have
#: fallen through to MetaPermanentError (non-retryable) instead of
#: MetaRateLimitError (retried with backoff).
BUC_RATE_LIMIT_ERROR_CODES: frozenset[int] = frozenset(
    {
        80000,  # Ads Insights
        80001,  # Page (Page/System User token)
        80002,  # Instagram
        80003,  # Custom Audience
        80004,  # Ads Management
        80005,  # LeadGen
        80006,  # Messenger
        80008,  # v3.3 and older Ads API
        80009,  # Catalog Batch
        80014,  # WhatsApp Business Management / Catalog Management
    }
)

RATE_LIMIT_ERROR_CODES: frozenset[int] = (
    PLATFORM_RATE_LIMIT_ERROR_CODES | BUC_RATE_LIMIT_ERROR_CODES
)

#: `error_subcode` 2446079 co-occurs with the Ads Insights / Ads Management /
#: Custom Audience BUC codes (80000 / 80004 / 80003) per Meta's docs. Not
#: every BUC code documents a subcode, so subcode is only ever a secondary
#: signal here, never required for detection. 1487742 is a defensive extra
#: carried over from general Graph API error-code references — it is not
#: confirmed on the BUC rate-limiting page itself.
RATE_LIMIT_ERROR_SUBCODES: frozenset[int] = frozenset({2446079, 1487742})

#: Codes that mean "your token/app is not authorized" — never retryable.
AUTH_ERROR_CODES: frozenset[int] = frozenset({190})
PERMISSION_ERROR_CODES: frozenset[int] = frozenset({10, 200, 299})

#: HTTP statuses worth retrying with backoff (transient server/network issues).
RETRYABLE_HTTP_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_USAGE_HEADERS: tuple[str, ...] = (
    "x-app-usage",
    "x-ad-account-usage",
    "x-business-use-case-usage",
)
#: Proactively pause once any usage metric crosses this percentage.
USAGE_THROTTLE_THRESHOLD = 90.0


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """JSON-encode list/dict values per Graph API convention for array- and
    object-typed parameters (e.g. ``effective_status``, ``breakdowns``,
    ``action_attribution_windows``, ``time_range``), so service code can
    pass native Python lists/dicts instead of hand-building query strings.
    Scalars pass through untouched.
    """
    normalized: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, dict)):
            normalized[key] = json.dumps(value)
        elif isinstance(value, bool):
            normalized[key] = "true" if value else "false"
        else:
            normalized[key] = value
    return normalized


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """A summary of Meta's self-reported usage across whichever of
    ``X-App-Usage`` / ``X-Ad-Account-Usage`` / ``X-Business-Use-Case-Usage``
    were present on a response. See the module docstring for field
    semantics and the Business Use Case rate-limiting reference.
    """

    #: Highest of call_count / total_time / total_cputime seen across every
    #: usage entry in the response, as a percentage (0-100+).
    max_percentage: float
    #: From `estimated_time_to_regain_access` — BUC header only, converted
    #: minutes -> seconds. The most conservative (largest) value seen
    #: across every BUC entry in the response. `None` if Meta didn't report
    #: one (this field never appears on `X-App-Usage`).
    estimated_wait_seconds: float | None
    #: From `ads_api_access_tier` — BUC header only ("development_access" |
    #: "standard_access"). Logged for operator visibility; the client does
    #: not change behavior based on it, but a persistently low rate-limit
    #: ceiling is diagnosable from this without an extra API call.
    access_tier: str | None


def _parse_usage_snapshot(headers: httpx.Headers) -> UsageSnapshot:
    """Inspect Meta's usage headers and build a :class:`UsageSnapshot` used
    both for proactive throttling (`max_percentage`) and for precise
    backoff timing (`estimated_wait_seconds`) when a request turns out to
    be rate-limited."""
    max_percentage = 0.0
    estimated_wait_seconds: float | None = None
    access_tier: str | None = None

    for header_name in _USAGE_HEADERS:
        raw = headers.get(header_name)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        candidates: list[dict[str, Any]] = []
        if isinstance(parsed, dict) and "call_count" in parsed:
            candidates = [parsed]
        elif isinstance(parsed, dict):
            # X-Business-Use-Case-Usage keys by object id -> list[dict],
            # one entry per Business Use Case `type` touched by the request
            # (e.g. "ads_insights", "ads_management").
            for value in parsed.values():
                if isinstance(value, list):
                    candidates.extend(value)
                elif isinstance(value, dict):
                    candidates.append(value)

        for candidate in candidates:
            for key in ("call_count", "total_time", "total_cputime"):
                value = candidate.get(key)
                if isinstance(value, (int, float)):
                    max_percentage = max(max_percentage, float(value))

            wait_minutes = candidate.get("estimated_time_to_regain_access")
            if isinstance(wait_minutes, (int, float)):
                wait_seconds = float(wait_minutes) * 60
                estimated_wait_seconds = max(estimated_wait_seconds or 0.0, wait_seconds)

            tier = candidate.get("ads_api_access_tier")
            if access_tier is None and isinstance(tier, str):
                access_tier = tier

    return UsageSnapshot(
        max_percentage=max_percentage,
        estimated_wait_seconds=estimated_wait_seconds,
        access_tier=access_tier,
    )


class MetaAPIClient:
    """Async client exposing generic, reusable access to any Graph API node/edge."""

    def __init__(
        self,
        credentials: MetaCredentials | None = None,
        settings: MetaAPISettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.credentials = credentials or get_meta_credentials()
        self.settings = settings or get_settings().meta
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                self.settings.http_timeout_seconds,
                connect=self.settings.http_connect_timeout_seconds,
            )
        )
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_requests)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()

    # ----------------------------------------------------------------
    # Low-level request execution with retry / backoff / rate limiting
    # ----------------------------------------------------------------

    def _url_for(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.credentials.base_url}/{path.lstrip('/')}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a single logical request against the Graph API, retrying
        transient/rate-limit failures with exponential backoff. Returns the
        parsed JSON response body. Raises a :class:`MetaAPIError` subclass
        on unrecoverable failure.
        """
        request_id = str(uuid.uuid4())
        url = self._url_for(path)
        request_params = {
            **self.credentials.auth_params(),
            **_normalize_params(params or {}),
        }

        attempt = 0
        last_exc: Exception | None = None

        while attempt <= self.settings.max_retries:
            attempt += 1
            log = logger.bind(
                request_id=request_id,
                method=method,
                path=path,
                attempt=attempt,
                max_retries=self.settings.max_retries,
            )
            try:
                async with self._semaphore:
                    log.debug("meta_api_request_start")
                    response = await self._http_client.request(
                        method,
                        url,
                        params=request_params,
                        json=json_body,
                    )
            except httpx.TimeoutException as exc:
                last_exc = exc
                log.warning("meta_api_timeout", error=str(exc))
                await self._sleep_backoff(attempt)
                continue
            except httpx.TransportError as exc:
                last_exc = exc
                log.warning("meta_api_transport_error", error=str(exc))
                await self._sleep_backoff(attempt)
                continue

            usage = _parse_usage_snapshot(response.headers)
            if usage.max_percentage >= USAGE_THROTTLE_THRESHOLD:
                # Prefer Meta's own estimate of when throttling ends
                # (`estimated_time_to_regain_access`, the value their docs
                # recommend using for this) over the synthetic formula.
                if usage.estimated_wait_seconds:
                    sleep_for = (
                        usage.estimated_wait_seconds
                        + self.settings.rate_limit_sleep_buffer_seconds
                    )
                else:
                    sleep_for = self.settings.rate_limit_sleep_buffer_seconds * (
                        1 + usage.max_percentage / 100
                    )
                log.warning(
                    "meta_api_usage_near_limit_proactive_wait",
                    usage_pct=usage.max_percentage,
                    sleep_seconds=sleep_for,
                    estimated_wait_seconds=usage.estimated_wait_seconds,
                    access_tier=usage.access_tier,
                )
                await asyncio.sleep(sleep_for)

            try:
                body = response.json()
            except ValueError:
                body = {"raw_text": response.text}

            if response.status_code < 400:
                log.debug("meta_api_request_success", status_code=response.status_code)
                return body

            error = body.get("error", {}) if isinstance(body, dict) else {}
            error_code = error.get("code")
            error_subcode = error.get("error_subcode")
            fbtrace_id = error.get("fbtrace_id")
            message = error.get("message", response.text)

            is_rate_limited = (
                response.status_code == 429
                or error_code in RATE_LIMIT_ERROR_CODES
                or error_subcode in RATE_LIMIT_ERROR_SUBCODES
            )
            is_auth_error = error_code in AUTH_ERROR_CODES
            is_permission_error = error_code in PERMISSION_ERROR_CODES

            if is_auth_error:
                log.error("meta_api_authentication_error", message=message)
                raise MetaAuthenticationError(
                    message,
                    status_code_from_meta=response.status_code,
                    meta_error_code=error_code,
                    meta_error_subcode=error_subcode,
                    fbtrace_id=fbtrace_id,
                )
            if is_permission_error:
                log.error("meta_api_permission_error", message=message)
                raise MetaPermissionError(
                    message,
                    status_code_from_meta=response.status_code,
                    meta_error_code=error_code,
                    meta_error_subcode=error_subcode,
                    fbtrace_id=fbtrace_id,
                )
            if is_rate_limited:
                # Precedence: the HTTP-standard Retry-After header (rare for
                # Meta, mainly literal HTTP 429s) first; otherwise Meta's own
                # `estimated_time_to_regain_access` from the BUC usage header
                # on this same response — their docs call this out as the
                # accurate way to time backoff, so prefer it over the
                # synthetic exponential backoff `_sleep_backoff` falls back
                # to when both of these are unavailable.
                retry_after = response.headers.get("Retry-After")
                retry_after_seconds = (
                    float(retry_after) if retry_after else usage.estimated_wait_seconds
                )
                log.warning(
                    "meta_api_rate_limited",
                    message=message,
                    retry_after_seconds=retry_after_seconds,
                    access_tier=usage.access_tier,
                )
                if attempt > self.settings.max_retries:
                    raise MetaRateLimitError(
                        message,
                        retry_after_seconds=retry_after_seconds,
                        status_code_from_meta=response.status_code,
                        meta_error_code=error_code,
                        meta_error_subcode=error_subcode,
                        fbtrace_id=fbtrace_id,
                    )
                await self._sleep_backoff(attempt, retry_after_seconds=retry_after_seconds)
                continue

            if response.status_code in RETRYABLE_HTTP_STATUSES:
                log.warning("meta_api_transient_error", status_code=response.status_code, message=message)
                if attempt > self.settings.max_retries:
                    raise MetaTransientError(
                        message,
                        status_code_from_meta=response.status_code,
                        meta_error_code=error_code,
                        meta_error_subcode=error_subcode,
                        fbtrace_id=fbtrace_id,
                    )
                await self._sleep_backoff(attempt)
                continue

            log.error("meta_api_permanent_error", status_code=response.status_code, message=message)
            raise MetaPermanentError(
                message,
                status_code_from_meta=response.status_code,
                meta_error_code=error_code,
                meta_error_subcode=error_subcode,
                fbtrace_id=fbtrace_id,
            )

        raise MetaTransientError(
            f"Exhausted {self.settings.max_retries} retries without success: {last_exc}"
        )

    async def _sleep_backoff(
        self, attempt: int, *, retry_after_seconds: float | None = None
    ) -> None:
        if retry_after_seconds is not None:
            delay = retry_after_seconds + self.settings.rate_limit_sleep_buffer_seconds
        else:
            delay = min(
                self.settings.retry_backoff_base_seconds * (2 ** (attempt - 1)),
                self.settings.retry_backoff_max_seconds,
            )
        logger.info("meta_api_backoff_sleep", attempt=attempt, delay_seconds=delay)
        await asyncio.sleep(delay)

    # ----------------------------------------------------------------
    # High-level generic accessors
    # ----------------------------------------------------------------

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform a single GET and return the parsed JSON body."""
        return await self.request("GET", path, params=params)

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        page_size: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield individual items from a ``{"data": [...], "paging": {...}}``
        response, transparently following ``paging.next`` cursors until
        exhausted. Streams lazily — never materializes the full result set.
        """
        request_params = {**(params or {}), "limit": page_size or self.settings.page_size}
        next_path: str | None = path
        next_params: dict[str, Any] | None = request_params
        pages_fetched = 0

        while next_path is not None:
            body = await self.get(next_path, params=next_params)
            data = body.get("data")
            if data is None:
                raise MetaPaginationError(
                    f"Expected a 'data' array in paginated response from {path}, got: {body!r}"
                )
            for item in data:
                yield item

            pages_fetched += 1
            paging = body.get("paging", {})
            cursors_next = paging.get("cursors", {}).get("after")
            next_url = paging.get("next")

            if next_url:
                # `next` is a fully-qualified URL that already embeds the
                # cursor + all original params; use it verbatim.
                next_path = next_url
                next_params = None
            elif cursors_next and len(data) == request_params["limit"]:
                next_params = {**request_params, "after": cursors_next}
                next_path = path
            else:
                next_path = None

        logger.debug("meta_api_pagination_complete", path=path, pages_fetched=pages_fetched)

    async def paginate_pages(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        page_size: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Like :meth:`paginate`, but yields whole page bodies (including
        ``paging``/summary metadata) instead of individual items — useful
        for Insights, where each page is itself the unit of persistence.
        """
        request_params = {**(params or {}), "limit": page_size or self.settings.page_size}
        next_path: str | None = path
        next_params: dict[str, Any] | None = request_params

        while next_path is not None:
            body = await self.get(next_path, params=next_params)
            yield body

            paging = body.get("paging", {})
            cursors_next = paging.get("cursors", {}).get("after")
            next_url = paging.get("next")
            data = body.get("data", [])

            if next_url:
                next_path = next_url
                next_params = None
            elif cursors_next and len(data) == request_params["limit"]:
                next_params = {**request_params, "after": cursors_next}
                next_path = path
            else:
                next_path = None

    async def batch(self, requests: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
        """Execute up to 50 sub-requests via the Graph API Batch endpoint in
        a single HTTP round trip. Each item in ``requests`` is a dict with
        ``method`` and ``relative_url`` keys (Meta batch request format).
        Returns one parsed body per sub-request, in order (``None`` for
        sub-requests Meta omitted from the response).
        """
        if len(requests) > 50:
            raise ValueError("Meta's Batch API accepts at most 50 requests per call.")

        response = await self.request(
            "POST",
            "",
            params={"include_headers": "false"},
            json_body={"batch": requests},
        )
        # The batch endpoint returns a top-level list, but `request()` always
        # returns a dict — handle both shapes defensively.
        raw_results = response if isinstance(response, list) else response.get("batch", [])

        parsed: list[dict[str, Any] | None] = []
        for item in raw_results:
            if item is None:
                parsed.append(None)
                continue
            try:
                parsed.append(json.loads(item["body"]))
            except (KeyError, ValueError, TypeError):
                parsed.append(None)
        return parsed

    # ----------------------------------------------------------------
    # Async Insights reports (POST -> poll -> GET), for large pulls
    # ----------------------------------------------------------------

    async def start_async_report(self, path: str, *, params: dict[str, Any]) -> str:
        """``POST`` an Insights request (same params as the synchronous
        ``GET``) and return the ``report_run_id`` Meta assigns to the async
        job. Use for large pulls — e.g. ``date_preset=maximum`` across a
        long-lived account — that risk timing out as a single synchronous
        request.
        """
        body = await self.request("POST", path, params=params)
        report_run_id = body.get("report_run_id")
        if not report_run_id:
            raise MetaTransientError(
                f"Meta did not return a report_run_id for async request to {path}: {body!r}"
            )
        return str(report_run_id)

    async def poll_async_report(
        self,
        report_run_id: str,
        *,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 3600.0,
    ) -> None:
        """Poll ``GET /<report_run_id>`` until Meta reports the async
        Insights job as complete. Raises :class:`MetaTransientError` if the
        job fails/is skipped, or if ``timeout_seconds`` elapses first (Meta
        documents async jobs as taking up to ~1 hour including retries).
        """
        elapsed = 0.0
        while True:
            status_body = await self.get(
                report_run_id, params={"fields": "async_status,async_percent_completion"}
            )
            status = status_body.get("async_status")
            percent = status_body.get("async_percent_completion")
            logger.info(
                "meta_async_report_poll",
                report_run_id=report_run_id,
                async_status=status,
                async_percent_completion=percent,
            )
            if status == "Job Completed":
                return
            if status in ("Job Failed", "Job Skipped"):
                raise MetaTransientError(
                    f"Async report {report_run_id} did not complete: status={status}"
                )
            if elapsed >= timeout_seconds:
                raise MetaTransientError(
                    f"Async report {report_run_id} did not complete within "
                    f"{timeout_seconds}s (last status={status}, {percent}% complete)."
                )
            await asyncio.sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds

    def paginate_async_report(
        self, report_run_id: str, *, page_size: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream results from a completed async report. Call only after
        :meth:`poll_async_report` returns without raising."""
        return self.paginate(f"{report_run_id}/insights", page_size=page_size)
