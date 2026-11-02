"""Study-time totals, week boundaries and stale topics."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from ..models import Session, Topic


def week_bounds(today: date, week_start: int = 0) -> tuple[date, date]:
    """First day of the week containing `today`, and the first day of the next week. 0 = Monday."""
    start = today - timedelta(days=(today.weekday() - week_start) % 7)
    return start, start + timedelta(days=7)


def week_range(today: date, week_start: int = 0) -> tuple[datetime, datetime]:
    start, end = week_bounds(today, week_start)
    return datetime.combine(start, time()), datetime.combine(end, time())


def minutes_per_day(sessions: Iterable[Session], first_day: date, days: int = 7) -> list[int]:
    """Minutes studied on each of `days` days from `first_day`. A session counts on the day it started."""
    totals = [0] * days
    for s in sessions:
        i = (s.started_at.date() - first_day).days
        if 0 <= i < days:
            totals[i] += s.minutes
    return totals


def minutes_between(sessions: Iterable[Session], start: datetime, end: datetime, course_id: int | None = None) -> int:
    return sum(
        s.minutes for s in sessions
        if start <= s.started_at < end and (course_id is None or s.course_id == course_id)
    )


def days_since(day: date | None, today: date) -> int | None:
    return None if day is None else (today - day).days


def is_stale(topic: Topic, today: date, stale_after_days: int) -> bool:
    """Studied before, but not for `stale_after_days` days or more."""
    since = days_since(topic.last_studied, today)
    return since is not None and since >= stale_after_days


def format_minutes(minutes: int) -> str:
    """'1h 30m', '2h', '45m', '0m'."""
    hours, mins = divmod(max(0, minutes), 60)
    if hours:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{mins}m"
