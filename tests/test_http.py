import unittest
import urllib.error

from jobpipe.http import USER_AGENT, HttpClient, HttpError
from tests.fakes import FakeTransport


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def client(transport, clock=None, **overrides) -> HttpClient:
    clock = clock or FakeClock()
    return HttpClient(
        transport=transport,
        sleep=clock.sleep,
        clock=clock,
        jitter=lambda delay: delay,
        **overrides,
    )


class HttpClientTest(unittest.TestCase):
    def test_returns_parsed_json_and_identifies_itself(self):
        transport = FakeTransport()
        transport.add(body={"ok": True})

        result = client(transport).get_json("https://api.example.com/jobs", {"page": 1})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(transport.urls(), ["https://api.example.com/jobs?page=1"])
        self.assertEqual(transport.requests[0].get_header("User-agent"), USER_AGENT)

    def test_waits_between_requests_to_the_same_host(self):
        transport = FakeTransport()
        transport.add(body={})
        transport.add(body={})
        clock = FakeClock()
        http = client(transport, clock, min_interval_seconds=1.0)

        http.get_json("https://api.example.com/a")
        http.get_json("https://api.example.com/b")

        self.assertEqual(clock.sleeps, [1.0])

    def test_does_not_throttle_different_hosts(self):
        transport = FakeTransport()
        transport.add(body={})
        transport.add(body={})
        clock = FakeClock()
        http = client(transport, clock, min_interval_seconds=1.0)

        http.get_json("https://one.example.com/a")
        http.get_json("https://two.example.com/a")

        self.assertEqual(clock.sleeps, [])

    def test_retries_server_errors_with_exponential_backoff(self):
        transport = FakeTransport()
        transport.add(status=503, body={})
        transport.add(status=502, body={})
        transport.add(body={"ok": True})
        clock = FakeClock()

        result = client(transport, clock, min_interval_seconds=0).get_json("https://api.example.com/x")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(clock.sleeps, [1.0, 2.0])

    def test_honours_retry_after_on_429(self):
        transport = FakeTransport()
        transport.add(status=429, body={}, headers={"Retry-After": "7"})
        transport.add(body={})
        clock = FakeClock()

        client(transport, clock, min_interval_seconds=0).get_json("https://api.example.com/x")

        self.assertEqual(clock.sleeps, [7.0])

    def test_retries_network_errors(self):
        transport = FakeTransport()
        transport.add_error(urllib.error.URLError("connection reset"))
        transport.add(body={"ok": True})

        result = client(transport, min_interval_seconds=0).get_json("https://api.example.com/x")

        self.assertEqual(result, {"ok": True})

    def test_does_not_retry_client_errors(self):
        transport = FakeTransport()
        transport.add(status=404, body={"error": "unknown board"})

        with self.assertRaises(HttpError) as raised:
            client(transport).get_json("https://api.example.com/x")

        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(len(transport.requests), 1)

    def test_gives_up_after_max_attempts(self):
        transport = FakeTransport()
        for _ in range(3):
            transport.add(status=500, body={})

        with self.assertRaises(HttpError):
            client(transport, max_attempts=3, min_interval_seconds=0).get_json("https://api.example.com/x")

        self.assertEqual(len(transport.requests), 3)

    def test_errors_never_leak_query_string_credentials(self):
        transport = FakeTransport()
        transport.add(status=401, body={"error": "bad key"})

        with self.assertRaises(HttpError) as raised:
            client(transport).get_json("https://api.example.com/x", {"app_key": "s3cret"})

        self.assertNotIn("s3cret", str(raised.exception))
        self.assertEqual(raised.exception.url, "https://api.example.com/x")


if __name__ == "__main__":
    unittest.main()
