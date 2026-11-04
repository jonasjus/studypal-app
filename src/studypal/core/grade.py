"""Grading an exam attempt with the model: `grade(provider, ...)` sends the questions, reference solutions and
answers (several requests for a long exam) and puts the points and feedback on the attempt.
"""

from __future__ import annotations

from typing import Callable

from .llm import LLMError, Provider, TooMuch
from .logic import attempts as A
from .models import ExamAttempt


def grade(provider: Provider, course: str, exam: str, attempt: ExamAttempt,
          progress: Callable[[str], None] = lambda _: None) -> None:
    worth = A.max_points(attempt.items)
    budget = getattr(provider, "example_chars", 40_000)
    groups = A.batches(attempt.items, budget)
    summaries: list[str] = []

    def ask(indexes: list[int]) -> None:
        prompt = A.grade_prompt(course, exam, [(i, attempt.items[i], worth[i]) for i in indexes])
        try:
            answer = provider.ask([prompt], A.GRADE_SCHEMA, A.GRADE_SYSTEM, 0.2)
        except TooMuch:
            if len(indexes) < 2:
                raise LLMError(f"Grading a single answer is more than {provider.name} can do in one go on your plan. "
                               "Try another provider in Settings, or mark it yourself.") from None
            half = len(indexes) // 2
            ask(indexes[:half])
            ask(indexes[half:])
            return
        if not isinstance(answer, dict):
            raise LLMError("The model's answer came back garbled. Try again.")
        A.apply_grades(attempt, answer.get("grades") or [], "")
        if str(answer.get("summary") or "").strip():
            summaries.append(str(answer["summary"]).strip())

    for n, indexes in enumerate(groups, start=1):
        progress(f"Grading answers{f' ({n} of {len(groups)})' if len(groups) > 1 else ''}")
        ask(indexes)
    if not any(i.get("verdict") for i in attempt.items):
        raise LLMError(f"{provider.name} didn't grade any of the answers. Try again.")
    attempt.summary = "\n\n".join(summaries)
    attempt.graded = "model"
