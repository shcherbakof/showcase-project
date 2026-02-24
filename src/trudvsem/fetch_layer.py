# Docs:
# - artifacts/docs/data/3.1.4.1 Fetch-layer (MVP).md
# - artifacts/docs/data/3.1.9.1 Jupyter ручная отладка API -> RAW -> MON.md

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

import requests


LOGGER = logging.getLogger(__name__)


class FetchLayerError(RuntimeError):
    """Domain-level error for fetch-layer failures."""

    pass


class RetryableHttpExhaustedError(FetchLayerError):
    """Raised when retryable HTTP status exhausts all retry attempts."""

    def __init__(self, *, status: int, url: str) -> None:
        super().__init__(f"retryable HTTP status={status} exhausted attempts url={url}")
        self.status = status
        self.url = url


@dataclass(frozen=True)
class RetryConfig:
    """Retry and timeout settings for HTTP requests."""

    max_attempts: int = 5
    base_delay_sec: float = 0.5
    max_delay_sec: float = 30.0
    jitter_sec: float = 0.3
    timeout_sec: float = 30.0
    retryable_statuses: Sequence[int] = (429, 500, 502, 503, 504)


@dataclass(frozen=True)
class SafetyLimits:
    """Safety-stop thresholds to prevent unbounded fetch loops."""

    max_pages: int = 500
    max_items: int = 50_000


@dataclass(frozen=True)
class FetchConfig:
    """Configuration of endpoint, paging, retry strategy and safety limits."""

    base_url: str = "http://opendata.trudvsem.ru"
    endpoint: str = "/api/v1/vacancies"
    limit: int = 100
    offset_start: int = 1
    offset_step: Optional[int] = None
    static_params: Dict[str, Any] = field(default_factory=dict)
    source_system: str = "trudvsem"
    retry: RetryConfig = field(default_factory=RetryConfig)
    safety: SafetyLimits = field(default_factory=SafetyLimits)


@dataclass
class FetchDiagnostics:
    """Operational counters and events collected during fetch execution."""

    requests_total: int = 0
    requests_success: int = 0
    pages_fetched: int = 0
    items_extracted: int = 0
    retry_count: int = 0
    http_429_count: int = 0
    http_5xx_count: int = 0
    timeout_count: int = 0
    connection_error_count: int = 0
    parse_error_count: int = 0
    terminal_http_error_count: int = 0
    stopped_reason: Optional[str] = None
    events: List[str] = field(default_factory=list)

    def event(self, message: str) -> None:
        self.events.append(message)


@dataclass(frozen=True)
class FetchPage:
    """One fetched page with extracted items and request/response metadata."""

    items: List[Dict[str, Any]]
    request_params: Dict[str, Any]
    request_url: str
    http_status: int
    response_meta: Optional[Dict[str, Any]]
    raw_response: Dict[str, Any]


class TrudvsemFetcher:
    """Fetches vacancy pages with paging, retry and diagnostics."""

    def __init__(
        self,
        config: Optional[FetchConfig] = None,
        *,
        session: Optional[requests.Session] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.config = config or FetchConfig()
        self.session = session or requests.Session()
        self.sleep_fn = sleep_fn
        self.random_fn = random_fn
        self.diagnostics = FetchDiagnostics()

    def iter_pages(
        self,
        *,
        modified_from: Optional[str] = None,
        modified_to: Optional[str] = None,
        region_code: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Iterator[FetchPage]:
        """Yield pages from API until paging rule or safety-stop is reached."""

        params = dict(self.config.static_params)
        if extra_params:
            params.update(extra_params)
        if modified_from:
            params["modifiedFrom"] = self._normalize_api_datetime(modified_from)
        if modified_to:
            params["modifiedTo"] = self._normalize_api_datetime(modified_to)

        endpoint = self.config.endpoint
        if region_code:
            endpoint = f"{endpoint.rstrip('/')}/region/{region_code}"

        step = self.config.offset_step if self.config.offset_step is not None else 1
        offset = self.config.offset_start

        while True:
            if self.diagnostics.pages_fetched >= self.config.safety.max_pages:
                self.diagnostics.stopped_reason = "max_pages_reached"
                self.diagnostics.event("stopped by safety stop: max_pages reached")
                return
            if self.diagnostics.items_extracted >= self.config.safety.max_items:
                self.diagnostics.stopped_reason = "max_items_reached"
                self.diagnostics.event("stopped by safety stop: max_items reached")
                return

            request_params = dict(params)
            request_params["offset"] = offset
            request_params["limit"] = self.config.limit

            try:
                response = self._request_with_retry(endpoint=endpoint, params=request_params)
            except RetryableHttpExhaustedError as exc:
                # Source API can return persistent HTTP 500 when paging reaches the boundary
                # even though previous pages were valid. Treat this as a graceful end.
                if exc.status == 500 and self.diagnostics.pages_fetched > 0 and self.diagnostics.items_extracted > 0:
                    self.diagnostics.stopped_reason = "http_500_boundary_after_data"
                    self.diagnostics.event(f"stopped by source boundary: exhausted HTTP 500 at offset={offset}")
                    return
                raise

            payload = self._parse_json(response)
            items = self._extract_vacancies(payload)
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None

            page = FetchPage(
                items=items,
                request_params=request_params,
                request_url=response.url,
                http_status=response.status_code,
                response_meta=meta,
                raw_response=payload,
            )

            self.diagnostics.pages_fetched += 1
            self.diagnostics.items_extracted += len(items)
            self.diagnostics.event(
                f"page fetched: offset={offset}, limit={self.config.limit}, items={len(items)}"
            )
            if meta and "total" in meta:
                self.diagnostics.event(f"page meta: offset={offset}, total={meta.get('total')}")
            yield page

            if len(items) == 0:
                self.diagnostics.stopped_reason = "empty_page"
                self.diagnostics.event("stopped by paging rule: empty page")
                return
            if len(items) < self.config.limit:
                self.diagnostics.stopped_reason = "short_page"
                self.diagnostics.event("stopped by paging rule: short page")
                return

            offset += step

    def _request_with_retry(self, *, endpoint: str, params: Dict[str, Any]) -> requests.Response:
        """Execute GET request with retry/backoff for transient failures."""

        url = f"{self.config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        retry = self.config.retry
        last_error: Optional[BaseException] = None

        for attempt in range(1, retry.max_attempts + 1):
            self.diagnostics.requests_total += 1
            try:
                response = self.session.get(url, params=params, timeout=retry.timeout_sec)
            except requests.Timeout as exc:
                self.diagnostics.timeout_count += 1
                last_error = exc
                if attempt == retry.max_attempts:
                    raise FetchLayerError(
                        f"timeout after {retry.max_attempts} attempts url={url} params={params}"
                    ) from exc
                self._sleep_before_retry(attempt=attempt, reason="timeout")
                continue
            except requests.ConnectionError as exc:
                self.diagnostics.connection_error_count += 1
                last_error = exc
                if attempt == retry.max_attempts:
                    raise FetchLayerError(
                        f"connection error after {retry.max_attempts} attempts url={url} params={params}"
                    ) from exc
                self._sleep_before_retry(attempt=attempt, reason="connection_error")
                continue

            status = response.status_code
            if status in retry.retryable_statuses:
                if status == 429:
                    self.diagnostics.http_429_count += 1
                elif 500 <= status < 600:
                    self.diagnostics.http_5xx_count += 1

                if attempt == retry.max_attempts:
                    raise RetryableHttpExhaustedError(status=status, url=response.url)
                self._sleep_before_retry(attempt=attempt, reason=f"http_{status}")
                continue

            if status >= 400:
                self.diagnostics.terminal_http_error_count += 1
                raise FetchLayerError(f"terminal HTTP status={status} url={response.url}")

            self.diagnostics.requests_success += 1
            return response

        raise FetchLayerError(f"unexpected retry loop state: {last_error!r}")

    def _sleep_before_retry(self, *, attempt: int, reason: str) -> None:
        """Sleep using exponential backoff and jitter before next retry attempt."""

        retry = self.config.retry
        base = min(retry.max_delay_sec, retry.base_delay_sec * (2 ** (attempt - 1)))
        delay = base + self.random_fn() * retry.jitter_sec
        self.diagnostics.retry_count += 1
        self.diagnostics.event(f"retry scheduled: reason={reason}, attempt={attempt}, sleep={delay:.3f}s")
        self.sleep_fn(delay)

    def _parse_json(self, response: requests.Response) -> Dict[str, Any]:
        """Parse response JSON and validate expected top-level type."""

        try:
            payload = response.json()
        except ValueError as exc:
            self.diagnostics.parse_error_count += 1
            raise FetchLayerError(f"invalid JSON in response url={response.url}") from exc
        if not isinstance(payload, dict):
            self.diagnostics.parse_error_count += 1
            raise FetchLayerError(f"unexpected payload type={type(payload).__name__} url={response.url}")
        return payload

    @staticmethod
    def _normalize_api_datetime(value: str) -> str:
        """Convert aware ISO datetime to UTC Zulu format expected by source API."""

        normalized = value.strip()
        if not normalized:
            return value

        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return value

        if parsed.tzinfo is None:
            return normalized
        return (
            parsed.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _extract_vacancies(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract vacancy objects from API payload regardless of wrapping shape."""

        results = payload.get("results")
        if not isinstance(results, dict):
            return []
        raw_vacancies = results.get("vacancies")
        if not isinstance(raw_vacancies, list):
            return []

        items: List[Dict[str, Any]] = []
        for raw_item in raw_vacancies:
            if isinstance(raw_item, dict) and isinstance(raw_item.get("vacancy"), dict):
                items.append(raw_item["vacancy"])
                continue
            if isinstance(raw_item, dict):
                items.append(raw_item)
        return items
