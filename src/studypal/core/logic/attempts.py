"""Taking an exam: the questions as an attempt sees them, its score, and the prompt for having the model grade
the answers. No I/O here: api.py stores attempts and core/grade.py makes the call.

An attempt's items are plain dicts (they're stored as JSON and synced):
    number, prompt, marks, solution, has_figure   copied from the exam when the attempt starts
    answer                                        what was written
    verdict, points, feedback                     once graded: ok/partial/missed, points out of `max_points`
"""

from __future__ import annotations

import re
from datetime import datetime

from ..models import ExamAttempt, ExamQuestion

VERDICTS = ("ok", "partial", "missed")
MINUTES_PER_QUESTION = 12


def items_from(questions: list[ExamQuestion]) -> list[dict]:
    return [{"number": q.number, "prompt": q.prompt, "marks": q.marks, "solution": q.answer or "",
             "has_figure": q.has_figure, "question_type": q.question_type or "", "answer": ""}
            for q in questions if q.prompt.strip()]


def suggested_minutes(n_questions: int) -> int:
    """A time limit to offer: about 12 minutes a question, in 5-minute steps, at most 4 hours."""
    return min(240, max(10, round(n_questions * MINUTES_PER_QUESTION / 5) * 5))


def _number(marks: str) -> float | None:
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(?:p|pts?|points?|marks?|poeng)?\.?\s*", marks or "", re.IGNORECASE)
    return float(m.group(1).replace(",", ".")) if m else None


def max_points(items: list[dict]) -> list[float]:
    """What each question is worth: its marks if every question has a number for them, else 1 each (an exam
    with marks on only some questions can't be added up fairly)."""
    marks = [_number(i.get("marks", "")) for i in items]
    if items and all(m is not None and m > 0 for m in marks):
        return [m for m in marks]  # type: ignore[misc]
    return [1.0] * len(items)


def points_for(verdict: str, worth: float) -> float:
    return {"ok": worth, "partial": worth / 2}.get(verdict, 0.0)


def set_verdict(a: ExamAttempt, index: int, verdict: str) -> None:
    """Mark one answer by hand; its points follow the verdict."""
    if verdict not in VERDICTS and verdict != "":
        raise ValueError("That isn't a way a question can go.")
    if not 0 <= index < len(a.items):
        raise ValueError("That question isn't in this attempt.")
    worth = max_points(a.items)[index]
    item = a.items[index]
    item["verdict"] = verdict
    item["points"] = points_for(verdict, worth) if verdict else None
    if not a.graded:
        a.graded = "self"


def score(a: ExamAttempt) -> dict:
    """{got, max, percent, marked}: points so far, out of what the marked questions are worth in total."""
    worth = max_points(a.items)
    got = sum(float(i.get("points") or 0) for i in a.items if i.get("verdict"))
    total = sum(worth)
    marked = sum(1 for i in a.items if i.get("verdict"))
    return {"got": round(got, 2), "max": round(total, 2), "percent": round(100 * got / total) if total and marked else None,
            "marked": marked, "total": len(a.items)}


def seconds_left(a: ExamAttempt, now: datetime) -> int | None:
    """None without a time limit; can be negative once time's up."""
    if not a.minutes:
        return None
    return a.minutes * 60 - int((now - a.started_at).total_seconds())


def elapsed(a: ExamAttempt, now: datetime) -> int:
    end = a.finished_at or now
    return max(0, int((end - a.started_at).total_seconds()))


def format_seconds(s: int) -> str:
    h, rest = divmod(max(0, s), 3600)
    m = rest // 60
    return f"{h}h {m:02d}m" if h else f"{m} min" if m else "under a minute"


# ---------- grading with the model ----------

GRADE_SYSTEM = ("You grade a university student's answers to exam questions. You are fair and exact, like an "
                "experienced examiner: you give credit for correct reasoning even when it's written differently from "
                "the solution, partial credit for partly correct work, and none for answers that are wrong, missing "
                "or only restate the question. Maths is written in LaTeX between $...$; everything else is Markdown.")

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "points": {"type": "number"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "feedback": {"type": "string"},
                },
                "required": ["index", "points", "verdict", "feedback"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["grades", "summary"],
    "additionalProperties": False,
}


def grade_prompt(course: str, exam: str, items: list[tuple[int, dict, float]]) -> str:
    """items: (index, item, points it's worth)."""
    parts = [f"Course: {course}\nExam: {exam}\n",
             "Grade each answer below. For each, give:\n"
             "- points: how many of the question's points the answer earns (0 up to what it's worth; halves are fine)\n"
             "- verdict: ok (fully or almost fully right), partial (some of it right), missed (wrong or no answer)\n"
             "- feedback: 1 to 3 sentences to the student: what was right, and what was wrong or missing and why. "
             "Be concrete. If the answer is blank, say briefly what the answer needed.\n"
             "Where a reference solution is given, grade against it; where there's none, work out the right answer "
             "yourself first. If a question relies on a figure you can't see, grade what you can.\n"
             "Then a summary: 2 to 4 sentences on how the exam went overall and what to practise next.\n"
             "Write the feedback and summary in the language the questions are written in."]
    for index, item, worth in items:
        parts.append(f"\n--- Question {item.get('number') or index + 1} (index {index}, worth {worth:g} "
                     f"point{'s' if worth != 1 else ''}) ---\n{item.get('prompt', '')}\n")
        if item.get("solution"):
            parts.append(f"Reference solution:\n{item['solution']}\n")
        else:
            parts.append("Reference solution: none given.\n")
        answer = (item.get("answer") or "").strip()
        parts.append(f"Student's answer:\n{answer if answer else '(left blank)'}\n")
    return "".join(parts)


def apply_grades(a: ExamAttempt, grades: list, summary: str) -> int:
    """Put the model's grades on the attempt; returns how many answers got one. Points are kept within what
    each question is worth."""
    worth = max_points(a.items)
    done = 0
    for g in grades:
        if not isinstance(g, dict):
            continue
        try:
            i = int(g.get("index"))
            points = float(g.get("points") or 0)
        except (TypeError, ValueError):
            continue
        if not 0 <= i < len(a.items):
            continue
        verdict = g.get("verdict") if g.get("verdict") in VERDICTS else ""
        points = min(max(points, 0.0), worth[i])
        if not verdict:
            verdict = "ok" if points >= worth[i] * 0.9 else "partial" if points > 0 else "missed"
        a.items[i].update(verdict=verdict, points=round(points, 2), feedback=str(g.get("feedback") or "").strip())
        done += 1
    if summary:
        a.summary = summary.strip()
    return done


def batches(items: list[dict], budget: int) -> list[list[int]]:
    """Split the questions into groups whose prompt text fits `budget` characters, keeping each whole."""
    out: list[list[int]] = [[]]
    size = 0
    for i, item in enumerate(items):
        n = len(item.get("prompt", "")) + len(item.get("solution", "")) + len(item.get("answer", "")) + 200
        if out[-1] and size + n > budget:
            out.append([])
            size = 0
        out[-1].append(i)
        size += n
    return [b for b in out if b]
