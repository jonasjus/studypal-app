"""Taking an exam: starting it with a time limit, saving answers as they're written, handing in, grading by the
model (a stand-in) and by hand, and the grades flowing back to the exam's questions. Attempts sync too."""

from __future__ import annotations

from datetime import datetime, timedelta

from studypal.api import Api
from studypal.core.logic import attempts as A
from studypal.core.models import ExamAttempt, ExamQuestion

from test_cloud import add_course
from test_exams import FakeModel, api, two, with_key  # noqa: F401  (fixtures)


def exam_with_questions(api: Api, marks: tuple[str, ...] = ("6", "4")) -> tuple[int, int]:
    course_id = add_course(api, "STK310")
    exam_id = api.save_exam({"course_id": course_id, "title": "Exam 2024"})["id"]
    for n, m in enumerate(marks, start=1):
        assert api.save_question({"exam_id": exam_id, "number": str(n), "prompt": f"Question {n}?", "marks": m,
                                  "answer": f"Solution {n}"}).get("ok")
    return course_id, exam_id


def test_taking_an_exam_and_marking_it_by_hand(api: Api) -> None:
    _, exam_id = exam_with_questions(api)
    assert "no questions" in api.start_attempt({"exam_id": api.save_exam({"course_id": add_course(api, "X1"),
                                                                           "title": "Empty"})["id"]})["error"]
    r = api.start_attempt({"exam_id": exam_id, "minutes": 30})
    attempt_id = r["id"]
    # Starting again carries on with the same attempt.
    assert api.start_attempt({"exam_id": exam_id, "minutes": 30})["id"] == attempt_id
    d = api.attempt(attempt_id)
    a = d["attempt"]
    assert not a["finished"] and 1790 <= a["seconds_left"] <= 1800 and [i["worth"] for i in a["items"]] == [6, 4]
    assert api.exam(exam_id)["exam"]["attempts"]["open"] == attempt_id

    assert api.save_answers(attempt_id, {"0": "My first answer"})["ok"]
    assert api.attempt(attempt_id)["attempt"]["answered"] == 1
    r = api.hand_in(attempt_id, {"1": "Second"})
    assert r["ok"] and r["grade"] is False  # no model set up
    a = api.attempt(attempt_id)["attempt"]
    assert a["finished"] and [i["answer"] for i in a["items"]] == ["My first answer", "Second"]
    assert a["score"]["percent"] is None
    # Answers can't change once handed in.
    api.save_answers(attempt_id, {"0": "changed"})
    assert api.attempt(attempt_id)["attempt"]["items"][0]["answer"] == "My first answer"

    assert api.set_attempt_verdict(attempt_id, 0, "ok")["ok"]
    assert api.set_attempt_verdict(attempt_id, 1, "partial")["ok"]
    a = api.attempt(attempt_id)["attempt"]
    assert a["graded"] == "self" and a["score"] == {"got": 8, "max": 10, "percent": 80, "marked": 2, "total": 2}
    # The marks become how the exam's questions went.
    exam = api.exam(exam_id)["exam"]
    assert [q["result"] for q in exam["questions"]] == ["ok", "partial"]
    assert exam["attempts"] == {"count": 1, "latest": 80, "best": 80, "open": None}
    assert "error" in api.set_attempt_verdict(attempt_id, 5, "ok")
    assert api.delete_attempt(attempt_id)["ok"]
    assert api.exam(exam_id)["attempt_list"] == []


def test_time_stops_at_the_limit(api: Api) -> None:
    _, exam_id = exam_with_questions(api)
    attempt_id = api.start_attempt({"exam_id": exam_id, "minutes": 10})["id"]
    a = api._store.get_attempt(attempt_id)
    a.started_at = datetime.now() - timedelta(hours=2)  # the window was closed
    api._store.conn.execute("update exam_attempt set started_at = ? where id = ?",
                            (a.started_at.isoformat(timespec="seconds"), attempt_id))
    assert api.attempt(attempt_id)["attempt"]["seconds_left"] < 0
    api.hand_in(attempt_id, {})
    assert api.attempt(attempt_id)["attempt"]["elapsed"] == 600


def test_grading_with_the_model(api: Api) -> None:
    _, exam_id = exam_with_questions(api)
    with_key(api)
    attempt_id = api.start_attempt({"exam_id": exam_id})["id"]
    assert api.hand_in(attempt_id, {"0": "T = sum", "1": ""})["grade"] is True
    FakeModel.replies["grade"] = [{"grades": [
        {"index": 0, "points": 9, "verdict": "ok", "feedback": "Right."},  # more than it's worth: kept to 6
        {"index": 1, "points": 0, "verdict": "missed", "feedback": "Needed the posterior."},
    ], "summary": "Practise Bayes."}]
    r = api.grade_attempt(attempt_id)
    assert r["ok"] and "6 of 10 points (60%)" in r["message"]
    kind, parts, _ = FakeModel.sent[-1]
    assert kind == "grade" and "Solution 1" in parts[0] and "(left blank)" in parts[0]
    a = api.attempt(attempt_id)["attempt"]
    assert a["graded"] == "model" and a["summary"] == "Practise Bayes." and a["items"][0]["points"] == 6
    questions = api.exam(exam_id)["exam"]["questions"]
    assert [q["result"] for q in questions] == ["ok", "missed"] and questions[1]["note"] == "Needed the posterior."
    # A grade can be changed by hand afterwards.
    api.set_attempt_verdict(attempt_id, 1, "partial")
    assert api.attempt(attempt_id)["attempt"]["score"]["got"] == 8


def test_grading_needs_a_handed_in_attempt(api: Api) -> None:
    _, exam_id = exam_with_questions(api)
    with_key(api)
    attempt_id = api.start_attempt({"exam_id": exam_id})["id"]
    assert "Hand the exam in" in api.grade_attempt(attempt_id)["error"]


def test_points_without_marks_on_every_question() -> None:
    a = ExamAttempt(exam_id=1, started_at=datetime.now(), items=[{"marks": "10"}, {"marks": ""}, {"marks": "5 p"}])
    assert A.max_points(a.items) == [1, 1, 1]
    assert A.max_points([{"marks": "10"}, {"marks": "2,5 points"}]) == [10, 2.5]
    A.set_verdict(a, 0, "partial")
    assert A.score(a)["got"] == 0.5 and A.score(a)["percent"] == 17
    assert A.suggested_minutes(5) == 60 and A.suggested_minutes(1) == 10 and A.suggested_minutes(40) == 240
    assert A.batches([{"prompt": "x" * 500}] * 3, 1500) == [[0, 1], [2]]


def test_attempts_sync_between_computers(two) -> None:
    _, laptop, desktop = two
    laptop.sign_up("ada@example.com", "correct horse")
    desktop.sign_in("ada@example.com", "correct horse")
    _, exam_id = exam_with_questions(laptop)
    attempt_id = laptop.start_attempt({"exam_id": exam_id, "minutes": 20})["id"]
    laptop.hand_in(attempt_id, {"0": "An answer"})
    laptop.set_attempt_verdict(attempt_id, 0, "ok")
    laptop.cloud_sync()
    desktop.cloud_sync()
    course = desktop.overview()["courses"][0]["id"]
    exam = desktop.exams(course)["past"][0]
    assert exam["attempts"]["count"] == 1 and exam["attempts"]["latest"] == 60
    desk_attempt = desktop.exam(exam["id"])["attempt_list"][0]
    assert desktop.attempt(desk_attempt["id"])["attempt"]["items"][0]["answer"] == "An answer"


def _objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for v in schema.values():
            yield from _objects(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from _objects(v)


def test_grade_schema_is_strict():
    # Groq (and OpenAI) refuse a strict json_schema unless every object closes its properties and requires them all.
    for obj in _objects(A.GRADE_SCHEMA):
        assert obj.get("additionalProperties") is False
        assert set(obj["required"]) == set(obj["properties"])


def test_items_carry_the_question_type():
    q = ExamQuestion(exam_id=1, number="1.1", prompt="P is NP.", answer="FALSE", question_type="true_false")
    assert A.items_from([q])[0]["question_type"] == "true_false"
