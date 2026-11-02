from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from studypal.core.models import COURSE_COLORS, Course, Deadline, DeadlineKind, Priority, Session, Topic, TopicStatus, WeakSpot
from studypal.core.storage import MIGRATIONS, Store, StorageError


def test_new_database_is_fully_migrated(store: Store) -> None:
    assert store.schema_version == len(MIGRATIONS)


def test_reopening_keeps_data_and_does_not_remigrate(db_file, ml: Course) -> None:
    with Store(db_file) as again:
        assert again.schema_version == len(MIGRATIONS)
        assert [c.code for c in again.list_courses()] == ["ML101"]


def test_changes_are_visible_to_another_connection_immediately(db_file, store: Store, ml: Course) -> None:
    store.add_topic(Topic(ml.id, "Kernels"))
    with Store(db_file) as other:  # no save step: a second connection sees it straight away
        assert [t.title for t in other.list_topics(ml.id)] == ["Kernels"]


# ---------- courses ----------

def test_adding_a_course_creates_its_exam_deadline(store: Store, ml: Course) -> None:
    [exam] = store.list_deadlines()
    assert exam.is_course_exam and exam.kind is DeadlineKind.EXAM
    assert exam.course_id == ml.id and exam.title == "ML101 exam"
    assert exam.due_at == datetime(2026, 12, 10, 9, 0)


def test_course_codes_are_unique_ignoring_case(store: Store, ml: Course) -> None:
    with pytest.raises(StorageError, match="already a course"):
        store.add_course(Course("Other", "ml101", date(2026, 11, 1), date(2026, 12, 1)))


def test_exam_cannot_be_before_cram_start(store: Store) -> None:
    with pytest.raises(StorageError, match="before the cram start"):
        store.add_course(Course("Stats", "ST", date(2026, 12, 1), date(2026, 11, 1)))


def test_moving_the_exam_date_moves_the_exam_deadline_and_keeps_its_time(store: Store, ml: Course) -> None:
    exam = store.list_deadlines()[0]
    exam.due_at = exam.due_at.replace(hour=14)
    store.update_deadline(exam)
    ml.exam_date = date(2026, 12, 15)
    store.update_course(ml)
    assert store.get_deadline(exam.id).due_at == datetime(2026, 12, 15, 14, 0)


def test_moving_the_exam_deadline_moves_the_course_exam_date(store: Store, ml: Course) -> None:
    exam = store.list_deadlines()[0]
    exam.due_at = datetime(2026, 12, 12, 9, 0)
    store.update_deadline(exam)
    assert store.get_course(ml.id).exam_date == date(2026, 12, 12)


def test_exam_deadline_cannot_move_before_cram_start(store: Store, ml: Course) -> None:
    exam = store.list_deadlines()[0]
    exam.due_at = datetime(2026, 10, 1, 9, 0)
    with pytest.raises(StorageError, match="cram start"):
        store.update_deadline(exam)


def test_exam_deadline_cannot_be_deleted_on_its_own(store: Store, ml: Course) -> None:
    with pytest.raises(StorageError, match="goes away with the course"):
        store.delete_deadline(store.list_deadlines()[0].id)


def test_deleting_a_course_removes_everything_that_belongs_to_it(store: Store, ml: Course) -> None:
    t = store.add_topic(Topic(ml.id, "Kernels"))
    store.add_weak_spot(WeakSpot(ml.id, "Dual form", topic_id=t.id))
    store.add_deadline(Deadline("Problem set", datetime(2026, 11, 20, 23, 59), course_id=ml.id))
    store.log_session(Session(ml.id, datetime(2026, 11, 2, 10, 0), 45, topic_id=t.id))
    store.start_timer(ml.id, t.id)
    standalone = store.add_deadline(Deadline("Hand in thesis plan", datetime(2026, 11, 30, 12, 0)))

    store.delete_course(ml.id)

    assert store.list_topics() == []
    assert store.list_weak_spots(include_resolved=True) == []
    assert store.list_sessions() == []
    assert store.get_timer() is None
    assert [d.id for d in store.list_deadlines()] == [standalone.id]


def test_colours_are_handed_out_in_order(store: Store) -> None:
    for i in range(3):
        store.add_course(Course(f"C{i}", f"C{i}", date(2026, 11, 1), date(2026, 12, 1), color=store.next_color()))
    assert [c.color for c in store.list_courses()] == list(COURSE_COLORS[:3])


def test_courses_list_soonest_exam_first(store: Store, ml: Course) -> None:
    store.add_course(Course("Statistics", "ST202", date(2026, 11, 1), date(2026, 12, 2)))
    assert [c.code for c in store.list_courses()] == ["ST202", "ML101"]


def test_find_course_by_code_name_or_prefix(store: Store, ml: Course) -> None:
    store.add_course(Course("Statistics", "ST202", date(2026, 11, 1), date(2026, 12, 2)))
    assert store.find_course("ml101").id == ml.id
    assert store.find_course("machine learning").id == ml.id
    assert store.find_course("stat").code == "ST202"
    with pytest.raises(StorageError, match="No course matches"):
        store.find_course("bio")


def test_find_course_refuses_ambiguous_prefixes(store: Store, ml: Course) -> None:
    store.add_course(Course("Machine Vision", "MV", date(2026, 11, 1), date(2026, 12, 2)))
    with pytest.raises(StorageError, match="more than one"):
        store.find_course("machine")


# ---------- topics ----------

def test_confidence_stays_between_1_and_5(store: Store, ml: Course) -> None:
    t = store.add_topic(Topic(ml.id, "Kernels", confidence=4))
    assert store.adjust_confidence(t.id, +1).confidence == 5
    assert store.adjust_confidence(t.id, +1).confidence == 5
    for _ in range(6):
        store.adjust_confidence(t.id, -1)
    assert store.get_topic(t.id).confidence == 1


def test_topic_needs_a_title_and_valid_confidence(store: Store, ml: Course) -> None:
    with pytest.raises(StorageError):
        store.add_topic(Topic(ml.id, "  "))
    with pytest.raises(StorageError):
        store.add_topic(Topic(ml.id, "X", confidence=6))


def test_find_topic(store: Store, ml: Course) -> None:
    store.add_topic(Topic(ml.id, "Kernels"))
    store.add_topic(Topic(ml.id, "Kernel PCA"))
    assert store.find_topic(ml.id, "kernels").title == "Kernels"
    with pytest.raises(StorageError, match="more than one"):
        store.find_topic(ml.id, "kern")


# ---------- sessions and the timer ----------

def test_logging_a_session_marks_the_topic_studied_and_in_progress(store: Store, ml: Course) -> None:
    t = store.add_topic(Topic(ml.id, "Kernels"))
    store.log_session(Session(ml.id, datetime(2026, 11, 5, 18, 0), 60, topic_id=t.id))
    t = store.get_topic(t.id)
    assert t.last_studied == date(2026, 11, 5)
    assert t.status is TopicStatus.IN_PROGRESS


def test_logging_an_older_session_never_moves_last_studied_back(store: Store, ml: Course) -> None:
    t = store.add_topic(Topic(ml.id, "Kernels", status=TopicStatus.REVIEWED))
    store.log_session(Session(ml.id, datetime(2026, 11, 5, 18, 0), 60, topic_id=t.id))
    store.log_session(Session(ml.id, datetime(2026, 11, 2, 18, 0), 30, topic_id=t.id))
    t = store.get_topic(t.id)
    assert t.last_studied == date(2026, 11, 5)
    assert t.status is TopicStatus.REVIEWED  # only "not started" gets bumped


def test_sessions_need_a_positive_length(store: Store, ml: Course) -> None:
    with pytest.raises(StorageError):
        store.log_session(Session(ml.id, datetime(2026, 11, 5), 0))


def test_list_sessions_filters_and_sorts_newest_first(store: Store, ml: Course) -> None:
    for day in (3, 9, 5):
        store.log_session(Session(ml.id, datetime(2026, 11, day, 10, 0), 30))
    got = store.list_sessions(since=datetime(2026, 11, 4), until=datetime(2026, 11, 10))
    assert [s.started_at.day for s in got] == [9, 5]
    assert store.total_minutes(ml.id) == 90


def test_timer_survives_closing_the_app_and_logs_on_stop(db_file, store: Store, ml: Course) -> None:
    start = datetime(2026, 11, 5, 18, 0, 0)
    store.start_timer(ml.id, now=start)
    store.close()
    with Store(db_file) as reopened:
        assert reopened.get_timer().started_at == start
        session = reopened.stop_timer(now=start + timedelta(minutes=50, seconds=20), note="mock exam")
        assert session.minutes == 50 and session.note == "mock exam"
        assert reopened.get_timer() is None
        assert reopened.total_minutes() == 50


def test_timer_under_a_minute_logs_nothing(store: Store, ml: Course) -> None:
    start = datetime(2026, 11, 5, 18, 0)
    store.start_timer(ml.id, now=start)
    assert store.stop_timer(now=start + timedelta(seconds=20)) is None
    assert store.list_sessions() == [] and store.get_timer() is None


def test_only_one_timer_at_a_time(store: Store, ml: Course) -> None:
    store.start_timer(ml.id)
    with pytest.raises(StorageError, match="already running"):
        store.start_timer(ml.id)
    store.cancel_timer()
    with pytest.raises(StorageError, match="No study timer"):
        store.stop_timer()


# ---------- weak spots ----------

def test_weak_spots_sort_by_priority_then_age(store: Store, ml: Course) -> None:
    base = datetime(2026, 11, 1, 9, 0)
    store.add_weak_spot(WeakSpot(ml.id, "old low", Priority.LOW, created_at=base))
    store.add_weak_spot(WeakSpot(ml.id, "new high", Priority.HIGH, created_at=base + timedelta(days=2)))
    store.add_weak_spot(WeakSpot(ml.id, "old high", Priority.HIGH, created_at=base))
    store.add_weak_spot(WeakSpot(ml.id, "med", Priority.MED, created_at=base))
    assert [w.description for w in store.list_weak_spots()] == ["old high", "new high", "med", "old low"]


def test_toggling_a_weak_spot_resolves_and_reopens_it(store: Store, ml: Course) -> None:
    w = store.add_weak_spot(WeakSpot(ml.id, "Dual form"))
    now = datetime(2026, 11, 8, 20, 15)
    w = store.toggle_weak_spot(w.id, now=now)
    assert w.resolved and w.resolved_at == now
    assert store.list_weak_spots() == []
    w = store.toggle_weak_spot(w.id)
    assert not w.resolved and w.resolved_at is None


def test_deleting_a_topic_keeps_its_weak_spots(store: Store, ml: Course) -> None:
    t = store.add_topic(Topic(ml.id, "Kernels"))
    w = store.add_weak_spot(WeakSpot(ml.id, "Dual form", topic_id=t.id))
    store.delete_topic(t.id)
    assert store.get_weak_spot(w.id).topic_id is None


# ---------- deadlines ----------

def test_deadlines_sort_soonest_first_and_hide_done(store: Store, ml: Course) -> None:
    a = store.add_deadline(Deadline("Problem set 2", datetime(2026, 11, 20, 23, 59), course_id=ml.id))
    b = store.add_deadline(Deadline("Problem set 1", datetime(2026, 11, 10, 23, 59), course_id=ml.id))
    standalone = store.add_deadline(Deadline("Thesis plan", datetime(2026, 11, 15, 12, 0), DeadlineKind.MILESTONE))
    assert [d.title for d in store.list_deadlines()] == ["Problem set 1", "Thesis plan", "Problem set 2", "ML101 exam"]
    store.toggle_deadline(b.id)
    assert b.id not in [d.id for d in store.list_deadlines()]
    assert b.id in [d.id for d in store.list_deadlines(include_done=True)]
    assert [d.id for d in store.list_deadlines(course_id=ml.id)][0] == a.id
    assert standalone.course_id is None


# ---------- sent notifications ----------

def test_sent_notifications_are_remembered_per_due_time(store: Store, ml: Course) -> None:
    exam = store.list_deadlines()[0]
    store.mark_sent(exam.id, ["7d", "2d"], exam.due_at)
    store.mark_sent(exam.id, ["7d"], exam.due_at)  # marking twice is harmless
    assert store.sent_keys() == {(exam.id, "7d", exam.due_at), (exam.id, "2d", exam.due_at)}
