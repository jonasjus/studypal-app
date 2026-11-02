from __future__ import annotations

from datetime import date, datetime

import pytest

from studypal.core.logic.reading import ReadingParseError, number_key, parse_section_ranges, parse_toc, progress
from studypal.core.models import Course, Section, Source, Topic, TopicStatus
from studypal.core.storage import Store, StorageError

# ---------- typing ranges ----------


@pytest.mark.parametrize(
    ("text", "chapter", "expected"),
    [
        ("6.1-6.5, 6.7", None, ["6.1", "6.2", "6.3", "6.4", "6.5", "6.7"]),
        ("6.1-4", None, ["6.1", "6.2", "6.3", "6.4"]),
        ("1-3 5", "6", ["6.1", "6.2", "6.3", "6.5"]),  # inside chapter 6, plain numbers are its sections
        ("6.1 - 6.3", None, ["6.1", "6.2", "6.3"]),
        ("6.1, 6.1, 6.2", None, ["6.1", "6.2"]),  # repeats dropped
        ("A.1-A.3", None, ["A.1", "A.2", "A.3"]),
        ("6.2.1-6.2.3", None, ["6.2.1", "6.2.2", "6.2.3"]),
    ],
)
def test_section_ranges(text: str, chapter: str | None, expected: list[str]) -> None:
    assert parse_section_ranges(text, chapter) == expected


@pytest.mark.parametrize("bad", ["6.5-6.1", "6.a-6.c", "1-500"])
def test_bad_ranges_explain_themselves(bad: str) -> None:
    with pytest.raises(ReadingParseError):
        parse_section_ranges(bad)


def test_numbers_sort_naturally() -> None:
    assert sorted(["6.10", "6.2", "A.1", "10.1", "6.9"], key=number_key) == ["6.2", "6.9", "6.10", "10.1", "A.1"]


# ---------- pasting a table of contents ----------

TOC = """Contents
Chapter 6: Kernel Methods
6.1 Dual Representations ............ 293
6.2 Constructing Kernels\t294
6.2.1 Sub-section  296
6.3 Radial Basis Function Networks 299
7 Sparse Kernel Machines 325
7.1 Maximum Margin Classifiers . . . 326
7.2 Lecture 3 recap
A.1 Appendix
"""


def test_toc_lines_become_chapters_and_sections() -> None:
    chapters = parse_toc(TOC)
    assert [(c.number, c.title) for c in chapters] == [("6", "Kernel Methods"), ("7", "Sparse Kernel Machines"), ("A", "")]
    assert chapters[0].sections == [("6.1", "Dual Representations"), ("6.2", "Constructing Kernels"),
                                    ("6.2.1", "Sub-section"), ("6.3", "Radial Basis Function Networks")]
    # Dot leaders and page numbers go; a short number inside a title stays.
    assert chapters[1].sections == [("7.1", "Maximum Margin Classifiers"), ("7.2", "Lecture 3 recap")]


def test_toc_without_numbers_is_refused() -> None:
    with pytest.raises(ReadingParseError, match="No numbered lines"):
        parse_toc("Introduction\nPreface\n")


def test_progress_counts_required_only() -> None:
    sections = [Section(1, "1.1", read=True), Section(1, "1.2"), Section(1, "1.3", required=False, read=True)]
    p = progress(sections)
    assert (p.read, p.required, p.optional_read, p.optional) == (1, 2, 1, 1)
    assert p.fraction == 0.5 and not p.complete


# ---------- storage ----------

@pytest.fixture
def course(store: Store) -> Course:
    return store.add_course(Course("Machine Learning", "INF301", date(2026, 11, 1), date(2026, 12, 10)))


@pytest.fixture
def bishop(store: Store, course: Course) -> Source:
    return store.add_source(Source(course.id, "Pattern Recognition and Machine Learning", "Bishop"))


def numbers(store: Store, course: Course) -> list[str]:
    return [s.number for _, chs in store.reading_list(course.id) for _, ss in chs for s in ss]


def test_add_chapter_by_ranges_and_extend_it(store: Store, course: Course, bishop: Source) -> None:
    chapter, added = store.add_chapter(bishop.id, "6", "Kernel methods", parse_section_ranges("1-3", "6"))
    assert added == 3 and chapter.title == "Kernel methods"
    _, added = store.add_chapter(bishop.id, "6", "", parse_section_ranges("6.3-6.5", "6"))
    assert added == 2  # 6.3 was already there
    assert numbers(store, course) == ["6.1", "6.2", "6.3", "6.4", "6.5"]
    assert store.get_chapter(chapter.id).title == "Kernel methods"  # an empty title never overwrites


def test_import_toc_merges_with_what_is_there(store: Store, course: Course, bishop: Source) -> None:
    store.add_chapter(bishop.id, "6", "", ["6.1", "6.2"])
    new_chapters, new_sections = store.import_toc(bishop.id, parse_toc(TOC))
    assert (new_chapters, new_sections) == (2, 5)  # 6.1 and 6.2 were already there
    [(_, chapters)] = store.reading_list(course.id)
    assert [c.number for c, _ in chapters] == ["6", "7", "A"]
    ch6_sections = chapters[0][1]
    assert ch6_sections[0].title == "Dual Representations"  # blank titles filled in from the pasted contents


def test_reading_counts_toward_linked_topics(store: Store, course: Course, bishop: Source) -> None:
    kernels = store.add_topic(Topic(course.id, "Kernels"))
    gp = store.add_topic(Topic(course.id, "Gaussian processes"))
    chapter, _ = store.add_chapter(bishop.id, "6", "Kernel methods", ["6.1", "6.2", "6.4"], topic_id=kernels.id)
    [s1, s2, s4] = store.reading_list(course.id)[0][1][0][1]
    s4.topic_id = gp.id  # one section counts toward a different topic
    store.update_section(s4)
    progress_by_topic = store.reading_by_topic(course.id)
    assert (progress_by_topic[kernels.id].required, progress_by_topic[gp.id].required) == (2, 1)

    now = datetime(2026, 11, 10, 20, 0)
    store.toggle_section_read(s1.id, now)
    t = store.get_topic(kernels.id)
    assert t.last_studied == date(2026, 11, 10) and t.status is TopicStatus.NOT_STARTED  # not all read yet
    store.toggle_section_read(s2.id, now)
    assert store.get_topic(kernels.id).status is TopicStatus.IN_PROGRESS  # all required reading done
    assert store.reading_by_topic(course.id)[kernels.id].complete


def test_reading_never_lowers_a_topic(store: Store, course: Course, bishop: Source) -> None:
    topic = store.add_topic(Topic(course.id, "Kernels", status=TopicStatus.CONFIDENT))
    store.add_chapter(bishop.id, "6", "", ["6.1"], topic_id=topic.id)
    store.set_chapter_read(store.reading_list(course.id)[0][1][0][0].id, True)
    assert store.get_topic(topic.id).status is TopicStatus.CONFIDENT


def test_optional_sections_dont_count(store: Store, course: Course, bishop: Source) -> None:
    store.add_chapter(bishop.id, "6", "", ["6.1", "6.2", "6.3"])
    sections = store.reading_list(course.id)[0][1][0][1]
    store.set_required([sections[2].id], False)
    chapter_id = sections[0].chapter_id
    store.set_chapter_read(chapter_id, True)  # marks required sections only
    p = store.reading_progress(course.id)
    assert (p.read, p.required, p.optional_read, p.optional) == (2, 2, 0, 1) and p.complete
    store.set_chapter_read(chapter_id, False)
    assert store.reading_progress(course.id).read == 0


def test_mark_read_by_number(store: Store, course: Course, bishop: Source) -> None:
    store.add_chapter(bishop.id, "6", "", ["6.1", "6.2"])
    marked = store.mark_read(course.id, ["6.2"])
    assert [s.number for s in marked] == ["6.2"] and marked[0].read
    with pytest.raises(StorageError, match="No section 6.9"):
        store.mark_read(course.id, ["6.9"])


def test_same_number_in_two_sources_needs_the_source(store: Store, course: Course, bishop: Source) -> None:
    notes = store.add_source(Source(course.id, "Lecture notes"))
    store.add_chapter(bishop.id, "1", "", ["1.1"])
    store.add_chapter(notes.id, "1", "", ["1.1"])
    with pytest.raises(StorageError, match="more than one source"):
        store.mark_read(course.id, ["1.1"])
    store.mark_read(course.id, ["1.1"], source_id=notes.id)
    assert store.reading_progress(course.id).read == 1


def test_find_source(store: Store, course: Course, bishop: Source) -> None:
    assert store.find_source(course.id, None).id == bishop.id  # the only one
    store.add_source(Source(course.id, "Lecture notes"))
    assert store.find_source(course.id, "lect").title == "Lecture notes"
    with pytest.raises(StorageError, match="say which"):
        store.find_source(course.id, None)


def test_deleting_course_or_topic(store: Store, course: Course, bishop: Source) -> None:
    topic = store.add_topic(Topic(course.id, "Kernels"))
    chapter, _ = store.add_chapter(bishop.id, "6", "", ["6.1"], topic_id=topic.id)
    store.delete_topic(topic.id)
    assert store.get_chapter(chapter.id).topic_id is None  # reading stays, unlinked
    store.delete_course(course.id)
    assert store.get_chapter(chapter.id) is None and store.get_source(bishop.id) is None


def test_duplicate_numbers_are_refused_on_edit(store: Store, course: Course, bishop: Source) -> None:
    store.add_chapter(bishop.id, "6", "", ["6.1", "6.2"])
    s2 = store.reading_list(course.id)[0][1][0][1][1]
    s2.number = "6.1"
    with pytest.raises(StorageError, match="already has a section 6.1"):
        store.update_section(s2)
