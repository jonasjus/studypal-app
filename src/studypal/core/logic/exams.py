"""What Gemini is asked when it reads a past exam or writes a practice exam, and the summary of what
someone struggled with that goes into the second. No I/O here: api.py gathers the data and files and
makes the calls.
"""

from __future__ import annotations

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

# Gemini's structured output: the shapes the answers must have.
_STRING = {"type": "STRING"}
READ_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "questions": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"number": _STRING, "prompt": _STRING, "marks": _STRING, "topic": _STRING,
                           "answer": _STRING, "result": {"type": "STRING", "enum": ["unknown", "ok", "partial", "missed"]},
                           "note": _STRING},
            "required": ["number", "prompt", "marks", "topic", "answer", "result", "note"],
            "propertyOrdering": ["number", "prompt", "marks", "topic", "answer", "result", "note"],
        }},
        "score": _STRING,
    },
    "required": ["questions", "score"],
    "propertyOrdering": ["questions", "score"],
}
MAKE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": _STRING,
        "intro": _STRING,
        "questions": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"number": _STRING, "prompt": _STRING, "marks": _STRING, "topic": _STRING,
                           "why": _STRING, "answer": _STRING},
            "required": ["number", "prompt", "marks", "topic", "why", "answer"],
            "propertyOrdering": ["number", "topic", "why", "marks", "prompt", "answer"],
        }},
    },
    "required": ["title", "intro", "questions"],
    "propertyOrdering": ["title", "intro", "questions"],
}


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


def read_prompt(course: Course, topics: list[Topic], files: list[tuple[str, str]]) -> str:
    """files: (role, name) in the order they're attached."""
    roles = {"exam": "the EXAM paper", "solution": "the SOLUTIONS / answer key",
             "attempt": "the STUDENT'S OWN ANSWERS (possibly graded by a teacher)"}
    listing = "\n".join(f"{i}. {name}: {roles.get(role, role)}" for i, (role, name) in enumerate(files, 1))
    has_solution = any(r == "solution" for r, _ in files)
    has_attempt = any(r == "attempt" for r, _ in files)
    answer = ("the answer from the solutions file, worked through concisely" if has_solution
              else "a short, correct worked answer you write yourself (there is no solutions file)")
    if has_attempt:
        result = ('compare the student\u2019s own answer with a correct one. result is "ok" (full or nearly full '
                  'credit), "partial" (some credit), "missed" (wrong or not answered) or "unknown" (you can\u2019t tell); '
                  'use the teacher\u2019s marking where there is any. note is one or two sentences, addressed to the student, on what went wrong '
                  '("" when ok)')
        score = "if it's written on their answers"
    else:
        result = 'result is "unknown" and note is "" (the student\u2019s answers aren\u2019t attached)'
        score = '("": not known)'
    return f"""Course: {course.code} {course.name}

The course's topics:
{_topic_list(topics)}

The attached files, in order:
{listing}

List every question of the exam paper, in order. Split a question into parts (1a, 1b, ...) when the parts are
answered or marked separately. For each question give:
- number: as printed ("1", "2b").
- prompt: the full question text, transcribed faithfully in the exam's own language, with everything needed to
  answer it (given values, tables as Markdown tables, code). Where a figure is needed, describe it in
  [square brackets]. Repeat shared context from the main question in each part, so every part can be read on its own.
- marks: the points the question is worth, if printed (else "").
- topic: the course topic it tests, copied exactly from the list above, or "" if none fits.
- answer: {answer}.
- result and note: {result}.
Also give score: the student's total score {score}."""


def make_prompt(course: Course, topics: list[Topic], files: list[tuple[str, str]], struggles: str, size: str,
                focus: str, focus_topics: list[str], wishes: str, earlier: list[str], number: int) -> str:
    listing = "\n".join(f"- {name}" + (" (solutions)" if role == "solution" else "") for role, name in files)
    sources = (f"Attached are past exams for this course{', with solutions' if any(r == 'solution' for r, _ in files) else ''}:\n"
               f"{listing}\nMatch them closely: the same style, format, language, notation, difficulty, level of rigour and "
               "kinds of questions. Write NEW questions that test the same skills, with different numbers, examples and "
               "contexts; don't copy questions." if files
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
