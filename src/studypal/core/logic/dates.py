"""Reading dates and times the way you'd type them on the command line.

Dates are day-month-year:
        10.12.2026, 10-12-2026, 10/12/2026, 10.12.26, 10.12 (the next 10 December),
        today, tomorrow, +3d, +2w, -5d (five days ago), mon/monday ... sun (the next one, never today).
        Year-first 2026-12-10 also works, since it can't be mistaken for anything else.
Times:  optional, after a space: "fri 23:59", "10.12.2026 09:00"

Dates are shown the same way: `format_date` / `format_datetime`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_RELATIVE = re.compile(r"^([+-])(\d+)([dw])$")
_DAY_MONTH_YEAR = re.compile(r"^(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}|\d{2})?)?\.?$")
DATE_FORMAT = "%d.%m.%Y"


def format_date(d: date) -> str:
    """10.12.2026"""
    return d.strftime(DATE_FORMAT)


def format_datetime(dt: datetime) -> str:
    """10.12.2026 09:00"""
    return dt.strftime(f"{DATE_FORMAT} %H:%M")


class DateParseError(ValueError):
    pass


def parse_date(text: str, today: date) -> date:
    t = text.strip().lower()
    if t == "today":
        return today
    if t == "tomorrow":
        return today + timedelta(days=1)
    if m := _RELATIVE.match(t):
        n = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
        return today + (timedelta(days=n) if m.group(3) == "d" else timedelta(weeks=n))
    for i, name in enumerate(WEEKDAYS):
        if len(t) >= 3 and name.startswith(t):  # "fri", "friday", "frid"
            ahead = (i - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    if m := _DAY_MONTH_YEAR.match(t):
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            if year:
                return date(int(year) + (2000 if len(year) == 2 else 0), month, day)
            candidate = date(today.year, month, day)
        except ValueError:
            raise DateParseError(f"{text!r} isn't a real date. Dates are day.month.year, like 10.12.2026.") from None
        # Without a year: the next time that date comes round.
        return candidate if candidate >= today else candidate.replace(year=today.year + 1)
    try:
        return date.fromisoformat(t)  # year first: 2026-12-10
    except ValueError:
        raise DateParseError(
            f"Can't read {text!r} as a date. Try 10.12.2026, 10.12, tomorrow, fri or +3d."
        ) from None


def parse_datetime(text: str, now: datetime, default_time: time) -> datetime:
    """A date, optionally followed by HH:MM. Without a time, `default_time` is used."""
    parts = text.strip().rsplit(" ", 1)
    if len(parts) == 2 and re.fullmatch(r"\d{1,2}:\d{2}", parts[1]):
        hours, minutes = map(int, parts[1].split(":"))
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise DateParseError(f"{parts[1]!r} isn't a time of day.")
        return datetime.combine(parse_date(parts[0], now.date()), time(hours, minutes))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text.strip()):
        return datetime.fromisoformat(text.strip())
    return datetime.combine(parse_date(text, now.date()), default_time)


def parse_minutes(text: str) -> int:
    """'90', '90m', '1h30m', '1h 30m', '2h' -> minutes."""
    t = text.strip().lower().replace(" ", "")
    if t.isdigit():
        return int(t)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m(?:in)?)?", t)
    if not m or not (m.group(1) or m.group(2)):
        raise DateParseError(f"Can't read {text!r} as a length of time. Use minutes, like 90, or 1h30m.")
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
