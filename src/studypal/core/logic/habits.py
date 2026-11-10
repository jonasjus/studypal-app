"""Statistics about your study habits, for the Statistics page: totals, streaks, when you study and what on.

Everything here comes from logged study time (subjects and research projects alike) and the to-do lists,
so the numbers include time logged before this page existed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from ..models import Session, Todo
from .badges import streak_runs
from .stats import week_bounds

WEEKS = 12  # weeks in the weekly chart
HEAT_WEEKS = 26  # weeks in the calendar of every day


@dataclass(frozen=True)
class Habits:
    total_minutes: int
    sessions: int
    study_days: int
    this_week: int
    last_week_so_far: int  # last week up to the same point (same number of days in), for a fair comparison
    current_streak: int  # days in a row, ending today or yesterday (a streak isn't broken until a day is missed)
    longest_streak: int
    average_session: int  # minutes
    longest_session: int
    weeks: list[tuple[date, int]]  # (first day, minutes), oldest first, the current week last
    days: list[tuple[date, int]]  # every day of the last HEAT_WEEKS weeks, from a week's first day up to today
    by_weekday: list[int]  # minutes by day of the week, in week order (starting at week_start)
    by_hour: list[int]  # minutes in each hour of the day, 0–23, with sessions split across the hours they span
    by_course: list[tuple[int, int]]  # (course id, minutes), most first
    research_minutes: int
    todos_done_week: int
    todos_week: int
    todos_done_month: int  # the last 30 days, today included
    todos_month: int


def _split_by_hour(s: Session, into: list[int]) -> None:
    at, left = s.started_at, s.minutes
    while left > 0:
        here = min(left, 60 - at.minute)
        into[at.hour] += here
        left -= here
        at = (at + timedelta(minutes=here)).replace(second=0, microsecond=0)


def habits(sessions: Iterable[Session], todos: Iterable[Todo], today: date, week_start: int = 0) -> Habits:
    sessions, todos = list(sessions), list(todos)
    per_day: dict[date, int] = defaultdict(int)
    per_course: dict[int, int] = defaultdict(int)
    by_hour = [0] * 24
    by_weekday = [0] * 7
    research = 0
    for s in sessions:
        d = s.started_at.date()
        per_day[d] += s.minutes
        by_weekday[(d.weekday() - week_start) % 7] += s.minutes
        _split_by_hour(s, by_hour)
        if s.course_id is not None:
            per_course[s.course_id] += s.minutes
        else:
            research += s.minutes

    def minutes(start: date, end: date) -> int:  # from start up to before end
        return sum(m for d, m in per_day.items() if start <= d < end)

    week_first, _ = week_bounds(today, week_start)
    into_week = (today - week_first).days + 1
    weeks = [(week_first - timedelta(weeks=n), minutes(week_first - timedelta(weeks=n), week_first - timedelta(weeks=n - 1)))
             for n in range(WEEKS - 1, -1, -1)]
    heat_first = week_first - timedelta(weeks=HEAT_WEEKS - 1)
    days = [(heat_first + timedelta(days=i), per_day.get(heat_first + timedelta(days=i), 0))
            for i in range((today - heat_first).days + 1)]

    studied = sorted(d for d, m in per_day.items() if m > 0 and d <= today)
    runs = dict(streak_runs(studied))
    current = runs.get(today) or runs.get(today - timedelta(days=1)) or 0

    week_todos = [t for t in todos if week_first <= t.day <= today]
    month_todos = [t for t in todos if today - timedelta(days=29) <= t.day <= today]
    return Habits(
        total_minutes=sum(s.minutes for s in sessions),
        sessions=len(sessions),
        study_days=len(studied),
        this_week=minutes(week_first, today + timedelta(days=1)),
        last_week_so_far=minutes(week_first - timedelta(weeks=1), week_first - timedelta(weeks=1) + timedelta(days=into_week)),
        current_streak=current,
        longest_streak=max(runs.values(), default=0),
        average_session=round(sum(s.minutes for s in sessions) / len(sessions)) if sessions else 0,
        longest_session=max((s.minutes for s in sessions), default=0),
        weeks=weeks,
        days=days,
        by_weekday=by_weekday,
        by_hour=by_hour,
        by_course=sorted(per_course.items(), key=lambda kv: -kv[1]),
        research_minutes=research,
        todos_done_week=sum(1 for t in week_todos if t.done),
        todos_week=len(week_todos),
        todos_done_month=sum(1 for t in month_todos if t.done),
        todos_month=len(month_todos),
    )
