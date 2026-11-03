"""Past exams, their files, marking questions, and Groq reading and writing exams (with a stand-in
for Groq), and exam files syncing between two computers."""

from __future__ import annotations

import base64
import io
import json
import sys

import pytest

import studypal.api as api_module
from studypal.api import Api
from studypal.core import files
from studypal.core import pages
from studypal.core.groq import Groq, GroqError, Image, parse_json
from studypal.core.logic import exams as L
from studypal.core.models import ExamQuestion, Priority, Topic, WeakSpot

from test_cloud import FakeCloud, add_course, computer

def make_pdf(n_pages: int, width: float = 595) -> bytes:
    """A real (blank) PDF with that many pages."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        pdf.new_page(width, 842)
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


PDF = make_pdf(4)  # the exam paper: two requests (3 pages, then 1)
SOLUTIONS = make_pdf(1, 600)
MINE = make_pdf(2, 610)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class FakeGroq:
    """Answers each kind of request with the next reply the test set for it, and remembers what it was sent."""

    replies: dict[str, list[dict]] = {}
    sent: list[tuple[str, list, str | None]] = []  # (kind, parts, model)
    progress: list[dict] = []  # the Api's running jobs at each request
    api = None

    def __init__(self, key: str, model: str) -> None:
        self.key, self.model = key, model

    def ask(self, parts, schema, system="", temperature=None, model=None):
        kind = {id(L.PAGES_SCHEMA): "pages", id(L.ANSWERS_SCHEMA): "answers", id(L.MARKS_SCHEMA): "marks",
                id(L.MAKE_SCHEMA): "make"}[id(schema)]
        FakeGroq.sent.append((kind, parts, model))
        FakeGroq.progress.append(dict(FakeGroq.api._jobs) if FakeGroq.api else {})
        queue = FakeGroq.replies.get(kind) or [{}]
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "Groq", FakeGroq)
    FakeGroq.sent, FakeGroq.replies, FakeGroq.progress = [], {}, []
    a = Api(tmp_path / "studypal.db", notify=lambda t, b: True)
    FakeGroq.api = a
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
    assert api.save_ai({"key": "gsk_TESTKEY0123456789abcdefCDEF"}).get("ok")


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


def test_groq_needs_a_key(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF))
    assert api.exams(course_id)["ai"] is False
    assert "API key" in api.read_exam(exam_id)["error"]
    assert "doesn't look like" in api.save_ai({"key": "AIzaSyNotAGroqKey-0123456789"})["error"]
    with_key(api)
    s = api.ai_settings()
    assert s["has_key"] and s["key_hint"] == "…CDEF" and s["model"] == "openai/gpt-oss-120b"
    assert api.exams(course_id)["ai"] is True
    # The key is only readable by this user (Windows has no such permission bits; the folder is per user).
    if sys.platform != "win32":
        assert (api._prefs_path().stat().st_mode & 0o777) == 0o600
    api.save_ai({"forget": True})
    assert not api.ai_settings()["has_key"]


def test_reading_an_exam_a_few_pages_at_a_time(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("attempt", "mine.pdf", MINE), ("exam", "exam.pdf", PDF),
                       ("solution", "lf.pdf", SOLUTIONS))
    with_key(api)
    FakeGroq.replies = {
        "pages": [
            {"questions": [{"number": "1a", "prompt": "Find a sufficient statistic", "marks": "10", "topic": "sufficiency "},
                           {"number": "1b", "prompt": "Find the MLE.", "marks": "", "topic": "Something else"}]},
            # The last page carries on 1b, then has question 2.
            {"questions": [{"number": "1b)", "prompt": "Show it's unbiased.", "marks": "5", "topic": ""},
                           {"number": "2", "prompt": "Describe a prior.", "marks": "", "topic": "Bayesian inference"}]},
        ],
        "answers": [{"answers": [{"number": "1a", "answer": "$T = \\sum X_i$"}, {"number": "1b", "answer": "x̄"},
                                 {"number": "7", "answer": "not a question"}]}],
        "marks": [{"results": [{"number": "1a", "result": "missed", "note": "Forgot the factorisation theorem."},
                               {"number": "1b", "result": "ok", "note": ""},
                               {"number": "2", "result": "partial", "note": "No prior given."}], "score": "41/60"}],
    }
    r = api.read_exam(exam_id)
    assert r["message"] == "Exam 2024: found 3 questions and marked 3 from your answers."
    # The paper's 4 pages in two requests, then the solutions, then your answers; images always to the vision model.
    kinds = [(kind, sum(isinstance(p, Image) for p in parts), model) for kind, parts, model in FakeGroq.sent]
    assert kinds == [("pages", 3, "qwen/qwen3.8-27b"), ("pages", 1, "qwen/qwen3.8-27b"),
                     ("answers", 1, "qwen/qwen3.8-27b"), ("marks", 2, "qwen/qwen3.8-27b")]
    first, second = FakeGroq.sent[0][1][-1], FakeGroq.sent[1][1][-1]
    assert "pages 1 to 3 of 4" in first and "Sufficiency" in first
    assert "page 4 of 4" in second and "1a, 1b" in second and "Find the MLE." in second
    assert "STUDENT'S OWN ANSWERS" in FakeGroq.sent[-1][1][-1] and "Correct answer: x̄" in FakeGroq.sent[-1][1][-1]
    # What the window shows while it works, and nothing once it's done.
    job = f"read:{exam_id}"
    assert [p[job] for p in FakeGroq.progress] == [
        "Reading the questions, pages 1–3 of 4", "Reading the questions, page 4 of 4",
        "Reading the solutions, page 1 of 1", "Marking your answers, pages 1–2 of 2"]
    assert api.ai_jobs() == {}
    exam = api.exams(course_id)["past"][0]
    assert exam["score"] == "41/60"
    q1, q2, q3 = exam["questions"]
    assert (q1["number"], q1["topic"], q1["result"], q1["note"]) == ("1a", "Sufficiency", "missed", "Forgot the factorisation theorem.")
    assert q2["prompt"] == "Find the MLE.\n\nShow it's unbiased." and q2["marks"] == "5" and q2["topic"] is None
    assert q2["answer"] == "x̄" and q3["result"] == "partial" and q3["answer"] == ""
    assert exam["has_solution"]


def test_without_solutions_the_answers_are_written(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", make_pdf(2)))
    with_key(api)
    FakeGroq.replies = {"pages": [{"questions": [{"number": "1", "prompt": "Q", "marks": "", "topic": ""}]}],
                        "answers": [{"answers": [{"number": "1", "answer": "A"}]}]}
    assert api.read_exam(exam_id)["message"] == "Exam 2024: found 1 question."
    assert [(kind, model) for kind, _, model in FakeGroq.sent] == [("pages", "qwen/qwen3.8-27b"), ("answers", None)]
    exam = api.exams(course_id)["past"][0]
    assert exam["score"] == "" and exam["questions"][0]["answer"] == "A" and exam["questions"][0]["result"] == ""


def test_photos_and_text_files_can_be_read(api: Api) -> None:
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (3000, 2000), "white").save(buf, "PNG")
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "page1.png", buf.getvalue()), ("exam", "rest.txt", b"2. Prove it."))
    with_key(api)
    FakeGroq.replies = {"pages": [{"questions": [{"number": "1", "prompt": "Q1", "marks": "", "topic": ""}]},
                                  {"questions": [{"number": "2", "prompt": "Prove it.", "marks": "", "topic": ""}]}]}
    assert api.read_exam(exam_id)["message"] == "Exam 2024: found 2 questions."
    photo = FakeGroq.sent[0][1][0]
    assert isinstance(photo, Image) and photo.data[:2] == b"\xff\xd8"  # sent as JPEG
    assert "2. Prove it." in FakeGroq.sent[1][1][-1] and not any(isinstance(p, Image) for p in FakeGroq.sent[1][1])


def test_nothing_found(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", make_pdf(1)))
    with_key(api)
    FakeGroq.replies = {"pages": [{"questions": []}]}
    assert "didn't find any questions" in api.read_exam(exam_id)["error"]


def test_reading_needs_the_paper(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("solution", "lf.pdf", SOLUTIONS))
    with_key(api)
    assert "exam paper itself" in api.read_exam(exam_id)["error"]


def test_making_a_practice_exam(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", PDF), ("solution", "lf.pdf", SOLUTIONS),
                       ("attempt", "mine.pdf", MINE))
    add_exam(api, course_id, ("exam", "old.pdf", make_pdf(1, 500)))  # not read yet
    topics = {t["title"]: t["id"] for t in api.exams(course_id)["topics"]}
    api.save_question({"exam_id": exam_id, "number": "2b", "prompt": "Show that T is sufficient.", "marks": "8",
                       "answer": "Use the factorisation theorem.", "topic_id": topics["Sufficiency"], "result": "missed",
                       "note": "Mixed up the factors."})
    with_key(api)
    FakeGroq.replies = {"make": [{"title": "Practice exam 1: sufficiency", "intro": "**Time:** 1 hour", "questions": [
        {"number": "1", "topic": "Sufficiency", "why": "Practises 2b.", "marks": "10", "prompt": "New question",
         "answer": "Worked solution"},
        {"number": "2", "topic": "", "why": "", "marks": "", "prompt": "", "answer": ""},  # empty: dropped
    ]}]}
    r = api.make_exam({"course_id": course_id, "size": "short", "focus": "struggles", "wishes": "in English"})
    assert r.get("ok"), r
    assert "1 past exam not used: press Read questions on it first" in r["message"]
    kind, parts, model = FakeGroq.sent[-1]
    # Text only, to the chosen writing model: the past exams as read, and what went badly.
    assert kind == "make" and model is None and len(parts) == 1
    prompt = parts[0]
    assert "**2b** (8 marks) Show that T is sufficient." in prompt and "*Solution:* Use the factorisation theorem." in prompt
    assert "question 2b" in prompt and "Mixed up the factors." in prompt and "in English" in prompt
    assert "practice exam number 1" in prompt
    practice = api.exams(course_id)["practice"]
    assert [(e["title"], len(e["questions"])) for e in practice] == [("Practice exam 1: sufficiency", 1)]
    assert practice[0]["questions"][0]["why"] == "Practises 2b." and practice[0]["questions"][0]["topic"] == "Sufficiency"
    # The next one is told about the questions already asked.
    api.make_exam({"course_id": course_id, "size": "full", "focus": "balanced"})
    assert "New question" in FakeGroq.sent[-1][1][0] and "practice exam number 2" in FakeGroq.sent[-1][1][0]


def test_practice_exam_on_chosen_topics(api: Api) -> None:
    course_id = course_with_topics(api)
    with_key(api)
    assert "Pick the topics" in api.make_exam({"course_id": course_id, "focus": "topics", "topic_ids": []})["error"]
    FakeGroq.replies = {"make": [{"title": "", "intro": "", "questions": [{"number": "1", "prompt": "Q", "answer": "A"}]}]}
    topics = {t["title"]: t["id"] for t in api.exams(course_id)["topics"]}
    r = api.make_exam({"course_id": course_id, "focus": "topics", "topic_ids": [topics["Likelihood"]], "size": "short"})
    assert "Practice exam 1" in r["message"]
    prompt = FakeGroq.sent[-1][1][0]
    assert "Only ask about these topics: Likelihood." in prompt and "no past exams" in prompt


def test_groq_errors_come_back_as_messages(api: Api, monkeypatch) -> None:
    course_id = course_with_topics(api)
    with_key(api)

    def broken(self, *a, **kw):
        raise GroqError("You've hit Groq's per-minute limit. Wait a minute and try again.")

    monkeypatch.setattr(FakeGroq, "ask", broken)
    assert "per-minute limit" in api.make_exam({"course_id": course_id})["error"]
    assert api.exams(course_id)["practice"] == []


def test_broken_pdfs_say_so(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", b"%PDF-1.4 not really"))
    with_key(api)
    assert "can't be opened as a PDF" in api.read_exam(exam_id)["error"]


def test_pages_are_jpegs_of_a_sensible_size() -> None:
    images = pages.pdf_pages("exam.pdf", make_pdf(2))
    from PIL import Image as PILImage

    sizes = [PILImage.open(io.BytesIO(img)).size for img in images]
    assert len(images) == 2 and all(max(s) == pages.LONG_SIDE for s in sizes)
    with pytest.raises(pages.PageError, match="at most"):
        pages.pdf_pages("huge.pdf", make_pdf(pages.MAX_PAGES + 1))


def test_merging_pages() -> None:
    found: list[dict] = []
    L.merge_questions(found, [{"number": "Question 1", "prompt": "Part one", "marks": "", "topic": ""}])
    L.merge_questions(found, [{"number": "1", "prompt": "continued", "marks": "4", "topic": "X"},
                              {"number": "2", "prompt": "Next", "marks": "", "topic": ""}])
    assert [(q["number"], q["prompt"], q["marks"]) for q in found] == [("Question 1", "Part one\n\ncontinued", "4"),
                                                                       ("2", "Next", "")]
    for q in found:
        q["answer"] = ""
    L.merge_field(found, [{"number": "1", "answer": "a"}], "answer")
    L.merge_field(found, [{"number": "1", "answer": "b"}, {"number": "1", "answer": "b"}], "answer")
    assert found[0]["answer"] == "a\n\nb"


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
    assert parse_json('<think>hmm</think>{"a": [1, 2]}') == {"a": [1, 2]}
    assert parse_json('Here you go: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(GroqError):
        parse_json("no json here")


def test_groq_error_messages() -> None:
    def err(status: int, body: dict) -> str:
        return str(Groq._error(status, json.dumps({"error": body}).encode()))

    assert "didn't accept the API key" in err(401, {"message": "Invalid API Key", "code": "invalid_api_key"})
    assert "per-minute" in err(429, {"message": "Rate limit reached for model on tokens per minute (TPM)"})
    assert "today's" in err(429, {"message": "Rate limit reached on tokens per day (TPD): Limit 200000"})
    assert "no longer offers" in err(404, {"message": "The model `x` does not exist", "code": "model_not_found"})
    assert "having problems" in err(503, {"message": "over capacity"})
    assert "right shape" in err(400, {"message": "Generated JSON does not match", "code": "json_validate_failed"})


def test_groq_reads_the_answer() -> None:
    assert Groq._text({"choices": [{"message": {"content": '{"x": 1}'}, "finish_reason": "stop"}]}) == '{"x": 1}'
    with pytest.raises(GroqError, match="ran out of room"):
        Groq._text({"choices": [{"message": {"content": '{"x": '}, "finish_reason": "length"}]})
    with pytest.raises(GroqError, match="nothing"):
        Groq._text({"choices": []})


def test_the_request(monkeypatch) -> None:
    """What goes over the wire: strict structured output, images as JPEG data URLs, the reasoning settings."""
    sent = {}

    def post(self, data):
        sent.update(json.loads(data))
        return {"choices": [{"message": {"content": '{"questions": []}'}, "finish_reason": "stop"}]}

    monkeypatch.setattr(Groq, "_post", post)
    g = Groq("gsk_x")
    assert g.ask([Image("p1", b"\xff\xd8jpeg"), "Read it"], L.PAGES_SCHEMA, "sys", 0.1, model="qwen/qwen3.8-27b") == {"questions": []}
    assert sent["response_format"]["json_schema"]["strict"] is True and sent["reasoning_format"] == "hidden"
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    g.ask(["Write"], L.MAKE_SCHEMA)
    assert sent["model"] == "openai/gpt-oss-120b" and sent["include_reasoning"] is False and sent["messages"][-1]["content"] == "Write"
    with pytest.raises(GroqError, match="at most 3"):
        g.ask([Image("p", b"x")] * 4 + ["too many"], L.PAGES_SCHEMA)


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


def test_schemas_are_strict() -> None:
    # Groq's strict mode: every object lists all its fields as required and allows nothing else.
    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
            assert all(v != "" for v in node.get("enum", []))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for schema in (L.PAGES_SCHEMA, L.ANSWERS_SCHEMA, L.MARKS_SCHEMA, L.MAKE_SCHEMA):
        walk(schema)


def test_one_job_at_a_time_per_exam(api: Api) -> None:
    course_id = course_with_topics(api)
    exam_id = add_exam(api, course_id, ("exam", "exam.pdf", make_pdf(1)))
    with_key(api)
    api._jobs[f"read:{exam_id}"] = "Reading"  # already running (from another click)
    assert "already on it" in api.read_exam(exam_id)["error"]
    assert api.ai_jobs() == {f"read:{exam_id}": "Reading"}  # the running one isn't disturbed
