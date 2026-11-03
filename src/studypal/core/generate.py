"""Writing new exam questions from past ones: `generate_exam(weak_topics, n)` takes 3 to 5 past questions
per weak topic as examples and asks the model for n new questions in the same schema as read questions
(core/logic/questions.Question), each with a worked answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import LLMError, Provider, TooMuch
from .logic import exams as E
from .logic import questions as Q
from .models import Course, ExamQuestion, Topic


@dataclass
class GeneratedExam:
    title: str
    intro: str
    questions: list[Q.Question]


def generate_exam(weak_topics: list[str], n: int, *, provider: Provider, course: Course, topics: list[Topic],
                  past: list[tuple[str, ExamQuestion]], struggles: str = "", wishes: str = "",
                  earlier: list[str] | None = None, number: int = 1) -> GeneratedExam:
    """n new questions on `weak_topics` (most on the first), with past questions as few-shot examples: 3 to 5
    per topic, fewer (and shortened) if that's more than the provider takes in one prompt. `past` is (exam
    title, question) from the course's past exams, newest exam first. If the whole exam won't fit in one
    answer (free plans allow little), it's written in two halves, the second numbered on."""
    if n < 1:
        raise ValueError("Ask for at least one question.")
    titles = {t.id: t.title for t in topics}
    # 3 to 5 per topic, or as many as fit the provider's prompt (free plans allow little per minute).
    budget = getattr(provider, "example_chars", 40_000)
    examples, short = E.fit_examples({topic: E.few_shot(past, topic, titles) for topic in weak_topics}, budget)
    used = {id(q) for shots in examples.values() for _, q in shots}
    # A few more past questions for the overall style, when the topics have few examples of their own.
    style = [(e, q) for e, q in past if id(q) not in used and q.prompt.strip()][:max(0, 5 - len(used))]

    def write(count: int, start: int, before: list[str]) -> GeneratedExam:
        prompt = E.generate_prompt(course, topics, weak_topics, count, examples, style, struggles, wishes,
                                   (earlier or []) + before, number, start, short)
        try:
            answer = provider.ask([prompt], Q.GENERATE_SCHEMA, E.SYSTEM, 0.7)
        except TooMuch:
            if count < 2:
                raise LLMError(f"A single question with its solution is more than {provider.name} can write in one "
                               "answer on your plan. Try another provider in Settings.") from None
            first = write(count // 2, start, before)
            rest = write(count - count // 2, start + len(_mains(first.questions)), before + [q.text for q in first.questions])
            return GeneratedExam(first.title, first.intro, first.questions + rest.questions)
        if not isinstance(answer, dict):
            raise LLMError("The model's answer came back garbled. Try again.")
        extraction, _ = Q.validate_extraction({"questions": answer.get("questions") or []})
        return GeneratedExam(" ".join(str(answer.get("title") or "").split())[:120], str(answer.get("intro") or ""),
                             extraction.questions)

    made = write(n, 1, [])
    questions = Q.dedupe(made.questions)
    if not questions:
        raise LLMError(f"{provider.name} didn't write any questions. Try again.")
    return GeneratedExam(made.title or f"Practice exam {number}", made.intro, questions)


def _mains(questions: list[Q.Question]) -> set[str]:
    """The main questions among these (2a and 2b are both question 2)."""
    return {Q.number_key(q.parent_number or q.number) for q in questions}
