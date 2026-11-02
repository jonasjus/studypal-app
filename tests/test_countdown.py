from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from studypal.core.logic.countdown import Urgency, countdown, describe_days, format_span, urgency

NOW = datetime(2026, 11, 20, 12, 0)


@pytest.mark.parametrize(
    ("span", "text"),
    [
        (timedelta(days=3, hours=4, minutes=59), "3d 4h"),
        (timedelta(days=2), "2d"),
        (timedelta(hours=5, minutes=20), "5h 20m"),
        (timedelta(hours=1), "1h"),
        (timedelta(minutes=12, seconds=59), "12m"),
        (timedelta(seconds=30), "<1m"),
        (timedelta(days=-1, hours=-2), "1d 2h"),  # sign is the caller's business
    ],
)
def test_format_span(span: timedelta, text: str) -> None:
    assert format_span(span) == text


def test_countdown_future_now_and_overdue() -> None:
    assert countdown(NOW + timedelta(days=3, hours=4), NOW) == "in 3d 4h"
    assert countdown(NOW + timedelta(seconds=20), NOW) == "now"
    assert countdown(NOW - timedelta(hours=2, minutes=5), NOW) == "overdue by 2h 5m"


@pytest.mark.parametrize(
    ("left", "expected"),
    [
        (timedelta(hours=-1), Urgency.OVERDUE),
        (timedelta(0), Urgency.OVERDUE),
        (timedelta(minutes=1), Urgency.CRITICAL),
        (timedelta(hours=47, minutes=59), Urgency.CRITICAL),
        (timedelta(hours=48), Urgency.SOON),
        (timedelta(days=6, hours=23), Urgency.SOON),
        (timedelta(days=7), Urgency.LATER),
    ],
)
def test_urgency_boundaries(left: timedelta, expected: Urgency) -> None:
    assert urgency(NOW + left, NOW) is expected


def test_done_wins_over_overdue() -> None:
    assert urgency(NOW - timedelta(days=3), NOW, done=True) is Urgency.DONE


@pytest.mark.parametrize(
    ("n", "text"), [(0, "today"), (1, "tomorrow"), (-1, "yesterday"), (12, "in 12 days"), (-3, "3 days ago")]
)
def test_describe_days(n: int, text: str) -> None:
    assert describe_days(n) == text
