from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from studypal.core import config
from studypal.core.logic import pomodoro as pomo
from studypal.core.logic.pomodoro import PomodoroSettings, PomoPhase
from studypal.core.models import Course, Topic, TopicStatus
from studypal.core.storage import Store, StorageError

S = PomodoroSettings()  # 25 / 5 / 15, long break every 4
T0 = datetime(2026, 11, 16, 9, 0)


def m(n: float) -> timedelta:
    return timedelta(minutes=n)


# ---------- the schedule ----------

def test_focus_runs_on_until_you_take_a_break() -> None:
    run = pomo.start(1, T0)
    assert pomo.remaining(run, T0 + m(24), S) == m(1) and not pomo.focus_done(run, T0 + m(24), S)

    # Time's up, but nothing happens by itself: the clock counts the extra minutes.
    run, done = pomo.advance(run, T0 + m(32), S)
    assert run.phase is PomoPhase.FOCUS and done == []
    assert pomo.focus_done(run, T0 + m(32), S) and pomo.overtime(run, T0 + m(32), S) == m(7)
    assert pomo.remaining(run, T0 + m(32), S) == m(0)

    run, done = pomo.take_break(run, T0 + m(32), S)
    assert run.phase is PomoPhase.SHORT_BREAK and run.completed == 1
    assert done == [pomo.FinishedBlock(T0, 32, 1)]  # the extra minutes count too

    run, done = pomo.advance(run, T0 + m(37), S)
    assert run.phase is PomoPhase.READY and done == []
    assert pomo.remaining(run, T0 + m(38), S) is None


def test_ready_waits_however_long_you_are_away() -> None:
    run, _ = pomo.take_break(pomo.start(1, T0), T0 + m(25), S)
    run, _ = pomo.advance(run, T0 + timedelta(hours=8), S)
    assert run.phase is PomoPhase.READY and run.completed == 1


def test_every_fourth_block_gets_a_long_break() -> None:
    run = pomo.start(1, T0)
    now = T0
    phases = []
    for _ in range(4):
        now += m(25)
        run, _ = pomo.take_break(run, now, S)
        phases.append(run.phase)
        run = pomo.next_focus(run, now)  # skip the break
    assert phases == [PomoPhase.SHORT_BREAK] * 3 + [PomoPhase.LONG_BREAK]
    assert run.completed == 4


def test_a_break_can_be_taken_early() -> None:
    run, done = pomo.take_break(pomo.start(1, T0), T0 + m(18), S)
    assert run.phase is PomoPhase.SHORT_BREAK and done == [pomo.FinishedBlock(T0, 18, 1, partial=True)]
    assert pomo.take_break(run, T0 + m(19), S) == (run, [])  # already on a break


def test_pause_freezes_the_countdown_and_the_overtime() -> None:
    run = pomo.pause(pomo.start(1, T0), T0 + m(10))
    run, done = pomo.advance(run, T0 + m(60), S)
    assert done == [] and pomo.remaining(run, T0 + m(60), S) == m(15)
    run = pomo.resume(run, T0 + m(60))  # paused for 50 minutes
    assert not pomo.focus_done(run, T0 + m(74), S) and pomo.focus_done(run, T0 + m(75), S)
    run = pomo.pause(run, T0 + m(80))
    assert pomo.overtime(run, T0 + m(200), S) == m(5)
    run, done = pomo.take_break(run, T0 + m(200), S)
    assert done == [pomo.FinishedBlock(T0, 30, 1)]  # 30 minutes of focus, starting when it really started


def test_pausing_while_ready_does_nothing() -> None:
    run, _ = pomo.take_break(pomo.start(1, T0), T0 + m(25), S)
    run, _ = pomo.advance(run, T0 + m(40), S)
    assert pomo.pause(run, T0 + m(41)) == run


def test_stopping_mid_focus_logs_the_minutes_done() -> None:
    run = pomo.start(1, T0)
    assert pomo.stop(run, T0 + m(12) + timedelta(seconds=40), S) == [pomo.FinishedBlock(T0, 12, 1, partial=True)]
    assert pomo.stop(run, T0 + timedelta(seconds=50), S) == []  # under a minute: nothing


def test_stopping_after_time_is_up_logs_the_extra_minutes() -> None:
    assert pomo.stop(pomo.start(1, T0), T0 + m(27), S) == [pomo.FinishedBlock(T0, 27, 1)]


def test_stopping_during_a_break_logs_nothing_more() -> None:
    run, _ = pomo.take_break(pomo.start(1, T0), T0 + m(25), S)
    assert pomo.stop(run, T0 + m(27), S) == []


def test_stopping_while_paused_counts_up_to_the_pause() -> None:
    run = pomo.pause(pomo.start(1, T0), T0 + m(8))
    assert pomo.stop(run, T0 + m(90), S) == [pomo.FinishedBlock(T0, 8, 1, partial=True)]


def test_settings_come_from_config(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[pomodoro]\nfocus = "50m"\nshort_break = "10m"\nlong_break = "30m"\nlong_break_every = 2\n')
    s = config.load(path).pomodoro
    assert (s.focus, s.short_break, s.long_break, s.long_break_every) == (m(50), m(10), m(30), 2)
    path.write_text('[pomodoro]\nfocus = "0m"\n')
    with pytest.raises(config.ConfigError, match="at least a minute"):
        config.load(path)


# ---------- storage: automatic logging ----------

@pytest.fixture
def course(store: Store) -> Course:
    return store.add_course(Course("Machine Learning", "ML101", date(2026, 11, 1), date(2026, 12, 10)))


def test_taking_a_break_logs_the_block_once(db_file, store: Store, course: Course) -> None:
    topic = store.add_topic(Topic(course.id, "Kernels"))
    store.start_pomodoro(course.id, topic.id, now=T0, note="chapter 6")
    store.close()

    with Store(db_file) as later:
        run, logged = later.settle_pomodoro(T0 + m(26), S)
        assert run.phase is PomoPhase.FOCUS and logged == []  # still going: nothing logged yet
        run, logged = later.pomodoro_break(T0 + m(31), S)
        assert run.phase is PomoPhase.SHORT_BREAK
        assert [(s.minutes, s.note) for s in logged] == [(31, "Pomodoro 1 · chapter 6")]
        assert later.pomodoro_break(T0 + m(32), S)[1] == []  # not logged twice
        t = later.get_topic(topic.id)
        assert t.last_studied == T0.date() and t.status is TopicStatus.IN_PROGRESS


def test_next_pause_resume_and_stop_through_storage(store: Store, course: Course) -> None:
    store.start_pomodoro(course.id, now=T0)
    run, logged = store.pomodoro_break(T0 + m(27), S)
    run, _ = store.pomodoro_next(T0 + m(29), S)  # skip the rest of the break
    assert run.phase is PomoPhase.FOCUS and run.block_started_at == T0 + m(29) and len(logged) == 1
    run, _ = store.pause_pomodoro(T0 + m(32), S)
    assert run.paused
    run, _ = store.resume_pomodoro(T0 + m(45), S)
    assert not run.paused
    logged = store.stop_pomodoro(T0 + m(55), S)  # 3 + 10 minutes of focus in block 2
    assert [(s.minutes, s.note) for s in logged] == [(13, "Pomodoro 2 (stopped early)")]
    assert store.get_pomodoro() is None
    assert store.total_minutes() == 40


def test_pomodoro_and_plain_timer_exclude_each_other(store: Store, course: Course) -> None:
    store.start_pomodoro(course.id, now=T0)
    with pytest.raises(StorageError, match="Pomodoro is running"):
        store.start_timer(course.id)
    with pytest.raises(StorageError, match="already running"):
        store.start_pomodoro(course.id)
    store.stop_pomodoro(T0 + m(1), S)
    store.start_timer(course.id)
    with pytest.raises(StorageError, match="timer is running"):
        store.start_pomodoro(course.id)


def test_no_run_errors(store: Store) -> None:
    assert store.settle_pomodoro(T0, S) == (None, [])
    for action in (store.pomodoro_next, store.pomodoro_break, store.pause_pomodoro, store.resume_pomodoro,
                   store.stop_pomodoro):
        with pytest.raises(StorageError, match="No Pomodoro"):
            action(T0, S)


def test_deleting_the_course_ends_its_run(store: Store, course: Course) -> None:
    store.start_pomodoro(course.id, now=T0)
    store.delete_course(course.id)
    assert store.get_pomodoro() is None
