"""Plain data types for everything study stores. No I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class TopicStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    REVIEWED = "reviewed"
    CONFIDENT = "confident"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")

    @property
    def is_done(self) -> bool:
        """Counts toward the 'material done' fill of the cram timeline."""
        return self in (TopicStatus.REVIEWED, TopicStatus.CONFIDENT)


class Priority(StrEnum):
    LOW = "low"
    MED = "med"
    HIGH = "high"

    @property
    def rank(self) -> int:
        """Higher is more urgent."""
        return {"low": 0, "med": 1, "high": 2}[self.value]


class DeadlineKind(StrEnum):
    EXAM = "exam"
    ASSIGNMENT = "assignment"
    MILESTONE = "milestone"


# One accent per course. Mid-tone colours that read on both light and dark terminals.
COURSE_COLORS: tuple[str, ...] = (
    "#5b8def",  # blue
    "#e07a5f",  # coral
    "#3ba99c",  # teal
    "#b07fe0",  # violet
    "#d9a930",  # amber
    "#6fae5a",  # green
    "#e0679a",  # pink
    "#7d8ba3",  # slate
)


@dataclass
class Course:
    name: str
    code: str
    cram_start: date
    exam_date: date
    color: str = COURSE_COLORS[0]
    notes: str = ""
    done: bool = False  # finished with: moved out of the way, its deadlines and weak spots go quiet
    id: int | None = None


@dataclass
class Topic:
    course_id: int
    title: str
    status: TopicStatus = TopicStatus.NOT_STARTED
    confidence: int = 1
    last_studied: date | None = None
    id: int | None = None


@dataclass
class WeakSpot:
    course_id: int
    description: str
    priority: Priority = Priority.MED
    topic_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now().replace(second=0, microsecond=0))
    resolved: bool = False
    resolved_at: datetime | None = None
    id: int | None = None


@dataclass
class Deadline:
    title: str
    due_at: datetime
    kind: DeadlineKind = DeadlineKind.ASSIGNMENT
    course_id: int | None = None
    done: bool = False
    # The exam deadline that every course gets automatically; it follows the course's exam date.
    is_course_exam: bool = False
    id: int | None = None


@dataclass
class Session:
    course_id: int
    started_at: datetime
    minutes: int
    topic_id: int | None = None
    note: str = ""
    id: int | None = None


@dataclass
class SentNotification:
    deadline_id: int
    threshold: str
    due_at: datetime
    sent_at: datetime


@dataclass
class ActiveTimer:
    """A study session that has started but not been logged yet. Survives quitting the TUI."""

    course_id: int
    started_at: datetime
    topic_id: int | None = None


@dataclass
class Source:
    """Something to read for a course: a textbook, lecture notes, a paper."""

    course_id: int
    title: str
    author: str = ""  # authors separated by semicolons: "Bishop, Christopher M.; Nasrabadi, Nasser"
    kind: str = "book"  # book, article, web or notes (for the APA reference)
    year: str = ""
    publisher: str = ""  # also a web page's site name, or the institution for lecture notes
    edition: str = ""
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    link: str = ""  # DOI or URL
    topic_id: int | None = None  # the topic the whole source belongs to (chapters and sections can differ)
    id: int | None = None


@dataclass
class Chapter:
    source_id: int
    number: str  # "6", "A"
    title: str = ""
    topic_id: int | None = None  # the topic this chapter's sections count toward
    # Ticked off as a whole. Only used while the chapter has no sections: then the chapter itself is
    # the one thing to read (logic/reading.reading_units).
    read: bool = False
    read_at: datetime | None = None
    id: int | None = None


@dataclass
class Section:
    chapter_id: int
    number: str  # "6.1"
    title: str = ""
    required: bool = True  # part of what you need to read; optional sections don't count toward progress
    read: bool = False
    read_at: datetime | None = None
    topic_id: int | None = None  # set to link just this section to a different topic than its chapter
    id: int | None = None


EXAM_KINDS = ("past", "practice")  # uploaded from a real exam, or made by Gemini to practise on
FILE_ROLES = ("exam", "solution", "attempt")  # the paper, its answer key, your own (graded) answers
RESULTS = ("ok", "partial", "missed")  # how a question went; "" while unmarked


@dataclass
class Exam:
    """A past exam for a course (with its files), or a practice exam made from them."""

    course_id: int
    title: str
    kind: str = "past"
    taken_on: str = ""  # free text: "Spring 2024", "3 June 2025"
    score: str = ""  # what you got, as you'd write it: "62/100", "C"
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now().replace(second=0, microsecond=0))
    id: int | None = None


@dataclass
class ExamFile:
    exam_id: int
    name: str  # the file's name when it was added
    key: str  # its copy in the files folder: <sha256>.<ext>, the same on every computer
    mime: str
    size: int = 0
    role: str = "exam"
    id: int | None = None


@dataclass
class ExamQuestion:
    exam_id: int
    number: str  # "1", "3b"
    prompt: str = ""  # Markdown, with $...$ for maths
    answer: str = ""
    marks: str = ""
    topic_id: int | None = None
    result: str = ""
    note: str = ""  # what went wrong, in your own words
    why: str = ""  # practice exams: what the question was made to practise
    id: int | None = None
