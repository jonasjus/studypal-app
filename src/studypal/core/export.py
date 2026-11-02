"""Export everything as Markdown (one readable document) or CSV (one file per table).

Markdown shows dates day.month.year like the rest of the app. CSV keeps year-first ISO dates
(2026-12-10), which spreadsheets and other programs read without guessing."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .logic.dates import format_date, format_datetime
from .logic.stats import format_minutes
from .logic.timeline import cram_progress
from .storage import Store


def _cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return lines + [""]


def to_markdown(store: Store, now: datetime | None = None) -> str:
    now = now or datetime.now()
    topics_by_id = {t.id: t for t in store.list_topics()}
    out = [f"# Study export, {format_datetime(now)}", ""]
    for course in store.list_courses():
        topics = store.list_topics(course.id)
        p = cram_progress(course, topics, now.date())
        out += [
            f"## {course.code} · {course.name}" + (" (done)" if course.done else ""), "",
            f"Cram {format_date(course.cram_start)} → exam {format_date(course.exam_date)} · {round(p.done * 100)}% done · "
            f"{format_minutes(store.total_minutes(course.id))} studied",
            "",
        ]
        if course.notes:
            out += [course.notes, ""]
        out += ["### Topics", ""]
        out += _table(["Topic", "Status", "Confidence", "Last studied"],
                      [[t.title, t.status.label, f"{t.confidence}/5", format_date(t.last_studied) if t.last_studied else "never"] for t in topics])
        out += ["### Weak spots", ""]
        out += _table(["Priority", "Weak spot", "Topic", "Added", "Resolved"],
                      [[w.priority.value, w.description, topics_by_id[w.topic_id].title if w.topic_id in topics_by_id else "",
                        format_date(w.created_at), format_date(w.resolved_at) if w.resolved_at else ""]
                       for w in store.list_weak_spots(course.id, include_resolved=True)])
        out += ["### Deadlines", ""]
        out += _table(["Due", "Deadline", "Type", "Done"],
                      [[format_datetime(d.due_at), d.title, d.kind.value, "yes" if d.done else ""]
                       for d in store.list_deadlines(course.id, include_done=True)])
        reading = store.reading_list(course.id)
        if reading:
            out += ["### Reading", ""]
            for source, chapters in reading:
                out += [f"**{source.title}**" + (f" · {source.author}" if source.author else ""), ""]
                for chapter, sections in chapters:
                    topic = topics_by_id[chapter.topic_id].title if chapter.topic_id in topics_by_id else ""
                    out.append(f"- {chapter.number} {chapter.title}".rstrip() + (f" → {topic}" if topic else ""))
                    for s in sections:
                        box = "x" if s.read else " "
                        out.append(f"  - [{box}] {s.number} {s.title}".rstrip() + ("" if s.required else " (optional)"))
                out.append("")
        out += ["### Sessions", ""]
        out += _table(["Started", "Minutes", "Topic", "Note"],
                      [[format_datetime(s.started_at), s.minutes,
                        topics_by_id[s.topic_id].title if s.topic_id in topics_by_id else "", s.note]
                       for s in store.list_sessions(course.id)])
    standalone = [d for d in store.list_deadlines(include_done=True) if d.course_id is None]
    if standalone:
        out += ["## Other deadlines", ""]
        out += _table(["Due", "Deadline", "Type", "Done"],
                      [[format_datetime(d.due_at), d.title, d.kind.value, "yes" if d.done else ""] for d in standalone])
    return "\n".join(out).rstrip() + "\n"


def to_csv(store: Store, folder: Path) -> list[Path]:
    """Write courses.csv, topics.csv, weak_spots.csv, deadlines.csv, reading.csv and sessions.csv into `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[list[str], list[list[object]]]] = {
        "courses": (["id", "code", "name", "cram_start", "exam_date", "color", "notes"],
                    [[c.id, c.code, c.name, c.cram_start, c.exam_date, c.color, c.notes] for c in store.list_courses()]),
        "topics": (["id", "course_id", "title", "status", "confidence", "last_studied"],
                   [[t.id, t.course_id, t.title, t.status.value, t.confidence, t.last_studied or ""]
                    for t in store.list_topics()]),
        "weak_spots": (["id", "course_id", "topic_id", "description", "priority", "created_at", "resolved", "resolved_at"],
                       [[w.id, w.course_id, w.topic_id or "", w.description, w.priority.value,
                         w.created_at.isoformat(timespec="minutes"), int(w.resolved),
                         w.resolved_at.isoformat(timespec="minutes") if w.resolved_at else ""]
                        for w in store.list_weak_spots(include_resolved=True)]),
        "deadlines": (["id", "course_id", "title", "due_at", "type", "done"],
                      [[d.id, d.course_id or "", d.title, d.due_at.isoformat(timespec="minutes"), d.kind.value, int(d.done)]
                       for d in store.list_deadlines(include_done=True)]),
        "reading": (["course_id", "source", "author", "chapter", "chapter_title", "section", "section_title",
                     "required", "read", "read_at", "topic_id"],
                    [[c.id, src.title, src.author, ch.number, ch.title, s.number, s.title, int(s.required), int(s.read),
                      s.read_at.isoformat(timespec="minutes") if s.read_at else "",
                      s.topic_id if s.topic_id is not None else (ch.topic_id or "")]
                     for c in store.list_courses() for src, chs in store.reading_list(c.id)
                     for ch, ss in chs for s in ss]),
        "sessions": (["id", "course_id", "topic_id", "started_at", "minutes", "note"],
                     [[s.id, s.course_id, s.topic_id or "", s.started_at.isoformat(timespec="minutes"), s.minutes, s.note]
                      for s in store.list_sessions()]),
    }
    written = []
    for name, (headers, rows) in tables.items():
        path = folder / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        written.append(path)
    return written
