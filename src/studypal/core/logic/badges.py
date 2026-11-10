"""Collectible badges, earned by studying.

Badges aren't stored. They're worked out from what's already saved (logged study time, for subjects and
research projects alike, and topic statuses), so time logged before badges existed counts, and badges
follow you to every computer your data syncs to. Badges that come from study time also know the day
they were earned. Badges that come from topic statuses don't, because the app doesn't record when a
status changed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from ..models import Course, Session, Topic, TopicStatus


@dataclass(frozen=True)
class BadgeKind:
    id: str
    name: str
    description: str
    icon: str
    tier: str  # "bronze", "silver" or "gold" for steps up a ladder, "" for the one-offs


@dataclass(frozen=True)
class Badge:
    kind: BadgeKind
    current: int  # progress towards it, in the badge's own unit
    target: int
    earned_on: date | None = None  # when known
    earned_flag: bool = False  # earned, for badges that can't say when

    @property
    def earned(self) -> bool:
        return self.earned_on is not None or self.earned_flag


# In the order they're shown: roughly from the first ones you'll get to the hardest.
KINDS = [
    BadgeKind("first_session", "First step", "Log your first study session.", "🌱", ""),
    BadgeKind("hours_10", "Ten hours", "Study for 10 hours in total.", "⏱️", "bronze"),
    BadgeKind("hours_50", "Fifty hours", "Study for 50 hours in total.", "⏱️", "silver"),
    BadgeKind("hours_100", "Hundred hours", "Study for 100 hours in total.", "⏱️", "gold"),
    BadgeKind("streak_3", "On a roll", "Study 3 days in a row.", "🔥", "bronze"),
    BadgeKind("streak_7", "Week streak", "Study 7 days in a row.", "🔥", "silver"),
    BadgeKind("streak_30", "Unstoppable", "Study 30 days in a row.", "🔥", "gold"),
    BadgeKind("deep_focus", "Deep focus", "Study for 90 minutes in one session.", "🎯", ""),
    BadgeKind("marathon", "Marathon", "Study for 5 hours in one day.", "🏃", ""),
    BadgeKind("early_bird", "Early bird", "Start a session between 5 and 7 in the morning.", "🌅", ""),
    BadgeKind("night_owl", "Night owl", "Start a session between 11 at night and 4 in the morning.", "🦉", ""),
    BadgeKind("weekend", "Weekend warrior", "Study on both the Saturday and the Sunday of a weekend.", "🏕️", ""),
    BadgeKind("all_rounder", "All-rounder", "Study 3 different subjects in one day.", "🎨", ""),
    BadgeKind("confident_10", "Know-it-all", "Mark 10 topics as Confident.", "💡", ""),
    BadgeKind("subject_ready", "Exam ready", "Get every topic in a subject to Reviewed or Confident.", "🎓", ""),
]
BY_ID = {k.id: k for k in KINDS}

DEEP_FOCUS_MINUTES = 90
MARATHON_MINUTES = 5 * 60
EARLY_BIRD_HOURS = range(5, 7)
NIGHT_OWL_HOURS = (23, 0, 1, 2, 3)


def _first_day_reaching(days: list[date], values: Callable[[date], int], target: int,
                        cumulative: bool = False) -> tuple[int, date | None]:
    """Walk the days in order: the best (or, if cumulative, the running total) value reached, and the
    first day it reached `target`."""
    best, total, reached = 0, 0, None
    for d in days:
        value = values(d)
        total = total + value if cumulative else value
        best = max(best, total)
        if reached is None and total >= target:
            reached = d
    return best, reached


def streak_runs(days: list[date]) -> list[tuple[date, int]]:
    """For each day studied (in order), how many days in a row it ends."""
    out, run, prev = [], 0, None
    for d in days:
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        out.append((d, run))
        prev = d
    return out


def badges(sessions: Iterable[Session], topics: Iterable[Topic], courses: Iterable[Course]) -> list[Badge]:
    """Every badge, earned or not, with progress towards it. `sessions` are course and research sessions."""
    sessions = sorted(sessions, key=lambda s: s.started_at)
    topics, courses = list(topics), list(courses)
    minutes_on: dict[date, int] = defaultdict(int)
    subjects_on: dict[date, set[int]] = defaultdict(set)
    for s in sessions:
        minutes_on[s.started_at.date()] += s.minutes
        if s.course_id is not None:
            subjects_on[s.started_at.date()].add(s.course_id)
    days = sorted(minutes_on)
    out: dict[str, Badge] = {}

    first = sessions[0].started_at.date() if sessions else None
    out["first_session"] = Badge(BY_ID["first_session"], min(1, len(sessions)), 1, first)

    for hours in (10, 50, 100):
        total, reached = _first_day_reaching(days, lambda d: minutes_on[d], hours * 60, cumulative=True)
        out[f"hours_{hours}"] = Badge(BY_ID[f"hours_{hours}"], total // 60, hours, reached)

    runs = streak_runs(days)
    for n in (3, 7, 30):
        best = max((r for _, r in runs), default=0)
        reached = next((d for d, r in runs if r >= n), None)
        out[f"streak_{n}"] = Badge(BY_ID[f"streak_{n}"], min(best, n), n, reached)

    focus = next((s.started_at.date() for s in sessions if s.minutes >= DEEP_FOCUS_MINUTES), None)
    longest = max((s.minutes for s in sessions), default=0)
    out["deep_focus"] = Badge(BY_ID["deep_focus"], min(longest, DEEP_FOCUS_MINUTES), DEEP_FOCUS_MINUTES, focus)

    best_day, marathon = _first_day_reaching(days, lambda d: minutes_on[d], MARATHON_MINUTES)
    out["marathon"] = Badge(BY_ID["marathon"], min(best_day, MARATHON_MINUTES) // 60, MARATHON_MINUTES // 60, marathon)

    early = next((s.started_at.date() for s in sessions if s.started_at.hour in EARLY_BIRD_HOURS), None)
    out["early_bird"] = Badge(BY_ID["early_bird"], int(early is not None), 1, early)
    owl = next((s.started_at.date() for s in sessions if s.started_at.hour in NIGHT_OWL_HOURS), None)
    out["night_owl"] = Badge(BY_ID["night_owl"], int(owl is not None), 1, owl)

    studied = set(days)
    weekend = next((d + timedelta(days=1) for d in days if d.weekday() == 5 and d + timedelta(days=1) in studied), None)
    out["weekend"] = Badge(BY_ID["weekend"], int(weekend is not None), 1, weekend)

    most, rounder = _first_day_reaching(days, lambda d: len(subjects_on[d]), 3)
    out["all_rounder"] = Badge(BY_ID["all_rounder"], min(most, 3), 3, rounder)

    confident = sum(1 for t in topics if t.status is TopicStatus.CONFIDENT)
    out["confident_10"] = Badge(BY_ID["confident_10"], min(confident, 10), 10, earned_flag=confident >= 10)

    by_course: dict[int, list[Topic]] = defaultdict(list)
    for t in topics:
        by_course[t.course_id].append(t)
    ready = any(by_course[c.id] and all(t.status.is_done for t in by_course[c.id]) for c in courses if c.id is not None)
    out["subject_ready"] = Badge(BY_ID["subject_ready"], int(ready), 1, earned_flag=ready)

    return [out[k.id] for k in KINDS]
