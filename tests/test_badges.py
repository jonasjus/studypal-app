from __future__ import annotations

from datetime import date, datetime, timedelta

from studypal.core.logic.badges import KINDS, badges
from studypal.core.models import Course, Session, Topic, TopicStatus

COURSE = Course("Machine Learning", "ML101", cram_start=date(2026, 11, 1), exam_date=date(2026, 12, 1), id=1)


def session(day: date, minutes: int = 30, hour: int = 14, course_id: int | None = 1, project_id: int | None = None) -> Session:
    return Session(course_id=course_id, started_at=datetime.combine(day, datetime.min.time()).replace(hour=hour),
                   minutes=minutes, project_id=project_id)


def by_id(sessions=(), topics=(), courses=(COURSE,)):
    return {b.kind.id: b for b in badges(sessions, topics, courses)}


def test_nothing_earned_without_study() -> None:
    got = by_id()
    assert len(got) == len(KINDS) and not any(b.earned for b in got.values())


def test_first_session_and_hours_know_when_they_were_earned() -> None:
    d = date(2026, 11, 2)
    got = by_id([session(d + timedelta(days=i), minutes=180) for i in range(5)])  # 3h a day
    assert got["first_session"].earned_on == d
    assert got["hours_10"].earned_on == d + timedelta(days=3)  # 12h after the fourth day
    assert not got["hours_50"].earned and got["hours_50"].current == 15


def test_streaks_need_days_in_a_row() -> None:
    d = date(2026, 11, 2)
    gap = [session(d), session(d + timedelta(days=1)), session(d + timedelta(days=3))]
    assert not by_id(gap)["streak_3"].earned and by_id(gap)["streak_3"].current == 2
    row = gap + [session(d + timedelta(days=2))]
    got = by_id(row)
    assert got["streak_3"].earned_on == d + timedelta(days=2)
    assert got["streak_7"].current == 4 and not got["streak_7"].earned


def test_one_off_badges() -> None:
    sat = date(2026, 11, 7)
    got = by_id([
        session(sat, minutes=95, hour=6),  # deep focus, early bird
        session(sat + timedelta(days=1), hour=23),  # Sunday: weekend, night owl
        session(sat, course_id=2), session(sat, course_id=3),  # three subjects on Saturday
        session(sat, minutes=200, course_id=None, project_id=1),  # research counts towards time: 5h+ that day
    ])
    for key in ("deep_focus", "early_bird", "night_owl", "weekend", "all_rounder", "marathon"):
        assert got[key].earned, key
    assert got["weekend"].earned_on == sat + timedelta(days=1)


def test_topic_badges() -> None:
    confident = [Topic(1, f"T{i}", status=TopicStatus.CONFIDENT, id=i) for i in range(10)]
    got = by_id(topics=confident)
    assert got["confident_10"].earned and got["confident_10"].earned_on is None
    assert got["subject_ready"].earned
    almost = confident[:9] + [Topic(1, "Last", status=TopicStatus.IN_PROGRESS, id=99)]
    got = by_id(topics=almost)
    assert not got["confident_10"].earned and got["confident_10"].current == 9
    assert not got["subject_ready"].earned
