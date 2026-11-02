"""Which deadline alerts are due right now, without ever repeating one.

Each threshold ("7d", "2d", "1d", "morning") fires once per deadline. If several thresholds
have passed since the last check (the laptop was asleep, or the deadline was added late),
only the most urgent one is sent and the rest are marked as sent with it, so you get one
alert instead of a burst. Deadlines that are done or already past send nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from ..config import Threshold
from ..models import Deadline
from .countdown import countdown

SentKey = tuple[int, str, datetime]  # (deadline id, threshold key, due_at at the time it was sent)


@dataclass(frozen=True)
class Alert:
    deadline: Deadline
    threshold: str  # the threshold the alert is for
    covers: tuple[str, ...]  # every threshold this alert settles (includes `threshold`)
    title: str
    body: str


def trigger_time(due: datetime, threshold: Threshold, morning_time: time) -> datetime | None:
    """When a threshold fires. The morning-of alert is skipped when the deadline is before that morning time."""
    if threshold.is_morning:
        morning = datetime.combine(due.date(), morning_time)
        return morning if morning < due else None
    return due - threshold.before  # type: ignore[operator]


def alert_text(deadline: Deadline, now: datetime, course_code: str | None = None) -> tuple[str, str]:
    """('ML101 exam is due in 6d 23h', 'Exam · Thu 10 Dec at 09:00')."""
    due = deadline.due_at
    name = deadline.title
    if course_code and course_code.lower() not in name.lower():
        name = f"{course_code}: {name}"
    if due.date() == now.date():
        when = f"today at {due:%H:%M}"
    elif due.date() == (now + timedelta(days=1)).date():
        when = f"tomorrow at {due:%H:%M}"
    else:
        when = countdown(due, now)
    return f"{name} is due {when}", f"{deadline.kind.value.capitalize()} · {due:%a} {due.day} {due:%b} at {due:%H:%M}"


def pending_alerts(
    deadlines: Iterable[Deadline],
    now: datetime,
    thresholds: Iterable[Threshold],
    morning_time: time,
    sent: set[SentKey],
    course_codes: Mapping[int, str] | None = None,
) -> list[Alert]:
    thresholds = list(thresholds)
    codes = course_codes or {}
    alerts: list[Alert] = []
    for d in deadlines:
        if d.done or d.id is None or d.due_at <= now:
            continue
        passed: list[tuple[datetime, Threshold]] = []
        for th in thresholds:
            at = trigger_time(d.due_at, th, morning_time)
            if at is not None and at <= now and (d.id, th.key, d.due_at) not in sent:
                passed.append((at, th))
        if not passed:
            continue
        _, closest = max(passed, key=lambda p: p[0])  # the latest trigger is the most urgent
        title, body = alert_text(d, now, codes.get(d.course_id) if d.course_id is not None else None)
        alerts.append(Alert(d, closest.key, tuple(th.key for _, th in passed), title, body))
    return sorted(alerts, key=lambda a: a.deadline.due_at)


def banner_groups(deadlines: Iterable[Deadline], now: datetime) -> tuple[list[Deadline], list[Deadline]]:
    """(overdue, due within 24 hours): what the TUI keeps in its banner. Done deadlines are left out."""
    open_ = [d for d in deadlines if not d.done]
    overdue = sorted((d for d in open_ if d.due_at <= now), key=lambda d: d.due_at)
    soon = sorted((d for d in open_ if now < d.due_at <= now + timedelta(hours=24)), key=lambda d: d.due_at)
    return overdue, soon


def within(deadlines: Iterable[Deadline], now: datetime, window: timedelta) -> list[Deadline]:
    """Open deadlines that are overdue or due within `window` (for in-app toasts and banners)."""
    return [d for d in deadlines if not d.done and d.due_at - now < window]
