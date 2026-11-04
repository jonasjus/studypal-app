"""Past exams, their files, marking questions, reading exams and writing practice exams through the
window's calls (with a stand-in model), and exam files syncing between two computers. The reader itself
is tested in test_ingest.py."""

from __future__ import annotations

import base64
import io
import json
import sys

import pytest

import studypal.api as api_module
from studypal.api import Api
from studypal.core import files, llm
from studypal.core.logic import attempts as A
from studypal.core.logic import exams as L
from studypal.core.logic import questions as Q
from studypal.core.models import ExamQuestion, Priority, Topic, WeakSpot

from pdfs import blank_pdf, text_pdf
from test_cloud import FakeCloud, add_course, computer

PDF = text_pdf(["STK310 exam 2024\nQuestion 1 (10 points)\na) Find a sufficient statistic for the Poisson mean.\n"
                "b) Find the maximum likelihood estimator, and show that it is unbiased.\n"
                "Question 2 (8 points)\nDescribe a conjugate prior for the Poisson mean and its posterior."])
SOLUTIONS = text_pdf(["STK310 exam 2024, solutions\n1a) T is the sum of the observations, by the factorisation theorem.\n"
                      "1b) The MLE is the sample mean; its expectation is the mean, so it is unbiased."])
MINE = blank_pdf(1, 610)  # handwritten: a scan


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class FakeModel:
    """A Provider that answers each kind of request with the next reply the test set, and remembers what it got."""

    name = "Fake"
    max_images = 3
    chunk_chars = 100_000
    replies: dict[str, list[dict]] = {}
    sent: list[tuple[str, list, bool]] = []
    progress: list[dict] = []
    api = None

    def ask(self, parts, schema, system="", temperature=None, vision=False, effort="medium"):
        kind = {id(Q.QUESTIONS_SCHEMA): "questions", id(Q.SOLUTIONS_SCHEMA): "solutions", id(Q.TRANSCRIBE_SCHEMA): "transcribe",
                id(Q.MARKS_SCHEMA): "marks", id(Q.GENERATE_SCHEMA): "generate", id(A.GRADE_SCHEMA): "grade"}[id(schema)]
        FakeModel.sent.append((kind, parts, vision))
        FakeModel.progress.append(dict(FakeModel.api._jobs) if FakeModel.api else {})
        queue = FakeModel.replies.get(kind) or [{}]
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
def api(tmp_path, monkeypatch):
    def provider(prefs):  # the real check for a key, then the stand-in
        llm.provider_from(prefs)
        return FakeModel()

    monkeypatch.setattr(api_module, "provider_from", provider)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    FakeModel.sent, FakeModel.replies, FakeModel.progress = [], {}, []
    a = Api(tmp_path / "studypal.db", notify=lambda t, b: True)
    FakeModel.api = a
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


GEMINI_KEY = "AIzaSyTESTKEY-0123456789abcdefghijCDEF"


def with_key(api: Api) -> None:
    assert api.save_ai({"provider": "gemini", "keys": {"gemini": GEMINI_KEY}}).get("ok")


def q(number: str, text: str, tags: list[str] | None = None, **more) -> dict:
    """A question as the model gives it."""
    return {"number": number, "parent_number": "", "text": text, "topic_tags": tags or [], "question_type": "other",
            "points": "", "has_figure": False, **more}


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


def test_a_model_needs_setting_up(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF))
    assert api.exams(course_id)["ai"] is False
    assert "Gemini API key" in api.read_exam(exam_id)["error"]
    assert "doesn't look like a Gemini API key" in api.save_ai({"provider": "gemini", "keys": {"gemini": "gsk_wrong"}})["error"]
    with_key(api)
    s = api.ai_settings()
    assert s["provider"] == "gemini" and s["keys"]["gemini"]["has_key"] and s["keys"]["gemini"]["key_hint"] == "…CDEF"
    assert not s["keys"]["groq"]["has_key"] and api.exams(course_id)["ai"] is True
    # The key is only readable by this user (Windows has no such permission bits; the folder is per user).
    if sys.platform != "win32":
        assert (api._prefs_path().stat().st_mode & 0o777) == 0o600
    # Ollama needs no key; a provider's saved key can be removed.
    assert api.save_ai({"provider": "ollama", "ollama_model": "qwen2.5vl:7b"}).get("ok")
    assert api.exams(course_id)["ai"] is True and api.ai_settings()["ollama_model"] == "qwen2.5vl:7b"
    assert "isn't an Ollama model" in api.save_ai({"provider": "ollama", "ollama_model": "rm -rf /"})["error"]
    api.save_ai({"provider": "gemini", "forget": ["gemini"]})
    assert not api.ai_settings()["keys"]["gemini"]["has_key"]


def test_the_environment_key_wins(api: Api, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "e" * 35)
    s = api.ai_settings()["keys"]["gemini"]
    assert s["from_env"] and s["has_key"] and s["env"] == "GEMINI_API_KEY"


def test_reading_an_exam(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("attempt", "mine.pdf", MINE), ("exam", "exam.pdf", PDF),
                       ("solution", "lf.pdf", SOLUTIONS))
    with_key(api)
    FakeModel.replies = {
        "transcribe": [{"pages": [{"page": 1, "markdown": "1a) $T = \\bar X$ ✗ (teacher: wrong)"}]}],
        "questions": [{"questions": [q("1a", "Find a sufficient statistic", ["sufficiency "], points="5", parent_number="1",
                                       question_type="proof"),
                                     q("1b", "Find the MLE and show it's unbiased.", ["Something else"], points="5 points"),
                                     q("2", "Describe a conjugate prior.", ["Bayesian inference"], has_figure=True)]}],
        "solutions": [{"solutions": [{"number": "1 a)", "answer": "$T = \\sum X_i$"}, {"number": "1b", "answer": "x̄"}]}],
        "marks": [{"results": [{"number": "1a", "result": "missed", "note": "Forgot the factorisation theorem."},
                               {"number": "2", "result": "partial", "note": "No prior given."}], "score": "41/60"}],
    }
    r = api.read_exam(exam_id)
    assert r["message"] == "Exam 2024: found 3 questions, 2 with an answer from the solutions, marked 2 from your answers."
    # The typed exam and solutions go as text; only your handwritten (scanned) answers are read from an image.
    assert [(kind, vision) for kind, _, vision in FakeModel.sent] == \
        [("transcribe", True), ("questions", False), ("solutions", False), ("marks", False)]
    assert "Find a sufficient statistic for the Poisson mean" in FakeModel.sent[1][1][0]
    assert "factorisation theorem" in FakeModel.sent[2][1][0]
    assert "teacher: wrong" in FakeModel.sent[3][1][0]
    assert [p[f"read:{exam_id}"] for p in FakeModel.progress] == [
        "Transcribing “mine.pdf”, page 1 of 1", "Finding the questions, page 1 of 1", "Reading the solutions, page 1 of 1",
        "Marking your answers, page 1 of 1"]
    assert api.ai_jobs() == {}
    exam = api.exams(course_id)["past"][0]
    assert exam["score"] == "41/60"
    q1, q2, q3 = exam["questions"]
    assert (q1["number"], q1["topic"], q1["result"], q1["note"]) == ("1a", "Sufficiency", "missed", "Forgot the factorisation theorem.")
    assert (q1["parent_number"], q1["question_type"], q1["type_label"], q1["marks"]) == ("1", "proof", "Proof", "5")
    assert q2["answer"] == "x̄" and q2["topic"] is None and q2["tags"] == ["Something else"] and q2["marks"] == "5"
    assert q3["answer"] is None and q3["has_figure"] and q3["result"] == "partial"  # not in the solutions: no answer
    stored = api._store.list_questions(exam_id)[2]
    assert stored.answer is None and stored.topic_tags == ["Bayesian inference"]


def test_without_solutions_nothing_is_answered_or_marked(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF))
    with_key(api)
    FakeModel.replies = {"questions": [{"questions": [q("1", "Q")]}]}
    assert api.read_exam(exam_id)["message"] == "Exam 2024: found 1 question."
    assert [kind for kind, _, _ in FakeModel.sent] == ["questions"]
    exam = api.exams(course_id)["past"][0]
    assert exam["score"] == "" and exam["questions"][0]["answer"] is None and exam["questions"][0]["result"] == ""


def test_numbering_mismatches_are_reported(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF), ("solution", "lf.pdf", SOLUTIONS))
    with_key(api)
    FakeModel.replies = {"questions": [{"questions": [q("1", "Q"), q("", "no number")]}],
                         "solutions": [{"solutions": [{"number": "I", "answer": "roman"}]}]}
    message = api.read_exam(exam_id)["message"]
    assert "0 with an answer" in message and "also answer I, which didn't match" in message and "1 came back incomplete" in message


def test_photos_are_read(api: Api) -> None:
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (3000, 2000), "white").save(buf, "PNG")
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "page1.png", buf.getvalue()), ("exam", "rest.txt", b"2. Prove it."))
    with_key(api)
    FakeModel.replies = {"transcribe": [{"pages": [{"page": 1, "markdown": "1. Find $x$."}]}],
                         "questions": [{"questions": [q("1", "Find $x$."), q("2", "Prove it.")]}]}
    assert api.read_exam(exam_id)["message"] == "Exam 2024: found 2 questions."
    photo = FakeModel.sent[0][1][0]
    assert isinstance(photo, llm.Image) and photo.data[:2] == b"\xff\xd8"  # sent as JPEG
    assert "1. Find $x$." in FakeModel.sent[1][1][0] and "2. Prove it." in FakeModel.sent[1][1][0]


def test_nothing_found(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF))
    with_key(api)
    FakeModel.replies = {"questions": [{"questions": []}]}
    assert "No questions were found" in api.read_exam(exam_id)["error"]


def test_reading_needs_the_paper(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("solution", "lf.pdf", SOLUTIONS))
    with_key(api)
    assert "exam paper itself" in api.read_exam(exam_id)["error"]


def test_making_a_practice_exam(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF), ("solution", "lf.pdf", SOLUTIONS))
    add_exam(api, course_id, ("exam", "old.pdf", blank_pdf(1, 500)))  # not read yet
    topics = {t["title"]: t["id"] for t in api.exams(course_id)["topics"]}
    api.save_question({"exam_id": exam_id, "number": "2b", "prompt": "Show that T is sufficient.", "marks": "8",
                       "answer": "Use the factorisation theorem.", "topic_id": topics["Sufficiency"], "result": "missed",
                       "note": "Mixed up the factors."})
    with_key(api)
    FakeModel.replies = {"generate": [{"title": "Practice exam 1: sufficiency", "intro": "**Time:** 1 hour", "questions": [
        q("1", "New question", ["Sufficiency"], why="Practises 2b.", points="10", answer="Worked solution",
          question_type="proof"),
        q("2", "", why="", answer=""),  # empty: dropped
    ]}]}
    r = api.make_exam({"course_id": course_id, "size": "short", "focus": "struggles", "wishes": "in English"})
    assert r.get("ok"), r
    assert "1 past exam not used: press Read questions on it first" in r["message"]
    kind, parts, vision = FakeModel.sent[-1]
    assert kind == "generate" and not vision and len(parts) == 1
    prompt = parts[0]
    # What went badly leads; the missed question is a few-shot example for its topic, with its solution.
    assert "5 questions" in prompt and "most on the first ones: Sufficiency;" in prompt
    assert "### Sufficiency\n- From Exam 2024, question 2b (8 points): Show that T is sufficient." in prompt
    assert "*Solution:* Use the factorisation theorem." in prompt and "Mixed up the factors." in prompt and "in English" in prompt
    assert "practice exam number 1" in prompt
    practice = api.exams(course_id)["practice"]
    assert [(e["title"], len(e["questions"])) for e in practice] == [("Practice exam 1: sufficiency", 1)]
    made = practice[0]["questions"][0]
    assert (made["why"], made["topic"], made["marks"], made["question_type"]) == ("Practises 2b.", "Sufficiency", "10", "proof")
    # The next one is told about the questions already asked.
    api.make_exam({"course_id": course_id, "size": "full", "focus": "balanced"})
    assert "New question" in FakeModel.sent[-1][1][0] and "practice exam number 2" in FakeModel.sent[-1][1][0]


def test_practice_exam_on_chosen_topics(api: Api) -> None:
    course_id = course_with_topics(api)
    with_key(api)
    assert "Pick the topics" in api.make_exam({"course_id": course_id, "focus": "topics", "topic_ids": []})["error"]
    FakeModel.replies = {"generate": [{"title": "", "intro": "", "questions": [q("1", "Q", answer="A")]}]}
    topics = {t["title"]: t["id"] for t in api.exams(course_id)["topics"]}
    r = api.make_exam({"course_id": course_id, "focus": "topics", "topic_ids": [topics["Likelihood"]], "size": "short"})
    assert "Practice exam 1" in r["message"]
    prompt = FakeModel.sent[-1][1][0]
    assert "most on the first ones: Likelihood." in prompt and "There are no past exams" in prompt


def test_model_errors_come_back_as_messages(api: Api, monkeypatch) -> None:
    course_id = course_with_topics(api)
    with_key(api)

    def broken(self, *a, **kw):
        raise llm.LLMError("You've hit Gemini's rate limit. Wait a minute and try again.")

    monkeypatch.setattr(FakeModel, "ask", broken)
    assert "rate limit" in api.make_exam({"course_id": course_id})["error"]
    assert api.exams(course_id)["practice"] == []


def test_broken_pdfs_say_so(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", b"%PDF-1.4 not really"))
    with_key(api)
    assert "can't be opened as a PDF" in api.read_exam(exam_id)["error"]


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
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('<think>hmm</think>{"a": [1, 2]}') == {"a": [1, 2]}
    assert llm.parse_json('Here you go: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(llm.LLMError):
        llm.parse_json("no json here")


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


def test_one_job_at_a_time_per_exam(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF))
    with_key(api)
    api._jobs[f"read:{exam_id}"] = "Reading"  # already running (from another click)
    assert "already being worked on" in api.read_exam(exam_id)["error"]
    assert api.ai_jobs() == {f"read:{exam_id}": "Reading"}  # the running one isn't disturbed
