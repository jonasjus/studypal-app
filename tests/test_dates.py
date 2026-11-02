from __future__ import annotations

from datetime import date, datetime, time

import pytest

from studypal.core.logic.dates import DateParseError, parse_date, parse_datetime

TODAY = date(2026, 11, 18)  # a Wednesday
NOW = datetime(2026, 11, 18, 14, 30)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-12-10", date(2026, 12, 10)),
        ("today", TODAY),
        ("Tomorrow", date(2026, 11, 19)),
        ("+3d", date(2026, 11, 21)),
        ("+2w", date(2026, 12, 2)),
        ("-5d", date(2026, 11, 13)),
        ("fri", date(2026, 11, 20)),
        ("friday", date(2026, 11, 20)),
        ("wed", date(2026, 11, 25)),  # never today: next week's Wednesday
        ("mon", date(2026, 11, 23)),
        ("10.12.2026", date(2026, 12, 10)),  # day.month.year
        ("10-12-2026", date(2026, 12, 10)),
        ("10/12/2026", date(2026, 12, 10)),
        ("1.2.27", date(2027, 2, 1)),  # two-digit year
        ("10.12", date(2026, 12, 10)),  # no year: the next 10 December
        ("10.12.", date(2026, 12, 10)),  # Norwegian-style trailing dot
        ("15.1", date(2027, 1, 15)),  # already passed this year -> next year
        ("18.11", TODAY),
        ("12-10", date(2027, 10, 12)),  # day first: 12 October, which has passed -> next year
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize("bad", ["soon", "2026-13-01", "30.2", "31.04.2026", "10.13.2026", "fr", "+3x"])
def test_unreadable_dates_explain_what_works(bad: str) -> None:
    with pytest.raises(DateParseError):
        parse_date(bad, TODAY)


def test_parse_datetime() -> None:
    assert parse_datetime("fri 23:59", NOW, time(9, 0)) == datetime(2026, 11, 20, 23, 59)
    assert parse_datetime("2026-12-10 9:00", NOW, time(23, 59)) == datetime(2026, 12, 10, 9, 0)
    assert parse_datetime("10.12.2026 09:00", NOW, time(23, 59)) == datetime(2026, 12, 10, 9, 0)
    assert parse_datetime("2026-12-10T09:00", NOW, time(23, 59)) == datetime(2026, 12, 10, 9, 0)
    assert parse_datetime("tomorrow", NOW, time(23, 59)) == datetime(2026, 11, 19, 23, 59)
    with pytest.raises(DateParseError, match="time of day"):
        parse_datetime("fri 25:00", NOW, time(9, 0))


def test_dates_are_shown_day_month_year() -> None:
    from studypal.core.logic.dates import format_date, format_datetime

    assert format_date(date(2026, 12, 1)) == "01.12.2026"
    assert format_datetime(datetime(2026, 12, 10, 9, 5)) == "10.12.2026 09:05"
    # What's shown can be typed straight back in.
    assert parse_datetime(format_datetime(datetime(2026, 12, 10, 9, 5)), NOW, time(0, 0)) == datetime(2026, 12, 10, 9, 5)
