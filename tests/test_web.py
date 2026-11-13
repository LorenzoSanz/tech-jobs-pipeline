import http.client
import http.server
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

from jobpipe import web
from jobpipe.bronze import BronzeWriter, read_records
from jobpipe.sources import manual


class FormTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "bronze"
        self.reloads = threading.Event()
        self.reloader = web.Reloader(lambda: (self.reloads.set(), "11296 postings")[1])
        # The allowed Host includes the port, known only once the server is bound.
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.server.RequestHandlerClass = web.make_handler(
            BronzeWriter(self.data_dir), self.reloader, {self.host}, "http://localhost:3000"
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(self.host, timeout=5)
        conn.request(method, path, body=body, headers={"Host": self.host, **(headers or {})})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode("utf-8")

    def post(self, form, origin=None):
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": origin or f"http://{self.host}"}
        return self.request("POST", "/add?lang=es", urllib.parse.urlencode(form), headers)

    def test_the_form_is_served_with_a_strict_policy(self):
        status, headers, body = self.request("GET", "/?lang=es")

        self.assertEqual(status, 200)
        self.assertIn("Añadir oferta", body)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        # The POST check needs a real Origin; no-referrer would make browsers send "null".
        self.assertEqual(headers["Referrer-Policy"], "same-origin")

    def test_a_posting_is_written_to_bronze_and_the_warehouse_reloads(self):
        status, headers, _ = self.post({
            "title": "Software Engineer III", "company": "Google", "location": "Zurich, Switzerland",
            "country": "ch", "url": "https://careers.example/1", "description": "Java.",
        })  # fmt: skip

        self.assertEqual(status, 303)
        self.assertIn("added=", headers["Location"])
        records = list(read_records(self.data_dir, manual.SOURCE))
        self.assertEqual([r["payload"]["title"] for r in records], ["Software Engineer III"])
        self.assertEqual(records[0]["payload"]["country"], "ch")
        self.assertTrue(self.reloads.wait(5))

    def test_missing_fields_and_bad_links_are_refused_and_the_form_keeps_what_was_typed(self):
        status, _, body = self.post({"title": "", "company": "Google"})
        self.assertEqual(status, 400)
        self.assertIn("obligatorios", body)

        status, _, body = self.post({"title": "<script>x</script>", "company": "Acme", "url": "javascript:alert(1)"})
        self.assertEqual(status, 400)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>x", body)
        self.assertEqual(list(read_records(self.data_dir, manual.SOURCE)), [])

    def test_posts_from_other_sites_and_unknown_hosts_are_refused(self):
        status, _, _ = self.post({"title": "x", "company": "y"}, origin="https://evil.example")
        self.assertEqual(status, 403)

        status, _, _ = self.request("GET", "/", headers={"Host": "evil.example:8100"})
        self.assertEqual(status, 421)
        self.assertEqual(list(read_records(self.data_dir, manual.SOURCE)), [])


class ReloaderTest(unittest.TestCase):
    def test_a_request_during_a_run_makes_one_more_run(self):
        started, release, runs = threading.Event(), threading.Event(), []

        def reload():
            runs.append(1)
            started.set()
            release.wait(5)
            return "ok"

        reloader = web.Reloader(reload)
        reloader.request()
        started.wait(5)
        reloader.request()
        reloader.request()
        release.set()
        deadline = time.monotonic() + 5
        while reloader.running and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(len(runs), 2)
        self.assertEqual(reloader.last, "ok")


if __name__ == "__main__":
    unittest.main()
