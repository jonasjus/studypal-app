"""The cram timeline: how far into the cram period today is, against how much material is done.

    cram start ──────────────────────────────── exam
    ████████████▒▒▒▒▒▒▒│░░░░░░░░░░░░░░░░░░░░░░░░
    done          behind today   still to come

If the done fill stops short of today's marker, the stretch in between is the gap
you're behind by.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from ..models import Course, Topic


class Phase(StrEnum):
    BEFORE = "before"  # cram period hasn't started
    CRAMMING = "cramming"
    EXAM_DAY = "exam_day"
    AFTER = "after"  # exam is over


class Cell(StrEnum):
    DONE = "done"
    BEHIND = "behind"  # time has passed but the material isn't done
    TODO = "todo"


@dataclass(frozen=True)
class CramProgress:
    elapsed: float  # share of the cram period that has passed, 0–1
    done: float  # share of topics reviewed or confident, 0–1
    days_total: int
    days_left: int  # days until the exam; negative once it's over
    phase: Phase
    topic_count: int

    @property
    def behind(self) -> float:
        """How far the done fill trails today's marker, 0–1. Zero once the exam is over, and while a
        course has no topics yet (there's nothing to be behind on)."""
        if self.phase is Phase.AFTER or self.topic_count == 0:
            return 0.0
        return max(0.0, self.elapsed - self.done)

    @property
    def is_behind(self) -> bool:
        # Ignore rounding-level differences so a course that's exactly on pace isn't flagged.
        return self.behind > 0.005


def done_fraction(topics: Iterable[Topic]) -> float:
    topics = list(topics)
    if not topics:
        return 0.0
    return sum(1 for t in topics if t.status.is_done) / len(topics)


def cram_progress(course: Course, topics: Iterable[Topic], today: date) -> CramProgress:
    topics = list(topics)
    total = (course.exam_date - course.cram_start).days
    if total <= 0:  # cram start and exam on the same day
        elapsed = 1.0 if today >= course.exam_date else 0.0
    else:
        elapsed = min(1.0, max(0.0, (today - course.cram_start).days / total))

    if today < course.cram_start:
        phase = Phase.BEFORE
    elif today < course.exam_date:
        phase = Phase.CRAMMING
    elif today == course.exam_date:
        phase = Phase.EXAM_DAY
    else:
        phase = Phase.AFTER

    return CramProgress(
        elapsed=elapsed,
        done=done_fraction(topics),
        days_total=max(total, 0),
        days_left=(course.exam_date - today).days,
        phase=phase,
        topic_count=len(topics),
    )


def timeline_cells(progress: CramProgress, width: int) -> tuple[list[Cell], int]:
    """Split a bar of `width` cells into done / behind / to-do, plus the cell index of today's marker."""
    if width < 1:
        return [], 0
    done_n = round(progress.done * width)
    today_n = round(progress.elapsed * width)
    cells = [
        Cell.DONE if i < done_n else Cell.BEHIND if i < today_n and progress.behind > 0 else Cell.TODO
        for i in range(width)
    ]
    marker = min(width - 1, max(0, round(progress.elapsed * (width - 1))))
    return cells, marker
