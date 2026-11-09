"""Test doubles shared by the test suite."""

from __future__ import annotations

import json
import urllib.parse
from collections import deque
from typing import Any

from jobpipe.http import HttpClient


class FakeTransport:
    """Returns queued responses and records every request it receives."""

    def __init__(self) -> None:
        self.responses: deque = deque()
        self.requests: list = []

    def add(self, status: int = 200, body: Any = None, headers: dict | None = None) -> None:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.responses.append((status, headers or {}, raw))

    def add_error(self, error: Exception) -> None:
        self.responses.append(error)

    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    def urls(self) -> list[str]:
        return [request.full_url for request in self.requests]

    def query(self, index: int) -> dict[str, str]:
        parts = urllib.parse.urlsplit(self.requests[index].full_url)
        return dict(urllib.parse.parse_qsl(parts.query))


def fast_client(transport) -> HttpClient:
    """An HttpClient that never really sleeps, for tests."""
    return HttpClient(
        transport=transport,
        sleep=lambda seconds: None,
        jitter=lambda delay: delay,
        min_interval_seconds=0,
    )
