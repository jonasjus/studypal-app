"""Countdown text ("in 3d 4h") and how urgent a deadline is."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import StrEnum

CRITICAL_WINDOW = timedelta(hours=48)  # shown red
SOON_WINDOW = timedelta(days=7)  # shown yellow


class Urgency(StrEnum):
    DONE = "done"
    OVERDUE = "overdue"
    CRITICAL = "critical"  # under 48 hours
    SOON = "soon"  # under 7 days
    LATER = "later"


def urgency(due: datetime, now: datetime, done: bool = False) -> Urgency:
    if done:
        return Urgency.DONE
    left = due - now
    if left <= timedelta(0):
        return Urgency.OVERDUE
    if left < CRITICAL_WINDOW:
        return Urgency.CRITICAL
    if left < SOON_WINDOW:
        return Urgency.SOON
    return Urgency.LATER


def format_span(span: timedelta) -> str:
    """The two largest units, rounded down: '3d 4h', '5h 20m', '12m', '<1m'."""
    minutes = int(abs(span).total_seconds() // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{mins}m" if mins else "<1m"


def countdown(due: datetime, now: datetime) -> str:
    """'in 3d 4h', 'now', or 'overdue by 2h 5m'."""
    left = due - now
    if abs(left) < timedelta(minutes=1):
        return "now"
    if left > timedelta(0):
        return f"in {format_span(left)}"
    return f"overdue by {format_span(left)}"


def days_until(target: date, today: date) -> int:
    return (target - today).days


def describe_days(n: int) -> str:
    """Whole days until something: 'today', 'tomorrow', 'in 12 days', 'yesterday', '3 days ago'."""
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n == -1:
        return "yesterday"
    return f"in {n} days" if n > 0 else f"{-n} days ago"
