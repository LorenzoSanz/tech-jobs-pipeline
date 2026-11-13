"""A small form to add a posting by hand from the dashboards: `jobpipe serve`.

Grafana cannot run commands, so its "Add a posting" link opens this page. The
form does what `jobpipe add` does, then rebuilds the warehouse in the
background so the posting shows up in the dashboards a few seconds later.

It is meant for one person on their own machine: docker compose publishes it
on 127.0.0.1 only. A POST must come from this page (its Origin is checked) and
the Host header must be one of ours, so another website open in the browser
cannot add postings or reach it through DNS rebinding.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from jobpipe.bronze import BronzeWriter
from jobpipe.sources import manual

log = logging.getLogger(__name__)

MAX_BODY = 256 * 1024
COUNTRIES = ("ch", "es", "de", "fr", "it", "at", "nl", "gb", "ie", "pt", "be", "lu", "dk", "se", "pl")


@dataclass
class Reloader:
    """Runs ``reload`` in a background thread, one run at a time.

    A posting added while a run is going makes one more run follow, so the
    last posting is never left out.
    """

    reload: Callable[[], str]
    running: bool = False
    pending: bool = False
    last: str = ""
    finished_at: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def request(self) -> None:
        with self._lock:
            if self.running:
                self.pending = True
                return
            self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                result = self.reload()
            except Exception as error:  # shown on the page; the server keeps running
                log.exception("reload failed")
                result = f"error: {error}"
            with self._lock:
                self.last, self.finished_at = result, datetime.now(UTC).strftime("%H:%M:%S UTC")
                if not self.pending:
                    self.running = False
                    return
                self.pending = False


TEXT = {
    "en": {
        "title": "Add a posting", "lead": "For postings on sites with no public API, such as Google or Apple careers.",
        "job_title": "Job title", "company": "Company", "location": "Location", "country": "Country",
        "url": "Link to the posting", "description": "Posting text", "save": "Add posting",
        "added": "Added. The dashboards are being reloaded.", "reloading": "Reloading the dashboards…",
        "last": "Last reload", "back": "Back to the dashboards", "required": "Title and company are required.",
        "bad_url": "The link must start with http:// or https://.", "bad_country": "Unknown country.",
    },
    "es": {
        "title": "Añadir oferta", "lead": "Para ofertas de webs sin API pública, como las de Google o Apple.",
        "job_title": "Puesto", "company": "Empresa", "location": "Ubicación", "country": "País",
        "url": "Enlace a la oferta", "description": "Texto de la oferta", "save": "Añadir oferta",
        "added": "Añadida. Se están recargando los paneles.", "reloading": "Recargando los paneles…",
        "last": "Última recarga", "back": "Volver a los paneles", "required": "El puesto y la empresa son obligatorios.",
        "bad_url": "El enlace debe empezar por http:// o https://.", "bad_country": "País desconocido.",
    },
}  # fmt: skip

STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; font: 15px/1.5 Inter, system-ui, sans-serif; color: #e5e7eb;
  background: radial-gradient(900px 500px at 0% -10%, rgba(59,130,246,.12), transparent 60%),
  radial-gradient(900px 500px at 100% -10%, rgba(168,85,247,.12), transparent 60%), #0e1016; }
main { max-width: 720px; margin: 0 auto; padding: 32px 16px 48px; }
h1 { margin: 0 0 4px; font-size: 26px; background: linear-gradient(90deg,#60a5fa,#c084fc);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
p.lead { margin: 0 0 24px; color: #9ca3af; }
form { display: grid; gap: 16px; padding: 24px; border-radius: 14px; background: rgba(24,27,38,.92);
  border: 1px solid rgba(129,140,248,.16); }
.row { display: grid; gap: 16px; grid-template-columns: 2fr 1fr; }
@media (max-width: 560px) { .row { grid-template-columns: 1fr; } }
label { display: grid; gap: 6px; font-size: 13px; color: #c4b5fd; }
input, select, textarea { width: 100%; padding: 10px 12px; border-radius: 12px; color: #e5e7eb; font: inherit;
  background: rgba(30,34,52,.85); border: 1px solid rgba(129,140,248,.24); }
input:focus, select:focus, textarea:focus { outline: none; border-color: #a78bfa; box-shadow: 0 0 0 3px rgba(167,139,250,.2); }
textarea { min-height: 220px; resize: vertical; }
button { justify-self: start; padding: 10px 20px; border: 0; border-radius: 12px; color: white; font: inherit;
  font-weight: 600; cursor: pointer; background: linear-gradient(90deg,#3b82f6,#a855f7); }
.note { padding: 12px 16px; border-radius: 12px; margin-bottom: 16px; }
.ok { background: rgba(34,197,94,.12); border: 1px solid rgba(34,197,94,.35); }
.err { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.35); }
.status { margin-top: 16px; color: #9ca3af; font-size: 13px; }
a { color: #93c5fd; }
"""


def page(lang: str, reloader: Reloader, grafana_url: str, message: str = "", error: str = "",
         values: dict[str, str] | None = None) -> str:  # fmt: skip
    t = TEXT[lang]
    v = {k: html.escape(x) for k, x in (values or {}).items()}
    options = "".join(
        f'<option value="{c}"{" selected" if c == (values or {}).get("country", "ch") else ""}>{c.upper()}</option>'
        for c in COUNTRIES
    )
    note = f'<div class="note ok">{html.escape(message)}</div>' if message else ""
    note += f'<div class="note err">{html.escape(error)}</div>' if error else ""
    status = t["reloading"] if reloader.running else (
        f'{t["last"]}: {html.escape(reloader.finished_at)} · {html.escape(reloader.last)}' if reloader.finished_at else ""
    )
    refresh = '<meta http-equiv="refresh" content="3">' if reloader.running else ""
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{refresh}<title>{t["title"]} · jobpipe</title><style>{STYLE}</style></head>
<body><main>
<h1>{t["title"]}</h1><p class="lead">{t["lead"]}</p>{note}
<form method="post" action="/add?lang={lang}">
  <label>{t["job_title"]} *<input name="title" required maxlength="300" value="{v.get("title", "")}"></label>
  <label>{t["company"]} *<input name="company" required maxlength="200" value="{v.get("company", "")}"></label>
  <div class="row">
    <label>{t["location"]}<input name="location" maxlength="200" placeholder="Zurich, Switzerland" value="{v.get("location", "")}"></label>
    <label>{t["country"]}<select name="country">{options}</select></label>
  </div>
  <label>{t["url"]}<input name="url" type="url" maxlength="2000" placeholder="https://" value="{v.get("url", "")}"></label>
  <label>{t["description"]}<textarea name="description" maxlength="100000">{v.get("description", "")}</textarea></label>
  <button type="submit">{t["save"]}</button>
</form>
<p class="status">{status}</p>
<p><a href="{html.escape(grafana_url)}">{t["back"]}</a></p>
</main></body></html>"""  # fmt: skip


def validate(form: dict[str, str], lang: str) -> str:
    t = TEXT[lang]
    if not form.get("title") or not form.get("company"):
        return t["required"]
    if form.get("url") and not re.match(r"https?://", form["url"]):
        return t["bad_url"]
    if form.get("country") and form["country"] not in COUNTRIES:
        return t["bad_country"]
    return ""


def make_handler(writer: BronzeWriter, reloader: Reloader, allowed_hosts: set[str],
                 grafana_url: str) -> type[BaseHTTPRequestHandler]:  # fmt: skip
    class Handler(BaseHTTPRequestHandler):
        server_version = "jobpipe"

        def log_message(self, format: str, *args: Any) -> None:
            log.info("%s %s", self.address_string(), format % args)

        def _lang(self) -> str:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return "en" if query.get("lang") == ["en"] else "es"

        def _send(self, status: HTTPStatus, body: str, content_type: str = "text/html; charset=utf-8",
                  headers: dict[str, str] | None = None) -> None:  # fmt: skip
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")  # fmt: skip
            self.send_header("X-Content-Type-Options", "nosniff")
            # Not no-referrer: with it, browsers send "Origin: null" on the form's POST and the check refuses it.
            self.send_header("Referrer-Policy", "same-origin")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:
            if self.headers.get("Host", "") in allowed_hosts:
                return True
            self._send(HTTPStatus.MISDIRECTED_REQUEST, "unknown host", "text/plain; charset=utf-8")
            return False

        def do_GET(self) -> None:
            if not self._host_ok():
                return
            path = urllib.parse.urlsplit(self.path).path
            if path == "/health":
                status = {"reloading": reloader.running, "last": reloader.last, "finished_at": reloader.finished_at}
                self._send(HTTPStatus.OK, json.dumps(status), "application/json")
            elif path == "/":
                lang = self._lang()
                added = "added" in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                self._send(HTTPStatus.OK, page(lang, reloader, grafana_url, TEXT[lang]["added"] if added else ""))
            else:
                self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if not self._host_ok():
                return
            origin = urllib.parse.urlsplit(self.headers.get("Origin", "")).netloc
            if origin not in allowed_hosts:
                self._send(HTTPStatus.FORBIDDEN, "forbidden", "text/plain; charset=utf-8")
                return
            if urllib.parse.urlsplit(self.path).path != "/add":
                self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too large", "text/plain; charset=utf-8")
                return
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = {k: v[0].strip() for k, v in urllib.parse.parse_qs(raw).items()}
            lang = self._lang()
            error = validate(form, lang)
            if error:
                self._send(HTTPStatus.BAD_REQUEST, page(lang, reloader, grafana_url, error=error, values=form))
                return
            item = manual.posting(form["title"], form["company"], form.get("location") or None,
                                  form.get("country") or None, form.get("url") or None, form.get("description", ""))  # fmt: skip
            writer.write(manual.SOURCE, [item])
            log.info("added %s: %s at %s", item.source_id, form["title"], form["company"])
            reloader.request()
            self._send(HTTPStatus.SEE_OTHER, "", headers={"Location": f"/?lang={lang}&added={item.source_id}"})

    return Handler


def serve(host: str, port: int, writer: BronzeWriter, reload: Callable[[], str], public_port: int | None = None,
          grafana_url: str = "http://localhost:3000") -> None:  # fmt: skip
    public = public_port or port
    allowed = {f"localhost:{public}", f"127.0.0.1:{public}"}
    server = ThreadingHTTPServer((host, port), make_handler(writer, Reloader(reload), allowed, grafana_url))
    log.info("add-a-posting form on http://localhost:%s", public)
    server.serve_forever()
