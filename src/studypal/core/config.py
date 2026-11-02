"""Settings from config.toml, with defaults for everything.

Example ~/.config/study/config.toml:

    [notifications]
    thresholds = ["7d", "2d", "1d", "morning"]   # "morning" = morning of the due day
    morning_time = "08:00"
    toast_window = "2d"                           # in-app toasts for deadlines this close

    [pomodoro]
    focus = "25m"
    short_break = "5m"
    long_break = "15m"
    long_break_every = 4                          # long break after every 4th focus block

    [sync]
    pull_on_start = true                          # with git sync set up (study sync --init)

    [study]
    week_start = "monday"
    stale_after_days = 7                          # highlight topics not studied for this long
    default_exam_time = "09:00"                   # time used for a course's exam deadline
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import time, timedelta
from pathlib import Path

from . import paths
from .logic.pomodoro import PomodoroSettings

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MORNING = "morning"
_DURATION = re.compile(r"^\s*(\d+)\s*([dhm])\s*$", re.IGNORECASE)


class ConfigError(ValueError):
    """The config file has a value study can't use. The message says which and why."""


@dataclass(frozen=True)
class Threshold:
    """When to warn about a deadline: a fixed time before it, or the morning of the due day."""

    key: str
    before: timedelta | None  # None means "morning of"

    @property
    def is_morning(self) -> bool:
        return self.before is None


@dataclass(frozen=True)
class Config:
    thresholds: tuple[Threshold, ...]
    morning_time: time = time(8, 0)
    toast_window: timedelta = timedelta(days=2)
    week_start: int = 0  # 0 = Monday
    stale_after_days: int = 7
    default_exam_time: time = time(9, 0)
    pomodoro: PomodoroSettings = field(default_factory=PomodoroSettings)
    pull_on_start: bool = True


def parse_duration(text: str) -> timedelta:
    """'7d', '48h', '30m' -> timedelta."""
    m = _DURATION.match(text)
    if not m:
        raise ConfigError(f"{text!r} isn't a duration. Use a number followed by d, h or m, like \"2d\".")
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]


def parse_threshold(text: str) -> Threshold:
    key = text.strip().lower()
    if key == MORNING:
        return Threshold(MORNING, None)
    return Threshold(key, parse_duration(key))


def parse_time(text: str, name: str) -> time:
    try:
        return time.fromisoformat(text.strip())
    except ValueError:
        raise ConfigError(f"{name} = {text!r} isn't a time. Use 24-hour HH:MM, like \"08:00\".") from None


DEFAULT_THRESHOLDS: tuple[Threshold, ...] = tuple(parse_threshold(t) for t in ("7d", "2d", "1d", MORNING))


def default_config() -> Config:
    return Config(thresholds=DEFAULT_THRESHOLDS)


def _pomodoro(section: dict, default: PomodoroSettings) -> PomodoroSettings:
    def length(key: str, fallback: timedelta) -> timedelta:
        if key not in section:
            return fallback
        value = parse_duration(str(section[key]))
        if value < timedelta(minutes=1):
            raise ConfigError(f"pomodoro.{key} must be at least a minute.")
        return value

    every = section.get("long_break_every", default.long_break_every)
    if not isinstance(every, int) or every < 1:
        raise ConfigError("pomodoro.long_break_every must be a whole number, 1 or more.")
    return PomodoroSettings(
        focus=length("focus", default.focus),
        short_break=length("short_break", default.short_break),
        long_break=length("long_break", default.long_break),
        long_break_every=every,
    )


def _bool(section: dict, key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false.")
    return value


def from_dict(data: dict) -> Config:
    notif = data.get("notifications", {}) or {}
    study = data.get("study", {}) or {}
    cfg = default_config()

    thresholds = cfg.thresholds
    if "thresholds" in notif:
        raw = notif["thresholds"]
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise ConfigError('notifications.thresholds must be a list of strings, like ["7d", "1d", "morning"].')
        thresholds = tuple(dict.fromkeys(parse_threshold(x) for x in raw))  # drop duplicates, keep order

    week_start = cfg.week_start
    if "week_start" in study:
        name = str(study["week_start"]).strip().lower()
        if name not in WEEKDAYS:
            raise ConfigError(f"study.week_start = {study['week_start']!r} isn't a weekday name.")
        week_start = WEEKDAYS.index(name)

    stale = study.get("stale_after_days", cfg.stale_after_days)
    if not isinstance(stale, int) or stale < 1:
        raise ConfigError("study.stale_after_days must be a whole number of days, 1 or more.")

    return Config(
        thresholds=thresholds,
        morning_time=parse_time(notif["morning_time"], "notifications.morning_time") if "morning_time" in notif else cfg.morning_time,
        toast_window=parse_duration(notif["toast_window"]) if "toast_window" in notif else cfg.toast_window,
        week_start=week_start,
        stale_after_days=stale,
        default_exam_time=parse_time(study["default_exam_time"], "study.default_exam_time") if "default_exam_time" in study else cfg.default_exam_time,
        pomodoro=_pomodoro(data.get("pomodoro", {}) or {}, cfg.pomodoro),
        pull_on_start=_bool(data.get("sync", {}) or {}, "pull_on_start", cfg.pull_on_start),
    )


def load(path: Path | None = None) -> Config:
    """Read the config file if there is one; otherwise use the defaults."""
    path = path or paths.config_path()
    if not path.exists():
        return default_config()
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} isn't valid TOML: {e}") from None
    return from_dict(data)
