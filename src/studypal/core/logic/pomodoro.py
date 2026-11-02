"""Pomodoro runs: focus blocks with breaks, where every finished focus block is logged as a session.

The run is just saved state (which phase, when it started), so nothing has to keep running in the
background: whoever looks next (the TUI, any `study` command, the `study notify` job) calls
`advance`, which works out what has happened since and returns the focus blocks that finished.

After a break ends the run waits in READY until you start the next focus block. Starting focus
automatically would log study time while you're away from the desk.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum


class PomoPhase(StrEnum):
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"
    READY = "ready"  # break is over; waiting for you to start the next focus block

    @property
    def label(self) -> str:
        return {"focus": "Focus", "short_break": "Short break", "long_break": "Long break", "ready": "Ready"}[self.value]

    @property
    def is_break(self) -> bool:
        return self in (PomoPhase.SHORT_BREAK, PomoPhase.LONG_BREAK)


@dataclass(frozen=True)
class PomodoroSettings:
    focus: timedelta = timedelta(minutes=25)
    short_break: timedelta = timedelta(minutes=5)
    long_break: timedelta = timedelta(minutes=15)
    long_break_every: int = 4  # a long break after every 4th focus block


@dataclass(frozen=True)
class PomodoroRun:
    course_id: int
    phase: PomoPhase
    phase_started_at: datetime  # moved forward by the length of any pause, so phase end = start + length
    block_started_at: datetime  # when the current focus block really began; the logged session starts here
    topic_id: int | None = None
    completed: int = 0  # focus blocks finished in this run
    paused_at: datetime | None = None
    note: str = ""

    @property
    def paused(self) -> bool:
        return self.paused_at is not None


@dataclass(frozen=True)
class FinishedBlock:
    """A stretch of focus to log as a study session."""

    started_at: datetime
    minutes: int
    number: int  # 1 for the run's first focus block, and so on
    partial: bool = False  # stopped before the block was over


def phase_length(phase: PomoPhase, settings: PomodoroSettings) -> timedelta | None:
    return {
        PomoPhase.FOCUS: settings.focus,
        PomoPhase.SHORT_BREAK: settings.short_break,
        PomoPhase.LONG_BREAK: settings.long_break,
        PomoPhase.READY: None,
    }[phase]


def remaining(run: PomodoroRun, now: datetime, settings: PomodoroSettings) -> timedelta | None:
    """Time left in the current phase (frozen while paused). None while READY."""
    length = phase_length(run.phase, settings)
    if length is None:
        return None
    end = run.phase_started_at + length
    return max(timedelta(0), end - (run.paused_at or now))


def start(course_id: int, now: datetime, topic_id: int | None = None, note: str = "") -> PomodoroRun:
    now = now.replace(microsecond=0)
    return PomodoroRun(course_id=course_id, topic_id=topic_id, phase=PomoPhase.FOCUS,
                       phase_started_at=now, block_started_at=now, note=note)


def advance(run: PomodoroRun, now: datetime, settings: PomodoroSettings) -> tuple[PomodoroRun, list[FinishedBlock]]:
    """Move the run forward to `now`, returning every focus block that finished on the way."""
    if run.paused:
        return run, []
    finished: list[FinishedBlock] = []
    while True:
        length = phase_length(run.phase, settings)
        if length is None:
            break
        end = run.phase_started_at + length
        if now < end:
            break
        if run.phase is PomoPhase.FOCUS:
            number = run.completed + 1
            finished.append(FinishedBlock(run.block_started_at, int(length.total_seconds() // 60), number))
            next_phase = PomoPhase.LONG_BREAK if number % settings.long_break_every == 0 else PomoPhase.SHORT_BREAK
            run = replace(run, phase=next_phase, phase_started_at=end, completed=number)
        else:
            run = replace(run, phase=PomoPhase.READY, phase_started_at=end)
    return run, finished


def next_focus(run: PomodoroRun, now: datetime) -> PomodoroRun:
    """Start the next focus block now: after a break, or to skip what's left of one."""
    if run.phase is PomoPhase.FOCUS:
        return run
    now = now.replace(microsecond=0)
    return replace(run, phase=PomoPhase.FOCUS, phase_started_at=now, block_started_at=now, paused_at=None)


def pause(run: PomodoroRun, now: datetime) -> PomodoroRun:
    if run.paused or run.phase is PomoPhase.READY:
        return run
    return replace(run, paused_at=now.replace(microsecond=0))


def resume(run: PomodoroRun, now: datetime) -> PomodoroRun:
    if not run.paused:
        return run
    gap = now.replace(microsecond=0) - run.paused_at  # type: ignore[operator]
    return replace(run, phase_started_at=run.phase_started_at + gap, paused_at=None)


def stop(run: PomodoroRun, now: datetime, settings: PomodoroSettings) -> list[FinishedBlock]:
    """End the run. Returns finished blocks, plus the focus done so far if stopped mid-block (a minute or more)."""
    run, finished = advance(run, now, settings)
    if run.phase is PomoPhase.FOCUS:
        done = (run.paused_at or now) - run.phase_started_at
        minutes = int(done.total_seconds() // 60)
        if minutes >= 1:
            finished.append(FinishedBlock(run.block_started_at, minutes, run.completed + 1, partial=True))
    return finished
