"""Past exams, their files, marking questions, and Gemini reading and writing exams (with a stand-in
for Gemini), and exam files syncing between two computers."""

from __future__ import annotations

import base64
import json
import sys

import pytest

import studypal.api as api_module
from studypal.api import Api
from studypal.core import files
from studypal.core.gemini import Gemini, GeminiError, parse_json
from studypal.core.logic import exams as L
from studypal.core.models import ExamQuestion, Priority, Topic, WeakSpot

from test_cloud import FakeCloud, add_course, computer

PDF = b"%PDF-1.4 a pretend exam paper"
SOLUTIONS = b"%PDF-1.4 a pretend answer key"
MINE = b"%PDF-1.4 my answers, with red ink"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class FakeGemini:
    """Answers with whatever the test set, and remembers what it was sent."""

    answer: dict = {}
    sent: list[list] = []

    def __init__(self, key: str, model: str) -> None:
        self.key, self.model = key, model

    def ask(self, parts, schema, system="", temperature=None):
        FakeGemini.sent.append(parts)
        return FakeGemini.answer


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "Gemini", FakeGemini)
    FakeGemini.sent = []
    a = Api(tmp_path / "studypal.db", notify=lambda t, b: True)
    yield a
    a._close()


def course_with_topics(api: Api) -> int:
    course_id = add_course(api, "STK310")
    api.add_topics(course_id, "Sufficiency\nLikelihood\nBayesian inference")
    return course_id


def add_exam(api: Api, course_id: int, *roles_and_data: tuple[str, str, bytes]) -> int:
    r = api.save_exam({"course_id": course_id, "title": "Exam 2024", "taken_on": "June 2024",
                       "add": [{"role": role, "name": name, "data": b64(data)} for role, name, data in roles_and_data]})
    assert r.get("ok"), r
    return r["id"]


def with_key(api: Api) -> None:
    assert api.save_gemini({"key": "AIzaSyTESTKEY-0123456789abcdef"}).get("ok")


def test_adding_a_past_exam_stores_its_files(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam 2024.pdf", PDF), ("solution", "solutions.pdf", SOLUTIONS))
    d = api.exams(course_id)
    exam = d["past"][0]
    assert [f["role"] for f in exam["files"]] == ["exam", "solution"]
    assert all(f["available"] for f in exam["files"])
    folder = files.folder_for(api._store.path)
    assert len(list(folder.iterdir())) == 2
    # Removing a file deletes the stored copy; deleting the exam removes the rest.
    api.save_exam({"id": exam_id, "title": "Exam 2024", "remove": [exam["files"][1]["id"]]})
    assert len(list(folder.iterdir())) == 1
    api.delete_exam(exam_id)
    assert list(folder.iterdir()) == []
    assert api.subject(course_id)["exams"] == 0


def test_files_it_cant_read_are_refused(api: Api) -> None:
    course_id = course_with_topics(api)
    r = api.save_exam({"course_id": course_id, "title": "Exam", "add": [{"role": "exam", "name": "exam.docx", "data": b64(b"x")}]})
    assert "Save it as a PDF first" in r["error"]
    assert api.exams(course_id)["past"] == []  # nothing half-saved


def test_marking_questions_and_what_to_practise(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id)
    topics = {t["title"]: t["id"] for t in api.exams(course_id)["topics"]}
    for number, topic, result in (("1", "Sufficiency", "missed"), ("2", "Sufficiency", "partial"), ("3", "Likelihood", "ok"),
                                  ("4", "Bayesian inference", "partial")):
        assert api.save_question({"exam_id": exam_id, "number": number, "prompt": f"Question {number}",
                                  "topic_id": topics[topic], "result": result}).get("ok")
    d = api.exams(course_id)
    assert d["past"][0]["counts"] == {"ok": 1, "partial": 2, "missed": 1, "unmarked": 0, "total": 4}
    assert [(t["title"], t["missed"], t["partial"]) for t in d["tally"]][:2] == [("Sufficiency", 1, 1), ("Bayesian inference", 0, 1)]
    q = d["past"][0]["questions"][0]
    assert api.set_question_result(q["id"], "")["ok"]
    assert api.exams(course_id)["past"][0]["counts"]["unmarked"] == 1
    assert "error" in api.set_question_result(q["id"], "great")
    # A question that went badly can become a weak spot.
    api.set_question_result(q["id"], "missed")
    assert "weak spots" in api.question_to_weak(q["id"])["message"]
    weak = api.subject(course_id)["weak_spots"]
    assert weak[0]["description"].startswith("Exam 2024, question 1")


def test_gemini_needs_a_key(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF))
    assert api.exams(course_id)["gemini"] is False
    assert "API key" in api.read_exam(exam_id)["error"]
    assert "doesn't look like" in api.save_gemini({"key": "nope"})["error"]
    with_key(api)
    s = api.gemini_settings()
    assert s["has_key"] and s["key_hint"] == "…cdef"
    assert api.exams(course_id)["gemini"] is True
    # The key is only readable by this user (Windows has no such permission bits; the folder is per user).
    if sys.platform != "win32":
        assert (api._prefs_path().stat().st_mode & 0o777) == 0o600
    api.save_gemini({"forget": True})
    assert not api.gemini_settings()["has_key"]


def test_reading_an_exam(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("attempt", "mine.pdf", MINE), ("exam", "exam.pdf", PDF),
                       ("solution", "lf.pdf", SOLUTIONS))
    with_key(api)
    FakeGemini.answer = {"score": "41/60", "questions": [
        {"number": "1a", "prompt": "Find a sufficient statistic.", "marks": "10", "topic": "sufficiency ",
         "answer": "$T = \\sum X_i$", "result": "missed", "note": "Forgot the factorisation theorem."},
        {"number": "1b", "prompt": "Find the MLE.", "marks": "5", "topic": "Something else", "answer": "x̄",
         "result": "ok", "note": ""},
    ]}
    r = api.read_exam(exam_id)
    assert r["message"] == "Found 2 questions and marked 2 from your answers."
    sent = FakeGemini.sent[-1]
    # The paper first, then the solutions, then the answers, then the instructions.
    assert [p.data for p in sent[:3]] == [PDF, SOLUTIONS, MINE]
    assert "STUDENT'S OWN ANSWERS" in sent[3] and "Sufficiency" in sent[3]
    exam = api.exams(course_id)["past"][0]
    assert exam["score"] == "41/60"
    q1, q2 = exam["questions"]
    assert (q1["number"], q1["topic"], q1["result"], q1["note"]) == ("1a", "Sufficiency", "missed", "Forgot the factorisation theorem.")
    assert q2["topic"] is None and q2["result"] == "ok"
    assert exam["has_solution"]


def test_without_your_answers_nothing_is_marked(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF))
    with_key(api)
    FakeGemini.answer = {"score": "made up", "questions": [
        {"number": "1", "prompt": "Q", "marks": "", "topic": "", "answer": "A", "result": "missed", "note": "guess"}]}
    assert api.read_exam(exam_id)["message"] == "Found 1 question."
    exam = api.exams(course_id)["past"][0]
    assert exam["score"] == "" and exam["questions"][0]["result"] == "" and exam["questions"][0]["note"] == ""


def test_reading_needs_the_paper(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("solution", "lf.pdf", SOLUTIONS))
    with_key(api)
    assert "exam paper itself" in api.read_exam(exam_id)["error"]


def test_making_a_practice_exam(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF), ("solution", "lf.pdf", SOLUTIONS),
                       ("attempt", "mine.pdf", MINE))
    topics = {t["title"]: t["id"] for t in api.exams(course_id)["topics"]}
    api.save_question({"exam_id": exam_id, "number": "2b", "prompt": "Show that T is sufficient.",
                       "topic_id": topics["Sufficiency"], "result": "missed", "note": "Mixed up the factors."})
    with_key(api)
    FakeGemini.answer = {"title": "Practice exam 1: sufficiency", "intro": "**Time:** 1 hour", "questions": [
        {"number": "1", "topic": "Sufficiency", "why": "Practises 2b.", "marks": "10", "prompt": "New question",
         "answer": "Worked solution"},
        {"number": "2", "topic": "", "why": "", "marks": "", "prompt": "", "answer": ""},  # empty: dropped
    ]}
    r = api.make_exam({"course_id": course_id, "size": "short", "focus": "struggles", "wishes": "in English"})
    assert r.get("ok"), r
    sent = FakeGemini.sent[-1]
    # Past papers and solutions go along; your own answers don't (what went wrong is in the text).
    assert [p.data for p in sent[:-1]] == [PDF, SOLUTIONS]
    prompt = sent[-1]
    assert "question 2b" in prompt and "Mixed up the factors." in prompt and "in English" in prompt
    assert "practice exam number 1" in prompt
    practice = api.exams(course_id)["practice"]
    assert [(e["title"], len(e["questions"])) for e in practice] == [("Practice exam 1: sufficiency", 1)]
    assert practice[0]["questions"][0]["why"] == "Practises 2b." and practice[0]["questions"][0]["topic"] == "Sufficiency"
    # The next one is told about the questions already asked.
    api.make_exam({"course_id": course_id, "size": "full", "focus": "balanced"})
    assert "New question" in FakeGemini.sent[-1][-1] and "practice exam number 2" in FakeGemini.sent[-1][-1]


def test_practice_exam_on_chosen_topics(api: Api) -> None:
    course_id = course_with_topics(api)
    with_key(api)
    assert "Pick the topics" in api.make_exam({"course_id": course_id, "focus": "topics", "topic_ids": []})["error"]
    FakeGemini.answer = {"title": "", "intro": "", "questions": [{"number": "1", "prompt": "Q", "answer": "A"}]}
    topics = {t["title"]: t["id"] for t in api.exams(course_id)["topics"]}
    r = api.make_exam({"course_id": course_id, "focus": "topics", "topic_ids": [topics["Likelihood"]], "size": "short"})
    assert "Practice exam 1" in r["message"]
    prompt = FakeGemini.sent[-1][-1]
    assert "Only ask about these topics: Likelihood." in prompt and "no past exams" in prompt


def test_gemini_errors_come_back_as_messages(api: Api, monkeypatch) -> None:
    course_id = course_with_topics(api)
    with_key(api)

    def broken(self, *a, **kw):
        raise GeminiError("You've hit Gemini's limit for now.")

    monkeypatch.setattr(FakeGemini, "ask", broken)
    assert api.make_exam({"course_id": course_id})["error"] == "You've hit Gemini's limit for now."
    assert api.exams(course_id)["practice"] == []


def test_struggle_summary() -> None:
    topics = [Topic(1, "Sufficiency", confidence=1, id=1), Topic(1, "Likelihood", confidence=4, id=2)]
    qs = [("Exam 2024", ExamQuestion(1, "2b", "Show T is sufficient", topic_id=1, result="missed", note="Wrong factor")),
          ("Exam 2024", ExamQuestion(1, "3", "Find the MLE", topic_id=2, result="ok"))]
    weak = [WeakSpot(1, "Factorisation proofs", Priority.HIGH, topic_id=1), WeakSpot(1, "Old", resolved=True)]
    text = L.struggle_summary(qs, topics, weak)
    assert "- Exam 2024, question 2b [topic: Sufficiency] (wrong or blank): Show T is sufficient What went wrong: Wrong factor" in text
    assert "answered questions correctly: Likelihood." in text
    assert "Factorisation proofs" in text and "Old" not in text
    assert "least confident about: Sufficiency." in text
    assert L.struggle_summary([], [], []).startswith("The student hasn't marked")


def test_parse_json() -> None:
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(GeminiError):
        parse_json("no json here")


def test_gemini_error_messages() -> None:
    def err(status: int, body: dict) -> str:
        return str(Gemini._error(status, json.dumps({"error": body}).encode()))

    assert "didn't accept the API key" in err(400, {"message": "API key not valid. Please pass a valid API key.",
                                                     "details": [{"reason": "API_KEY_INVALID"}]})
    assert "limit" in err(429, {"message": "Resource has been exhausted"})
    assert "having problems" in err(503, {"message": "overloaded"})
    assert type(Gemini._error(404, b"{}")).__name__ == "_ModelGone"


def test_gemini_reads_the_answer() -> None:
    ok = {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"x": 1}'}]},
                          "finishReason": "STOP"}]}
    assert Gemini._text(ok) == '{"x": 1}'
    with pytest.raises(GeminiError, match="ran out of room"):
        Gemini._text({"candidates": [{"content": {"parts": [{"text": '{"x": '}]}, "finishReason": "MAX_TOKENS"}]})
    with pytest.raises(GeminiError, match="wouldn't answer"):
        Gemini._text({"promptFeedback": {"blockReason": "SAFETY"}})


# ---------- syncing files between computers ----------

@pytest.fixture
def two(tmp_path, monkeypatch):
    fake = FakeCloud()
    laptop, desktop = computer(tmp_path, "laptop", fake), computer(tmp_path, "desktop", fake)
    yield fake, laptop, desktop
    laptop._close()
    desktop._close()


def test_exam_files_sync_between_computers(two) -> None:
    fake, laptop, desktop = two
    laptop.sign_up("ada@example.com", "correct horse")
    desktop.sign_in("ada@example.com", "correct horse")
    course_id = add_course(laptop, "STK310")
    add_exam(laptop, course_id, ("exam", "exam.pdf", PDF))
    laptop.cloud_sync()
    user = laptop._account.session.user_id
    assert [d for d, _ in fake.files[user].values()] == [PDF]

    desktop.cloud_sync()
    desk_course = desktop.overview()["courses"][0]["id"]
    exam = desktop.exams(desk_course)["past"][0]
    assert exam["files"][0]["available"]
    key = next(iter(fake.files[user]))
    assert (files.folder_for(desktop._store.path) / key).read_bytes() == PDF

    # Nothing new: no file requests at all.
    before = fake.file_requests
    laptop.cloud_sync()
    desktop.cloud_sync()
    assert fake.file_requests == before

    # Deleted on the desktop: gone here, and from the cloud once it's been there a while.
    desktop.delete_exam(exam["id"])
    desktop.cloud_sync()
    assert list(files.folder_for(desktop._store.path).iterdir()) == []
    assert key in fake.files[user]  # just uploaded: kept for now (another computer may still be adding it)
    fake.files[user][key] = (PDF, "2020-01-01T00:00:00")
    desktop.cloud_sync()
    assert fake.files[user] == {}
    laptop.cloud_sync()
    assert list(files.folder_for(laptop._store.path).iterdir()) == []


def test_bringing_local_exams_into_an_account(two) -> None:
    fake, laptop, _ = two
    course_id = add_course(laptop, "STK310")
    add_exam(laptop, course_id, ("exam", "exam.pdf", PDF))
    local_folder = files.folder_for(laptop._store.path)
    laptop.sign_up("ada@example.com", "correct horse", True)
    new_course = laptop.overview()["courses"][0]["id"]
    assert laptop.exams(new_course)["past"][0]["files"][0]["available"]
    assert list(local_folder.iterdir()) == []  # moved, not copied
    user = laptop._account.session.user_id
    assert [d for d, _ in fake.files[user].values()] == [PDF]


def test_deleting_the_account_deletes_its_files(two) -> None:
    fake, laptop, _ = two
    laptop.sign_up("ada@example.com", "correct horse")
    add_exam(laptop, add_course(laptop, "STK310"), ("exam", "exam.pdf", PDF))
    laptop.cloud_sync()
    user = laptop._account.session.user_id
    assert fake.files[user]
    assert laptop.delete_account().get("ok")
    assert user not in fake.files


def test_schemas_are_ones_gemini_accepts() -> None:
    # Gemini refuses empty enum values ("enum[0]: cannot be empty") and anything but its own type names.
    def walk(node) -> None:
        if isinstance(node, dict):
            assert node.get("type", "OBJECT") in ("OBJECT", "ARRAY", "STRING", "INTEGER", "NUMBER", "BOOLEAN")
            assert all(v != "" for v in node.get("enum", []))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(L.READ_SCHEMA)
    walk(L.MAKE_SCHEMA)
