from __future__ import annotations

from datetime import datetime, time, timedelta

from studypal.core.config import DEFAULT_THRESHOLDS, parse_threshold
from studypal.core.logic.notify import alert_text, pending_alerts, trigger_time, within
from studypal.core.models import Course, Deadline, DeadlineKind
from studypal.core.storage import Store

MORNING = time(8, 0)
DUE = datetime(2026, 12, 10, 9, 0)
EXAM = Deadline("ML101 exam", DUE, DeadlineKind.EXAM, course_id=1, id=1)


def pending(now: datetime, sent=frozenset(), deadlines=(EXAM,)):
    return pending_alerts(deadlines, now, DEFAULT_THRESHOLDS, MORNING, set(sent))


def test_trigger_times() -> None:
    assert trigger_time(DUE, parse_threshold("7d"), MORNING) == DUE - timedelta(days=7)
    assert trigger_time(DUE, parse_threshold("morning"), MORNING) == datetime(2026, 12, 10, 8, 0)
    # A deadline at 07:00 has no "morning of" alert at 08:00.
    assert trigger_time(datetime(2026, 12, 10, 7, 0), parse_threshold("morning"), MORNING) is None


def test_nothing_before_the_first_threshold() -> None:
    assert pending(DUE - timedelta(days=7, minutes=1)) == []


def test_each_threshold_fires_once_when_reached() -> None:
    sent: set = set()
    fired = []
    # Check every 30 minutes for the last 8 days, the way a cron job would.
    now = DUE - timedelta(days=8)
    while now < DUE:
        for a in pending(now, sent):
            fired.append((a.threshold, now))
            sent |= {(a.deadline.id, k, a.deadline.due_at) for k in a.covers}
        now += timedelta(minutes=30)
    assert fired == [
        ("7d", DUE - timedelta(days=7)),
        ("2d", DUE - timedelta(days=2)),
        ("1d", DUE - timedelta(days=1)),
        ("morning", datetime(2026, 12, 10, 8, 0)),
    ]


def test_missed_thresholds_collapse_into_one_alert() -> None:
    # Laptop asleep for a week: wake up 20 hours before the exam.
    [alert] = pending(DUE - timedelta(hours=20))
    assert alert.threshold == "1d"
    assert set(alert.covers) == {"7d", "2d", "1d"}


def test_already_sent_thresholds_are_not_repeated() -> None:
    sent = {(1, "7d", DUE), (1, "2d", DUE)}
    [alert] = pending(DUE - timedelta(hours=20), sent)
    assert alert.covers == ("1d",)
    assert pending(DUE - timedelta(hours=20), sent | {(1, "1d", DUE)}) == []


def test_moving_a_deadline_rearms_its_alerts() -> None:
    sent = {(1, "7d", DUE)}
    moved = Deadline("ML101 exam", DUE + timedelta(days=3), DeadlineKind.EXAM, course_id=1, id=1)
    [alert] = pending(moved.due_at - timedelta(days=6), sent, deadlines=(moved,))
    assert alert.threshold == "7d"


def test_done_and_past_deadlines_send_nothing() -> None:
    done = Deadline("Problem set", DUE, done=True, id=2)
    assert pending(DUE - timedelta(hours=1), deadlines=(done,)) == []
    assert pending(DUE + timedelta(minutes=1)) == []


def test_alerts_come_back_soonest_first() -> None:
    later = Deadline("Report", DUE + timedelta(days=1), id=2)
    alerts = pending(DUE - timedelta(hours=2), deadlines=(later, EXAM))
    assert [a.deadline.id for a in alerts] == [1, 2]


def test_custom_thresholds() -> None:
    custom = [parse_threshold("3h")]
    assert pending_alerts([EXAM], DUE - timedelta(hours=4), custom, MORNING, set()) == []
    [a] = pending_alerts([EXAM], DUE - timedelta(hours=2, minutes=59), custom, MORNING, set())
    assert a.threshold == "3h"


def test_alert_text() -> None:
    title, body = alert_text(EXAM, DUE - timedelta(days=6, hours=23))
    assert title == "ML101 exam is due in 6d 23h"
    assert body == "Exam · Thu 10 Dec at 09:00"
    assert alert_text(EXAM, datetime(2026, 12, 10, 8, 0))[0] == "ML101 exam is due today at 09:00"
    assert alert_text(EXAM, datetime(2026, 12, 9, 9, 0))[0] == "ML101 exam is due tomorrow at 09:00"
    report = Deadline("Report", DUE, course_id=1, id=2)
    assert alert_text(report, DUE - timedelta(hours=3), course_code="ST202")[0].startswith("ST202: Report")


def test_within_window_includes_overdue() -> None:
    now = DUE - timedelta(hours=30)
    overdue = Deadline("Old", now - timedelta(hours=1), id=3)
    far = Deadline("Far", now + timedelta(days=5), id=4)
    assert [d.id for d in within([overdue, EXAM, far], now, timedelta(days=2))] == [3, 1]


def test_works_with_storage_deduplication(store: Store) -> None:
    course = store.add_course(Course("Machine Learning", "ML101", DUE.date() - timedelta(days=30), DUE.date()))
    now = DUE - timedelta(days=1, hours=1)
    first = pending_alerts(store.list_deadlines(), now, DEFAULT_THRESHOLDS, MORNING, store.sent_keys(),
                           {course.id: course.code})
    assert [a.threshold for a in first] == ["2d"]
    for a in first:
        store.mark_sent(a.deadline.id, list(a.covers), a.deadline.due_at, now)
    assert pending_alerts(store.list_deadlines(), now, DEFAULT_THRESHOLDS, MORNING, store.sent_keys()) == []


def test_banner_groups_overdue_and_next_24_hours() -> None:
    from studypal.core.logic.notify import banner_groups

    now = datetime(2026, 12, 1, 12, 0)
    late = Deadline("Late", now - timedelta(hours=3), id=1)
    soon = Deadline("Soon", now + timedelta(hours=23), id=2)
    edge = Deadline("Edge", now + timedelta(hours=24), id=3)
    later = Deadline("Later", now + timedelta(hours=25), id=4)
    done = Deadline("Done", now - timedelta(hours=1), done=True, id=5)
    overdue, within_day = banner_groups([later, edge, soon, late, done], now)
    assert [d.id for d in overdue] == [1]
    assert [d.id for d in within_day] == [2, 3]


def test_send_due_records_only_what_was_shown(store: Store) -> None:
    from studypal.core import alerts
    from studypal.core.config import default_config

    course = store.add_course(Course("Machine Learning", "ML101", DUE.date() - timedelta(days=30), DUE.date()))
    store.add_deadline(Deadline("Problem set", DUE - timedelta(hours=5), course_id=course.id))
    now = DUE - timedelta(hours=20)
    failed = alerts.send_due(store, default_config(), now, send=lambda title, body: False)
    assert len(failed.failed) == 2 and failed.sent == [] and store.sent_keys() == set()
    shown: list[str] = []
    ok = alerts.send_due(store, default_config(), now, send=lambda title, body: shown.append(title) or True)
    assert len(ok.sent) == 2 and len(shown) == 2
    assert alerts.send_due(store, default_config(), now, send=lambda t, b: shown.append(t) or True).sent == []
