"""Everything the overview needs, gathered from storage in one place (used by `study status` and the TUI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .config import Config
from .logic.pomodoro import PomodoroRun
from .logic.reading import ReadingProgress
from .logic.stats import is_stale, minutes_between, minutes_per_day, week_range
from .logic.timeline import CramProgress, cram_progress
from .models import ActiveTimer, Course, Deadline, Topic, WeakSpot
from .storage import Store


@dataclass(frozen=True)
class CourseSummary:
    course: Course
    topics: list[Topic]
    progress: CramProgress
    week_minutes: int
    total_minutes: int
    open_weak: int
    stale_topics: int
    next_deadline: Deadline | None
    reading: ReadingProgress = ReadingProgress()


@dataclass(frozen=True)
class Dashboard:
    now: datetime
    courses: list[CourseSummary]
    deadlines: list[Deadline]  # open, soonest first (overdue included)
    weak_spots: list[WeakSpot]  # open, by priority then age
    week_days: list[date]
    week_minutes: list[int]  # per day, aligned with week_days
    timer: ActiveTimer | None
    pomodoro: PomodoroRun | None
    done_courses: list[CourseSummary] = field(default_factory=list)  # marked done; kept out of the way

    @property
    def today(self) -> date:
        return self.now.date()

    def course(self, course_id: int | None) -> Course | None:
        return next((s.course for s in self.courses + self.done_courses if s.course.id == course_id), None)


def build(store: Store, cfg: Config, now: datetime | None = None) -> Dashboard:
    now = now or datetime.now()
    today = now.date()
    week_start, week_end = week_range(today, cfg.week_start)
    week_sessions = store.list_sessions(since=week_start, until=week_end)
    deadlines = store.list_deadlines(active_only=True)
    weak = store.list_weak_spots(active_only=True)

    summaries = []
    for course in store.list_courses():
        topics = store.list_topics(course.id)
        upcoming = [d for d in deadlines if d.course_id == course.id]
        summaries.append(CourseSummary(
            course=course,
            topics=topics,
            progress=cram_progress(course, topics, today),
            week_minutes=minutes_between(week_sessions, week_start, week_end, course.id),
            total_minutes=store.total_minutes(course.id),
            open_weak=sum(1 for w in weak if w.course_id == course.id),
            stale_topics=sum(1 for t in topics if is_stale(t, today, cfg.stale_after_days)),
            next_deadline=upcoming[0] if upcoming else None,
            reading=store.reading_progress(course.id),
        ))

    first_day = week_start.date()
    return Dashboard(
        now=now,
        courses=[s for s in summaries if not s.course.done],
        done_courses=[s for s in summaries if s.course.done],
        deadlines=deadlines,
        weak_spots=weak,
        week_days=[first_day + timedelta(days=i) for i in range(7)],
        week_minutes=minutes_per_day(week_sessions, first_day),
        timer=store.get_timer(),
        pomodoro=store.get_pomodoro(),
    )
