from __future__ import annotations

from datetime import date, datetime

import pytest

from studypal.core.logic.stats import days_since, format_minutes, is_stale, minutes_between, minutes_per_day, week_bounds
from studypal.core.models import Session, Topic


@pytest.mark.parametrize(
    ("today", "week_start", "first"),
    [
        (date(2026, 11, 18), 0, date(2026, 11, 16)),  # Wednesday -> Monday
        (date(2026, 11, 16), 0, date(2026, 11, 16)),  # Monday itself
        (date(2026, 11, 22), 0, date(2026, 11, 16)),  # Sunday belongs to the week before
        (date(2026, 11, 18), 6, date(2026, 11, 15)),  # Sunday-start weeks
    ],
)
def test_week_bounds(today: date, week_start: int, first: date) -> None:
    start, end = week_bounds(today, week_start)
    assert start == first and (end - start).days == 7


def test_minutes_per_day_buckets_by_start_day() -> None:
    sessions = [
        Session(1, datetime(2026, 11, 16, 9, 0), 60),
        Session(2, datetime(2026, 11, 16, 20, 0), 30),
        Session(1, datetime(2026, 11, 18, 23, 30), 90),  # runs past midnight, counts on the 18th
        Session(1, datetime(2026, 11, 23, 9, 0), 45),  # next week
    ]
    assert minutes_per_day(sessions, date(2026, 11, 16)) == [90, 0, 90, 0, 0, 0, 0]
    week = (datetime(2026, 11, 16), datetime(2026, 11, 23))
    assert minutes_between(sessions, *week) == 180
    assert minutes_between(sessions, *week, course_id=2) == 30


def test_stale_topics() -> None:
    today = date(2026, 11, 20)
    assert is_stale(Topic(1, "a", last_studied=date(2026, 11, 13)), today, 7)
    assert not is_stale(Topic(1, "b", last_studied=date(2026, 11, 14)), today, 7)
    assert not is_stale(Topic(1, "never"), today, 7)  # never studied is shown as "never", not stale
    assert days_since(None, today) is None


@pytest.mark.parametrize(("m", "text"), [(0, "0m"), (45, "45m"), (60, "1h"), (90, "1h 30m"), (-5, "0m")])
def test_format_minutes(m: int, text: str) -> None:
    assert format_minutes(m) == text
