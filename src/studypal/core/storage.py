"""SQLite storage. The only module that knows about SQL.

Every method that changes data commits before it returns, so nothing is ever waiting
to be saved. Dates are stored as ISO strings in local time ("2026-12-10", "2026-12-10T09:00").
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path

from .logic import pomodoro as pomo
from .logic.pomodoro import PomodoroRun, PomodoroSettings, PomoPhase
from .logic.reading import ReadingProgress, TocChapter, number_key, progress, reading_units
from .models import (
    COURSE_COLORS,
    ActiveTimer,
    Chapter,
    Course,
    Deadline,
    DeadlineKind,
    Exam,
    ExamAttempt,
    ExamFile,
    ExamQuestion,
    LINK_CATEGORIES,
    PROJECT_STATUSES,
    READING_STATUSES,
    Priority,
    Project,
    ProjectEntry,
    ProjectLink,
    CourseNote,
    ProjectNote,
    ProjectSource,
    ProjectTask,
    Section,
    Session,
    Source,
    Topic,
    TopicStatus,
    WeakSpot,
)


# A source's reference details (models.Source), stored as they're typed.
_CITE_FIELDS = ("kind", "year", "publisher", "edition", "journal", "volume", "issue", "pages", "link")


class StorageError(Exception):
    """Something the user asked for can't be done (unknown course, duplicate code, ...)."""


# Each entry upgrades the schema by one version; PRAGMA user_version records how far we are.

PROJECT_TABLES = ("project", "project_note", "project_entry", "project_link", "project_source", "project_task",
                  "project_session")
# The parts of a project that keep an order you can change by dragging.
ORDERED = {"link": "project_link", "source": "project_source", "task": "project_task"}


def _sync_columns(table: str) -> str:
    """uid and updated_at for a table added after the sync migration, filled in by triggers the same way."""
    return f"""
    alter table {table} add column uid text;
    alter table {table} add column updated_at text;
    create unique index {table}_uid on {table}(uid);
    create trigger {table}_new after insert on {table} when new.uid is null or new.updated_at is null begin
        update {table} set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger {table}_changed after update on {table} when new.updated_at is old.updated_at begin
        update {table} set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    """


MIGRATIONS: list[str] = [
    """
    create table course (
        id          integer primary key,
        name        text not null,
        code        text not null unique collate nocase,
        cram_start  text not null,
        exam_date   text not null,
        color       text not null,
        notes       text not null default '',
        check (exam_date >= cram_start)
    );

    create table topic (
        id            integer primary key,
        course_id     integer not null references course(id) on delete cascade,
        title         text not null,
        status        text not null default 'not_started'
                      check (status in ('not_started', 'in_progress', 'reviewed', 'confident')),
        confidence    integer not null default 1 check (confidence between 1 and 5),
        last_studied  text
    );
    create index topic_course on topic(course_id);

    create table weak_spot (
        id           integer primary key,
        course_id    integer not null references course(id) on delete cascade,
        topic_id     integer references topic(id) on delete set null,
        description  text not null,
        priority     text not null default 'med' check (priority in ('low', 'med', 'high')),
        created_at   text not null,
        resolved     integer not null default 0,
        resolved_at  text
    );
    create index weak_spot_course on weak_spot(course_id);

    create table deadline (
        id              integer primary key,
        course_id       integer references course(id) on delete cascade,
        title           text not null,
        due_at          text not null,
        kind            text not null default 'assignment' check (kind in ('exam', 'assignment', 'milestone')),
        done            integer not null default 0,
        is_course_exam  integer not null default 0
    );
    create index deadline_due on deadline(due_at);
    create unique index deadline_one_exam_per_course on deadline(course_id) where is_course_exam = 1;

    create table session (
        id          integer primary key,
        course_id   integer not null references course(id) on delete cascade,
        topic_id    integer references topic(id) on delete set null,
        started_at  text not null,
        minutes     integer not null check (minutes > 0),
        note        text not null default ''
    );
    create index session_started on session(started_at);

    -- One row per alert already sent. due_at is part of the key, so moving a deadline re-arms its alerts.
    create table sent_notification (
        deadline_id  integer not null references deadline(id) on delete cascade,
        threshold    text not null,
        due_at       text not null,
        sent_at      text not null,
        primary key (deadline_id, threshold, due_at)
    );

    -- At most one running study timer.
    create table active_timer (
        id          integer primary key check (id = 1),
        course_id   integer not null references course(id) on delete cascade,
        topic_id    integer references topic(id) on delete set null,
        started_at  text not null
    );
    """,
    """
    -- At most one Pomodoro run. Times keep seconds so countdowns stay exact.
    create table pomodoro_run (
        id                integer primary key check (id = 1),
        course_id         integer not null references course(id) on delete cascade,
        topic_id          integer references topic(id) on delete set null,
        phase             text not null check (phase in ('focus', 'short_break', 'long_break', 'ready')),
        phase_started_at  text not null,
        block_started_at  text not null,
        completed         integer not null default 0,
        paused_at         text,
        note              text not null default ''
    );
    """,
    """
    -- Small preferences chosen inside the app (the theme), as opposed to config.toml.
    create table setting (
        key    text primary key,
        value  text not null
    );
    """,
    """
    -- Reading lists: sources (books, notes) have chapters, chapters have sections.
    -- A section counts toward its own topic if set, otherwise its chapter's topic.
    create table source (
        id         integer primary key,
        course_id  integer not null references course(id) on delete cascade,
        title      text not null,
        author     text not null default '',
        position   integer not null default 0
    );
    create index source_course on source(course_id);

    create table chapter (
        id         integer primary key,
        source_id  integer not null references source(id) on delete cascade,
        number     text not null,
        title      text not null default '',
        topic_id   integer references topic(id) on delete set null,
        position   integer not null default 0,
        unique (source_id, number)
    );

    create table section (
        id          integer primary key,
        chapter_id  integer not null references chapter(id) on delete cascade,
        number      text not null,
        title       text not null default '',
        required    integer not null default 1,
        read        integer not null default 0,
        read_at     text,
        topic_id    integer references topic(id) on delete set null,
        position    integer not null default 0,
        unique (chapter_id, number)
    );
    """,
    # For syncing between devices: every row gets a stable id (uid) and a last-changed time (updated_at).
    # Triggers fill both in, so the rest of the code never has to think about them. Import sets
    # updated_at explicitly, and the update trigger leaves an explicitly changed updated_at alone.
    """
    alter table course add column uid text;
    alter table course add column updated_at text;
    update course set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index course_uid on course(uid);
    create trigger course_new after insert on course when new.uid is null or new.updated_at is null begin
        update course set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger course_changed after update on course when new.updated_at is old.updated_at begin
        update course set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    alter table topic add column uid text;
    alter table topic add column updated_at text;
    update topic set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index topic_uid on topic(uid);
    create trigger topic_new after insert on topic when new.uid is null or new.updated_at is null begin
        update topic set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger topic_changed after update on topic when new.updated_at is old.updated_at begin
        update topic set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    alter table weak_spot add column uid text;
    alter table weak_spot add column updated_at text;
    update weak_spot set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index weak_spot_uid on weak_spot(uid);
    create trigger weak_spot_new after insert on weak_spot when new.uid is null or new.updated_at is null begin
        update weak_spot set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger weak_spot_changed after update on weak_spot when new.updated_at is old.updated_at begin
        update weak_spot set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    alter table deadline add column uid text;
    alter table deadline add column updated_at text;
    update deadline set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index deadline_uid on deadline(uid);
    create trigger deadline_new after insert on deadline when new.uid is null or new.updated_at is null begin
        update deadline set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger deadline_changed after update on deadline when new.updated_at is old.updated_at begin
        update deadline set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    alter table session add column uid text;
    alter table session add column updated_at text;
    update session set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index session_uid on session(uid);
    create trigger session_new after insert on session when new.uid is null or new.updated_at is null begin
        update session set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger session_changed after update on session when new.updated_at is old.updated_at begin
        update session set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    alter table source add column uid text;
    alter table source add column updated_at text;
    update source set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index source_uid on source(uid);
    create trigger source_new after insert on source when new.uid is null or new.updated_at is null begin
        update source set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger source_changed after update on source when new.updated_at is old.updated_at begin
        update source set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    alter table chapter add column uid text;
    alter table chapter add column updated_at text;
    update chapter set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index chapter_uid on chapter(uid);
    create trigger chapter_new after insert on chapter when new.uid is null or new.updated_at is null begin
        update chapter set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger chapter_changed after update on chapter when new.updated_at is old.updated_at begin
        update chapter set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    alter table section add column uid text;
    alter table section add column updated_at text;
    update section set uid = lower(hex(randomblob(16))), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
    create unique index section_uid on section(uid);
    create trigger section_new after insert on section when new.uid is null or new.updated_at is null begin
        update section set uid = coalesce(new.uid, lower(hex(randomblob(16)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    create trigger section_changed after update on section when new.updated_at is old.updated_at begin
        update section set updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') where rowid = new.rowid;
    end;
    """,
    """
    -- Subjects you're done with: hidden from the overview, their deadlines and weak spots go quiet.
    alter table course add column done integer not null default 0;
    """,
    # StudyPal only: new uids start with the creation time and the local row number, so rows synced
    # to another computer are added there in the order they were made (topics keep their order).
    # The random tail keeps uids from two computers apart.
    """
    drop trigger course_new;
    create trigger course_new after insert on course when new.uid is null or new.updated_at is null begin
        update course set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    drop trigger topic_new;
    create trigger topic_new after insert on topic when new.uid is null or new.updated_at is null begin
        update topic set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    drop trigger weak_spot_new;
    create trigger weak_spot_new after insert on weak_spot when new.uid is null or new.updated_at is null begin
        update weak_spot set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    drop trigger deadline_new;
    create trigger deadline_new after insert on deadline when new.uid is null or new.updated_at is null begin
        update deadline set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    drop trigger session_new;
    create trigger session_new after insert on session when new.uid is null or new.updated_at is null begin
        update session set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    drop trigger source_new;
    create trigger source_new after insert on source when new.uid is null or new.updated_at is null begin
        update source set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    drop trigger chapter_new;
    create trigger chapter_new after insert on chapter when new.uid is null or new.updated_at is null begin
        update chapter set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    drop trigger section_new;
    create trigger section_new after insert on section when new.uid is null or new.updated_at is null begin
        update section set uid = coalesce(new.uid, printf('%012x%08x', cast((julianday('now') - 2440587.5) * 86400000 as integer),
                                                     new.rowid % 4294967296) || lower(hex(randomblob(8)))),
                       updated_at = coalesce(new.updated_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        where rowid = new.rowid;
    end;
    """,
    # StudyPal only: what an APA reference needs, and a topic for a whole book or article.
    # Nullable, so rows synced in without these fields still load.
    """
    alter table source add column kind text default 'book';
    alter table source add column year text default '';
    alter table source add column publisher text default '';
    alter table source add column edition text default '';
    alter table source add column journal text default '';
    alter table source add column volume text default '';
    alter table source add column issue text default '';
    alter table source add column pages text default '';
    alter table source add column link text default '';
    alter table source add column topic_id integer references topic(id) on delete set null;
    """,
    # StudyPal only: a chapter without sections can be ticked off as a whole.
    """
    alter table chapter add column read integer default 0;
    alter table chapter add column read_at text;
    """,
    # StudyPal only: past exams (with their files) and practice exams, and how each question went.
    """
    create table exam (
        id          integer primary key,
        course_id   integer not null references course(id) on delete cascade,
        title       text not null,
        kind        text not null default 'past',
        taken_on    text default '',
        score       text default '',
        notes       text default '',
        created_at  text
    );
    create index exam_course on exam(course_id);

    create table exam_file (
        id       integer primary key,
        exam_id  integer not null references exam(id) on delete cascade,
        name     text not null,
        key      text not null,
        mime     text not null,
        size     integer default 0,
        role     text not null default 'exam'
    );
    create index exam_file_exam on exam_file(exam_id);

    create table exam_question (
        id        integer primary key,
        exam_id   integer not null references exam(id) on delete cascade,
        number    text not null default '',
        prompt    text default '',
        answer    text default '',
        marks     text default '',
        topic_id  integer references topic(id) on delete set null,
        result    text default '',
        note      text default '',
        why       text default '',
        position  integer not null default 0
    );
    create index exam_question_exam on exam_question(exam_id);
    """ + "".join(_sync_columns(t) for t in ("exam", "exam_file", "exam_question")),
    # StudyPal only: research projects, which sit in the overview's list with the courses (in an order you
    # choose by dragging), with notes, a journal, shortcuts, references, tasks and their own study time.
    # Project time has its own table so older versions syncing the same account never see a session
    # without a course. The timer and Pomodoro (local only, not synced) are rebuilt to run for either.
    """
    alter table course add column position integer default 0;

    create table project (
        id           integer primary key,
        title        text not null,
        description  text default '',
        status       text not null default 'active',
        tags         text default '',
        start_on     text,
        end_on       text,
        color        text not null,
        position     integer default 0,
        created_at   text
    );

    create table project_note (
        id          integer primary key,
        project_id  integer not null references project(id) on delete cascade,
        title       text default '',
        body        text default '',
        created_at  text
    );
    create index project_note_project on project_note(project_id);

    create table project_entry (
        id          integer primary key,
        project_id  integer not null references project(id) on delete cascade,
        day         text not null,
        body        text default ''
    );
    create index project_entry_project on project_entry(project_id);

    create table project_link (
        id          integer primary key,
        project_id  integer not null references project(id) on delete cascade,
        name        text not null,
        url         text not null,
        category    text default '',
        position    integer default 0
    );
    create index project_link_project on project_link(project_id);

    create table project_source (
        id          integer primary key,
        project_id  integer not null references project(id) on delete cascade,
        title       text not null,
        authors     text default '',
        year        text default '',
        link        text default '',
        status      text default 'to_read',
        annotation  text default '',
        position    integer default 0
    );
    create index project_source_project on project_source(project_id);

    create table project_task (
        id          integer primary key,
        project_id  integer not null references project(id) on delete cascade,
        text        text not null,
        done        integer default 0,
        done_at     text,
        position    integer default 0
    );
    create index project_task_project on project_task(project_id);

    create table project_session (
        id          integer primary key,
        project_id  integer not null references project(id) on delete cascade,
        started_at  text not null,
        minutes     integer not null check (minutes > 0),
        note        text default ''
    );
    create index project_session_started on project_session(started_at);

    create table active_timer_new (
        id          integer primary key check (id = 1),
        course_id   integer references course(id) on delete cascade,
        project_id  integer references project(id) on delete cascade,
        topic_id    integer references topic(id) on delete set null,
        started_at  text not null,
        check ((course_id is null) <> (project_id is null))
    );
    insert into active_timer_new (id, course_id, topic_id, started_at)
        select id, course_id, topic_id, started_at from active_timer;
    drop table active_timer;
    alter table active_timer_new rename to active_timer;

    create table pomodoro_run_new (
        id                integer primary key check (id = 1),
        course_id         integer references course(id) on delete cascade,
        project_id        integer references project(id) on delete cascade,
        topic_id          integer references topic(id) on delete set null,
        phase             text not null check (phase in ('focus', 'short_break', 'long_break', 'ready')),
        phase_started_at  text not null,
        block_started_at  text not null,
        completed         integer not null default 0,
        paused_at         text,
        note              text not null default '',
        check ((course_id is null) <> (project_id is null))
    );
    insert into pomodoro_run_new (id, course_id, topic_id, phase, phase_started_at, block_started_at, completed, paused_at, note)
        select id, course_id, topic_id, phase, phase_started_at, block_started_at, completed, paused_at, note from pomodoro_run;
    drop table pomodoro_run;
    alter table pomodoro_run_new rename to pomodoro_run;
    """ + "".join(_sync_columns(t) for t in PROJECT_TABLES),
    # StudyPal only: what the exam reader extracts about each question, for writing exams like them.
    # topic_tags is a JSON list; answer may now be null (the solutions don't answer it).
    """
    alter table exam_question add column parent_number text default '';
    alter table exam_question add column question_type text default '';
    alter table exam_question add column topic_tags text default '[]';
    alter table exam_question add column has_figure integer default 0;
    """,
    # StudyPal only: taking an exam, timed, and how it was graded. items is a JSON list (models.ExamAttempt).
    """
    create table exam_attempt (
        id           integer primary key,
        exam_id      integer not null references exam(id) on delete cascade,
        started_at   text not null,
        minutes      integer not null default 0,
        finished_at  text,
        seconds      integer not null default 0,
        items        text not null default '[]',
        summary      text default '',
        graded       text default ''
    );
    create index exam_attempt_exam on exam_attempt(exam_id);
    """ + _sync_columns("exam_attempt"),
    # StudyPal only: each course's banner ("" for the one made from the course, else a picture's file key).
    """
    alter table course add column banner text default '';
    """,
    # StudyPal only: notes for a subject, like a research project's, each optionally about one of its topics.
    """
    create table course_note (
        id          integer primary key,
        course_id   integer not null references course(id) on delete cascade,
        topic_id    integer references topic(id) on delete set null,
        title       text default '',
        body        text default '',
        created_at  text
    );
    create index course_note_course on course_note(course_id);
    """ + _sync_columns("course_note"),
]


def _statements(script: str) -> list[str]:
    """Split a migration into statements, keeping trigger bodies (begin ... end;) whole."""
    out, buf = [], ""
    for piece in script.split(";"):
        buf += piece + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \n;"):
                out.append(buf.strip())
            buf = ""
    return out


def _answer(answer: str | None) -> str | None:
    """An answer as stored: None (no answer known) stays None, a blank one becomes None too."""
    return answer.strip() or None if answer is not None else None


def _split_tags(text: str) -> list[str]:
    """"ml, Thesis ,ml" -> ["ml", "Thesis"]: trimmed, no blanks, no repeats (ignoring case)."""
    out: list[str] = []
    for tag in text.split(","):
        tag = tag.strip()
        if tag and tag.lower() not in (t.lower() for t in out):
            out.append(tag)
    return out


def _utc(value: str) -> datetime:
    """A sync timestamp (UTC, "2026-11-03T12:00:00.000Z") as local time, to the minute."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().replace(tzinfo=None, second=0, microsecond=0)


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso_s(value: datetime | None) -> str | None:
    """To the second, for the clock of an exam being taken."""
    return value.replace(microsecond=0).isoformat(timespec="seconds") if value else None


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    return value.isoformat()


class Store:
    def __init__(self, path: Path | str, exam_time: time = time(9, 0)) -> None:
        self.path = Path(path)
        self.exam_time = exam_time
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # The window calls in from worker threads; the Api serialises access with a lock.
        self.conn = sqlite3.connect(str(path), detect_types=0, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")
        self.conn.execute("pragma busy_timeout = 3000")  # two windows may overlap
        if str(path) != ":memory:":
            self.conn.execute("pragma journal_mode = wal")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("begin immediate")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("rollback")
            raise
        else:
            self.conn.execute("commit")

    @contextmanager
    def sync_lock(self) -> Iterator[sqlite3.Connection]:
        """Hold the database's write lock while a sync exports, merges and imports, so nothing changes
        in between. Other writers wait (up to the busy timeout)."""
        with self._tx() as c:
            yield c

    def _migrate(self) -> None:
        version = self.conn.execute("pragma user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self._tx() as c:
                for statement in _statements(script):
                    c.execute(statement)
                c.execute(f"pragma user_version = {i}")

    @property
    def schema_version(self) -> int:
        return self.conn.execute("pragma user_version").fetchone()[0]

    # ---------- courses ----------

    @staticmethod
    def _course(r: sqlite3.Row) -> Course:
        return Course(
            id=r["id"], name=r["name"], code=r["code"], cram_start=_d(r["cram_start"]),
            exam_date=_d(r["exam_date"]), color=r["color"], notes=r["notes"], done=bool(r["done"]),
            position=r["position"] or 0, banner=r["banner"] or "",
        )

    def next_color(self) -> str:
        """The first palette colour no course or project uses yet (cycles once all are taken)."""
        used = [r[0] for r in self.conn.execute("select color from course order by id")]
        used += [r[0] for r in self.conn.execute("select color from project order by id")]
        for color in COURSE_COLORS:
            if color not in used:
                return color
        return COURSE_COLORS[len(used) % len(COURSE_COLORS)]

    def add_course(self, course: Course) -> Course:
        """Adds the course and its exam deadline (which then follows the course's exam date)."""
        self._check_course(course)
        try:
            with self._tx() as c:
                course.position = course.position or self._next_place(c)
                cur = c.execute(
                    "insert into course (name, code, cram_start, exam_date, color, notes, done, position)"
                    " values (?, ?, ?, ?, ?, ?, ?, ?)",
                    (course.name.strip(), course.code.strip(), _iso(course.cram_start), _iso(course.exam_date),
                     course.color, course.notes, int(course.done), course.position),
                )
                course.id = cur.lastrowid
                c.execute(
                    "insert into deadline (course_id, title, due_at, kind, is_course_exam) values (?, ?, ?, 'exam', 1)",
                    (course.id, f"{course.code.strip()} exam", _iso(datetime.combine(course.exam_date, self.exam_time))),
                )
        except sqlite3.IntegrityError as e:
            raise StorageError(self._integrity_message(e, course.code)) from None
        return course

    def update_course(self, course: Course) -> Course:
        self._check_course(course)
        if course.id is None:
            raise StorageError("Can't update a course that hasn't been saved.")
        try:
            with self._tx() as c:
                cur = c.execute(
                    "update course set name = ?, code = ?, cram_start = ?, exam_date = ?, color = ?, notes = ?, done = ?"
                    " where id = ?",
                    (course.name.strip(), course.code.strip(), _iso(course.cram_start), _iso(course.exam_date),
                     course.color, course.notes, int(course.done), course.id),
                )
                if cur.rowcount == 0:
                    raise StorageError("That course no longer exists.")
                # Keep the exam deadline's date in step, keeping whatever time of day it has.
                row = c.execute(
                    "select id, due_at from deadline where course_id = ? and is_course_exam = 1", (course.id,)
                ).fetchone()
                if row:
                    old = datetime.fromisoformat(row["due_at"])
                    c.execute(
                        "update deadline set due_at = ?, title = ? where id = ?",
                        (_iso(datetime.combine(course.exam_date, old.time())), f"{course.code.strip()} exam", row["id"]),
                    )
        except sqlite3.IntegrityError as e:
            raise StorageError(self._integrity_message(e, course.code)) from None
        return course

    @staticmethod
    def _check_course(course: Course) -> None:
        if not course.name.strip() or not course.code.strip():
            raise StorageError("A course needs both a name and a short code.")
        if course.exam_date < course.cram_start:
            raise StorageError("The exam date can't be before the cram start date.")

    @staticmethod
    def _integrity_message(e: sqlite3.IntegrityError, code: str) -> str:
        if "course.code" in str(e):
            return f"There's already a course with the code {code.strip()!r}."
        return f"That change isn't allowed: {e}"

    def delete_course(self, course_id: int) -> None:
        """Deletes the course with all its topics, weak spots, deadlines and sessions."""
        with self._tx() as c:
            c.execute("delete from course where id = ?", (course_id,))

    def get_course(self, course_id: int) -> Course | None:
        r = self.conn.execute("select * from course where id = ?", (course_id,)).fetchone()
        return self._course(r) if r else None

    def list_courses(self, done: bool | None = None) -> list[Course]:
        """Courses in exam order: soonest exam first. done=False for active ones only, True for done only."""
        where = "" if done is None else f" where done = {int(done)}"
        return [self._course(r) for r in self.conn.execute(f"select * from course{where} order by exam_date, code")]

    def set_course_done(self, course_id: int, done: bool) -> Course:
        with self._tx() as c:
            c.execute("update course set done = ? where id = ?", (int(done), course_id))
        course = self.get_course(course_id)
        if course is None:
            raise StorageError("That course no longer exists.")
        return course

    def find_course(self, ref: str) -> Course:
        """Look a course up by code, name, or an unambiguous prefix of either (case-insensitive)."""
        ref = ref.strip().lower()
        courses = self.list_courses()
        for match in (
            lambda c: c.code.lower() == ref or c.name.lower() == ref,
            lambda c: c.code.lower().startswith(ref) or c.name.lower().startswith(ref),
        ):
            found = [c for c in courses if match(c)]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                names = ", ".join(c.code for c in found)
                raise StorageError(f"{ref!r} matches more than one course ({names}). Use the full code.")
        known = ", ".join(c.code for c in courses) or "none yet"
        raise StorageError(f"No course matches {ref!r}. Courses: {known}.")

    # ---------- topics ----------

    @staticmethod
    def _topic(r: sqlite3.Row) -> Topic:
        return Topic(
            id=r["id"], course_id=r["course_id"], title=r["title"], status=TopicStatus(r["status"]),
            confidence=r["confidence"], last_studied=_d(r["last_studied"]),
        )

    def add_topic(self, topic: Topic) -> Topic:
        self._check_topic(topic)
        with self._tx() as c:
            cur = c.execute(
                "insert into topic (course_id, title, status, confidence, last_studied) values (?, ?, ?, ?, ?)",
                (topic.course_id, topic.title.strip(), topic.status.value, topic.confidence, _iso(topic.last_studied)),
            )
            topic.id = cur.lastrowid
        return topic

    def update_topic(self, topic: Topic) -> Topic:
        self._check_topic(topic)
        with self._tx() as c:
            c.execute(
                "update topic set title = ?, status = ?, confidence = ?, last_studied = ? where id = ?",
                (topic.title.strip(), topic.status.value, topic.confidence, _iso(topic.last_studied), topic.id),
            )
        return topic

    @staticmethod
    def _check_topic(topic: Topic) -> None:
        if not topic.title.strip():
            raise StorageError("A topic needs a title.")
        if not 1 <= topic.confidence <= 5:
            raise StorageError("Confidence goes from 1 to 5.")

    def adjust_confidence(self, topic_id: int, delta: int) -> Topic:
        """Nudge confidence up or down, staying within 1–5."""
        with self._tx() as c:
            c.execute(
                "update topic set confidence = max(1, min(5, confidence + ?)) where id = ?", (delta, topic_id)
            )
        return self.get_topic(topic_id)  # type: ignore[return-value]

    def delete_topic(self, topic_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from topic where id = ?", (topic_id,))

    def get_topic(self, topic_id: int) -> Topic | None:
        r = self.conn.execute("select * from topic where id = ?", (topic_id,)).fetchone()
        return self._topic(r) if r else None

    def list_topics(self, course_id: int | None = None) -> list[Topic]:
        if course_id is None:
            rows = self.conn.execute("select * from topic order by course_id, id")
        else:
            rows = self.conn.execute("select * from topic where course_id = ? order by id", (course_id,))
        return [self._topic(r) for r in rows]

    def find_topic(self, course_id: int, ref: str) -> Topic:
        ref = ref.strip().lower()
        topics = self.list_topics(course_id)
        exact = [t for t in topics if t.title.lower() == ref]
        found = exact or [t for t in topics if t.title.lower().startswith(ref)]
        if len(found) == 1:
            return found[0]
        if not found:
            raise StorageError(f"No topic in that course matches {ref!r}.")
        raise StorageError(f"{ref!r} matches more than one topic: {', '.join(t.title for t in found)}.")

    # ---------- weak spots ----------

    @staticmethod
    def _weak(r: sqlite3.Row) -> WeakSpot:
        return WeakSpot(
            id=r["id"], course_id=r["course_id"], topic_id=r["topic_id"], description=r["description"],
            priority=Priority(r["priority"]), created_at=_dt(r["created_at"]), resolved=bool(r["resolved"]),
            resolved_at=_dt(r["resolved_at"]),
        )

    def add_weak_spot(self, weak: WeakSpot) -> WeakSpot:
        if not weak.description.strip():
            raise StorageError("Describe the weak spot in a few words.")
        with self._tx() as c:
            cur = c.execute(
                "insert into weak_spot (course_id, topic_id, description, priority, created_at, resolved, resolved_at)"
                " values (?, ?, ?, ?, ?, ?, ?)",
                (weak.course_id, weak.topic_id, weak.description.strip(), weak.priority.value, _iso(weak.created_at),
                 int(weak.resolved), _iso(weak.resolved_at)),
            )
            weak.id = cur.lastrowid
        return weak

    def update_weak_spot(self, weak: WeakSpot) -> WeakSpot:
        if not weak.description.strip():
            raise StorageError("Describe the weak spot in a few words.")
        with self._tx() as c:
            c.execute(
                "update weak_spot set topic_id = ?, description = ?, priority = ?, resolved = ?, resolved_at = ? where id = ?",
                (weak.topic_id, weak.description.strip(), weak.priority.value, int(weak.resolved),
                 _iso(weak.resolved_at), weak.id),
            )
        return weak

    def toggle_weak_spot(self, weak_id: int, now: datetime | None = None) -> WeakSpot:
        """Resolve an open weak spot, or reopen a resolved one."""
        now = now or datetime.now()
        with self._tx() as c:
            c.execute(
                "update weak_spot set resolved = 1 - resolved,"
                " resolved_at = case when resolved = 0 then ? else null end where id = ?",
                (_iso(now), weak_id),
            )
        return self.get_weak_spot(weak_id)  # type: ignore[return-value]

    def delete_weak_spot(self, weak_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from weak_spot where id = ?", (weak_id,))

    def get_weak_spot(self, weak_id: int) -> WeakSpot | None:
        r = self.conn.execute("select * from weak_spot where id = ?", (weak_id,)).fetchone()
        return self._weak(r) if r else None

    def list_weak_spots(self, course_id: int | None = None, include_resolved: bool = False,
                        active_only: bool = False) -> list[WeakSpot]:
        """Open weak spots first by priority (high first), then oldest first.
        active_only leaves out subjects marked done."""
        sql = "select * from weak_spot where 1 = 1"
        args: list[object] = []
        if active_only:
            sql += " and course_id in (select id from course where done = 0)"
        if course_id is not None:
            sql += " and course_id = ?"
            args.append(course_id)
        if not include_resolved:
            sql += " and resolved = 0"
        sql += (" order by resolved, case priority when 'high' then 0 when 'med' then 1 else 2 end, created_at, id")
        return [self._weak(r) for r in self.conn.execute(sql, args)]

    # ---------- deadlines ----------

    @staticmethod
    def _deadline(r: sqlite3.Row) -> Deadline:
        return Deadline(
            id=r["id"], course_id=r["course_id"], title=r["title"], due_at=_dt(r["due_at"]),
            kind=DeadlineKind(r["kind"]), done=bool(r["done"]), is_course_exam=bool(r["is_course_exam"]),
        )

    def add_deadline(self, deadline: Deadline) -> Deadline:
        if not deadline.title.strip():
            raise StorageError("A deadline needs a title.")
        with self._tx() as c:
            cur = c.execute(
                "insert into deadline (course_id, title, due_at, kind, done) values (?, ?, ?, ?, ?)",
                (deadline.course_id, deadline.title.strip(), _iso(deadline.due_at), deadline.kind.value,
                 int(deadline.done)),
            )
            deadline.id = cur.lastrowid
        return deadline

    def update_deadline(self, deadline: Deadline) -> Deadline:
        if not deadline.title.strip():
            raise StorageError("A deadline needs a title.")
        if deadline.is_course_exam and deadline.course_id is not None:
            course = self.get_course(deadline.course_id)
            if course and deadline.due_at.date() < course.cram_start:
                raise StorageError(f"The exam can't be before {course.code}'s cram start "
                                   f"({course.cram_start:%d.%m.%Y}).")
        with self._tx() as c:
            c.execute(
                "update deadline set course_id = ?, title = ?, due_at = ?, kind = ?, done = ? where id = ?",
                (deadline.course_id, deadline.title.strip(), _iso(deadline.due_at), deadline.kind.value,
                 int(deadline.done), deadline.id),
            )
            if deadline.is_course_exam and deadline.course_id is not None:
                # Moving the exam deadline moves the course's exam date with it.
                c.execute("update course set exam_date = ? where id = ?",
                          (_iso(deadline.due_at.date()), deadline.course_id))
        return deadline

    def toggle_deadline(self, deadline_id: int) -> Deadline:
        with self._tx() as c:
            c.execute("update deadline set done = 1 - done where id = ?", (deadline_id,))
        return self.get_deadline(deadline_id)  # type: ignore[return-value]

    def delete_deadline(self, deadline_id: int) -> None:
        r = self.conn.execute("select is_course_exam from deadline where id = ?", (deadline_id,)).fetchone()
        if r and r["is_course_exam"]:
            raise StorageError("A course's exam deadline goes away with the course. Edit or delete the course instead.")
        with self._tx() as c:
            c.execute("delete from deadline where id = ?", (deadline_id,))

    def get_deadline(self, deadline_id: int) -> Deadline | None:
        r = self.conn.execute("select * from deadline where id = ?", (deadline_id,)).fetchone()
        return self._deadline(r) if r else None

    def list_deadlines(self, course_id: int | None = None, include_done: bool = False,
                       active_only: bool = False) -> list[Deadline]:
        """Soonest first. Overdue deadlines that aren't done are included (they sort first).
        active_only leaves out deadlines of subjects marked done (standalone deadlines stay)."""
        sql = "select * from deadline where 1 = 1"
        args: list[object] = []
        if active_only:
            sql += " and (course_id is null or course_id in (select id from course where done = 0))"
        if course_id is not None:
            sql += " and course_id = ?"
            args.append(course_id)
        if not include_done:
            sql += " and done = 0"
        sql += " order by due_at, id"
        return [self._deadline(r) for r in self.conn.execute(sql, args)]

    # ---------- sessions ----------

    @staticmethod
    def _session(r: sqlite3.Row) -> Session:
        return Session(
            id=r["id"], course_id=r["course_id"], topic_id=r["topic_id"], started_at=_dt(r["started_at"]),
            minutes=r["minutes"], note=r["note"],
        )

    def log_session(self, session: Session) -> Session:
        """Record study time. Also marks the topic as studied that day and moves it to 'in progress'."""
        if session.minutes <= 0:
            raise StorageError("A session needs at least one minute.")
        with self._tx() as c:
            self._insert_session(c, session)
        return session

    @staticmethod
    def _insert_session(c: sqlite3.Connection, session: Session) -> None:
        if session.project_id is not None:
            cur = c.execute("insert into project_session (project_id, started_at, minutes, note) values (?, ?, ?, ?)",
                            (session.project_id, _iso(session.started_at), session.minutes, session.note.strip()))
            session.id = cur.lastrowid
            return
        cur = c.execute(
            "insert into session (course_id, topic_id, started_at, minutes, note) values (?, ?, ?, ?, ?)",
            (session.course_id, session.topic_id, _iso(session.started_at), session.minutes, session.note.strip()),
        )
        session.id = cur.lastrowid
        if session.topic_id is not None:
            c.execute(
                "update topic set last_studied = max(coalesce(last_studied, ''), ?),"
                " status = case status when 'not_started' then 'in_progress' else status end where id = ?",
                (_iso(session.started_at.date()), session.topic_id),
            )

    def update_session(self, session: Session) -> Session:
        if session.minutes <= 0:
            raise StorageError("A session needs at least one minute.")
        with self._tx() as c:
            if session.project_id is not None:
                c.execute("update project_session set started_at = ?, minutes = ?, note = ? where id = ?",
                          (_iso(session.started_at), session.minutes, session.note.strip(), session.id))
                return session
            c.execute(
                "update session set topic_id = ?, started_at = ?, minutes = ?, note = ? where id = ?",
                (session.topic_id, _iso(session.started_at), session.minutes, session.note.strip(), session.id),
            )
        return session

    def get_session(self, session_id: int) -> Session | None:
        r = self.conn.execute("select * from session where id = ?", (session_id,)).fetchone()
        return self._session(r) if r else None

    def delete_session(self, session_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from session where id = ?", (session_id,))

    def list_sessions(
        self, course_id: int | None = None, since: datetime | None = None, until: datetime | None = None,
        limit: int | None = None,
    ) -> list[Session]:
        """Newest first."""
        sql = "select * from session where 1 = 1"
        args: list[object] = []
        if course_id is not None:
            sql += " and course_id = ?"
            args.append(course_id)
        if since is not None:
            sql += " and started_at >= ?"
            args.append(_iso(since))
        if until is not None:
            sql += " and started_at < ?"
            args.append(_iso(until))
        sql += " order by started_at desc, id desc"
        if limit is not None:
            sql += " limit ?"
            args.append(limit)
        return [self._session(r) for r in self.conn.execute(sql, args)]

    def total_minutes(self, course_id: int | None = None) -> int:
        if course_id is None:
            row = self.conn.execute("select coalesce(sum(minutes), 0) from session").fetchone()
        else:
            row = self.conn.execute("select coalesce(sum(minutes), 0) from session where course_id = ?", (course_id,)).fetchone()
        return int(row[0])

    # ---------- the running timer ----------

    def start_timer(self, course_id: int | None, topic_id: int | None = None, now: datetime | None = None,
                    project_id: int | None = None) -> ActiveTimer:
        """Time a course (with an optional topic) or, with project_id instead, a research project."""
        if self.get_timer() is not None:
            raise StorageError("A study timer is already running. Stop it first.")
        if self.get_pomodoro() is not None:
            raise StorageError("A Pomodoro is running. Stop it before starting a plain timer.")
        self._check_target(course_id, project_id)
        timer = ActiveTimer(course_id=course_id, topic_id=topic_id if course_id else None, project_id=project_id,
                            started_at=(now or datetime.now()).replace(microsecond=0))
        with self._tx() as c:
            c.execute(
                "insert into active_timer (id, course_id, project_id, topic_id, started_at) values (1, ?, ?, ?, ?)",
                (course_id, project_id, timer.topic_id, timer.started_at.isoformat(timespec="seconds")),
            )
        return timer

    @staticmethod
    def _check_target(course_id: int | None, project_id: int | None) -> None:
        if (course_id is None) == (project_id is None):
            raise StorageError("Pick one subject or research project to work on.")

    def get_timer(self) -> ActiveTimer | None:
        r = self.conn.execute("select * from active_timer where id = 1").fetchone()
        if not r:
            return None
        return ActiveTimer(course_id=r["course_id"], topic_id=r["topic_id"], started_at=_dt(r["started_at"]),
                           project_id=r["project_id"])

    def stop_timer(self, now: datetime | None = None, note: str = "") -> Session | None:
        """Stop the running timer and log it. Returns None (and logs nothing) if it ran under a minute."""
        timer = self.get_timer()
        if timer is None:
            raise StorageError("No study timer is running.")
        minutes = round(((now or datetime.now()) - timer.started_at).total_seconds() / 60)
        session = None
        if minutes >= 1:
            session = Session(course_id=timer.course_id, topic_id=timer.topic_id, started_at=timer.started_at,
                              minutes=minutes, note=note, project_id=timer.project_id)
        # Clearing the timer and logging the session happen together, so neither can be lost.
        with self._tx() as c:
            c.execute("delete from active_timer where id = 1")
            if session is not None:
                self._insert_session(c, session)
        return session

    def cancel_timer(self) -> None:
        with self._tx() as c:
            c.execute("delete from active_timer where id = 1")

    # ---------- Pomodoro ----------
    # Every method settles the run first: focus blocks that have finished since the last look are
    # logged as sessions in the same transaction that saves the run, so a block is logged exactly once.

    def get_pomodoro(self) -> PomodoroRun | None:
        r = self.conn.execute("select * from pomodoro_run where id = 1").fetchone()
        if not r:
            return None
        return PomodoroRun(
            course_id=r["course_id"], topic_id=r["topic_id"], phase=PomoPhase(r["phase"]),
            phase_started_at=_dt(r["phase_started_at"]), block_started_at=_dt(r["block_started_at"]),
            completed=r["completed"], paused_at=_dt(r["paused_at"]), note=r["note"], project_id=r["project_id"],
        )

    @staticmethod
    def _write_pomodoro(c: sqlite3.Connection, run: PomodoroRun) -> None:
        def ts(value: datetime | None) -> str | None:
            return value.isoformat(timespec="seconds") if value else None

        c.execute(
            "insert or replace into pomodoro_run"
            " (id, course_id, project_id, topic_id, phase, phase_started_at, block_started_at, completed, paused_at, note)"
            " values (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run.course_id, run.project_id, run.topic_id, run.phase.value, ts(run.phase_started_at),
             ts(run.block_started_at), run.completed, ts(run.paused_at), run.note),
        )

    def _log_blocks(self, c: sqlite3.Connection, run: PomodoroRun, blocks: list[pomo.FinishedBlock]) -> list[Session]:
        sessions = []
        for b in blocks:
            note = f"Pomodoro {b.number}" + (" (stopped early)" if b.partial else "") + (f" · {run.note}" if run.note else "")
            session = Session(course_id=run.course_id, topic_id=run.topic_id, started_at=b.started_at,
                              minutes=b.minutes, note=note, project_id=run.project_id)
            self._insert_session(c, session)
            sessions.append(session)
        return sessions

    def start_pomodoro(self, course_id: int | None, topic_id: int | None = None, now: datetime | None = None,
                       note: str = "", project_id: int | None = None) -> PomodoroRun:
        if self.get_pomodoro() is not None:
            raise StorageError("A Pomodoro is already running. Stop it first.")
        if self.get_timer() is not None:
            raise StorageError("A study timer is running. Stop it before starting a Pomodoro.")
        self._check_target(course_id, project_id)
        run = pomo.start(course_id, now or datetime.now(), topic_id if course_id else None, note.strip(), project_id)
        with self._tx() as c:
            self._write_pomodoro(c, run)
        return run

    def _change_pomodoro(self, now: datetime, settings: PomodoroSettings, change=None) -> tuple[PomodoroRun | None, list[Session]]:
        run = self.get_pomodoro()
        if run is None:
            return None, []
        settled, blocks = pomo.advance(run, now, settings)
        if change is not None:
            settled = change(settled)
        if settled == run and not blocks:
            return run, []
        with self._tx() as c:
            # Re-read inside the transaction: another process may have settled this run a moment ago.
            current = self.get_pomodoro()
            if current != run:
                return current, []
            self._write_pomodoro(c, settled)
            sessions = self._log_blocks(c, settled, blocks)
        return settled, sessions

    def settle_pomodoro(self, now: datetime | None = None,
                        settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun | None, list[Session]]:
        """Log any focus blocks that have finished. Returns the current run and the sessions just logged."""
        return self._change_pomodoro(now or datetime.now(), settings)

    def pomodoro_next(self, now: datetime | None = None,
                      settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun, list[Session]]:
        """Start the next focus block (also skips the rest of a break)."""
        now = now or datetime.now()
        run, sessions = self._change_pomodoro(now, settings, lambda r: pomo.next_focus(r, now))
        if run is None:
            raise StorageError("No Pomodoro is running.")
        return run, sessions

    def pomodoro_break(self, now: datetime | None = None,
                       settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun, list[Session]]:
        """End the focus block (logging it, extra minutes included) and start the break."""
        now = now or datetime.now()
        with self._tx() as c:
            run = self.get_pomodoro()
            if run is None:
                raise StorageError("No Pomodoro is running.")
            if run.phase is not PomoPhase.FOCUS:
                return run, []
            run, blocks = pomo.take_break(run, now, settings)
            self._write_pomodoro(c, run)
            return run, self._log_blocks(c, run, blocks)

    def pause_pomodoro(self, now: datetime | None = None,
                       settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun, list[Session]]:
        now = now or datetime.now()
        run, sessions = self._change_pomodoro(now, settings, lambda r: pomo.pause(r, now))
        if run is None:
            raise StorageError("No Pomodoro is running.")
        return run, sessions

    def resume_pomodoro(self, now: datetime | None = None,
                        settings: PomodoroSettings = PomodoroSettings()) -> tuple[PomodoroRun, list[Session]]:
        now = now or datetime.now()
        run, sessions = self._change_pomodoro(now, settings, lambda r: pomo.resume(r, now))
        if run is None:
            raise StorageError("No Pomodoro is running.")
        return run, sessions

    def stop_pomodoro(self, now: datetime | None = None,
                      settings: PomodoroSettings = PomodoroSettings()) -> list[Session]:
        """End the run, logging finished blocks and the part of a block in progress (a minute or more)."""
        with self._tx() as c:
            # Read inside the transaction so a concurrent settle can't make us log a block twice.
            run = self.get_pomodoro()
            if run is None:
                raise StorageError("No Pomodoro is running.")
            blocks = pomo.stop(run, now or datetime.now(), settings)
            c.execute("delete from pomodoro_run where id = 1")
            return self._log_blocks(c, run, blocks)

    # ---------- reading lists ----------

    @staticmethod
    def _source(r: sqlite3.Row) -> Source:
        return Source(id=r["id"], course_id=r["course_id"], title=r["title"], author=r["author"],
                      kind=r["kind"] or "book", **{f: r[f] or "" for f in _CITE_FIELDS[1:]}, topic_id=r["topic_id"])

    @staticmethod
    def _chapter(r: sqlite3.Row) -> Chapter:
        return Chapter(id=r["id"], source_id=r["source_id"], number=r["number"], title=r["title"], topic_id=r["topic_id"],
                       read=bool(r["read"]), read_at=_dt(r["read_at"]))

    @staticmethod
    def _section(r: sqlite3.Row) -> Section:
        return Section(id=r["id"], chapter_id=r["chapter_id"], number=r["number"], title=r["title"],
                       required=bool(r["required"]), read=bool(r["read"]), read_at=_dt(r["read_at"]),
                       topic_id=r["topic_id"])

    def add_source(self, source: Source) -> Source:
        if not source.title.strip():
            raise StorageError("A source needs a title, e.g. the book's name.")
        with self._tx() as c:
            pos = c.execute("select coalesce(max(position), -1) + 1 from source where course_id = ?",
                            (source.course_id,)).fetchone()[0]
            cur = c.execute(
                f"insert into source (course_id, title, author, position, topic_id, {', '.join(_CITE_FIELDS)})"
                f" values (?, ?, ?, ?, ?, {', '.join('?' * len(_CITE_FIELDS))})",
                (source.course_id, source.title.strip(), source.author.strip(), pos, source.topic_id,
                 *(str(getattr(source, f)).strip() for f in _CITE_FIELDS)))
            source.id = cur.lastrowid
        return source

    def update_source(self, source: Source) -> Source:
        if not source.title.strip():
            raise StorageError("A source needs a title, e.g. the book's name.")
        with self._tx() as c:
            c.execute(f"update source set title = ?, author = ?, topic_id = ?, {', '.join(f + ' = ?' for f in _CITE_FIELDS)}"
                      " where id = ?",
                      (source.title.strip(), source.author.strip(), source.topic_id,
                       *(str(getattr(source, f)).strip() for f in _CITE_FIELDS), source.id))
        return source

    def delete_source(self, source_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from source where id = ?", (source_id,))

    def get_source(self, source_id: int) -> Source | None:
        r = self.conn.execute("select * from source where id = ?", (source_id,)).fetchone()
        return self._source(r) if r else None

    def list_sources(self, course_id: int) -> list[Source]:
        rows = self.conn.execute("select * from source where course_id = ? order by position, id", (course_id,))
        return [self._source(r) for r in rows]

    def find_source(self, course_id: int, ref: str | None) -> Source:
        """By title prefix (case-insensitive); with no ref, the course's only source."""
        sources = self.list_sources(course_id)
        if not sources:
            raise StorageError("That course has no reading list yet. Add a source (a book or notes) first.")
        if ref is None:
            if len(sources) == 1:
                return sources[0]
            raise StorageError(f"That course has {len(sources)} sources; say which: {', '.join(s.title for s in sources)}.")
        found = [s for s in sources if s.title.lower().startswith(ref.strip().lower())]
        if len(found) == 1:
            return found[0]
        raise StorageError(f"No source matches {ref!r}." if not found else f"{ref!r} matches more than one source.")

    def _chapter_for(self, c: sqlite3.Connection, source_id: int, number: str, title: str = "",
                     topic_id: int | None = None) -> int:
        """The chapter with this number in the source, created if it's new (an empty title never overwrites)."""
        row = c.execute("select id, title from chapter where source_id = ? and number = ?", (source_id, number)).fetchone()
        if row:
            if title and not row["title"]:
                c.execute("update chapter set title = ? where id = ?", (title, row["id"]))
            if topic_id is not None:
                c.execute("update chapter set topic_id = ? where id = ?", (topic_id, row["id"]))
            return row["id"]
        pos = c.execute("select coalesce(max(position), -1) + 1 from chapter where source_id = ?", (source_id,)).fetchone()[0]
        return c.execute("insert into chapter (source_id, number, title, topic_id, position) values (?, ?, ?, ?, ?)",
                         (source_id, number, title, topic_id, pos)).lastrowid

    def _add_sections(self, c: sqlite3.Connection, chapter_id: int, sections: list[tuple[str, str]],
                      required: bool) -> int:
        """Adds the sections the chapter doesn't have yet (keeping existing ones as they are). Returns how many were new."""
        existing = {r[0] for r in c.execute("select number from section where chapter_id = ?", (chapter_id,))}
        pos = c.execute("select coalesce(max(position), -1) + 1 from section where chapter_id = ?", (chapter_id,)).fetchone()[0]
        added = 0
        for number, title in sections:
            if number in existing:
                if title:
                    c.execute("update section set title = ? where chapter_id = ? and number = ? and title = ''",
                              (title, chapter_id, number))
                continue
            c.execute("insert into section (chapter_id, number, title, required, position) values (?, ?, ?, ?, ?)",
                      (chapter_id, number, title, int(required), pos))
            existing.add(number)
            pos += 1
            added += 1
        return added

    def add_chapter(self, source_id: int, number: str, title: str = "", section_numbers: list[str] | None = None,
                    topic_id: int | None = None, required: bool = True) -> tuple[Chapter, int]:
        """Add (or extend) a chapter with sections by number. Returns the chapter and how many sections were new."""
        number = number.strip().rstrip(".")
        if not number:
            raise StorageError("A chapter needs a number, like 6.")
        with self._tx() as c:
            chapter_id = self._chapter_for(c, source_id, number, title.strip(), topic_id)
            added = self._add_sections(c, chapter_id, [(n, "") for n in section_numbers or []], required)
        return self.get_chapter(chapter_id), added  # type: ignore[return-value]

    def import_toc(self, source_id: int, chapters: list[TocChapter], required: bool = True,
                   topic_id: int | None = None) -> tuple[int, int]:
        """Add a pasted table of contents. Existing chapters and sections are kept; returns (new chapters, new sections)."""
        with self._tx() as c:
            before = c.execute("select count(*) from chapter where source_id = ?", (source_id,)).fetchone()[0]
            new_sections = 0
            for ch in chapters:
                chapter_id = self._chapter_for(c, source_id, ch.number, ch.title, topic_id)
                new_sections += self._add_sections(c, chapter_id, ch.sections, required)
            after = c.execute("select count(*) from chapter where source_id = ?", (source_id,)).fetchone()[0]
        return after - before, new_sections

    def update_chapter(self, chapter: Chapter) -> Chapter:
        if not chapter.number.strip():
            raise StorageError("A chapter needs a number, like 6.")
        try:
            with self._tx() as c:
                c.execute("update chapter set number = ?, title = ?, topic_id = ? where id = ?",
                          (chapter.number.strip(), chapter.title.strip(), chapter.topic_id, chapter.id))
        except sqlite3.IntegrityError:
            raise StorageError(f"That source already has a chapter {chapter.number}.") from None
        return chapter

    def delete_chapter(self, chapter_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from chapter where id = ?", (chapter_id,))

    def get_chapter(self, chapter_id: int) -> Chapter | None:
        r = self.conn.execute("select * from chapter where id = ?", (chapter_id,)).fetchone()
        return self._chapter(r) if r else None

    def update_section(self, section: Section) -> Section:
        if not section.number.strip():
            raise StorageError("A section needs a number, like 6.1.")
        try:
            with self._tx() as c:
                c.execute("update section set number = ?, title = ?, required = ?, topic_id = ? where id = ?",
                          (section.number.strip(), section.title.strip(), int(section.required), section.topic_id,
                           section.id))
        except sqlite3.IntegrityError:
            raise StorageError(f"That chapter already has a section {section.number}.") from None
        return section

    def delete_section(self, section_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from section where id = ?", (section_id,))

    def get_section(self, section_id: int) -> Section | None:
        r = self.conn.execute("select * from section where id = ?", (section_id,)).fetchone()
        return self._section(r) if r else None

    def reading_list(self, course_id: int) -> list[tuple[Source, list[tuple[Chapter, list[Section]]]]]:
        """The course's sources with their chapters and sections, in reading order."""
        out = []
        for source in self.list_sources(course_id):
            chapters = [self._chapter(r) for r in self.conn.execute(
                "select * from chapter where source_id = ? order by position, id", (source.id,))]
            chapters.sort(key=lambda ch: number_key(ch.number))
            entries = []
            for ch in chapters:
                sections = [self._section(r) for r in self.conn.execute(
                    "select * from section where chapter_id = ?", (ch.id,))]
                sections.sort(key=lambda s: number_key(s.number))
                entries.append((ch, sections))
            out.append((source, entries))
        return out

    def _set_read(self, section_ids: list[int], read: bool, now: datetime) -> None:
        """Mark sections read or unread. Reading counts as studying the topic that day, and when a not-started
        topic's required reading is all done, the topic moves to in progress."""
        if not section_ids:
            return
        marks = ",".join("?" * len(section_ids))
        with self._tx() as c:
            c.execute(f"update section set read = ?, read_at = ? where id in ({marks})",
                      (int(read), _iso(now) if read else None, *section_ids))
            if read:
                topics = {r[0] for r in c.execute(
                    f"select coalesce(s.topic_id, ch.topic_id, src.topic_id) from section s"
                    f" join chapter ch on ch.id = s.chapter_id join source src on src.id = ch.source_id"
                    f" where s.id in ({marks})", section_ids)}
                self._studied(c, topics, now)

    @staticmethod
    def _studied(c: sqlite3.Connection, topics: set[int | None], now: datetime) -> None:
        """Reading something counts as studying its topic that day; once all of a not-started topic's needed
        reading is done, it moves to in progress. Needed reading is its required sections, plus chapters
        without sections."""
        for topic_id in topics - {None}:
            c.execute("update topic set last_studied = max(coalesce(last_studied, ''), ?) where id = ?",
                      (_iso(now.date()), topic_id))
            left = c.execute(
                "select (select count(*) from section s join chapter ch on ch.id = s.chapter_id"
                "        join source src on src.id = ch.source_id"
                "        where coalesce(s.topic_id, ch.topic_id, src.topic_id) = ?1 and s.required = 1 and s.read = 0)"
                "     + (select count(*) from chapter ch join source src on src.id = ch.source_id"
                "        where coalesce(ch.topic_id, src.topic_id) = ?1 and coalesce(ch.read, 0) = 0"
                "        and not exists (select 1 from section s where s.chapter_id = ch.id))",
                (topic_id,)).fetchone()[0]
            if left == 0:
                c.execute("update topic set status = 'in_progress' where id = ? and status = 'not_started'", (topic_id,))

    def toggle_section_read(self, section_id: int, now: datetime | None = None) -> Section:
        section = self.get_section(section_id)
        if section is None:
            raise StorageError("That section no longer exists.")
        self._set_read([section_id], not section.read, now or datetime.now())
        return self.get_section(section_id)  # type: ignore[return-value]

    def set_chapter_read(self, chapter_id: int, read: bool, now: datetime | None = None) -> None:
        """Mark every required section of a chapter read (or unread); a chapter without sections is
        marked itself."""
        now = now or datetime.now()
        has_sections = self.conn.execute("select 1 from section where chapter_id = ? limit 1", (chapter_id,)).fetchone()
        if has_sections:
            ids = [r[0] for r in self.conn.execute(
                "select id from section where chapter_id = ? and required = 1", (chapter_id,))]
            self._set_read(ids, read, now)
            return
        with self._tx() as c:
            c.execute("update chapter set read = ?, read_at = ? where id = ?", (int(read), _iso(now) if read else None, chapter_id))
            if read:
                topic = c.execute("select coalesce(ch.topic_id, src.topic_id) from chapter ch"
                                  " join source src on src.id = ch.source_id where ch.id = ?", (chapter_id,)).fetchone()
                self._studied(c, {topic[0]} if topic else set(), now)

    def mark_read(self, course_id: int, numbers: list[str], source_id: int | None = None,
                  now: datetime | None = None) -> list[Section]:
        """Mark sections read by number ('6.1'); used by the CLI. Unknown numbers raise an error naming them."""
        found: dict[str, Section] = {}
        for source, chapters in self.reading_list(course_id):
            if source_id is not None and source.id != source_id:
                continue
            for _, sections in chapters:
                for s in sections:
                    if s.number in numbers:
                        if s.number in found:
                            raise StorageError(f"Section {s.number} is in more than one source; use --source.")
                        found[s.number] = s
        missing = [n for n in numbers if n not in found]
        if missing:
            raise StorageError(f"No section {', '.join(missing)} in that reading list.")
        self._set_read([s.id for s in found.values()], True, now or datetime.now())
        return [self.get_section(s.id) for s in found.values()]  # type: ignore[misc]

    def set_required(self, section_ids: list[int], required: bool) -> None:
        if not section_ids:
            return
        with self._tx() as c:
            c.execute(f"update section set required = ? where id in ({','.join('?' * len(section_ids))})",
                      (int(required), *section_ids))

    def reading_progress(self, course_id: int) -> ReadingProgress:
        return progress(s for _, chapters in self.reading_list(course_id) for ch, sections in chapters
                        for s in reading_units(ch, sections))

    def reading_by_topic(self, course_id: int) -> dict[int, ReadingProgress]:
        """Required-reading progress for each topic that has reading linked to it."""
        by_topic: dict[int, list[Section]] = {}
        for source, chapters in self.reading_list(course_id):
            for chapter, sections in chapters:
                for s in reading_units(chapter, sections):
                    topic = next((t for t in (s.topic_id, chapter.topic_id, source.topic_id) if t is not None), None)
                    if topic is not None:
                        by_topic.setdefault(topic, []).append(s)
        return {t: progress(ss) for t, ss in by_topic.items()}

    # ---------- exams ----------

    @staticmethod
    def _exam(r: sqlite3.Row) -> Exam:
        return Exam(id=r["id"], course_id=r["course_id"], title=r["title"], kind=r["kind"] or "past",
                    taken_on=r["taken_on"] or "", score=r["score"] or "", notes=r["notes"] or "",
                    created_at=_dt(r["created_at"]) or datetime.now().replace(second=0, microsecond=0))

    @staticmethod
    def _exam_file(r: sqlite3.Row) -> ExamFile:
        return ExamFile(id=r["id"], exam_id=r["exam_id"], name=r["name"], key=r["key"], mime=r["mime"],
                        size=r["size"] or 0, role=r["role"] or "exam")

    @staticmethod
    def _question(r: sqlite3.Row) -> ExamQuestion:
        try:
            tags = [str(t) for t in json.loads(r["topic_tags"] or "[]") if str(t).strip()]
        except (ValueError, TypeError):
            tags = []
        return ExamQuestion(id=r["id"], exam_id=r["exam_id"], number=r["number"] or "", prompt=r["prompt"] or "",
                            answer=r["answer"], marks=r["marks"] or "", topic_id=r["topic_id"],
                            result=r["result"] or "", note=r["note"] or "", why=r["why"] or "",
                            parent_number=r["parent_number"] or "", question_type=r["question_type"] or "",
                            topic_tags=tags, has_figure=bool(r["has_figure"]))

    def add_exam(self, exam: Exam) -> Exam:
        if not exam.title.strip():
            raise StorageError("Give the exam a name, e.g. “Exam spring 2024”.")
        with self._tx() as c:
            cur = c.execute("insert into exam (course_id, title, kind, taken_on, score, notes, created_at)"
                            " values (?, ?, ?, ?, ?, ?, ?)",
                            (exam.course_id, exam.title.strip(), exam.kind, exam.taken_on.strip(), exam.score.strip(),
                             exam.notes.strip(), _iso(exam.created_at)))
            exam.id = cur.lastrowid
        return exam

    def update_exam(self, exam: Exam) -> Exam:
        if not exam.title.strip():
            raise StorageError("Give the exam a name, e.g. “Exam spring 2024”.")
        with self._tx() as c:
            c.execute("update exam set title = ?, taken_on = ?, score = ?, notes = ? where id = ?",
                      (exam.title.strip(), exam.taken_on.strip(), exam.score.strip(), exam.notes.strip(), exam.id))
        return exam

    def delete_exam(self, exam_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from exam where id = ?", (exam_id,))

    def get_exam(self, exam_id: int) -> Exam | None:
        r = self.conn.execute("select * from exam where id = ?", (exam_id,)).fetchone()
        return self._exam(r) if r else None

    def list_exams(self, course_id: int) -> list[Exam]:
        """Newest first."""
        rows = self.conn.execute("select * from exam where course_id = ? order by created_at desc, uid desc", (course_id,))
        return [self._exam(r) for r in rows]

    def add_exam_file(self, f: ExamFile) -> ExamFile:
        with self._tx() as c:
            cur = c.execute("insert into exam_file (exam_id, name, key, mime, size, role) values (?, ?, ?, ?, ?, ?)",
                            (f.exam_id, f.name, f.key, f.mime, f.size, f.role))
            f.id = cur.lastrowid
        return f

    def delete_exam_file(self, file_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from exam_file where id = ?", (file_id,))

    def get_exam_file(self, file_id: int) -> ExamFile | None:
        r = self.conn.execute("select * from exam_file where id = ?", (file_id,)).fetchone()
        return self._exam_file(r) if r else None

    def list_exam_files(self, exam_id: int) -> list[ExamFile]:
        rows = self.conn.execute("select * from exam_file where exam_id = ? order by id", (exam_id,))
        return [self._exam_file(r) for r in rows]

    def file_keys(self) -> set[str]:
        """Every file any exam or course banner uses, for keeping the files folder (and the cloud's copy) tidy."""
        return ({r[0] for r in self.conn.execute("select distinct key from exam_file")}
                | {r[0] for r in self.conn.execute("select banner from course where banner like '%.%'")})

    def set_course_banner(self, course_id: int, banner: str) -> None:
        with self._tx() as c:
            if c.execute("update course set banner = ? where id = ?", (banner, course_id)).rowcount == 0:
                raise StorageError("That course no longer exists.")

    def add_question(self, q: ExamQuestion) -> ExamQuestion:
        with self._tx() as c:
            q.id = self._insert_question(c, q)
        return q

    @staticmethod
    def _insert_question(c: sqlite3.Connection, q: ExamQuestion) -> int:
        pos = c.execute("select coalesce(max(position), -1) + 1 from exam_question where exam_id = ?",
                        (q.exam_id,)).fetchone()[0]
        cur = c.execute("insert into exam_question (exam_id, number, prompt, answer, marks, topic_id, result, note, why,"
                        " position, parent_number, question_type, topic_tags, has_figure)"
                        " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (q.exam_id, q.number.strip(), q.prompt.strip(), _answer(q.answer), q.marks.strip(), q.topic_id,
                         q.result, q.note.strip(), q.why.strip(), pos, q.parent_number.strip(), q.question_type,
                         json.dumps(q.topic_tags, ensure_ascii=False), int(q.has_figure)))
        return cur.lastrowid  # type: ignore[return-value]

    def replace_questions(self, exam_id: int, questions: list[ExamQuestion]) -> None:
        """Swap an exam's questions for a new list (after Groq has read it again)."""
        with self._tx() as c:
            c.execute("delete from exam_question where exam_id = ?", (exam_id,))
            for q in questions:
                q.exam_id = exam_id
                q.id = self._insert_question(c, q)

    def update_question(self, q: ExamQuestion) -> ExamQuestion:
        if q.result not in ("", "ok", "partial", "missed"):
            raise StorageError("That isn't a way a question can go.")
        with self._tx() as c:
            c.execute("update exam_question set number = ?, prompt = ?, answer = ?, marks = ?, topic_id = ?, result = ?,"
                      " note = ?, why = ?, parent_number = ?, question_type = ?, topic_tags = ?, has_figure = ?"
                      " where id = ?",
                      (q.number.strip(), q.prompt.strip(), _answer(q.answer), q.marks.strip(), q.topic_id, q.result,
                       q.note.strip(), q.why.strip(), q.parent_number.strip(), q.question_type,
                       json.dumps(q.topic_tags, ensure_ascii=False), int(q.has_figure), q.id))
        return q

    def delete_question(self, question_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from exam_question where id = ?", (question_id,))

    def get_question(self, question_id: int) -> ExamQuestion | None:
        r = self.conn.execute("select * from exam_question where id = ?", (question_id,)).fetchone()
        return self._question(r) if r else None

    def list_questions(self, exam_id: int) -> list[ExamQuestion]:
        rows = self.conn.execute("select * from exam_question where exam_id = ? order by position, id", (exam_id,))
        return [self._question(r) for r in rows]

    # ---------- taking exams ----------

    @staticmethod
    def _attempt(r: sqlite3.Row) -> ExamAttempt:
        try:
            items = [i for i in json.loads(r["items"] or "[]") if isinstance(i, dict)]
        except (ValueError, TypeError):
            items = []
        return ExamAttempt(id=r["id"], exam_id=r["exam_id"], started_at=_dt(r["started_at"]) or datetime.now(),
                           minutes=r["minutes"] or 0, finished_at=_dt(r["finished_at"]), seconds=r["seconds"] or 0,
                           items=items, summary=r["summary"] or "", graded=r["graded"] or "")

    def add_attempt(self, a: ExamAttempt) -> ExamAttempt:
        with self._tx() as c:
            cur = c.execute("insert into exam_attempt (exam_id, started_at, minutes, finished_at, seconds, items,"
                            " summary, graded) values (?, ?, ?, ?, ?, ?, ?, ?)",
                            (a.exam_id, _iso_s(a.started_at), a.minutes, _iso_s(a.finished_at), a.seconds,
                             json.dumps(a.items, ensure_ascii=False), a.summary, a.graded))
            a.id = cur.lastrowid
        return a

    def update_attempt(self, a: ExamAttempt) -> ExamAttempt:
        with self._tx() as c:
            c.execute("update exam_attempt set minutes = ?, finished_at = ?, seconds = ?, items = ?, summary = ?,"
                      " graded = ? where id = ?",
                      (a.minutes, _iso_s(a.finished_at), a.seconds, json.dumps(a.items, ensure_ascii=False), a.summary,
                       a.graded, a.id))
        return a

    def get_attempt(self, attempt_id: int) -> ExamAttempt | None:
        r = self.conn.execute("select * from exam_attempt where id = ?", (attempt_id,)).fetchone()
        return self._attempt(r) if r else None

    def list_attempts(self, exam_id: int) -> list[ExamAttempt]:
        """Newest first."""
        rows = self.conn.execute("select * from exam_attempt where exam_id = ? order by started_at desc, id desc",
                                 (exam_id,))
        return [self._attempt(r) for r in rows]

    def delete_attempt(self, attempt_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from exam_attempt where id = ?", (attempt_id,))

    # ---------- research projects ----------

    def _next_place(self, c: sqlite3.Connection) -> int:
        """Where a new course or project goes in the overview's list: last, once you've put the list in an
        order of your own; until then 0, so courses keep listing soonest exam first."""
        top = c.execute("select max(coalesce(position, 0)) from (select position from course"
                        " union all select position from project)").fetchone()[0] or 0
        return top + 1 if top else 0

    def reorder(self, items: list[tuple[str, int]]) -> None:
        """Put the overview's list in this order: [("course", id) or ("project", id), ...]."""
        with self._tx() as c:
            for place, (kind, item_id) in enumerate(items, start=1):
                if kind not in ("course", "project"):
                    raise StorageError("Only subjects and research projects can be moved.")
                c.execute(f"update {kind} set position = ? where id = ? and coalesce(position, 0) != ?",
                          (place, item_id, place))

    @staticmethod
    def _project(r: sqlite3.Row) -> Project:
        return Project(id=r["id"], title=r["title"], description=r["description"] or "", status=r["status"] or "active",
                       tags=_split_tags(r["tags"] or ""), start_on=_d(r["start_on"]), end_on=_d(r["end_on"]),
                       color=r["color"], position=r["position"] or 0,
                       created_at=_dt(r["created_at"]) or datetime.now().replace(second=0, microsecond=0))

    @staticmethod
    def _check_project(p: Project) -> None:
        if not p.title.strip():
            raise StorageError("Give the project a title.")
        if p.status not in PROJECT_STATUSES:
            raise StorageError("Pick a status: idea, active, paused or done.")
        if p.start_on and p.end_on and p.end_on < p.start_on:
            raise StorageError("The target date can't be before the start.")

    def add_project(self, p: Project) -> Project:
        self._check_project(p)
        with self._tx() as c:
            p.position = p.position or self._next_place(c)
            cur = c.execute("insert into project (title, description, status, tags, start_on, end_on, color, position,"
                            " created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (p.title.strip(), p.description.strip(), p.status, ", ".join(p.tags), _iso(p.start_on),
                             _iso(p.end_on), p.color, p.position, _iso(p.created_at)))
            p.id = cur.lastrowid
        return p

    def update_project(self, p: Project) -> Project:
        self._check_project(p)
        with self._tx() as c:
            cur = c.execute("update project set title = ?, description = ?, status = ?, tags = ?, start_on = ?, end_on = ?,"
                            " color = ? where id = ?",
                            (p.title.strip(), p.description.strip(), p.status, ", ".join(p.tags), _iso(p.start_on),
                             _iso(p.end_on), p.color, p.id))
            if cur.rowcount == 0:
                raise StorageError("That project no longer exists.")
        return p

    def set_project_status(self, project_id: int, status: str) -> Project:
        p = self.get_project(project_id)
        if p is None:
            raise StorageError("That project no longer exists.")
        p.status = status
        return self.update_project(p)

    def delete_project(self, project_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from project where id = ?", (project_id,))

    def get_project(self, project_id: int) -> Project | None:
        r = self.conn.execute("select * from project where id = ?", (project_id,)).fetchone()
        return self._project(r) if r else None

    def list_projects(self) -> list[Project]:
        """In the order they were added (the overview sorts them in with the courses)."""
        return [self._project(r) for r in self.conn.execute("select * from project order by created_at, uid")]

    # a subject's notes

    @staticmethod
    def _course_note(r: sqlite3.Row) -> CourseNote:
        updated = r["updated_at"]
        return CourseNote(id=r["id"], course_id=r["course_id"], topic_id=r["topic_id"], title=r["title"] or "",
                          body=r["body"] or "",
                          created_at=_dt(r["created_at"]) or datetime.now().replace(second=0, microsecond=0),
                          updated_at=_utc(updated) if updated else None)

    def add_course_note(self, n: CourseNote) -> CourseNote:
        with self._tx() as c:
            cur = c.execute("insert into course_note (course_id, topic_id, title, body, created_at) values (?, ?, ?, ?, ?)",
                            (n.course_id, n.topic_id, n.title.strip(), n.body, _iso(n.created_at)))
            n.id = cur.lastrowid
        return self.get_course_note(n.id)  # type: ignore[arg-type,return-value]

    def update_course_note(self, n: CourseNote) -> CourseNote:
        with self._tx() as c:
            cur = c.execute("update course_note set title = ?, body = ?, topic_id = ? where id = ?",
                            (n.title.strip(), n.body, n.topic_id, n.id))
            if cur.rowcount == 0:
                raise StorageError("That note no longer exists.")
        return self.get_course_note(n.id)  # type: ignore[arg-type,return-value]

    def delete_course_note(self, note_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from course_note where id = ?", (note_id,))

    def get_course_note(self, note_id: int) -> CourseNote | None:
        r = self.conn.execute("select * from course_note where id = ?", (note_id,)).fetchone()
        return self._course_note(r) if r else None

    def list_course_notes(self, course_id: int) -> list[CourseNote]:
        """Most recently changed first."""
        rows = self.conn.execute("select * from course_note where course_id = ? order by updated_at desc, id desc",
                                 (course_id,))
        return [self._course_note(r) for r in rows]

    # a project's notes

    @staticmethod
    def _note(r: sqlite3.Row) -> ProjectNote:
        updated = r["updated_at"]
        return ProjectNote(id=r["id"], project_id=r["project_id"], title=r["title"] or "", body=r["body"] or "",
                           created_at=_dt(r["created_at"]) or datetime.now().replace(second=0, microsecond=0),
                           updated_at=_utc(updated) if updated else None)

    def add_note(self, n: ProjectNote) -> ProjectNote:
        with self._tx() as c:
            cur = c.execute("insert into project_note (project_id, title, body, created_at) values (?, ?, ?, ?)",
                            (n.project_id, n.title.strip(), n.body, _iso(n.created_at)))
            n.id = cur.lastrowid
        return self.get_note(n.id)  # type: ignore[arg-type,return-value]

    def update_note(self, n: ProjectNote) -> ProjectNote:
        with self._tx() as c:
            cur = c.execute("update project_note set title = ?, body = ? where id = ?", (n.title.strip(), n.body, n.id))
            if cur.rowcount == 0:
                raise StorageError("That note no longer exists.")
        return self.get_note(n.id)  # type: ignore[arg-type,return-value]

    def delete_note(self, note_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from project_note where id = ?", (note_id,))

    def get_note(self, note_id: int) -> ProjectNote | None:
        r = self.conn.execute("select * from project_note where id = ?", (note_id,)).fetchone()
        return self._note(r) if r else None

    def list_notes(self, project_id: int) -> list[ProjectNote]:
        """Most recently changed first."""
        rows = self.conn.execute("select * from project_note where project_id = ? order by updated_at desc, id desc",
                                 (project_id,))
        return [self._note(r) for r in rows]

    # journal

    @staticmethod
    def _entry(r: sqlite3.Row) -> ProjectEntry:
        return ProjectEntry(id=r["id"], project_id=r["project_id"], day=_d(r["day"]), body=r["body"] or "")  # type: ignore[arg-type]

    def add_entry(self, e: ProjectEntry) -> ProjectEntry:
        if not e.body.strip():
            raise StorageError("Write something in the entry.")
        with self._tx() as c:
            e.id = c.execute("insert into project_entry (project_id, day, body) values (?, ?, ?)",
                             (e.project_id, _iso(e.day), e.body.strip())).lastrowid
        return e

    def update_entry(self, e: ProjectEntry) -> ProjectEntry:
        if not e.body.strip():
            raise StorageError("Write something in the entry.")
        with self._tx() as c:
            c.execute("update project_entry set day = ?, body = ? where id = ?", (_iso(e.day), e.body.strip(), e.id))
        return e

    def delete_entry(self, entry_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from project_entry where id = ?", (entry_id,))

    def get_entry(self, entry_id: int) -> ProjectEntry | None:
        r = self.conn.execute("select * from project_entry where id = ?", (entry_id,)).fetchone()
        return self._entry(r) if r else None

    def list_entries(self, project_id: int) -> list[ProjectEntry]:
        """Newest day first."""
        rows = self.conn.execute("select * from project_entry where project_id = ? order by day desc, uid desc",
                                 (project_id,))
        return [self._entry(r) for r in rows]

    # shortcuts, references and tasks: each kept in an order you can drag

    @staticmethod
    def _next_position(c: sqlite3.Connection, table: str, project_id: int) -> int:
        return c.execute(f"select coalesce(max(position), 0) + 1 from {table} where project_id = ?",
                         (project_id,)).fetchone()[0]

    def move_items(self, kind: str, ids: list[int]) -> None:
        """Put a project's shortcuts, references or tasks in this order."""
        table = ORDERED.get(kind)
        if table is None:
            raise StorageError("That list can't be reordered.")
        with self._tx() as c:
            for place, item_id in enumerate(ids, start=1):
                c.execute(f"update {table} set position = ? where id = ? and position != ?", (place, item_id, place))

    @staticmethod
    def _link(r: sqlite3.Row) -> ProjectLink:
        return ProjectLink(id=r["id"], project_id=r["project_id"], name=r["name"], url=r["url"],
                           category=r["category"] or "")

    def add_link(self, link: ProjectLink) -> ProjectLink:
        self._check_link(link)
        with self._tx() as c:
            link.id = c.execute("insert into project_link (project_id, name, url, category, position) values (?, ?, ?, ?, ?)",
                                (link.project_id, link.name.strip(), link.url.strip(), link.category,
                                 self._next_position(c, "project_link", link.project_id))).lastrowid
        return link

    def update_link(self, link: ProjectLink) -> ProjectLink:
        self._check_link(link)
        with self._tx() as c:
            c.execute("update project_link set name = ?, url = ?, category = ? where id = ?",
                      (link.name.strip(), link.url.strip(), link.category, link.id))
        return link

    @staticmethod
    def _check_link(link: ProjectLink) -> None:
        if not link.name.strip():
            raise StorageError("Give the shortcut a name.")
        if not link.url.strip():
            raise StorageError("Paste the address the shortcut opens.")
        if link.category and link.category not in LINK_CATEGORIES:
            raise StorageError("Pick a kind of shortcut from the list.")

    def delete_link(self, link_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from project_link where id = ?", (link_id,))

    def get_link(self, link_id: int) -> ProjectLink | None:
        r = self.conn.execute("select * from project_link where id = ?", (link_id,)).fetchone()
        return self._link(r) if r else None

    def list_links(self, project_id: int) -> list[ProjectLink]:
        rows = self.conn.execute("select * from project_link where project_id = ? order by position, uid", (project_id,))
        return [self._link(r) for r in rows]

    @staticmethod
    def _psource(r: sqlite3.Row) -> ProjectSource:
        return ProjectSource(id=r["id"], project_id=r["project_id"], title=r["title"], authors=r["authors"] or "",
                             year=r["year"] or "", link=r["link"] or "", status=r["status"] or "to_read",
                             annotation=r["annotation"] or "")

    @staticmethod
    def _check_psource(s: ProjectSource) -> None:
        if not s.title.strip():
            raise StorageError("Give the reference a title.")
        if s.status not in READING_STATUSES:
            raise StorageError("Pick to read, reading or read.")

    def add_project_source(self, s: ProjectSource) -> ProjectSource:
        self._check_psource(s)
        with self._tx() as c:
            s.id = c.execute("insert into project_source (project_id, title, authors, year, link, status, annotation,"
                             " position) values (?, ?, ?, ?, ?, ?, ?, ?)",
                             (s.project_id, s.title.strip(), s.authors.strip(), s.year.strip(), s.link.strip(), s.status,
                              s.annotation.strip(), self._next_position(c, "project_source", s.project_id))).lastrowid
        return s

    def update_project_source(self, s: ProjectSource) -> ProjectSource:
        self._check_psource(s)
        with self._tx() as c:
            c.execute("update project_source set title = ?, authors = ?, year = ?, link = ?, status = ?, annotation = ?"
                      " where id = ?", (s.title.strip(), s.authors.strip(), s.year.strip(), s.link.strip(), s.status,
                                        s.annotation.strip(), s.id))
        return s

    def delete_project_source(self, source_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from project_source where id = ?", (source_id,))

    def get_project_source(self, source_id: int) -> ProjectSource | None:
        r = self.conn.execute("select * from project_source where id = ?", (source_id,)).fetchone()
        return self._psource(r) if r else None

    def list_project_sources(self, project_id: int) -> list[ProjectSource]:
        rows = self.conn.execute("select * from project_source where project_id = ? order by position, uid", (project_id,))
        return [self._psource(r) for r in rows]

    @staticmethod
    def _task(r: sqlite3.Row) -> ProjectTask:
        return ProjectTask(id=r["id"], project_id=r["project_id"], text=r["text"], done=bool(r["done"]),
                           done_at=_dt(r["done_at"]))

    def add_task(self, t: ProjectTask) -> ProjectTask:
        if not t.text.strip():
            raise StorageError("Write what needs doing.")
        with self._tx() as c:
            t.id = c.execute("insert into project_task (project_id, text, done, position) values (?, ?, 0, ?)",
                             (t.project_id, t.text.strip(), self._next_position(c, "project_task", t.project_id))).lastrowid
        return t

    def update_task(self, t: ProjectTask) -> ProjectTask:
        if not t.text.strip():
            raise StorageError("Write what needs doing.")
        with self._tx() as c:
            c.execute("update project_task set text = ? where id = ?", (t.text.strip(), t.id))
        return t

    def toggle_task(self, task_id: int, now: datetime | None = None) -> ProjectTask:
        t = self.get_task(task_id)
        if t is None:
            raise StorageError("That task no longer exists.")
        t.done = not t.done
        t.done_at = (now or datetime.now()).replace(second=0, microsecond=0) if t.done else None
        with self._tx() as c:
            c.execute("update project_task set done = ?, done_at = ? where id = ?", (int(t.done), _iso(t.done_at), t.id))
        return t

    def delete_task(self, task_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from project_task where id = ?", (task_id,))

    def get_task(self, task_id: int) -> ProjectTask | None:
        r = self.conn.execute("select * from project_task where id = ?", (task_id,)).fetchone()
        return self._task(r) if r else None

    def list_tasks(self, project_id: int) -> list[ProjectTask]:
        rows = self.conn.execute("select * from project_task where project_id = ? order by position, uid", (project_id,))
        return [self._task(r) for r in rows]

    # study time

    @staticmethod
    def _project_session(r: sqlite3.Row) -> Session:
        return Session(id=r["id"], course_id=None, project_id=r["project_id"], started_at=_dt(r["started_at"]),  # type: ignore[arg-type]
                       minutes=r["minutes"], note=r["note"] or "")

    def get_project_session(self, session_id: int) -> Session | None:
        r = self.conn.execute("select * from project_session where id = ?", (session_id,)).fetchone()
        return self._project_session(r) if r else None

    def delete_project_session(self, session_id: int) -> None:
        with self._tx() as c:
            c.execute("delete from project_session where id = ?", (session_id,))

    def list_project_sessions(self, project_id: int | None = None, since: datetime | None = None,
                              until: datetime | None = None, limit: int | None = None) -> list[Session]:
        """Newest first."""
        sql, args = "select * from project_session where 1 = 1", []  # type: tuple[str, list[object]]
        if project_id is not None:
            sql += " and project_id = ?"
            args.append(project_id)
        if since is not None:
            sql += " and started_at >= ?"
            args.append(_iso(since))
        if until is not None:
            sql += " and started_at < ?"
            args.append(_iso(until))
        sql += " order by started_at desc, id desc"
        if limit is not None:
            sql += " limit ?"
            args.append(limit)
        return [self._project_session(r) for r in self.conn.execute(sql, args)]

    def project_minutes(self, project_id: int | None = None) -> int:
        if project_id is None:
            row = self.conn.execute("select coalesce(sum(minutes), 0) from project_session").fetchone()
        else:
            row = self.conn.execute("select coalesce(sum(minutes), 0) from project_session where project_id = ?",
                                    (project_id,)).fetchone()
        return int(row[0])

    # ---------- settings ----------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("select value from setting where key = ?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self._tx() as c:
            c.execute("insert into setting (key, value) values (?, ?)"
                      " on conflict (key) do update set value = excluded.value", (key, value))

    # ---------- notifications already sent ----------

    def sent_keys(self) -> set[tuple[int, str, datetime]]:
        """(deadline id, threshold, due_at) for every alert sent so far."""
        return {
            (r["deadline_id"], r["threshold"], datetime.fromisoformat(r["due_at"]))
            for r in self.conn.execute("select deadline_id, threshold, due_at from sent_notification")
        }

    def mark_sent(self, deadline_id: int, thresholds: list[str], due_at: datetime, now: datetime | None = None) -> None:
        now = now or datetime.now()
        with self._tx() as c:
            c.executemany(
                "insert or ignore into sent_notification (deadline_id, threshold, due_at, sent_at) values (?, ?, ?, ?)",
                [(deadline_id, t, _iso(due_at), _iso(now)) for t in thresholds],
            )
