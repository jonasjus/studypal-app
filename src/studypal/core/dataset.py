"""The database as plain rows, for syncing: {table: {uid: row}}, where each row has its uid, when it last
changed ("updated") and its fields, with links to other rows given by uid. Copied from `study`'s git sync.
"""

from __future__ import annotations

import sqlite3

from .logic.merge import LINKS, TABLES, Dataset, empty

# Fields stored for each table (besides uid, updated and links).
FIELDS: dict[str, list[str]] = {
    "course": ["name", "code", "cram_start", "exam_date", "color", "notes", "done", "position", "banner"],
    "topic": ["title", "status", "confidence", "last_studied"],
    "source": ["title", "author", "position", "kind", "year", "publisher", "edition", "journal", "volume", "issue",
               "pages", "link"],
    "chapter": ["number", "title", "position", "read", "read_at"],
    "section": ["number", "title", "required", "read", "read_at", "position"],
    "weak_spot": ["description", "priority", "created_at", "resolved", "resolved_at"],
    "deadline": ["title", "due_at", "kind", "done", "is_course_exam"],
    "session": ["started_at", "minutes", "note"],
    "exam": ["title", "kind", "taken_on", "score", "notes", "created_at"],
    "exam_file": ["name", "key", "mime", "size", "role"],
    "exam_question": ["number", "prompt", "answer", "marks", "result", "note", "why", "position", "parent_number",
                      "question_type", "topic_tags", "has_figure"],
    "exam_attempt": ["started_at", "minutes", "finished_at", "seconds", "items", "summary", "graded"],
    "course_note": ["title", "body", "created_at"],
    "project": ["title", "description", "status", "tags", "start_on", "end_on", "color", "position", "created_at"],
    "project_note": ["title", "body", "created_at"],
    "project_entry": ["day", "body"],
    "project_link": ["name", "url", "category", "position"],
    "project_source": ["title", "authors", "year", "link", "status", "annotation", "position"],
    "project_task": ["text", "done", "done_at", "position"],
    "project_session": ["started_at", "minutes", "note"],
    "todo": ["day", "text", "done", "done_at", "position"],
}


def export_dataset(conn: sqlite3.Connection) -> Dataset:
    uids: dict[str, dict[int, str]] = {}
    data = empty()
    for table in TABLES:
        if table == "sent":
            continue
        rows = conn.execute(f"select * from {table}").fetchall()
        uids[table] = {r["id"]: r["uid"] for r in rows}
        for r in rows:
            row = {"uid": r["uid"], "updated": r["updated_at"]}
            row.update({f: r[f] for f in FIELDS[table]})
            for link, (parent, _) in LINKS[table].items():
                local_id = r[f"{link}_id"]
                row[link] = uids[parent].get(local_id) if local_id is not None else None
            data[table][r["uid"]] = row
    for r in conn.execute("select * from sent_notification"):
        deadline = uids["deadline"].get(r["deadline_id"])
        if deadline:
            key = f"{deadline}|{r['threshold']}|{r['due_at']}"
            data["sent"][key] = {"uid": key, "deadline": deadline, "threshold": r["threshold"],
                                 "due_at": r["due_at"], "sent_at": r["sent_at"]}
    return data


def apply_dataset(conn: sqlite3.Connection, data: Dataset) -> None:
    """Make the database hold exactly `data`. Rows keep their local ids, so a running timer stays valid.
    Must run inside a transaction."""
    conn.execute("pragma defer_foreign_keys = on")
    # Deletions first, children before parents (a deleted parent's children are gone from `data` too).
    conn.execute("delete from sent_notification")
    for table in reversed([t for t in TABLES if t != "sent"]):
        keep = set(data[table])
        for (row_id, uid) in conn.execute(f"select id, uid from {table}").fetchall():
            if uid not in keep:
                conn.execute(f"delete from {table} where id = ?", (row_id,))
    ids: dict[str, dict[str, int]] = {}
    for table in TABLES:
        if table == "sent":
            continue
        local = {uid: row_id for row_id, uid in conn.execute(f"select id, uid from {table}")}
        columns = FIELDS[table] + [f"{link}_id" for link in LINKS[table]] + ["updated_at"]
        # Existing rows first, then new ones, so a renamed course code is free before a new course takes it.
        rows = sorted(data[table].items(), key=lambda item: item[0] not in local)
        for uid, row in rows:
            values = [row.get(f) for f in FIELDS[table]]
            values += [ids[parent].get(row.get(link)) if row.get(link) else None
                       for link, (parent, _) in LINKS[table].items()]
            values.append(row.get("updated"))
            if uid in local:
                sets = ", ".join(f"{c} = ?" for c in columns)
                conn.execute(f"update {table} set {sets} where id = ?", (*values, local[uid]))
            else:
                marks = ", ".join("?" * (len(columns) + 1))
                cur = conn.execute(f"insert into {table} ({', '.join(columns)}, uid) values ({marks})", (*values, uid))
                local[uid] = cur.lastrowid
        ids[table] = local
    for row in data["sent"].values():
        deadline_id = ids["deadline"].get(row["deadline"])
        if deadline_id is not None:
            conn.execute("insert or ignore into sent_notification (deadline_id, threshold, due_at, sent_at) values (?, ?, ?, ?)",
                         (deadline_id, row["threshold"], row["due_at"], row["sent_at"]))
