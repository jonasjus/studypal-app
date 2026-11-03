"""Writing practice exams: what went badly before (the summary and the tally by topic), choosing past
questions as examples for each weak topic, and the prompt. No I/O here: core/generate.py makes the call
and api.py gathers the data. Reading exams is in core/ingest.py.
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


def few_shot(past: list[tuple[str, ExamQuestion]], topic: str, titles: dict[int, str], lo: int = 3,
             hi: int = 5) -> list[tuple[str, ExamQuestion]]:
    """Up to `hi` past questions on `topic` to show as examples (fewer than `lo` only if that's all there
    are): ones tagged with it or counted toward it, those with a known answer first, then those that went
    badly (they're what needs practising), then the newest. `past` is (exam title, question), newest exam first."""
    want = " ".join(topic.split()).casefold()

    def on_topic(q: ExamQuestion) -> bool:
        tags = [" ".join(t.split()).casefold() for t in q.topic_tags]
        return want in tags or " ".join(titles.get(q.topic_id, "").split()).casefold() == want

    picked = [(i, exam, q) for i, (exam, q) in enumerate(past) if on_topic(q) and q.prompt.strip()]
    picked.sort(key=lambda t: (not t[2].answer, t[2].result not in ("missed", "partial"), t[0]))
    return [(exam, q) for _, exam, q in picked[:max(lo, hi)]]


def _example(exam: str, q: ExamQuestion, short: bool = False) -> str:
    points = f" ({q.marks} points)" if q.marks else ""
    kind = f" [{q.question_type}]" if q.question_type else ""
    answer = f"\n  *Solution:* {_clip(q.answer, 300 if short else 700)}" if q.answer else ""
    return f"- From {exam}, question {q.number}{points}{kind}: {_clip(q.prompt, 450 if short else 900)}{answer}"


def fit_examples(examples: dict[str, list[tuple[str, ExamQuestion]]], budget: int) -> tuple[dict, bool]:
    """As many examples per topic as fit in `budget` characters (the same number for every topic, at least
    one), shortened if the full ones don't fit even one each. Returns them and whether they're shortened."""
    def size(per: int, short: bool) -> int:
        return sum(len(_example(e, q, short)) for shots in examples.values() for e, q in shots[:per])

    most = max((len(v) for v in examples.values()), default=0)
    for short in (False, True):
        for per in range(most, 0, -1):
            if size(per, short) <= budget:
                return {t: v[:per] for t, v in examples.items()}, short
    return {t: v[:1] for t, v in examples.items()}, True


def generate_prompt(course: Course, topics: list[Topic], weak_topics: list[str], n: int,
                    examples: dict[str, list[tuple[str, ExamQuestion]]], style: list[tuple[str, ExamQuestion]],
                    struggles: str, wishes: str, earlier: list[str], number: int, start: int = 1,
                    short: bool = False) -> str:
    """The prompt for `generate_exam`: n new questions on the weak topics, with past questions as examples."""
    shots = []
    for topic in weak_topics:
        got = examples.get(topic) or []
        shots.append(f"### {topic}\n" + ("\n".join(_example(e, q, short) for e, q in got) if got
                                         else "(No past questions on this topic: follow the style of the others.)"))
    general = ("\n\nOther questions from the past exams, for their style:\n" + "\n".join(_example(e, q, short) for e, q in style)
               if style else "")
    sources = ("Past exam questions for each topic, as examples of the style, format, language, notation, difficulty "
               "and level of rigour to match:\n\n" + "\n\n".join(shots) + general
               + "\n\nWrite NEW questions that test the same skills, with different numbers, examples and contexts; "
               "don't copy them." if any(examples.values()) or style
               else "There are no past exams to go on. Write questions a university would set for this course.")
    earlier_text = ("\n\nQuestions from earlier practice exams (write different ones):\n"
                    + "\n".join(f"- {_clip(p, 80 if short else 160)}" for p in earlier[:30 if short else 60])) if earlier else ""
    wishes_text = f"\n\nThe student also asks: {wishes.strip()}" if wishes.strip() else ""
    carry = (f"\nThese carry on an exam already begun: number them from {start}, and don't repeat the earlier questions "
             "listed below." if start > 1 else "")
    return f"""Course: {course.code} {course.name}

The course's topics:
{_topic_list(topics)}

Write practice exam number {number}: {n} question{"s" if n != 1 else ""} (count each part, 2a and 2b, as one),
spread over these topics, with the most on the first ones: {"; ".join(weak_topics) or "the whole course"}.{carry}

{sources}

What the student struggles with:
{struggles}{earlier_text}{wishes_text}

Give:
- title: short, e.g. "Practice exam {number}: eigenvalues and diagonalisation".
- intro: the cover instructions, as on the real exams (time allowed, total points, allowed aids), in Markdown.
- questions, each with:
  - number ("1", "2a"), parent_number ("2" for 2a, else "").
  - text: the question, complete and self-contained, Markdown with maths in LaTeX ($...$).
  - topic_tags: the topics it tests, copied exactly from the list above.
  - question_type: one of short_answer, calculation, proof, multiple_choice, true_false, essay, code, other.
  - points: what it's worth ("10"), or "" if the past exams don't show points.
  - has_figure: false (describe anything visual in words instead).
  - why: one short sentence to the student on what it practises and, when it targets an earlier mistake,
    which one (e.g. "Practises the sign error you made in 2b of the 2023 exam.").
  - answer: a full worked solution, detailed enough for the student to mark their own answer."""
