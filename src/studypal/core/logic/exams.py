"""What Groq is asked when it reads a past exam or writes a practice exam, the summary of what someone
struggled with that goes into the second, and putting together what's read a few pages at a time.
No I/O here: api.py gathers the data and files and makes the calls.

Reading goes in stages, because Groq takes three page images per request: the exam paper's pages give
the questions; then the solutions' pages give answers (or, without solutions, the text model writes
them); then the student's own answer pages give how each question went.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Course, ExamQuestion, Topic, WeakSpot

SIZES = {
    "short": "about 4 to 6 questions, roughly 45 minutes of work",
    "half": "about half as long as one of the past exams",
    "full": "as long as one of the past exams, with the same number of questions and total marks",
}
FOCUSES = ("struggles", "balanced", "topics")

SYSTEM = ("You help a university student prepare for exams. You are careful and exact: you transcribe exam text "
          "faithfully, and your answers and solutions are correct. Maths is written in LaTeX between $...$ "
          "(inline) or $$...$$ (on its own line); everything else is Markdown.")

# Groq's structured output (strict: every field required, nothing extra): the shapes answers must have.
_STR = {"type": "string"}


def _obj(**fields: dict) -> dict:
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def _list(name: str, item: dict, **more: dict) -> dict:
    return _obj(**{name: {"type": "array", "items": item}}, **more)


PAGES_SCHEMA = _list("questions", _obj(number=_STR, prompt=_STR, marks=_STR, topic=_STR))
ANSWERS_SCHEMA = _list("answers", _obj(number=_STR, answer=_STR))
MARKS_SCHEMA = _list("results", _obj(number=_STR, result={"type": "string", "enum": ["unknown", "ok", "partial", "missed"]},
                                     note=_STR), score=_STR)
MAKE_SCHEMA = _obj(title=_STR, intro=_STR,
                   questions={"type": "array", "items": _obj(number=_STR, topic=_STR, why=_STR, marks=_STR, prompt=_STR,
                                                             answer=_STR)})


def number_key(number: str) -> str:
    """"Question 1 a)" and "1a" are the same question."""
    key = re.sub(r"^(question|oppgave|task|problem|q)\s*", "", number.strip().lower())
    return re.sub(r"[^0-9a-z]", "", key)


def merge_questions(found: list[dict], more: list[dict]) -> None:
    """Add questions read from the next pages. One with a number already found continues it (a question
    that runs over a page break): its text is added on, and empty marks or topic are filled in."""
    by = {number_key(q["number"]): q for q in found}
    for q in more:
        number = str(q.get("number") or "").strip()
        if not number and not str(q.get("prompt") or "").strip():
            continue
        old = by.get(number_key(number)) if number else None
        if old is None:
            new = {"number": number[:20], "prompt": str(q.get("prompt") or "").strip(),
                   "marks": str(q.get("marks") or "").strip()[:20], "topic": str(q.get("topic") or "").strip()}
            found.append(new)
            if number:
                by[number_key(number)] = new
        else:
            extra = str(q.get("prompt") or "").strip()
            if extra and extra not in old["prompt"]:
                old["prompt"] = f"{old['prompt']}\n\n{extra}".strip()
            old["marks"] = old["marks"] or str(q.get("marks") or "").strip()[:20]
            old["topic"] = old["topic"] or str(q.get("topic") or "").strip()


def merge_field(found: list[dict], items: list[dict], field: str) -> None:
    """Put each item's `field` (an answer, a note) on the question with its number, adding on to what
    earlier pages gave."""
    by = {number_key(q["number"]): q for q in found}
    for item in items:
        q = by.get(number_key(str(item.get("number") or "")))
        value = str(item.get(field) or "").strip()
        if q is None or not value:
            continue
        q[field] = f"{q[field]}\n\n{value}".strip() if q.get(field) and value not in q[field] else (q.get(field) or value)


def _question_list(found: list[dict], with_answers: bool = False) -> str:
    out = []
    for q in found:
        line = f"- {q['number']}: {_clip(q['prompt'], 500)}"
        if with_answers and q.get("answer"):
            line += f"\n  Correct answer: {_clip(q['answer'], 600)}"
        out.append(line)
    return "\n".join(out)


def _where(name: str, first: int, last: int, total: int, text: bool) -> str:
    if text:
        return f"Below is the text of “{name}”."
    pages = f"page {first}" if first == last else f"pages {first} to {last}"
    return f"Attached are {pages} of {total} of “{name}”."


@dataclass
class Struggle:
    """A question that went badly, with where it's from."""

    exam: str
    question: ExamQuestion
    topic: str


@dataclass
class TopicTally:
    topic_id: int | None
    title: str
    missed: int = 0
    partial: int = 0
    ok: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def weight(self) -> float:
        """How much it needs practice: a missed question counts double a partly right one."""
        return self.missed * 2 + self.partial


def tally(questions: list[tuple[str, ExamQuestion]], topics: dict[int, str]) -> list[TopicTally]:
    """How each topic went across all marked questions, the ones needing the most practice first.
    Questions without a topic are counted under topic_id None."""
    by: dict[int | None, TopicTally] = {}
    for _, q in questions:
        if q.result not in ("ok", "partial", "missed"):
            continue
        key = q.topic_id if q.topic_id in topics else None
        t = by.setdefault(key, TopicTally(key, topics.get(key, "") if key is not None else ""))
        setattr(t, q.result, getattr(t, q.result) + 1)
        if q.note and q.result != "ok":
            t.notes.append(q.note)
    return sorted(by.values(), key=lambda t: (-t.weight, t.topic_id is None, t.title.lower()))


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def struggle_summary(questions: list[tuple[str, ExamQuestion]], topics: list[Topic], weak: list[WeakSpot]) -> str:
    """Plain text for the prompt: questions that went badly, open weak spots, and shaky topics."""
    titles = {t.id: t.title for t in topics}
    lines: list[str] = []
    bad = [(exam, q) for exam, q in questions if q.result in ("partial", "missed")]
    if bad:
        lines.append("Questions the student got wrong or only partly right on earlier exams:")
        for exam, q in bad:
            what = "wrong or blank" if q.result == "missed" else "partly right"
            topic = f" [topic: {titles[q.topic_id]}]" if q.topic_id in titles else ""
            note = f" What went wrong: {_clip(q.note, 300)}" if q.note else ""
            lines.append(f"- {exam}, question {q.number}{topic} ({what}): {_clip(q.prompt, 400)}{note}")
    good = [(exam, q) for exam, q in questions if q.result == "ok"]
    if good:
        mastered = sorted({titles[q.topic_id] for _, q in good if q.topic_id in titles})
        if mastered:
            lines.append("Topics where the student has answered questions correctly: " + ", ".join(mastered) + ".")
    open_weak = [w for w in weak if not w.resolved]
    if open_weak:
        lines.append("Weak spots the student has noted themselves:")
        for w in open_weak:
            topic = f" [topic: {titles[w.topic_id]}]" if w.topic_id in titles else ""
            lines.append(f"- {_clip(w.description, 300)}{topic} (priority {w.priority.value})")
    shaky = [t for t in topics if t.confidence <= 2]
    if shaky:
        lines.append("Topics the student feels least confident about: " + ", ".join(t.title for t in shaky) + ".")
    return "\n".join(lines) or "The student hasn't marked anything they struggled with yet."


def _topic_list(topics: list[Topic]) -> str:
    if not topics:
        return "(The student hasn't listed the course's topics.)"
    return "\n".join(f"- {t.title}" for t in topics)


def pages_prompt(course: Course, topics: list[Topic], name: str, first: int, last: int, total: int,
                 found: list[dict], text: str = "") -> str:
    """Read the exam paper's questions off a few of its pages (or its text)."""
    so_far = ""
    if found:
        tail = found[-1]
        so_far = (f"\n\nEarlier pages had questions {', '.join(q['number'] for q in found)}. The last one, "
                  f"{tail['number']}, ended: “…{_clip(tail['prompt'][-300:], 300)}”. If these pages start in the middle "
                  f"of it, give it again with number {tail['number']} and only the part on these pages.")
    return f"""Course: {course.code} {course.name}

The course's topics:
{_topic_list(topics)}

{_where(name, first, last, total, bool(text))} It's the EXAM PAPER.{so_far}

List every question on {"it" if text else "these pages"}, in order. Split a question into parts (1a, 1b, ...) when the
parts are answered or marked separately. For each question give:
- number: as printed ("1", "2b").
- prompt: the full question text, transcribed faithfully in the exam's own language, with everything needed to
  answer it (given values, tables as Markdown tables, code). Where a figure is needed, describe it in
  [square brackets]. Repeat shared context from the main question in each part, so every part can be read on its own.
- marks: the points the question is worth, if printed (else "").
- topic: the course topic it tests, copied exactly from the list above, or "" if none fits.
Cover pages and instructions without questions give an empty list.{chr(10) * 2 + text if text else ""}"""


def answers_prompt(course: Course, found: list[dict], name: str, first: int, last: int, total: int, text: str = "") -> str:
    """Take the answers from a few pages of the solutions."""
    return f"""Course: {course.code} {course.name}

The exam's questions:
{_question_list(found)}

{_where(name, first, last, total, bool(text))} It's the SOLUTIONS / answer key for this exam.

For each question answered {"in it" if text else "on these pages"}, give its number exactly as in the list above and
the answer, worked through concisely and faithfully to the solutions. If an answer starts on an earlier page, give
only the part here. Leave out questions that aren't answered here.{chr(10) * 2 + text if text else ""}"""


def write_answers_prompt(course: Course, topics: list[Topic], found: list[dict]) -> str:
    """No solutions: write the answers."""
    return f"""Course: {course.code} {course.name}

The course's topics:
{_topic_list(topics)}

An exam from this course has these questions:
{_question_list(found)}

There is no answer key. For every question, give its number exactly as above and a short, correct worked answer in
the exam's language, detailed enough for the student to check their own answer."""


def marks_prompt(course: Course, found: list[dict], name: str, first: int, last: int, total: int, text: str = "") -> str:
    """Mark the student's own answers on a few pages against the correct ones."""
    return f"""Course: {course.code} {course.name}

The exam's questions, with correct answers:
{_question_list(found, with_answers=True)}

{_where(name, first, last, total, bool(text))} It's the STUDENT'S OWN ANSWERS (possibly graded by a teacher).

For each question the student answered {"in it" if text else "on these pages"}, give its number exactly as in the
list above, and compare their answer with the correct one:
- result: "ok" (full or nearly full credit), "partial" (some credit), "missed" (wrong or not answered) or
  "unknown" (you can't tell). Use the teacher's marking where there is any.
- note: one or two sentences, addressed to the student, on what went wrong ("" when ok).
Leave out questions not on these pages. Also give score: the student's total score if it's written here, else "".
{chr(10) + text if text else ""}"""


PAST_CHARS = 60_000  # past exam text sent along: about 15,000 tokens, newest exams first


def past_exams_text(past: list[tuple[str, str, list[ExamQuestion]]]) -> str:
    """Past exams as text: (title, cover notes, questions), newest first, cut off at PAST_CHARS."""
    parts, used = [], 0
    for title, notes, questions in past:
        lines = [f"### {title}"] + ([notes.strip()] if notes.strip() else [])
        for q in questions:
            marks = f" ({q.marks} marks)" if q.marks else ""
            lines.append(f"**{q.number}**{marks} {q.prompt.strip()}")
            if q.answer.strip():
                lines.append(f"*Solution:* {_clip(q.answer, 600)}")
        block = "\n\n".join(lines)
        if used + len(block) > PAST_CHARS and parts:
            break
        parts.append(block[:PAST_CHARS])
        used += len(block)
    return "\n\n".join(parts)


def make_prompt(course: Course, topics: list[Topic], past: list[tuple[str, str, list[ExamQuestion]]], struggles: str,
                size: str, focus: str, focus_topics: list[str], wishes: str, earlier: list[str], number: int) -> str:
    sources = (f"Here are past exams for this course, as read from the papers:\n\n{past_exams_text(past)}\n\n"
               "Match them closely: the same style, format, language, notation, difficulty, level of rigour and "
               "kinds of questions. Write NEW questions that test the same skills, with different numbers, examples and "
               "contexts; don't copy questions." if past
               else "There are no past exams to go on. Write an exam a university would set for this course, based on its topics.")
    if focus == "struggles":
        aim = ("Focus on what the student struggles with (below): about two thirds of the marks should practise those "
               "skills, with fresh questions that would catch the same mistakes. Use the rest to cover the remaining "
               "material, so it still feels like a real exam.")
    elif focus == "topics" and focus_topics:
        aim = "Only ask about these topics: " + "; ".join(focus_topics) + ". Lean towards what the student struggles with within them."
    else:
        aim = ("Cover the course the way the real exam does, and include a few questions on what the student struggles "
               "with.")
    earlier_text = ("\n\nQuestions from earlier practice exams (write different ones):\n"
                    + "\n".join(f"- {_clip(p, 160)}" for p in earlier[:60])) if earlier else ""
    wishes_text = f"\n\nThe student also asks: {wishes.strip()}" if wishes.strip() else ""
    return f"""Course: {course.code} {course.name}

The course's topics:
{_topic_list(topics)}

{sources}

Write practice exam number {number}. Length: {SIZES.get(size, SIZES['full'])}.
{aim}

What the student struggles with:
{struggles}{earlier_text}{wishes_text}

Give:
- title: short, e.g. "Practice exam {number}: eigenvalues and diagonalisation".
- intro: the cover instructions, as on the real exams (time allowed, total marks, allowed aids), in Markdown.
- questions, each with:
  - number: "1", "2a", ...
  - topic: the course topic it tests, copied exactly from the list above, or "".
  - why: one short sentence to the student on what this question practises and, when it targets an earlier
    mistake, which one (e.g. "Practises the sign error you made in 2b of the 2023 exam.").
  - marks: points, if the past exams show them (else "").
  - prompt: the question, complete and self-contained.
  - answer: a full worked solution, detailed enough for the student to mark their own answer."""
