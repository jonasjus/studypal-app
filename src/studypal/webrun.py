"""StudyPal in a browser, for the iPhone: the same Api, run by Pyodide in a Web Worker (see mobile/worker.js).

The desktop app gets a window, threads, sockets and the computer's own programs. A browser has none of
these, so this module stands in for them:

- requests (to Supabase and the model providers) go through the browser's own XMLHttpRequest, which a
  worker may use synchronously, so cloud.py and llm.py work unchanged;
- opening a file or a link, notifications and saving a file are handed to the page with `host(...)`;
- the data lives in /data, which the worker keeps in the browser's IndexedDB between visits.

`start()` makes the Api; `handle(name, args_json)` is what the page calls, returning JSON.
"""

from __future__ import annotations

import base64
import email.message
import io
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import js  # the worker's global scope
from pyodide.ffi import to_js

DATA = Path("/data")


def host(kind: str, **fields: Any) -> None:
    """Ask the page to do something only it can (open a tab, show a notification, save a file)."""
    js.postMessage(json.dumps({"host": kind, **fields}))


# ---------- requests through the browser ----------

_FORBIDDEN = {"user-agent", "content-length", "host", "connection", "accept-encoding"}  # the browser sets these


class _Response(io.BytesIO):
    def __init__(self, url: str, status: int, body: bytes, headers: email.message.Message) -> None:
        super().__init__(body)
        self.url, self.status, self.headers = url, status, headers

    def getcode(self) -> int:
        return self.status


def _headers(raw: str) -> email.message.Message:
    m = email.message.Message()
    for line in raw.strip().splitlines():
        name, _, value = line.partition(":")
        if name.strip():
            m[name.strip()] = value.strip()
    return m


def urlopen(req: urllib.request.Request | str, data: bytes | None = None, timeout: float | None = None,
            context: Any = None, **_: Any) -> _Response:
    """urllib.request.urlopen, done by the browser. Raises HTTPError and URLError the same way."""
    if isinstance(req, str):
        req = urllib.request.Request(req)
    if data is not None:
        req.data = data
    xhr = js.XMLHttpRequest.new()
    xhr.open(req.get_method(), req.full_url, False)
    xhr.responseType = "arraybuffer"
    if timeout:
        try:
            xhr.timeout = int(timeout * 1000)
        except Exception:  # some browsers don't allow it on a synchronous request
            pass
    for name, value in req.header_items():
        if name.lower() not in _FORBIDDEN:
            xhr.setRequestHeader(name, value)
    try:
        xhr.send(to_js(req.data) if req.data is not None else None)
    except Exception as e:  # offline, refused, or blocked by the browser (CORS)
        raise urllib.error.URLError(f"no connection: {e}") from None
    if not xhr.status:
        raise urllib.error.URLError("no connection")
    body = js.Uint8Array.new(xhr.response).to_bytes() if xhr.response else b""
    headers = _headers(xhr.getAllResponseHeaders() or "")
    if xhr.status >= 400:
        raise urllib.error.HTTPError(req.full_url, xhr.status, xhr.statusText or "", headers, io.BytesIO(body))
    return _Response(req.full_url, xhr.status, body, headers)


urllib.request.urlopen = urlopen  # cloud.py and llm.py look it up each time they ask

# There are no certificate files to load here: the browser checks the connection itself.
from .core import cloud  # noqa: E402

cloud._ssl_context = lambda: None  # type: ignore[assignment]

from .api import Api, UserError, action  # noqa: E402
from .core import files  # noqa: E402
from .core import pages  # noqa: E402


# ---------- the Api, with the computer's programs swapped for the page ----------

def _no_pdf(*_: Any, **__: Any) -> Any:
    raise pages.PageError("The iPhone version can't read PDFs yet. Add photos of the pages instead, "
                          "or add the PDF in the desktop app.")


try:
    import pypdfium2  # noqa: F401  (not built for the browser)
except ImportError:
    for name in ("pdf_text_pages", "pdf_pages"):
        if hasattr(pages, name):
            setattr(pages, name, _no_pdf)


class WebApi(Api):
    def watch(self) -> None:
        """No threads here: the page's tick (every 30 s) catches up on the Pomodoro instead."""

    @action
    def open_exam_file(self, file_id: int) -> None:
        f = self._store.get_exam_file(file_id)
        if f is None:
            raise UserError("That file is gone.")
        path = files.path(self._files_dir(), f.key)
        if not path.exists():
            raise UserError(f"“{f.name}” hasn't arrived on this phone yet. It downloads when StudyPal syncs.")
        mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        host("open_file", name=f.name, mime=mime, data=base64.b64encode(path.read_bytes()).decode())

    @action
    def open_link(self, url: str) -> None:
        from .api import link_address

        host("open_url", url=link_address(str(url)))

    @action
    def save_printable(self, title: str, html: str) -> dict:
        host("open_html", html=str(html))
        return {"ok": True, "message": "Opened in a new tab, ready to print or share."}

    @action
    def export_markdown(self) -> dict:
        from datetime import datetime

        from .core.export import to_markdown

        host("download", name=f"StudyPal backup {datetime.now():%Y-%m-%d}.md", mime="text/markdown",
             text=to_markdown(self._store))
        return {"ok": True, "message": ""}


api: WebApi | None = None


def start(demo: bool = False) -> None:
    global api
    os.environ["XDG_DATA_HOME"] = str(DATA)  # paths.data_dir() is then /data/studypal
    from .app import cloud_client
    from .core import paths

    def notify(title: str, body: str) -> bool:
        host("notify", title=title, body=body)
        return True

    def play(kind: str) -> None:
        host("play", kind=str(kind))

    if demo:
        from .core.demo import seed, temporary_store_path

        api = WebApi(temporary_store_path(), notify=notify, play=play)
        seed(api._store)
    else:
        db = paths.db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        api = WebApi(db, notify=notify, play=play, client=cloud_client())


def handle(name: str, args_json: str) -> str:
    method = getattr(api, name, None)
    if method is None or name.startswith("_") or not callable(method):
        return json.dumps({"error": f"No such call: {name}"})
    try:
        return json.dumps(method(*json.loads(args_json or "[]")))
    except Exception as e:  # anything @action didn't catch: show it rather than hang the page
        return json.dumps({"error": f"Something went wrong: {e}"})
