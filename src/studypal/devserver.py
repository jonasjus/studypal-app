"""Serves the window's page in an ordinary browser, for working on the interface without the app shell.

    python -m studypal.devserver [--demo] [--port 8765]

The page calls the same Api over HTTP: a small shim stands in for pywebview's bridge.
"""

from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .api import Api
from .app import WEB
from .core import paths

SHIM = b"""<script>
window.pywebview = { api: new Proxy({}, { get: (_, name) => async (...args) => {
  const r = await fetch('/api/' + name, { method: 'POST', body: JSON.stringify(args) });
  return r.json();
} }) };
</script>"""


def serve(api: Api, port: int) -> None:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB), **kw)

        def log_message(self, *a) -> None:
            pass

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                html = (WEB / "index.html").read_bytes().replace(b'<script src="app.js">', SHIM + b'<script src="app.js">')
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html)
                return
            super().do_GET()

        def do_POST(self) -> None:
            name = self.path.removeprefix("/api/")
            args = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"[]")
            method = getattr(api, name, None)
            result = method(*args) if method and not name.startswith("_") else {"error": f"No such call: {name}"}
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    print(f"StudyPal on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.demo:
        from .core.demo import seed, temporary_store_path

        api = Api(temporary_store_path(), notify=lambda title, body: True)
        seed(api._store)
    else:
        api = Api(paths.db_path())
    api.watch()
    serve(api, args.port)


if __name__ == "__main__":
    main()
