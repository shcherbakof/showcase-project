import unittest
from typing import Any, Dict, List, Optional

import requests

from src.trudvsem.fetch_layer import (
    FetchConfig,
    FetchLayerError,
    SafetyLimits,
    TrudvsemFetcher,
)


class _FakeResponse:
    def __init__(
        self, status_code: int, payload: Dict[str, Any], url: str = "http://example/api"
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.url = url

    def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(self, steps: List[Any]) -> None:
        self._steps = steps
        self.calls: List[Dict[str, Any]] = []

    def get(
        self, url: str, params: Optional[Dict[str, Any]] = None, timeout: float = 0
    ) -> _FakeResponse:
        self.calls.append(
            {"url": url, "params": dict(params or {}), "timeout": timeout}
        )
        if not self._steps:
            raise RuntimeError("no scripted response")
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _payload_with_items(count: int) -> Dict[str, Any]:
    vacancies = [
        {"vacancy": {"id": f"id-{i}", "date_modify": "2026-02-20T13:34:06+0300"}}
        for i in range(count)
    ]
    return {"results": {"vacancies": vacancies}, "meta": {"count": count}}


class FetchLayerTests(unittest.TestCase):
    def test_iter_pages_stops_on_short_page(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    200, _payload_with_items(2), "http://example/api?offset=1&limit=2"
                ),
                _FakeResponse(
                    200, _payload_with_items(1), "http://example/api?offset=3&limit=2"
                ),
            ]
        )
        cfg = FetchConfig(limit=2)
        fetcher = TrudvsemFetcher(
            cfg, session=session, sleep_fn=lambda _: None, random_fn=lambda: 0.0
        )

        pages = list(fetcher.iter_pages())

        self.assertEqual(len(pages), 2)
        self.assertEqual(fetcher.diagnostics.pages_fetched, 2)
        self.assertEqual(fetcher.diagnostics.items_extracted, 3)
        self.assertEqual(fetcher.diagnostics.stopped_reason, "short_page")

    def test_retry_on_429_then_success(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(429, {"error": "rate limit"}, "http://example/api"),
                _FakeResponse(200, _payload_with_items(0), "http://example/api"),
            ]
        )
        fetcher = TrudvsemFetcher(
            FetchConfig(limit=100),
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        pages = list(fetcher.iter_pages())

        self.assertEqual(len(pages), 1)
        self.assertEqual(fetcher.diagnostics.http_429_count, 1)
        self.assertEqual(fetcher.diagnostics.retry_count, 1)
        self.assertEqual(fetcher.diagnostics.requests_success, 1)

    def test_retry_timeout_then_success(self) -> None:
        session = _FakeSession(
            [
                requests.Timeout("timeout"),
                _FakeResponse(200, _payload_with_items(0), "http://example/api"),
            ]
        )
        fetcher = TrudvsemFetcher(
            FetchConfig(limit=100),
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        list(fetcher.iter_pages())

        self.assertEqual(fetcher.diagnostics.timeout_count, 1)
        self.assertEqual(fetcher.diagnostics.retry_count, 1)
        self.assertEqual(fetcher.diagnostics.requests_success, 1)

    def test_safety_stop_max_pages(self) -> None:
        session = _FakeSession(
            [_FakeResponse(200, _payload_with_items(2), "http://example/api")] * 5
        )
        cfg = FetchConfig(limit=2, safety=SafetyLimits(max_pages=2, max_items=100))
        fetcher = TrudvsemFetcher(
            cfg, session=session, sleep_fn=lambda _: None, random_fn=lambda: 0.0
        )

        pages = list(fetcher.iter_pages())

        self.assertEqual(len(pages), 2)
        self.assertEqual(fetcher.diagnostics.stopped_reason, "max_pages_reached")

    def test_terminal_http_error_raises(self) -> None:
        session = _FakeSession(
            [_FakeResponse(400, {"error": "bad request"}, "http://example/api")]
        )
        fetcher = TrudvsemFetcher(
            FetchConfig(),
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        with self.assertRaises(FetchLayerError):
            list(fetcher.iter_pages())

        self.assertEqual(fetcher.diagnostics.terminal_http_error_count, 1)

    def test_iter_pages_normalizes_modified_window_to_utc_z(self) -> None:
        session = _FakeSession(
            [_FakeResponse(200, _payload_with_items(0), "http://example/api")]
        )
        fetcher = TrudvsemFetcher(
            FetchConfig(limit=20),
            session=session,
            sleep_fn=lambda _: None,
            random_fn=lambda: 0.0,
        )

        list(
            fetcher.iter_pages(
                modified_from="2026-02-20T00:00:00+00:00",
                modified_to="2026-02-21T23:59:59+00:00",
            )
        )

        self.assertEqual(
            session.calls[0]["params"]["modifiedFrom"], "2026-02-20T00:00:00Z"
        )
        self.assertEqual(
            session.calls[0]["params"]["modifiedTo"], "2026-02-21T23:59:59Z"
        )


if __name__ == "__main__":
    unittest.main()
