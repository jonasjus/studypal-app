"""Builds the iPhone version: a static web app that runs StudyPal's Python in the browser with Pyodide.

    python mobile/build.py [out folder]     # default dist/web

The result can be served from any HTTPS host (GitHub Pages, for one). On the iPhone, open it in Safari and
choose Share → Add to Home Screen. It's the same interface as the desktop app (src/studypal/web), with
bridge.js standing in for the desktop window's bridge, and the Python package zipped for the worker.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "studypal"
HERE = Path(__file__).resolve().parent

HEAD = """  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <meta name="apple-mobile-web-app-title" content="StudyPal">
  <meta name="theme-color" content="#e9eae6">
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="apple-touch-icon" href="icon-180.png">
"""


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(PKG / "web", out)

    html = (out / "index.html").read_text(encoding="utf-8")
    html = html.replace('content="width=device-width, initial-scale=1"',
                        'content="width=device-width, initial-scale=1, viewport-fit=cover"')
    html = html.replace('  <link rel="icon" href="data:,">\n', '  <link rel="icon" href="icon-192.png">\n' + HEAD)
    html = html.replace('  <script src="vendor/marked.umd.js">', '  <script src="bridge.js"></script>\n  <script src="vendor/marked.umd.js">')
    assert "bridge.js" in html and "manifest.webmanifest" in html, "index.html changed: update mobile/build.py"
    (out / "index.html").write_text(html, encoding="utf-8")

    for name in ("bridge.js", "worker.js", "sw.js", "manifest.webmanifest"):
        shutil.copy(HERE / name, out / name)

    from PIL import Image

    icon = Image.open(ROOT / "packaging" / "icon.png").convert("RGBA")
    for size in (180, 192, 512):
        # iOS draws a home-screen icon on black where it's transparent, so give it the app's background.
        square = Image.new("RGBA", icon.size, (233, 234, 230, 255))
        square.alpha_composite(icon)
        square.convert("RGB").resize((size, size), Image.LANCZOS).save(out / f"icon-{size}.png")

    # The Python package, without the interface (it's served next to it) and the desktop-only window code.
    with zipfile.ZipFile(out / "studypal.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(PKG.rglob("*")):
            rel = path.relative_to(PKG.parent)
            if path.is_dir() or "__pycache__" in path.parts or rel.parts[1] == "web" or path.suffix == ".pyc":
                continue
            if path.suffix in (".py", ".json"):
                z.write(path, rel.as_posix())
    print(f"Built {out}")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "web")
