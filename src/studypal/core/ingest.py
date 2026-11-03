"""Reading an exam into structured questions: files to Markdown, Markdown to questions, questions matched
with their solutions, and (given the student's own answers) marked.

1. Parse: each file becomes Markdown, page by page (core/pages.py). Pages with a usable text layer are
   taken as they are (the next step writes their formulas back as LaTeX); scanned pages go to the model
   as images, a few per request, to be transcribed with the maths in LaTeX.
2. Extract: the exam's Markdown goes to the model a few pages at a time for its questions, then the
   solutions' for their answers. Pydantic checks both (core/logic/questions.py) and they're matched by
   number, so a question the solutions don't answer has answer None.
3. Mark: if the student's own answers are there, the model compares them with the answers.

Free plans let a model write little per answer (and per minute). So every request covers only a few
pages (Provider.chunk_chars), and a request whose answer is cut off anyway (TooMuch) is split in half
and asked again, down to a single page.

Storage and the window stay in api.py; this module only needs a Provider and the files' bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from . import pages
from .llm import Image, LLMError, Provider, TooMuch
from .logic import questions as Q
from .logic.exams import SYSTEM, _clip, _topic_list
from .models import Course, Topic

Progress = Callable[[str], None]


@dataclass
class SourceFile:
    name: str
    mime: str
    data: bytes
    role: str  # exam, solution or attempt


@dataclass
class Result:
    questions: list[Q.Question]
    results: dict[str, tuple[str, str]] = field(default_factory=dict)  # number key -> (result, note)
    score: str = ""
    unmatched: list[str] = field(default_factory=list)  # solutions whose number isn't a question
    dropped: int = 0  # questions or solutions the model gave in the wrong shape
    read_pages: int = 0  # pages that had to be transcribed from images
    kept_text: int = 0  # maths pages that kept their plain text (too much to transcribe on this plan)


@dataclass
class Doc:
    """A file as Markdown, page by page."""

    name: str
    role: str
    pages: list[tuple[int, str]]  # (page number, Markdown)
    total: int


Piece = list[tuple[Doc, int, str]]  # pages (of one or more files) sent in one request


def in_pieces(items: list, do: Callable[[list], None]) -> None:
    """do(items) as one request, or, if the answer won't fit (TooMuch), each half on its own."""
    try:
        do(items)
    except TooMuch:
        if len(items) < 2:
            raise
        mid = len(items) // 2
        in_pieces(items[:mid], do)
        in_pieces(items[mid:], do)


def pieces(docs: list[Doc], limit: int) -> list[Piece]:
    """The docs' pages in groups of at most `limit` characters (a page bigger than that goes alone)."""
    out: list[Piece] = []
    size = 0
    for doc in docs:
        for n, text in doc.pages:
            if not out or size + len(text) > limit:
                out.append([])
                size = 0
            out[-1].append((doc, n, text))
            size += len(text)
    return out


def piece_markdown(piece: Piece) -> str:
    out, last = [], None
    for doc, n, text in piece:
        if doc is not last:
            out.append(f"# {doc.name}")
            last = doc
        out.append(f"<!-- page {n} of {doc.total} -->\n{text.strip()}")
    return "\n\n".join(out)


def where(piece: Piece) -> str:
    """"pages 3–5 of 8" (of the first file in the piece), for the progress line."""
    doc = piece[0][0]
    numbers = [n for d, n, _ in piece if d is doc]
    return f"page {numbers[0]} of {doc.total}" if len(numbers) == 1 else f"pages {numbers[0]}–{numbers[-1]} of {doc.total}"


def transcribe_prompt(name: str, batch: list, total: int) -> str:
    numbers = [p.number for p in batch]
    which = f"page {numbers[0]}" if len(numbers) == 1 else f"pages {', '.join(map(str, numbers))}"
    layers = "".join(f"\n\n--- The text layer of page {p.number} ---\n{p.text}" for p in batch if p.text.strip())
    reference = ("\n\nWhat little text layer the pages have is below, as a check." if layers else "")
    return f"""Attached, in order, {which} of {total} of “{name}”, as images.

Transcribe each page into Markdown, completely and exactly as written, in its own language, down to the last
line: headings, numbering, lists, code (in ``` blocks) and tables (as Markdown tables). Write every formula in
LaTeX between $...$ (inline) or $$...$$ (on its own line). Describe figures and diagrams in [square brackets].
Handwriting too. Don't solve, summarise, shorten or add anything. Give one entry per page, with its page
number.{reference}{layers}"""


# A transcription this much shorter than the page's text layer has left something out.
COMPLETE = 0.8


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def to_markdown(provider: Provider, f: SourceFile, progress: Progress = lambda _: None) -> tuple[Doc, int, int]:
    """The file as Markdown pages, how many pages were transcribed from images, and how many maths pages kept
    their plain text because the model couldn't write them out (too much for one answer on this plan)."""
    file_pages = pages.to_pages(f.name, f.mime, f.data)
    total = len(file_pages)
    texts = {p.number: p.text for p in file_pages}
    read = kept = 0
    nonlocal_kept: list[int] = []  # pages whose transcription came back incomplete, so they keep their text

    def transcribe(batch: list) -> None:
        nonlocal read
        numbers = [p.number for p in batch]
        progress(f"Transcribing “{f.name}”, page{'s' if len(numbers) > 1 else ''} "
                 f"{numbers[0]}{f'–{numbers[-1]}' if len(numbers) > 1 else ''} of {total}")
        parts = [*[Image(f"{f.name} p{p.number}", p.image) for p in batch], transcribe_prompt(f.name, batch, total)]
        answer = provider.ask(parts, Q.TRANSCRIBE_SCHEMA, SYSTEM, 0.0, vision=True, effort="low")
        got = {int(p.get("page", 0)): str(p.get("markdown") or "") for p in answer.get("pages") or [] if isinstance(p, dict)}
        # Pages given without (or with wrong) numbers are taken in order.
        loose = [md for n, md in got.items() if n not in numbers]
        for p in batch:
            md = got.get(p.number) or (loose.pop(0) if loose else "")
            if p.text.strip() and _letters(md) < COMPLETE * _letters(p.text):
                nonlocal_kept.append(p.number)  # it left part of the page out: the text layer has it all
                continue
            if md.strip():
                texts[p.number] = md
        read += len(batch)

    def transcribe_or_keep(batch: list) -> None:
        """Transcribe the batch; a single page that won't fit even alone keeps its text layer, if it has one
        (its maths stays as plain characters). A real scan can't be read with this model."""
        nonlocal kept
        try:
            transcribe(batch)
        except TooMuch:
            if len(batch) > 1:
                raise  # in_pieces splits it
            page = batch[0]
            if not page.text.strip():
                raise LLMError(f"Page {page.number} of “{f.name}” has more on it than {provider.name} can write out in "
                               "one answer on your plan. Try another provider in Settings.") from None
            kept += 1

    to_read = [p for p in file_pages if p.image is not None]
    for i in range(0, len(to_read), provider.max_images):
        in_pieces(to_read[i:i + provider.max_images], transcribe_or_keep)
    doc = Doc(f.name, f.role, [(n, texts[n]) for n in sorted(texts) if texts[n].strip()], total)
    return doc, read, kept + len(nonlocal_kept)


def _course_head(course: Course, topics: list[Topic]) -> str:
    return f"Course: {course.code} {course.name}\n\nThe course's topics:\n{_topic_list(topics)}"


def questions_prompt(course: Course, topics: list[Topic], piece: Piece, found: list[Q.Question]) -> str:
    """Find the questions on a few pages of the exam paper."""
    so_far = ""
    if found:
        last = found[-1]
        so_far = (f"\n\nEarlier pages had questions {', '.join(q.number for q in found)}. The last one, {last.number}, "
                  f"ended: “…{_clip(last.text[-300:], 300)}”. If these pages start in the middle of it, give it again "
                  f"with number {last.number} and only the part on these pages.")
    return f"""{_course_head(course, topics)}

Below are {where(piece)} of the EXAM PAPER: the PDF's text, or a transcription of scanned pages. In PDF text
formulas come out garbled (x2 for x², fraction bars and sub- and superscripts lost); write them as they were
meant, in LaTeX.{so_far}

List every question on these pages, in order, splitting a question into its parts when they're answered or
marked separately. For each give:
- number: the full number, never renumbered: a part's number is its main question's number followed by its
  own, in the exam's own style: numbered items with a dot ("1.3" for item 3 under "1. True or false", so an
  exam whose question 1 has items 1-19 has 1.1 ... 1.19), lettered parts with their letter ("2b"). Don't
  change 1.3 into 1c, or leave off the main question's number.
- parent_number: the main question a part belongs to ("1" for 1.3, "2" for 2b), or "" for a question without parts.
- text: the full question, faithfully, in the exam's own language, Markdown with maths in LaTeX ($...$).
  Repeat shared context from the main question in each part, so every part can be read on its own.
- topic_tags: the course topics it tests, copied exactly from the list above (empty if none fits).
- question_type: one of {", ".join(Q.QUESTION_TYPES)}.
- points: what this question or part is worth, as a number ("10"), if printed for it. When only the main
  question's total is printed ("Question 1 (10 points)" with parts a and b), give it on the first part and ""
  on the others, so the points add up to the exam's total. "" if no points are printed.
- has_figure: whether it relies on a figure, diagram or graph.
Cover pages and instructions without questions give an empty list.

{piece_markdown(piece)}"""


def solutions_prompt(course: Course, questions: list[Q.Question], piece: Piece, last: str | None) -> str:
    """Take the answers from a few pages of the solutions."""
    listing = "\n".join(f"- {q.number}: {_clip(q.text, 90)}" for q in questions)
    before = (f"\n\nThe pages before these ended with the answer to question {last}, so numbering at the top of these "
              "pages may continue inside that same main question.") if last else ""
    return f"""Course: {course.code} {course.name}

The exam's questions, with their numbers and how each starts:
{listing}

Below are {where(piece)} of the SOLUTIONS (answer key) for this exam: the PDF's text (formulas may be garbled:
write them as meant, in LaTeX) or a transcription of scanned pages.{before}

For each answer on these pages give the number of the question it answers, exactly as in the list above (the
solutions may number things more briefly, like "14." for 1.14: use the full number from the list, going by
which question it answers), and the answer, faithfully and in full, Markdown with maths in LaTeX ($...$). If
an answer starts on an earlier page, give only the part here. Only take answers from the solutions; never
write one yourself.

{piece_markdown(piece)}"""


def marks_prompt(course: Course, questions: list[Q.Question], piece: Piece) -> str:
    listing = "\n".join(f"- {q.number}: {_clip(q.text, 500)}"
                        + (f"\n  Correct answer: {_clip(q.answer, 600)}" if q.answer else "") for q in questions)
    return f"""Course: {course.code} {course.name}

The exam's questions{", with correct answers where known" if any(q.answer for q in questions) else ""}:
{listing}

Below are {where(piece)} of the STUDENT'S OWN ANSWERS (possibly graded by a teacher), transcribed to Markdown.

For each question the student answered on these pages, give its number exactly as in the list above, and:
- result: "ok" (full or nearly full credit), "partial" (some credit), "missed" (wrong or not answered) or
  "unknown" (you can't tell). Use the teacher's marking where there is any.
- note: one or two sentences, addressed to the student, on what went wrong ("" when ok).
Also give score: the student's total score if it's written on these pages, else "".

{piece_markdown(piece)}"""


def ingest(provider: Provider, course: Course, topics: list[Topic], files: list[SourceFile], exam_id: int | None = None,
           progress: Progress = lambda _: None) -> Result:
    """Read an exam's files into checked questions (with answers from the solutions only) and, if the
    student's own answers are among the files, how each question went."""
    if not any(f.role == "exam" for f in files):
        raise LLMError("Add the exam paper itself first (a PDF or photos).")
    if hasattr(provider, "on_wait"):
        provider.on_wait = lambda s: progress(f"Waiting {round(s)}s for {provider.name}'s per-minute limit")  # type: ignore[attr-defined]
    progress("Reading the files")
    docs: dict[str, list[Doc]] = {"exam": [], "solution": [], "attempt": []}
    result = Result([])
    kept = 0
    for f in files:
        doc, read, k = to_markdown(provider, f, progress)
        result.read_pages += read
        kept += k
        if doc.pages:
            docs.setdefault(f.role, []).append(doc)
    result.kept_text = kept
    if not docs["exam"]:
        raise LLMError("There's no text in the exam paper, even after reading its pages.")

    def too_much(what: str, piece: Piece) -> LLMError:
        return LLMError(f"Page {piece[0][1]} of “{piece[0][0].name}” has more {what} than {provider.name} can write out "
                        "in one answer on your plan. Try another provider in Settings.")

    # The questions, a few pages at a time (each request knows what came before, for questions over a page break).
    found: list[Q.Question] = []

    def find(piece: Piece) -> None:
        progress(f"Finding the questions, {where(piece)}")
        answer = provider.ask([questions_prompt(course, topics, piece, found)], Q.QUESTIONS_SCHEMA, SYSTEM, 0.1, effort="low")
        extraction, dropped = Q.validate_extraction(answer, exam_id)
        found.extend(extraction.questions)
        result.dropped += dropped

    for piece in pieces(docs["exam"], provider.chunk_chars):
        try:
            in_pieces(piece, find)
        except TooMuch:
            raise too_much("questions on it", piece) from None
    found = Q.dedupe(found)
    if not found:
        raise LLMError("No questions were found in the exam. Is the right file marked as the exam?")

    # The answers from the solutions, then matched by number.
    solutions: list[Q.Solution] = []

    def answers(piece: Piece) -> None:
        progress(f"Reading the solutions, {where(piece)}")
        last = solutions[-1].number if solutions else None
        answer = provider.ask([solutions_prompt(course, found, piece, last)], Q.SOLUTIONS_SCHEMA, SYSTEM, 0.1, effort="low")
        extraction, dropped = Q.validate_extraction(answer)
        solutions.extend(extraction.solutions)
        result.dropped += dropped

    for piece in pieces(docs["solution"], provider.chunk_chars):
        try:
            in_pieces(piece, answers)
        except TooMuch:
            raise too_much("answers on it", piece) from None
    result.questions, result.unmatched = Q.match_solutions(found, solutions)

    # How each question went, from the student's own answers.
    keys = {Q.number_key(q.number) for q in result.questions}

    def mark(piece: Piece) -> None:
        progress(f"Marking your answers, {where(piece)}")
        answer = provider.ask([marks_prompt(course, result.questions, piece)], Q.MARKS_SCHEMA, SYSTEM, 0.1)
        for r in answer.get("results") or []:
            if not isinstance(r, dict):
                continue
            key = Q.number_key(str(r.get("number") or ""))
            if key in keys and r.get("result") in ("ok", "partial", "missed"):
                result.results[key] = (r["result"], str(r.get("note") or "").strip())
        result.score = result.score or str(answer.get("score") or "").strip()[:30]

    for piece in pieces(docs["attempt"], provider.chunk_chars):
        try:
            in_pieces(piece, mark)
        except TooMuch:
            raise too_much("of your answers", piece) from None
    return result
