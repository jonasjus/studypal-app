"""Exam questions as structured data: the shape the model must give them in, checking what it gave
(Pydantic), and matching each question with its solution by number. No I/O here.

The model is asked for the exam's questions and the solutions' answers separately (a few pages per
request), and the matching happens here, by number, so an answer is never guessed: a question whose
number isn't in the solutions gets answer None.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

QUESTION_TYPES = ("short_answer", "calculation", "proof", "multiple_choice", "true_false", "essay", "code", "other")
QuestionType = Literal["short_answer", "calculation", "proof", "multiple_choice", "true_false", "essay", "code", "other"]


def number_key(number: str | None) -> str:
    """The same question however it's written: "Question 3 b)", "3(b)", "3.b" and "3b" are "3.b"; "Oppgave 2"
    is "2". The levels stay apart, so "1.1" (item 1 of question 1) is never "11"."""
    key = re.sub(r"^(question|oppgave|task|problem|exercise|q)\.?\s*", "", (number or "").strip().lower())
    key = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", ".", key)  # 3b -> 3.b
    return re.sub(r"[^0-9a-z]+", ".", key).strip(".")


class Question(BaseModel):
    """One exam question (or part of one), linked to the exam it came from."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: int | None = None
    exam_id: int | None = None
    number: str = Field(min_length=1, max_length=20)  # "3b"
    parent_number: str | None = Field(default=None, max_length=20)  # "3" for 3b; None for a whole question
    text: str = Field(min_length=1)  # Markdown, with $...$ for maths
    topic_tags: list[str] = Field(default_factory=list)
    question_type: QuestionType = "other"
    points: float | None = Field(default=None, ge=0)
    answer: str | None = None  # from the solutions; None when they don't have one (never guessed)
    has_figure: bool = False
    why: str | None = None  # practice questions: what it was made to practise

    @field_validator("parent_number", "answer", "why", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("points", mode="before")
    @classmethod
    def _points(cls, v: object) -> object:
        """"10", "10 points", "7,5 p" and "" (none) as the model writes them."""
        if isinstance(v, str):
            m = re.search(r"\d+(?:[.,]\d+)?", v)
            return float(m.group().replace(",", ".")) if m else None
        return v

    @field_validator("topic_tags", mode="before")
    @classmethod
    def _tags(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.split(",")
        if isinstance(v, list):
            seen: list[str] = []
            for tag in v:
                tag = " ".join(str(tag).split())
                if tag and tag.casefold() not in (t.casefold() for t in seen):
                    seen.append(tag)
            return seen
        return v

    @field_validator("question_type", mode="before")
    @classmethod
    def _type(cls, v: object) -> object:
        v = str(v or "other").strip().lower().replace(" ", "_").replace("-", "_")
        return v if v in QUESTION_TYPES else "other"


class Solution(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    number: str = Field(min_length=1, max_length=20)
    answer: str = Field(min_length=1)


class Extraction(BaseModel):
    """What the model gives for an exam and its solutions."""

    model_config = ConfigDict(extra="ignore")

    questions: list[Question]
    solutions: list[Solution] = Field(default_factory=list)


def validate_extraction(data: object, exam_id: int | None = None) -> tuple[Extraction, int]:
    """The model's answer, checked. A question or solution that doesn't fit the schema is dropped (and
    counted) rather than failing the whole exam; an answer that isn't the right shape at all raises."""
    if not isinstance(data, dict):
        raise ValueError("The model's answer wasn't an object.")
    dropped = 0
    questions, solutions = [], []
    for raw in data.get("questions") or []:
        try:
            questions.append(Question.model_validate({**raw, "exam_id": exam_id, "id": None}) if isinstance(raw, dict)
                             else Question.model_validate(raw))
        except ValidationError:
            dropped += 1
    for raw in data.get("solutions") or []:
        try:
            solutions.append(Solution.model_validate(raw))
        except ValidationError:
            dropped += 1
    return Extraction(questions=questions, solutions=solutions), dropped


def match_solutions(questions: list[Question], solutions: list[Solution]) -> tuple[list[Question], list[str]]:
    """Give each question the answer with the same number ("3 b)" matches "3b"). Several solutions with one
    number are joined in order; a question with none keeps answer None. Returns the questions and the
    numbers of solutions that matched no question (for the message: likely a numbering mismatch)."""
    by: dict[str, list[str]] = {}
    for s in solutions:
        by.setdefault(number_key(s.number), []).append(s.answer)
    keys = {number_key(q.number) for q in questions}
    matched = [q.model_copy(update={"answer": "\n\n".join(by[k]) if (k := number_key(q.number)) in by else None})
               for q in questions]
    unmatched = [s.number for s in solutions if number_key(s.number) not in keys]
    return matched, list(dict.fromkeys(unmatched))


def dedupe(questions: list[Question]) -> list[Question]:
    """One question per number: a question repeated (say across a page break) keeps its first copy, with
    the later text added on."""
    out: dict[str, Question] = {}
    for q in questions:
        k = number_key(q.number)
        if k in out:
            first = out[k]
            if q.text not in first.text:
                out[k] = first.model_copy(update={"text": f"{first.text}\n\n{q.text}",
                                                  "has_figure": first.has_figure or q.has_figure,
                                                  "points": first.points if first.points is not None else q.points})
        else:
            out[k] = q
    return list(out.values())


# The schema the model is held to (strict structured output: every field present, nothing extra;
# "" stands for none, and validation turns it into None).
_STR = {"type": "string"}


def _obj(**fields: dict) -> dict:
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


_QUESTION_FIELDS = dict(
    number=_STR, parent_number=_STR, text=_STR, topic_tags={"type": "array", "items": _STR},
    question_type={"type": "string", "enum": list(QUESTION_TYPES)}, points=_STR, has_figure={"type": "boolean"},
)
QUESTIONS_SCHEMA = _obj(questions={"type": "array", "items": _obj(**_QUESTION_FIELDS)})
SOLUTIONS_SCHEMA = _obj(solutions={"type": "array", "items": _obj(number=_STR, answer=_STR)})
GENERATE_SCHEMA = _obj(title=_STR, intro=_STR,
                       questions={"type": "array", "items": _obj(**_QUESTION_FIELDS, why=_STR, answer=_STR)})
TRANSCRIBE_SCHEMA = _obj(pages={"type": "array", "items": _obj(page={"type": "integer"}, markdown=_STR)})
MARKS_SCHEMA = _obj(results={"type": "array", "items": _obj(
    number=_STR, result={"type": "string", "enum": ["unknown", "ok", "partial", "missed"]}, note=_STR)}, score=_STR)
