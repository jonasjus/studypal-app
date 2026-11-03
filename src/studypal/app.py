"""Opens StudyPal's window.

    studypal            your own data
    studypal --demo     sample subjects in a throwaway database, to look around
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .api import Api
from .core import paths

WEB = Path(__file__).parent / "web"


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="studypal", description="StudyPal, a study tracker for exam season.")
    parser.add_argument("--demo", action="store_true", help="open with sample data that's thrown away afterwards")
    parser.add_argument("--debug", action="store_true", help="allow the web inspector (right-click > Inspect)")
    parser.add_argument("--version", action="version", version=f"StudyPal {__version__}")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    # macOS passes -psn_... when an app is opened from Finder on some versions; ignore anything unknown.
    args, _ = parser.parse_known_args(argv)
    return args


def _window_background(api: Api) -> str:
    """The saved theme's background, so the window doesn't open white under a dark theme."""
    return api._prefs().get("background") or "#f5f4f0"


def cloud_client():
    """The Supabase project accounts live in, from cloud.json (or STUDYPAL_SUPABASE_URL and
    STUDYPAL_SUPABASE_ANON_KEY). Without one the app works as before, on this computer only."""
    from .core.cloud import Client

    try:
        saved = json.loads((Path(__file__).parent / "cloud.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    url = os.environ.get("STUDYPAL_SUPABASE_URL") or saved.get("url", "")
    key = os.environ.get("STUDYPAL_SUPABASE_ANON_KEY") or saved.get("anon_key", "")
    return Client(url, key) if url and key else None


def _smoke_test(window) -> None:
    """Checks a build works end to end: the page loads, reaches Python through the bridge and draws the
    overview. Prints what it found and closes the window. Used with --demo after packaging."""
    import time

    found = "nothing"
    try:  # the exam reader's PDF, image and schema libraries made it into the build
        import io

        import pypdfium2 as pdfium

        from .core import pages

        pdf, out = pdfium.PdfDocument.new(), io.BytesIO()
        pdf.new_page(595, 842)
        pdf.save(out)
        from .core.logic.questions import Question

        Question(number="1", text="check")  # Pydantic (and its compiled core) made it in too
        pdf_check = "pages on" if pages.pdf_text_pages("check.pdf", out.getvalue())[0].image else "pages off"
    except Exception as e:
        pdf_check = f"pages off ({e})"
    for _ in range(40):
        time.sleep(0.5)
        try:
            found = window.evaluate_js(
                "document.querySelectorAll('.card:not(.research)').length + ' subjects, ' + "
                "document.querySelectorAll('.card.research').length + ' research, ' + "
                "document.querySelectorAll('.list .row').length + ' list rows, accounts ' + "
                "(state.account && state.account.configured ? 'on' : 'off') + ', maths ' + "
                "(window.katex && window.marked && typeof renderExams === 'function' ? 'on' : 'off') + ', research ' + "
                "(typeof renderResearch === 'function' ? 'on' : 'off')")
        except Exception as e:  # the page isn't ready yet
            found = repr(e)
        if found and "subjects" in str(found) and (not str(found).startswith("0 subjects") or ".welcome" in str(
                window.evaluate_js("document.querySelector('.welcome') ? '.welcome' : ''"))):
            break
    # A windowed Windows build has no console to print to, so it can write the result to a file instead.
    found = f"{found}, {pdf_check}"
    out = os.environ.get("STUDYPAL_SMOKE_OUT")
    if out:
        Path(out).write_text(f"smoke test: {found}\n", encoding="utf-8")
    elif sys.stdout is not None:
        print(f"smoke test: {found}", flush=True)
    window.destroy()


def main(argv: list[str] | None = None) -> None:
    import webview

    args = _args(argv if argv is not None else sys.argv[1:])
    if args.demo:
        from .core.demo import seed, temporary_store_path

        db = temporary_store_path()
        api = Api(db)
        seed(api._store)
    else:
        api = Api(paths.db_path(), client=cloud_client())

    window = webview.create_window(
        "StudyPal" + (" (demo)" if args.demo else ""),
        url=str(WEB / "index.html"),
        js_api=api,
        width=1240,
        height=820,
        min_size=(760, 560),
        background_color=_window_background(api),
        text_select=True,
    )
    api._window = window
    api.watch()  # the Pomodoro's pling and notifications, also while the window is in the background
    try:
        webview.start(_smoke_test, window, debug=args.debug) if args.smoke_test else webview.start(debug=args.debug)
    finally:
        api._close()


if __name__ == "__main__":
    main()
