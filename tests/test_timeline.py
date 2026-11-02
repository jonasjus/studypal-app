from __future__ import annotations

from datetime import date

import pytest

from studypal.core.logic.timeline import Cell, Phase, cram_progress, done_fraction, timeline_cells
from studypal.core.models import Course, Topic, TopicStatus

COURSE = Course("Machine Learning", "ML101", cram_start=date(2026, 11, 1), exam_date=date(2026, 12, 1), id=1)  # 30 days


def topics(*statuses: TopicStatus) -> list[Topic]:
    return [Topic(1, f"T{i}", status=s) for i, s in enumerate(statuses)]


NS, IP, RV, CF = TopicStatus.NOT_STARTED, TopicStatus.IN_PROGRESS, TopicStatus.REVIEWED, TopicStatus.CONFIDENT


def test_done_counts_reviewed_and_confident() -> None:
    assert done_fraction(topics(NS, IP, RV, CF)) == 0.5
    assert done_fraction([]) == 0.0


@pytest.mark.parametrize(
    ("today", "elapsed", "phase", "days_left"),
    [
        (date(2026, 10, 25), 0.0, Phase.BEFORE, 37),
        (date(2026, 11, 1), 0.0, Phase.CRAMMING, 30),
        (date(2026, 11, 16), 0.5, Phase.CRAMMING, 15),
        (date(2026, 12, 1), 1.0, Phase.EXAM_DAY, 0),
        (date(2026, 12, 5), 1.0, Phase.AFTER, -4),
    ],
)
def test_elapsed_and_phase(today: date, elapsed: float, phase: Phase, days_left: int) -> None:
    p = cram_progress(COURSE, [], today)
    assert p.elapsed == pytest.approx(elapsed)
    assert p.phase is phase
    assert p.days_left == days_left
    assert p.days_total == 30


def test_behind_when_done_trails_today() -> None:
    p = cram_progress(COURSE, topics(RV, NS, NS, NS), date(2026, 11, 16))  # 50% of time, 25% done
    assert p.is_behind and p.behind == pytest.approx(0.25)


def test_not_behind_when_done_is_ahead_or_level() -> None:
    assert not cram_progress(COURSE, topics(RV, CF, NS, NS), date(2026, 11, 16)).is_behind  # 50% / 50%
    assert not cram_progress(COURSE, topics(RV, CF, CF, NS), date(2026, 11, 16)).is_behind  # 75% done


def test_nothing_is_behind_after_the_exam() -> None:
    p = cram_progress(COURSE, topics(NS, NS), date(2026, 12, 3))
    assert p.behind == 0 and not p.is_behind


def test_cram_start_on_exam_day() -> None:
    same_day = Course("Quick", "Q", date(2026, 11, 10), date(2026, 11, 10), id=2)
    assert cram_progress(same_day, [], date(2026, 11, 9)).elapsed == 0.0
    assert cram_progress(same_day, [], date(2026, 11, 10)).elapsed == 1.0


def test_cells_split_into_done_behind_and_todo() -> None:
    p = cram_progress(COURSE, topics(RV, NS, NS, NS), date(2026, 11, 16))  # done 25%, today 50%
    cells, marker = timeline_cells(p, 20)
    assert cells.count(Cell.DONE) == 5
    assert cells.count(Cell.BEHIND) == 5
    assert cells.count(Cell.TODO) == 10
    assert cells[:5] == [Cell.DONE] * 5 and cells[5:10] == [Cell.BEHIND] * 5
    assert marker == 10  # round(0.5 * 19)


def test_cells_when_ahead_have_no_behind_gap() -> None:
    p = cram_progress(COURSE, topics(RV, CF, CF, NS), date(2026, 11, 16))
    cells, _ = timeline_cells(p, 20)
    assert Cell.BEHIND not in cells and cells.count(Cell.DONE) == 15


def test_marker_stays_inside_the_bar() -> None:
    _, start_marker = timeline_cells(cram_progress(COURSE, [], date(2026, 10, 1)), 10)
    _, end_marker = timeline_cells(cram_progress(COURSE, [], date(2026, 12, 20)), 10)
    assert (start_marker, end_marker) == (0, 9)
    assert timeline_cells(cram_progress(COURSE, [], date(2026, 11, 16)), 0) == ([], 0)


def test_a_course_without_topics_is_never_behind() -> None:
    p = cram_progress(COURSE, [], date(2026, 11, 20))
    assert not p.is_behind
    cells, _ = timeline_cells(p, 20)
    assert Cell.BEHIND not in cells
