"""A subject's notes: like a project's, saved while you type, each optionally about one of the subject's topics."""

from __future__ import annotations

from studypal.core import dataset
from studypal.core.logic.merge import TABLES

from test_cloud import add_course
from test_exams import api  # noqa: F401  (fixture)


def _topic(api, course_id: int, title: str) -> int:
    r = api.save_topic({"course_id": course_id, "title": title})
    assert r.get("ok"), r
    return next(t["id"] for t in api.subject(course_id)["topics"] if t["title"] == title)


def test_a_note_is_added_saved_and_listed(api) -> None:
    cid = add_course(api, "MAT100")
    note = api.add_course_note(cid)
    assert note["topic_id"] is None and note["title"] == ""
    saved = api.save_course_note({"id": note["id"], "title": " Limits ", "body": "$\\lim_{x \\to 0}$"})
    assert saved["title"] == "Limits" and saved["body"] == "$\\lim_{x \\to 0}$"
    page = api.notes(cid)
    assert [n["title"] for n in page["notes"]] == ["Limits"]
    assert api.subject(cid)["notes"] == 1


def test_a_note_can_point_to_a_topic_and_the_text_saves_leave_it(api) -> None:
    cid = add_course(api, "MAT100")
    tid = _topic(api, cid, "Derivatives")
    note = api.add_course_note(cid, tid)
    assert note["topic_id"] == tid and note["topic"] == "Derivatives"
    # Saving while typing sends only the title and text: the topic stays.
    assert api.save_course_note({"id": note["id"], "title": "Chain rule", "body": "..."})["topic_id"] == tid
    rows = {t["title"]: t["notes"] for t in api.subject(cid)["topics"]}
    assert rows["Derivatives"] == 1
    assert api.save_course_note({"id": note["id"], "topic_id": None})["topic_id"] is None


def test_a_note_cant_point_to_another_subjects_topic(api) -> None:
    a, b = add_course(api, "MAT100"), add_course(api, "MAT200")
    other = _topic(api, b, "Integrals")
    assert "error" in api.add_course_note(a, other)
    note = api.add_course_note(a)
    assert "error" in api.save_course_note({"id": note["id"], "topic_id": other})


def test_deleting_the_topic_keeps_the_note_and_deleting_the_subject_removes_it(api) -> None:
    cid = add_course(api, "MAT100")
    tid = _topic(api, cid, "Derivatives")
    note = api.add_course_note(cid, tid)
    api.delete_topic(tid)
    assert api.notes(cid)["notes"][0]["topic_id"] is None
    api.delete_course(cid)
    assert api._store.get_course_note(note["id"]) is None


def test_notes_sync_with_their_subject_and_topic(api) -> None:
    cid = add_course(api, "MAT100")
    tid = _topic(api, cid, "Derivatives")
    note = api.add_course_note(cid, tid)
    api.save_course_note({"id": note["id"], "title": "Chain rule", "body": "f(g(x))' = f'(g(x)) g'(x)"})
    assert "course_note" in TABLES
    data = dataset.export_dataset(api._store.conn)
    row = next(iter(data["course_note"].values()))
    assert row["title"] == "Chain rule"
    assert row["course"] in data["course"] and row["topic"] in data["topic"]
    # Written back into an empty database, it's the same note on the same topic.
    api.delete_course(cid)
    with api._store._tx() as c:
        dataset.apply_dataset(c, data)
    cid = api._store.list_courses()[0].id
    page = api.notes(cid)
    assert [(n["title"], n["topic"]) for n in page["notes"]] == [("Chain rule", "Derivatives")]


def test_notes_are_in_the_markdown_backup(api) -> None:
    from studypal.core.export import to_markdown

    cid = add_course(api, "MAT100")
    tid = _topic(api, cid, "Derivatives")
    note = api.add_course_note(cid, tid)
    api.save_course_note({"id": note["id"], "title": "Chain rule", "body": "Outside in."})
    text = to_markdown(api._store)
    assert "### Note: Chain rule (Derivatives)" in text and "Outside in." in text
