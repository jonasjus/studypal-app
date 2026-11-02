"""Merging StudyPal data from two places (this computer and the cloud), row by row.

A dataset is {table: {uid: row}}; each row is a dict with "uid", "updated" (when it last changed)
and its fields, with links to other rows given by uid ("course": "<uid>").

merge3 compares each row against the last shared version (base):
- changed on one side only: that side wins (including a deletion);
- changed on both: the newer change wins;
- deleted on one side and edited on the other: the edit is kept, so nothing is lost.

repair then makes the result consistent: rows whose parent was deleted get the parent back,
and duplicates of things that must be unique (a course code, a chapter number within a book)
are combined or renamed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Row = dict[str, Any]
Dataset = dict[str, dict[str, Row]]

# table -> {link field: (parent table, required?)}. Order matters: parents before children.
LINKS: dict[str, dict[str, tuple[str, bool]]] = {
    "course": {},
    "topic": {"course": ("course", True)},
    "source": {"course": ("course", True), "topic": ("topic", False)},
    "chapter": {"source": ("source", True), "topic": ("topic", False)},
    "section": {"chapter": ("chapter", True), "topic": ("topic", False)},
    "weak_spot": {"course": ("course", True), "topic": ("topic", False)},
    "deadline": {"course": ("course", False)},
    "session": {"course": ("course", True), "topic": ("topic", False)},
    "exam": {"course": ("course", True)},
    "exam_file": {"exam": ("exam", True)},
    "exam_question": {"exam": ("exam", True), "topic": ("topic", False)},
    "sent": {"deadline": ("deadline", True)},
}
TABLES = list(LINKS)


@dataclass
class MergeReport:
    both_changed: int = 0  # rows changed on both devices (the newer change won)
    kept_edits: int = 0  # rows deleted on one device but edited on the other (kept)
    restored: int = 0  # rows brought back because something still pointed at them
    combined: int = 0  # duplicate chapters/sections combined
    renamed: list[str] = field(default_factory=list)  # course codes renamed to stay unique

    def notes(self) -> list[str]:
        out = []
        if self.both_changed:
            out.append(f"{self.both_changed} item{'s' if self.both_changed != 1 else ''} changed on both devices; kept the newer change")
        if self.kept_edits:
            out.append(f"kept {self.kept_edits} item{'s' if self.kept_edits != 1 else ''} deleted on one device but edited on the other")
        if self.restored:
            out.append(f"restored {self.restored} item{'s' if self.restored != 1 else ''} that other changes still needed")
        if self.combined:
            out.append(f"combined {self.combined} duplicate chapter{'s' if self.combined != 1 else ''} or section{'s' if self.combined != 1 else ''}")
        out += [f"renamed a duplicate course code to {code}" for code in self.renamed]
        return out


def empty() -> Dataset:
    return {t: {} for t in TABLES}


def _same(a: Row | None, b: Row | None) -> bool:
    """Equal apart from when they were last saved (re-saving a row unchanged isn't a change)."""
    if a is None or b is None:
        return a is b
    return {k: v for k, v in a.items() if k != "updated"} == {k: v for k, v in b.items() if k != "updated"}


def changed_rows(before: Dataset, after: Dataset) -> int:
    """How many rows were added, removed or changed (ignoring re-saves)."""
    count = 0
    for table in TABLES:
        b, a = before.get(table, {}), after.get(table, {})
        count += sum(1 for uid in set(b) | set(a) if not _same(b.get(uid), a.get(uid)))
    return count


def merge3(base: Dataset, ours: Dataset, theirs: Dataset) -> tuple[Dataset, MergeReport]:
    report = MergeReport()
    merged = empty()
    for table in TABLES:
        b, o, t = base.get(table, {}), ours.get(table, {}), theirs.get(table, {})
        for uid in sorted(set(b) | set(o) | set(t)):
            mine, other, before = o.get(uid), t.get(uid), b.get(uid)
            if _same(mine, other):
                result = _newer(mine, other) if mine and other else mine
            elif _same(mine, before):
                result = other
            elif _same(other, before):
                result = mine
            elif mine is None or other is None:
                result = mine or other  # deleted on one side, edited on the other: keep the edit
                report.kept_edits += 1
            else:
                result = mine if str(mine.get("updated", "")) >= str(other.get("updated", "")) else other
                report.both_changed += 1
            if result is not None:
                merged[table][uid] = result
    repair(merged, [ours, theirs], report)
    return merged, report


def repair(data: Dataset, sources: list[Dataset], report: MergeReport) -> None:
    _restore_parents(data, sources, report)
    _combine_duplicates(data, report)


def _restore_parents(data: Dataset, sources: list[Dataset], report: MergeReport) -> None:
    changed = True
    while changed:
        changed = False
        for table in TABLES:
            for uid, row in list(data[table].items()):
                for link, (parent, required) in LINKS[table].items():
                    ref = row.get(link)
                    if ref is None or ref in data[parent]:
                        continue
                    found = [s[parent][ref] for s in sources if ref in s.get(parent, {})]
                    if found:
                        data[parent][ref] = max(found, key=lambda r: str(r.get("updated", "")))
                        report.restored += 1
                        changed = True
                    elif required:
                        del data[table][uid]
                        changed = True
                        break
                    else:
                        data[table][uid] = {**row, link: None}


def _newer(a: Row, b: Row) -> Row:
    return a if str(a.get("updated", "")) >= str(b.get("updated", "")) else b


def _combine_duplicates(data: Dataset, report: MergeReport) -> None:
    # Two devices added the same chapter number to the same book: keep one, move the sections over.
    keep: dict[tuple, str] = {}
    for uid, ch in sorted(data["chapter"].items()):
        key = (ch.get("source"), str(ch.get("number")))
        if key in keep:
            kept = keep[key]
            winner = _newer(data["chapter"][kept], ch)
            survivor, gone = (kept, uid) if winner is data["chapter"][kept] else (uid, kept)
            for s_uid, s in data["section"].items():
                if s.get("chapter") == gone:
                    data["section"][s_uid] = {**s, "chapter": survivor}
            del data["chapter"][gone]
            keep[key] = survivor
            report.combined += 1
        else:
            keep[key] = uid

    # The same section number twice in one chapter: keep the one that's been read (or the newer).
    seen: dict[tuple, str] = {}
    for uid, s in sorted(data["section"].items()):
        key = (s.get("chapter"), str(s.get("number")))
        if key in seen:
            other = data["section"][seen[key]]
            if bool(s.get("read")) != bool(other.get("read")):
                winner = s if s.get("read") else other
            else:
                winner = _newer(other, s)
            loser = uid if winner is other else seen[key]
            del data["section"][loser]
            seen[key] = uid if winner is s else seen[key]
            report.combined += 1
        else:
            seen[key] = uid

    # Course codes are unique: rename later duplicates (INF301 -> INF301-2).
    codes: set[str] = set()
    for uid, c in sorted(data["course"].items(), key=lambda kv: (str(kv[1].get("updated", "")), kv[0])):
        code = str(c.get("code", ""))
        new, n = code, 2
        while new.lower() in codes:
            new, n = f"{code}-{n}", n + 1
        if new != code:
            data["course"][uid] = {**c, "code": new}
            report.renamed.append(new)
        codes.add(new.lower())

    # One automatic exam deadline per course.
    exams: dict[Any, str] = {}
    for uid, d in sorted(data["deadline"].items()):
        if not d.get("is_course_exam") or d.get("course") is None:
            continue
        if d["course"] in exams:
            other = exams[d["course"]]
            loser = other if _newer(data["deadline"][other], d) is d else uid
            del data["deadline"][loser]
            exams[d["course"]] = uid if loser == other else other
        else:
            exams[d["course"]] = uid
