"""The exam reader: the question schema (Pydantic), matching questions with their solutions, PDFs to
Markdown, the pipeline with a stand-in model, the provider client's retries, and generate_exam."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from studypal.core import ingest, llm, pages
from studypal.core.generate import generate_exam
from studypal.core.logic import exams as E
from studypal.core.logic import questions as Q
from studypal.core.models import Course, ExamQuestion, Topic

from pdfs import blank_pdf, text_pdf

FIXTURES = Path(__file__).parent / "fixtures"
EXAM = (FIXTURES / "exam.txt").read_text()
SOLUTIONS = (FIXTURES / "solutions.txt").read_text()
EXTRACTION = json.loads((FIXTURES / "extraction.json").read_text())
COURSE = Course("Statistical Inference", "STK310", None, None, id=1)  # type: ignore[arg-type]
TOPICS = [Topic(1, "Sufficiency", id=1), Topic(1, "Likelihood", id=2), Topic(1, "Bayesian inference", id=3)]


class FakeModel:
    """A Provider that answers each kind of request from a list, and remembers what it was sent."""

    name = "Fake"
    max_images = 2
    chunk_chars = 100_000

    def __init__(self, **replies: list) -> None:
        self.replies = replies
        self.sent: list[tuple[str, list, bool]] = []

    def ask(self, parts, schema, system="", temperature=None, vision=False, effort="medium"):
        kind = {id(Q.QUESTIONS_SCHEMA): "questions", id(Q.SOLUTIONS_SCHEMA): "solutions", id(Q.TRANSCRIBE_SCHEMA): "transcribe",
                id(Q.MARKS_SCHEMA): "marks", id(Q.GENERATE_SCHEMA): "generate"}[id(schema)]
        self.sent.append((kind, parts, vision))
        queue = self.replies.get(kind) or [{}]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


QUESTIONS = {"questions": EXTRACTION["questions"]}
ANSWERS = {"solutions": EXTRACTION["solutions"]}


# ---------- the schema ----------

def test_a_question_is_checked_and_tidied() -> None:
    q = Q.Question.model_validate({"number": " 3b ", "parent_number": "", "text": "Find $x$.", "points": "7,5 p",
                                   "topic_tags": ["Likelihood", " likelihood ", ""], "question_type": "Short Answer",
                                   "answer": "  ", "has_figure": False})
    assert (q.number, q.parent_number, q.points, q.topic_tags, q.question_type, q.answer) == \
        ("3b", None, 7.5, ["Likelihood"], "short_answer", None)
    assert Q.Question.model_validate({"number": "1", "text": "Q", "question_type": "riddle"}).question_type == "other"
    assert Q.Question.model_validate({"number": "1", "text": "Q", "points": ""}).points is None


@pytest.mark.parametrize("bad", [
    {"number": "", "text": "Q"},  # no number
    {"number": "1", "text": ""},  # no question
    {"number": "1", "text": "Q", "points": -2},  # negative points
    {"number": "1", "text": "Q", "has_figure": "maybe"},
    {"number": "x" * 21, "text": "Q"},
])
def test_questions_that_dont_fit_are_refused(bad) -> None:
    with pytest.raises(Q.ValidationError):
        Q.Question.model_validate(bad)


def test_the_fixture_validates_and_bad_entries_are_dropped() -> None:
    extraction, dropped = Q.validate_extraction(EXTRACTION, exam_id=7)
    assert [q.number for q in extraction.questions] == ["1a", "1 b)", "2", "3"]
    assert dropped == 1  # question 4 has no text
    assert all(q.exam_id == 7 and q.id is None for q in extraction.questions)
    assert extraction.questions[3].has_figure and extraction.questions[1].points == 5.0
    with pytest.raises(ValueError):
        Q.validate_extraction(["not", "an", "object"])


def test_schemas_sent_to_the_model_are_strict() -> None:
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

    for schema in (Q.QUESTIONS_SCHEMA, Q.SOLUTIONS_SCHEMA, Q.GENERATE_SCHEMA, Q.TRANSCRIBE_SCHEMA, Q.MARKS_SCHEMA):
        walk(schema)


# ---------- matching questions with solutions ----------

def test_each_question_gets_its_own_solution_and_none_is_guessed() -> None:
    extraction, _ = Q.validate_extraction(EXTRACTION)
    matched, unmatched = Q.match_solutions(extraction.questions, extraction.solutions)
    answers = {q.number: q.answer for q in matched}
    assert answers["1a"].startswith("By the factorisation theorem")
    assert answers["1 b)"].startswith("The log-likelihood")  # "1 b)" matches "1b"
    assert answers["2"].startswith("A confidence interval")  # "Question 2" matches "2"
    assert answers["3"] is None  # the solutions don't answer it: no answer, not a guess
    assert unmatched == ["7"]


@pytest.mark.parametrize("a, b, same", [("3b", "3 b)", True), ("Oppgave 2", "2", True), ("Q4.", "4", True),
                                        ("3(b)", "3.b", True), ("1 . 14", "1.14", True),
                                        ("3a", "3b", False), ("1", "11", False), ("3", "3a", False), ("1.1", "11", False),
                                        ("1.10", "1.1", False)])
def test_numbers_match_only_when_they_are_the_same_question(a, b, same) -> None:
    assert (Q.number_key(a) == Q.number_key(b)) is same


def test_a_solution_given_in_pieces_is_joined() -> None:
    qs = [Q.Question(number="1", text="Q")]
    matched, _ = Q.match_solutions(qs, [Q.Solution(number="1", answer="First"), Q.Solution(number="1.", answer="Then")])
    assert matched[0].answer == "First\n\nThen"
    assert qs[0].answer is None  # the input isn't changed


def test_a_question_split_by_a_page_break_is_joined() -> None:
    qs = Q.dedupe([Q.Question(number="2", text="Part one"), Q.Question(number="2", text="continued", points=4),
                   Q.Question(number="3", text="Next")])
    assert [(q.number, q.text, q.points) for q in qs] == [("2", "Part one\n\ncontinued", 4.0), ("3", "Next", None)]


# ---------- PDFs to Markdown ----------

def test_typed_pages_use_their_text_and_scans_are_read() -> None:
    data = text_pdf([EXAM, "1"])
    got = pages.pdf_text_pages("exam.pdf", data)
    assert got[0].image is None and "Question 2 (8 points)" in got[0].text
    assert got[1].image is not None and got[1].image[:2] == b"\xff\xd8"  # almost no text: a scan, as a JPEG


def test_typed_pages_with_maths_keep_their_text() -> None:
    # Only scans go to the model as images; garbled formulas in a text layer are fixed when finding questions.
    maths = "Show that ∑ᵢ (xᵢ − x̄)² ≥ 0 and that ∫ f(x) dx = 1 for all θ ∈ Θ. " * 4
    assert not pages.needs_reading(maths) and not pages.needs_reading(EXAM) and pages.needs_reading("Page 3")


def test_markdown_comes_from_the_text_layer_without_asking_the_model() -> None:
    model = FakeModel()
    doc, read, kept = ingest.to_markdown(model, ingest.SourceFile("exam.pdf", "application/pdf", text_pdf([EXAM]), "exam"))
    assert (read, kept, model.sent) == (0, 0, [])
    assert doc.total == 1 and doc.pages[0][0] == 1 and "Explain the difference" in doc.pages[0][1]


def test_scanned_pages_are_transcribed_a_few_at_a_time() -> None:
    model = FakeModel(transcribe=[{"pages": [{"page": 1, "markdown": "Question 1: find $x$"},
                                             {"page": 2, "markdown": "(continued) $$x^2 = 4$$"}]},
                                  {"pages": [{"page": 0, "markdown": "Question 2"}]}])  # a page without its number
    doc, read, kept = ingest.to_markdown(model, ingest.SourceFile("scan.pdf", "application/pdf", blank_pdf(3), "exam"))
    assert (read, kept) == (3, 0)
    assert [(k, sum(isinstance(p, llm.Image) for p in parts), vision) for k, parts, vision in model.sent] == \
        [("transcribe", 2, True), ("transcribe", 1, True)]  # max_images is 2
    assert "pages 1, 2 of 3" in model.sent[0][1][-1] and "LaTeX" in model.sent[0][1][-1]
    assert doc.pages == [(1, "Question 1: find $x$"), (2, "(continued) $$x^2 = 4$$"), (3, "Question 2")]


def test_pages_that_dont_fit_are_split_and_a_hopeless_scan_says_so() -> None:
    too_much = llm.TooMuch("ran out of room")
    model = FakeModel(transcribe=[too_much, {"pages": [{"page": 1, "markdown": "One"}]}, too_much])
    with pytest.raises(llm.LLMError, match="Page 2 of “scan.pdf” has more on it than Fake can write out"):
        ingest.to_markdown(model, ingest.SourceFile("scan.pdf", "application/pdf", blank_pdf(2), "exam"))
    assert [sum(isinstance(p, llm.Image) for p in parts) for _, parts, _ in model.sent] == [2, 1, 1]  # both, then each


def test_an_incomplete_transcription_keeps_the_text_layer() -> None:
    page = pages.Page(1, "Some text " * 5, b"\xff\xd8jpeg")  # a short page with a little text, read as an image
    model = FakeModel(transcribe=[{"pages": [{"page": 1, "markdown": "Some"}]}])  # most of it left out
    original = pages.to_pages
    pages.to_pages = lambda *a: [page]
    try:
        doc, read, kept = ingest.to_markdown(model, ingest.SourceFile("x.pdf", "application/pdf", b"", "exam"))
    finally:
        pages.to_pages = original
    assert kept == 1 and doc.pages == [(1, page.text)]


def test_long_documents_go_in_pieces() -> None:
    doc = ingest.Doc("exam.pdf", "exam", [(1, "a" * 300), (2, "b" * 300), (3, "c" * 900), (4, "d" * 100)], 4)
    assert [[n for _, n, _ in piece] for piece in ingest.pieces([doc], 700)] == [[1, 2], [3], [4]]
    assert ingest.where(ingest.pieces([doc], 700)[0]) == "pages 1–2 of 4"
    done: list[list[int]] = []

    def do(items: list[int]) -> None:
        if len(items) > 2:
            raise llm.TooMuch("too long")
        done.append(items)

    ingest.in_pieces([1, 2, 3, 4, 5], do)
    assert done == [[1, 2], [3], [4, 5]]


# ---------- the pipeline ----------

def test_ingesting_an_exam_with_its_solutions() -> None:
    model = FakeModel(questions=[json.loads(json.dumps(QUESTIONS))], solutions=[json.loads(json.dumps(ANSWERS))])
    files = [ingest.SourceFile("exam.pdf", "application/pdf", text_pdf([EXAM]), "exam"),
             ingest.SourceFile("lf.pdf", "application/pdf", text_pdf([SOLUTIONS]), "solution")]
    steps: list[str] = []
    result = ingest.ingest(model, COURSE, TOPICS, files, exam_id=7, progress=steps.append)
    assert [(kind, vision) for kind, _, vision in model.sent] == [("questions", False), ("solutions", False)]
    questions, solutions = model.sent[0][1][0], model.sent[1][1][0]
    assert "page 1 of 1 of the EXAM PAPER" in questions and "Question 3 (12 points)" in questions and "Sufficiency" in questions
    assert "garbled" in questions  # told to write formulas from the text layer as LaTeX
    assert "SOLUTIONS" in solutions and "factorisation theorem" in solutions and "- 1 b): Let $X_1" in solutions
    assert [q.answer is not None for q in result.questions] == [True, True, True, False]
    assert result.unmatched == ["7"] and result.dropped == 1 and result.results == {}
    assert steps == ["Reading the files", "Finding the questions, page 1 of 1", "Reading the solutions, page 1 of 1"]


def test_questions_over_several_requests_carry_on() -> None:
    first = {"questions": [{**EXTRACTION["questions"][0]}, {**EXTRACTION["questions"][1], "text": "Find the MLE"}]}
    second = {"questions": [{**EXTRACTION["questions"][1], "number": "1b", "text": "of lambda."},
                            {**EXTRACTION["questions"][2]}]}
    model = FakeModel(questions=[first, second])
    model.chunk_chars = 400  # each page its own request
    exam = ingest.SourceFile("exam.pdf", "application/pdf", text_pdf([EXAM[:350], EXAM[350:]]), "exam")
    result = ingest.ingest(model, COURSE, TOPICS, [exam])
    assert len(model.sent) == 2 and "Earlier pages had questions 1a, 1 b)" in model.sent[1][1][0]
    assert [(q.number, q.text) for q in result.questions][1] == ("1 b)", "Find the MLE\n\nof lambda.")


def test_without_solutions_every_answer_is_none() -> None:
    model = FakeModel(questions=[{"questions": EXTRACTION["questions"][:2]}])
    result = ingest.ingest(model, COURSE, TOPICS, [ingest.SourceFile("exam.txt", "text/plain", EXAM.encode(), "exam")])
    assert [kind for kind, _, _ in model.sent] == ["questions"]  # nothing asked about solutions there aren't
    assert [q.answer for q in result.questions] == [None, None]


def test_your_answers_mark_each_question() -> None:
    model = FakeModel(questions=[{"questions": EXTRACTION["questions"][:3]}],
                      marks=[{"results": [{"number": "1A", "result": "missed", "note": "Forgot the theorem."},
                                          {"number": "2", "result": "unknown", "note": ""},
                                          {"number": "9", "result": "ok", "note": ""}], "score": "41/60"}])
    files = [ingest.SourceFile("exam.txt", "text/plain", EXAM.encode(), "exam"),
             ingest.SourceFile("mine.txt", "text/plain", b"1a) I think T is the mean", "attempt")]
    result = ingest.ingest(model, COURSE, TOPICS, files)
    assert "STUDENT'S OWN ANSWERS" in model.sent[1][1][0] and "I think T is the mean" in model.sent[1][1][0]
    assert result.results == {"1.a": ("missed", "Forgot the theorem.")} and result.score == "41/60"


def test_an_exam_without_questions_says_so() -> None:
    model = FakeModel(questions=[{"questions": []}])
    with pytest.raises(llm.LLMError, match="No questions"):
        ingest.ingest(model, COURSE, TOPICS, [ingest.SourceFile("exam.txt", "text/plain", EXAM.encode(), "exam")])
    with pytest.raises(llm.LLMError, match="exam paper itself"):
        ingest.ingest(model, COURSE, TOPICS, [ingest.SourceFile("lf.txt", "text/plain", b"x", "solution")])


def test_a_page_too_dense_to_list_says_which() -> None:
    model = FakeModel(questions=[llm.TooMuch("ran out of room")])
    with pytest.raises(llm.LLMError, match="Page 1 of “exam.txt” has more questions on it than Fake"):
        ingest.ingest(model, COURSE, TOPICS, [ingest.SourceFile("exam.txt", "text/plain", EXAM.encode(), "exam")])


# ---------- the provider client ----------

class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(status: int, body: dict, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", status, "err", headers or {}, io.BytesIO(json.dumps(body).encode()))


def test_rate_limits_are_retried_with_backoff(monkeypatch) -> None:
    calls: list[dict] = []
    waits: list[float] = []
    replies = [_http_error(429, {"error": {"message": "Rate limit"}}, {"retry-after": "7"}),
               _http_error(429, {"error": {"message": "Rate limit"}}),
               _http_error(503, {"error": {"message": "overloaded"}})]

    def urlopen(req, timeout=None, context=None):
        calls.append(json.loads(req.data))
        if replies:
            raise replies.pop(0)
        return _Reply(json.dumps({"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}).encode())

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(llm.random, "uniform", lambda a, b: 0)
    client = llm.OpenAICompatible(llm.PROVIDERS["gemini"], "AIza" + "x" * 35, sleep=waits.append)
    assert client.ask(["hi"], {"type": "object"}) == {"ok": True}
    assert len(calls) == 4 and waits == [7.5, 4.0, 8.0]  # what the server asked for, then 2·2ⁿ seconds
    assert calls[0]["model"] == "gemini-3.8-flash" and calls[0]["response_format"]["json_schema"]["strict"] is True


def _ok(content: str = '{"ok": true}', used: int = 10) -> _Reply:
    return _Reply(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                              "usage": {"completion_tokens": used}}).encode())


def test_a_plan_that_allows_less_output_gets_asked_for_less(monkeypatch) -> None:
    calls: list[dict] = []
    replies = [_http_error(429, {"error": {"code": "rate_limit_exceeded", "message":
               "Request too large for model `qwen/qwen3.8-27b` on output tokens per minute (OTPM): Limit 1000, Requested 8192."}}),
               _ok()]

    def urlopen(req, timeout=None, context=None):
        calls.append(json.loads(req.data))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    waits: list[float] = []
    client = llm.OpenAICompatible(llm.PROVIDERS["groq"], "gsk_x", sleep=waits.append)
    assert client.ask(["hi"], {"type": "object"}, vision=True, effort="low") == {"ok": True}
    assert [c["max_completion_tokens"] for c in calls] == [8192, 900] and waits == []  # straight away, no waiting
    assert calls[0]["model"] == "qwen/qwen3.8-27b" and calls[0]["reasoning_effort"] == "none"


def test_an_answer_that_used_its_whole_allowance_was_cut_off(monkeypatch) -> None:
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None, context=None: _ok(used=8192))
    with pytest.raises(llm.TooMuch):
        llm.OpenAICompatible(llm.PROVIDERS["groq"], "gsk_x").ask(["hi"], {"type": "object"})


def test_an_answer_broken_twice_is_too_much(monkeypatch) -> None:
    calls = []

    def urlopen(req, timeout=None, context=None):
        calls.append(1)
        raise _http_error(400, {"error": {"code": "json_validate_failed", "message": "Failed to generate JSON."}})

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    with pytest.raises(llm.TooMuch):
        llm.OpenAICompatible(llm.PROVIDERS["groq"], "gsk_x", sleep=lambda s: None).ask(["hi"], {"type": "object"})
    assert len(calls) == 2  # once more, then it's split by the caller


def test_giving_up_and_daily_limits(monkeypatch) -> None:
    def urlopen(req, timeout=None, context=None):
        raise _http_error(429, {"error": {"message": "Rate limit reached on tokens per day (TPD)"}})

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    waits: list[float] = []
    client = llm.OpenAICompatible(llm.PROVIDERS["groq"], "gsk_x", sleep=waits.append)
    with pytest.raises(llm.LLMError, match="today's Groq allowance"):
        client.ask(["hi"], {"type": "object"})
    assert waits == []  # no point waiting for tomorrow


def test_backoff_is_capped() -> None:
    assert llm.backoff(10, None) <= 60.5 and llm.backoff(0, 120) == 60.0


def test_the_key_comes_from_the_environment_first(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="Gemini API key"):
        llm.provider_from({})
    assert llm.provider_from({"gemini_key": "from-settings"}).api_key == "from-settings"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert llm.provider_from({"gemini_key": "from-settings"}).api_key == "from-env"
    ollama = llm.provider_from({"ai_provider": "ollama", "ollama_model": "qwen2.5vl:7b"})
    assert ollama.base_url == "http://localhost:11434/v1" and ollama.vision_model == "qwen2.5vl:7b" and ollama.api_key == ""


def test_errors_say_what_to_do() -> None:
    client = llm.OpenAICompatible(llm.PROVIDERS["gemini"], "k")
    err = lambda status, body: str(client.error(status, json.dumps(body).encode()))  # noqa: E731
    assert "didn't accept the API key" in err(400, [{"error": {"message": "API key not valid. Please pass a valid API key."}}])
    assert "doesn't have the model" in err(404, {"error": {"message": "models/x is not found"}})
    assert "having problems" in err(500, {"error": {"message": "internal"}})
    ollama = llm.OpenAICompatible(llm.PROVIDERS["ollama"])
    assert "ollama pull" in str(ollama.error(404, b'{"error": "model \\"gemma3\\" not found"}'))


# ---------- writing exams ----------

def _past() -> list[tuple[str, ExamQuestion]]:
    qs = [ExamQuestion(1, f"{i}", f"Likelihood question {i}", answer="A" if i % 2 else None, topic_tags=["Likelihood"],
                       result="missed" if i == 4 else "") for i in range(1, 8)]
    qs.append(ExamQuestion(1, "8", "Prior question", topic_id=3))
    return [("Exam 2024", q) for q in qs]


def test_few_shot_examples_prefer_answered_and_missed_questions() -> None:
    titles = {t.id: t.title for t in TOPICS}
    picked = E.few_shot(_past(), "likelihood", titles)
    # Up to 5: those with an answer first (1, 3, 5, 7), then the one that went badly (4).
    assert [q.number for _, q in picked] == ["1", "3", "5", "7", "4"]
    assert [q.number for _, q in E.few_shot(_past(), "Bayesian inference", titles)] == ["8"]  # by its topic, not a tag
    assert E.few_shot(_past(), "Sufficiency", titles) == []


def test_generate_exam_returns_checked_questions() -> None:
    model = FakeModel(generate=[{"title": "Practice exam 2: likelihood", "intro": "**Time:** 1 hour", "questions": [
        {"number": "1", "parent_number": "", "text": "New question", "topic_tags": ["Likelihood"],
         "question_type": "calculation", "points": "10", "has_figure": False, "why": "Practises 4.", "answer": "Worked"},
        {"number": "2", "parent_number": "", "text": "", "topic_tags": [], "question_type": "other", "points": "",
         "has_figure": False, "why": "", "answer": ""}]}])
    made = generate_exam(["Likelihood", "Sufficiency"], 3, provider=model, course=COURSE, topics=TOPICS, past=_past(),
                         struggles="Missed 4.", number=2)
    assert made.title == "Practice exam 2: likelihood" and made.intro == "**Time:** 1 hour"
    assert [(q.number, q.points, q.answer, q.why) for q in made.questions] == [("1", 10.0, "Worked", "Practises 4.")]
    prompt = model.sent[0][1][0]
    assert "3 questions" in prompt and "### Likelihood" in prompt and "Likelihood question 1" in prompt
    assert "### Sufficiency\n(No past questions on this topic" in prompt
    assert "Prior question" not in prompt  # five examples already: no extra ones for style
    generate_exam(["Sufficiency"], 2, provider=model, course=COURSE, topics=TOPICS, past=_past())
    assert "Other questions from the past exams, for their style" in model.sent[-1][1][0]  # none on the topic: style ones
    with pytest.raises(ValueError):
        generate_exam(["Likelihood"], 0, provider=model, course=COURSE, topics=TOPICS, past=[])


def test_someone_already_on_groq_stays_on_groq(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    old = {"groq_key": "gsk_" + "a" * 30, "groq_model": "openai/gpt-oss-20b"}  # saved before there was a choice
    client = llm.provider_from(old)
    assert client.name == "Groq" and client.model == "openai/gpt-oss-20b"
    assert llm.chosen({**old, "ai_provider": "gemini"}) == "gemini"  # once picked, the pick counts
    assert llm.chosen({}) == "gemini"


def test_an_exam_too_long_for_one_answer_is_written_in_halves() -> None:
    one = lambda number, text: {"number": number, "parent_number": "", "text": text, "topic_tags": [],  # noqa: E731
                                "question_type": "other", "points": "", "has_figure": False, "why": "", "answer": "A"}
    model = FakeModel(generate=[llm.TooMuch("ran out of room"),
                                {"title": "Practice exam 1", "intro": "1 hour", "questions": [one("1", "First"), one("2", "Second")]},
                                {"title": "", "intro": "", "questions": [one("3", "Third"), one("4", "Fourth")]}])
    made = generate_exam(["Likelihood"], 4, provider=model, course=COURSE, topics=TOPICS, past=[])
    assert [q.number for q in made.questions] == ["1", "2", "3", "4"] and made.title == "Practice exam 1"
    prompts = [parts[0] for _, parts, _ in model.sent]
    assert "4 questions" in prompts[0] and "2 questions" in prompts[1] and "number them from 3" in prompts[2]
    assert "- First" in prompts[2]  # told what the first half asked


def test_a_prompt_and_answer_over_the_minute_limit_ask_for_a_shorter_answer(monkeypatch) -> None:
    calls: list[dict] = []
    replies = [_http_error(413, {"error": {"code": "rate_limit_exceeded", "message":
               "Request too large for model `openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Requested 9960, "
               "please reduce your message size and try again."}}), _ok()]

    def urlopen(req, timeout=None, context=None):
        calls.append(json.loads(req.data))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    assert llm.OpenAICompatible(llm.PROVIDERS["groq"], "gsk_x").ask(["hi"], {"type": "object"}) == {"ok": True}
    assert [c["max_completion_tokens"] for c in calls] == [8192, 8192 - 1960 - 100]
    assert llm._lower_output(b"(TPM): Limit 8000, Requested 16000", 8192) is None  # the prompt alone is too big


def test_examples_are_cut_to_fit_a_small_prompt() -> None:
    titles = {t.id: t.title for t in TOPICS}
    examples = {"Likelihood": E.few_shot(_past(), "Likelihood", titles), "Bayesian inference": E.few_shot(_past(), "Bayesian inference", titles)}
    full, short = E.fit_examples(examples, 100_000)
    assert [len(v) for v in full.values()] == [5, 1] and not short
    some, short = E.fit_examples(examples, 200)
    assert [len(v) for v in some.values()] == [2, 1] and not short  # the same number per topic where there are that many
    least, short = E.fit_examples(examples, 10)
    assert [len(v) for v in least.values()] == [1, 1] and short
