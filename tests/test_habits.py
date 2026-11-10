from __future__ import annotations

from datetime import date, datetime, timedelta

from studypal.core.logic.habits import HEAT_WEEKS, WEEKS, habits
from studypal.core.models import Session, Todo

TODAY = date(2026, 11, 10)  # a Tuesday


def s(days_ago: int, minutes: int, hour: int = 10, minute: int = 0, course_id: int | None = 1) -> Session:
    start = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).replace(hour=hour, minute=minute)
    return Session(course_id=course_id, started_at=start, minutes=minutes, project_id=None if course_id else 7)


def test_nothing_logged() -> None:
    h = habits([], [], TODAY)
    assert h.total_minutes == 0 and h.current_streak == 0 and h.average_session == 0
    assert len(h.weeks) == WEEKS and h.days[0][0].weekday() == 0 and h.days[-1][0] == TODAY
    assert len(h.days) == 7 * (HEAT_WEEKS - 1) + 2  # full weeks, then this week's Monday and Tuesday


def test_totals_weeks_and_fair_week_comparison() -> None:
    h = habits([s(0, 60), s(1, 30), s(7, 45), s(8, 15), s(5, 100)], [], TODAY)  # 5 days ago: last Thursday
    assert h.total_minutes == 250 and h.sessions == 5
    assert h.this_week == 90
    assert h.last_week_so_far == 60  # last Monday and Tuesday only
    assert h.weeks[-1][1] == 90 and h.weeks[-2][1] == 160
    assert h.average_session == 50 and h.longest_session == 100


def test_streak_survives_until_a_day_is_missed() -> None:
    h = habits([s(1, 30), s(2, 30), s(3, 30), s(6, 30)], [], TODAY)  # not yet today
    assert h.current_streak == 3 and h.longest_streak == 3
    assert habits([s(2, 30), s(3, 30)], [], TODAY).current_streak == 0  # yesterday was missed


def test_minutes_split_over_the_hours_they_span() -> None:
    h = habits([s(0, 90, hour=9, minute=30)], [], TODAY)
    assert h.by_hour[9] == 30 and h.by_hour[10] == 60 and sum(h.by_hour) == 90
    late = habits([s(1, 40, hour=23, minute=40)], [], TODAY)
    assert late.by_hour[23] == 20 and late.by_hour[0] == 20


def test_weekdays_follow_the_week_start() -> None:
    h = habits([s(0, 30)], [], TODAY, week_start=6)  # weeks start on Sunday; today is Tuesday
    assert h.by_weekday[2] == 30


def test_subjects_and_research() -> None:
    h = habits([s(0, 30, course_id=2), s(1, 90, course_id=1), s(2, 20, course_id=None)], [], TODAY)
    assert h.by_course == [(1, 90), (2, 30)] and h.research_minutes == 20


def test_to_dos() -> None:
    todos = [Todo(TODAY, "a", done=True), Todo(TODAY, "b"), Todo(TODAY - timedelta(days=20), "c", done=True),
             Todo(TODAY + timedelta(days=1), "planned")]  # future days don't count yet
    h = habits([], todos, TODAY)
    assert (h.todos_done_week, h.todos_week) == (1, 2)
    assert (h.todos_done_month, h.todos_month) == (2, 3)
