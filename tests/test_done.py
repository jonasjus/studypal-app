"""Subjects marked done: out of the overview, quiet deadlines, still there when you want them."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from studypal.core import alerts, dashboard
from studypal.core.config import default_config
from studypal.core.models import Course, Deadline, WeakSpot
from studypal.core.storage import Store


def setup(store: Store) -> tuple[Course, Course]:
    today = date.today()
    old = store.add_course(Course("Data Engineering", "DAT255", today - timedelta(days=30), today + timedelta(days=1)))
    ml = store.add_course(Course("Machine Learning", "INF301", today, today + timedelta(days=20)))
    store.add_deadline(Deadline("Report", datetime.now() + timedelta(hours=20), course_id=old.id))
    store.add_weak_spot(WeakSpot(old.id, "Kafka"))
    store.add_deadline(Deadline("Thesis plan", datetime.now() + timedelta(hours=20)))  # standalone
    return old, ml


def test_marking_done_and_back(store: Store) -> None:
    old, ml = setup(store)
    assert store.set_course_done(old.id, True).done
    assert [c.code for c in store.list_courses(done=False)] == ["INF301"]
    assert [c.code for c in store.list_courses(done=True)] == ["DAT255"]
    assert len(store.list_courses()) == 2  # nothing is deleted
    assert not store.set_course_done(old.id, False).done


def test_done_subjects_leave_the_dashboard(store: Store) -> None:
    old, ml = setup(store)
    store.set_course_done(old.id, True)
    dash = dashboard.build(store, default_config())
    assert [s.course.code for s in dash.courses] == ["INF301"]
    assert [s.course.code for s in dash.done_courses] == ["DAT255"]
    assert all(d.course_id != old.id for d in dash.deadlines)
    assert "Thesis plan" in [d.title for d in dash.deadlines]  # standalone deadlines stay
    assert dash.weak_spots == []
    assert dash.course(old.id).code == "DAT255"  # still found by id


def test_done_subjects_send_no_alerts(store: Store) -> None:
    old, _ = setup(store)
    now = datetime.now()
    before = {a.deadline.title for a in alerts.due_alerts(store, default_config(), now)}
    store.set_course_done(old.id, True)
    after = {a.deadline.title for a in alerts.due_alerts(store, default_config(), now)}
    assert "Report" in before and "Report" not in after and "Thesis plan" in after


def test_done_survives_reopening_and_edits(db_file, store: Store) -> None:
    old, _ = setup(store)
    store.set_course_done(old.id, True)
    course = store.get_course(old.id)
    course.notes = "passed"
    store.update_course(course)
    with Store(db_file) as again:
        assert again.get_course(old.id).done and again.get_course(old.id).notes == "passed"

