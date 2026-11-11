"""A small, polite HTTP client for public APIs.

Politeness is a feature here, not an afterthought: every source is called at a
bounded rate, transient failures are retried with backoff, and the server's
``Retry-After`` is honoured. Query strings are never included in errors or logs
because some APIs (Adzuna) take credentials as query parameters.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

from jobpipe import __version__

logger = logging.getLogger(__name__)

USER_AGENT = (
    f"swiss-tech-jobs-pipeline/{__version__} "
    "(+https://github.com/LorenzoSanz/swiss-tech-jobs-pipeline)"
)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

Response = tuple[int, Mapping[str, str], bytes]
Transport = Callable[[urllib.request.Request, float], Response]


class HttpError(Exception):
    """A request failed for good. ``url`` never contains the query string."""

    def __init__(self, url: str, status: int | None, detail: str) -> None:
        super().__init__(f"GET {url} failed (status={status}): {detail}")
        self.url = url
        self.status = status


def urllib_transport(request: urllib.request.Request, timeout: float) -> Response:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        headers = dict(error.headers.items()) if error.headers else {}
        return error.code, headers, error.read()


def _without_query(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


@dataclass
class HttpClient:
    transport: Transport = urllib_transport
    min_interval_seconds: float = 1.0
    max_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    timeout_seconds: float = 30.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    jitter: Callable[[float], float] = lambda delay: random.uniform(delay / 2, delay)
    _last_request_at: dict[str, float] = field(default_factory=dict, repr=False)

    def get_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        body = self.get(url, params, headers)
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise HttpError(_without_query(url), 200, f"invalid JSON: {error}") from error

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        full_url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}" if params else url
        safe_url = _without_query(full_url)
        host = urllib.parse.urlsplit(full_url).netloc
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            **(headers or {}),
        }

        for attempt in range(1, self.max_attempts + 1):
            self._throttle(host)
            request = urllib.request.Request(full_url, headers=request_headers, method="GET")
            try:
                status, response_headers, body = self.transport(request, self.timeout_seconds)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt == self.max_attempts:
                    raise HttpError(safe_url, None, str(error)) from error
                delay = self._backoff(attempt)
                logger.warning("GET %s network error (%s), retry in %.1fs", safe_url, error, delay)
                self.sleep(delay)
                continue

            if 200 <= status < 300:
                return body

            if status in RETRYABLE_STATUS and attempt < self.max_attempts:
                delay = self._retry_delay(attempt, response_headers)
                logger.warning("GET %s returned %s, retry in %.1fs", safe_url, status, delay)
                self.sleep(delay)
                continue

            detail = body[:300].decode("utf-8", errors="replace")
            raise HttpError(safe_url, status, detail)

        raise AssertionError("unreachable")  # pragma: no cover

    def _throttle(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is not None:
            wait = self.min_interval_seconds - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request_at[host] = self.clock()

    def _backoff(self, attempt: int) -> float:
        delay = min(self.max_backoff_seconds, self.base_backoff_seconds * 2 ** (attempt - 1))
        return self.jitter(delay)

    def _retry_delay(self, attempt: int, headers: Mapping[str, str]) -> float:
        retry_after = {k.lower(): v for k, v in headers.items()}.get("retry-after")
        server_delay = _parse_retry_after(retry_after) if retry_after else None
        if server_delay is not None:
            return min(self.max_backoff_seconds, server_delay)
        return self._backoff(attempt)


def _parse_retry_after(value: str) -> float | None:
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
