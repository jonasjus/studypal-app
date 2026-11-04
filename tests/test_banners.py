"""Course banners: a pattern made from the course by default, another pattern on request, or your own picture,
kept with the exam files (so it syncs) and handed to the page as a data URL."""

from __future__ import annotations

import base64
import io

from studypal.core import dataset

from test_cloud import add_course
from test_exams import api  # noqa: F401  (fixture)


def _png() -> str:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 10), (200, 80, 40)).save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode()


def _course(api, cid):
    return next(c for c in api.overview()["courses"] if c["id"] == cid)


def test_a_new_course_has_the_generated_banner(api) -> None:
    cid = add_course(api, "MAT100")
    assert _course(api, cid)["banner"] == ""


def test_another_pattern_and_back(api) -> None:
    cid = add_course(api, "MAT100")
    assert api.set_course_banner(cid, {"generated": 2})["ok"]
    assert _course(api, cid)["banner"] == "gen:2"
    api.set_course_banner(cid, {})
    assert _course(api, cid)["banner"] == ""


def test_your_own_picture_is_stored_synced_and_served(api) -> None:
    cid = add_course(api, "MAT100")
    assert api.set_course_banner(cid, {"name": "header.png", "data": _png()})["ok"]
    key = _course(api, cid)["banner"]
    assert key.endswith(".jpg")
    assert key in api._store.file_keys()  # kept by the tidy-up, and synced like exam files
    assert api.banner_image(key)["url"].startswith("data:image/jpeg;base64,")
    assert any(r["banner"] == key for r in dataset.export_dataset(api._store.conn)["course"].values())


def test_not_a_picture_is_refused(api) -> None:
    cid = add_course(api, "MAT100")
    r = api.set_course_banner(cid, {"name": "notes.txt", "data": base64.b64encode(b"hi").decode()})
    assert not r.get("ok")
    assert _course(api, cid)["banner"] == ""


def test_unknown_keys_give_no_picture(api) -> None:
    assert api.banner_image("../../etc/passwd")["url"] == ""
