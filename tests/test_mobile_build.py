"""The iPhone build: the desktop interface with the browser bridge, and the Python package zipped for Pyodide."""

import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _build(out: Path) -> None:
    spec = importlib.util.spec_from_file_location("mobile_build", ROOT / "mobile" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build(out)


def test_build_makes_a_web_app(tmp_path):
    out = tmp_path / "web"
    _build(out)
    html = (out / "index.html").read_text(encoding="utf-8")
    # The bridge has to come before app.js, which starts as soon as it finds window.pywebview.
    assert html.index('src="bridge.js"') < html.index('src="app.js"')
    assert "manifest.webmanifest" in html and "viewport-fit=cover" in html
    for name in ("worker.js", "sw.js", "manifest.webmanifest", "icon-180.png", "app.css", "fonts"):
        assert (out / name).exists(), name
    names = zipfile.ZipFile(out / "studypal.zip").namelist()
    assert "studypal/webrun.py" in names and "studypal/api.py" in names and "studypal/cloud.json" in names
    assert not any(n.startswith("studypal/web/") or "__pycache__" in n for n in names)
