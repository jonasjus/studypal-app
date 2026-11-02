"""Reading lists: turning what you type or paste into chapters and sections, and counting progress.

Sections are "required" (part of what you need to read) or optional. Progress only counts
required sections; optional ones are shown but never make you look behind.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..models import Chapter, Section


class ReadingParseError(ValueError):
    pass


# ---------- section numbers ----------

def number_key(number: str) -> tuple:
    """Sort '6.10' after '6.9' and 'A.1' after the numbered chapters."""
    parts = []
    for part in number.split("."):
        parts.append((0, int(part), "") if part.isdigit() else (1, 0, part.lower()))
    return tuple(parts)


def _expand(token: str, chapter: str | None) -> list[str]:
    token = token.strip().rstrip(".")
    if not token:
        return []

    def full(n: str) -> str:
        # "3" inside chapter 6 means 6.3; anything with a dot is already a full number.
        return n if "." in n or chapter is None else f"{chapter}.{n}"

    if "-" not in token and "–" not in token:
        return [full(token)]
    start, end = re.split(r"\s*[-–]\s*", token, maxsplit=1)
    start = full(start)
    prefix, _, first = start.rpartition(".")
    last = end.rpartition(".")[2]  # "6.1-6.5" and "6.1-5" both end at 5
    if not (first.isdigit() and last.isdigit()):
        raise ReadingParseError(f"Can't read the range {token!r}. Use numbers like 6.1-6.5.")
    lo, hi = int(first), int(last)
    if hi < lo:
        raise ReadingParseError(f"The range {token!r} goes backwards.")
    if hi - lo > 200:
        raise ReadingParseError(f"The range {token!r} has more than 200 sections. Check the numbers.")
    return [f"{prefix}.{n}" if prefix else str(n) for n in range(lo, hi + 1)]


def parse_section_ranges(text: str, chapter: str | None = None) -> list[str]:
    """'6.1-6.5, 6.7' -> ['6.1', ..., '6.5', '6.7']. Inside chapter 6, '1-3' means 6.1-6.3. Keeps order, drops repeats."""
    numbers: list[str] = []
    joined = re.sub(r"\s*[-–]\s*", "-", text.strip())  # "6.1 - 6.3" is one range
    for token in re.split(r"[,;\s]+", joined):
        for n in _expand(token, chapter):
            if n not in numbers:
                numbers.append(n)
    return numbers


def chapter_of(section_number: str) -> str:
    """'6.1' and '6.1.2' belong to chapter '6'."""
    return section_number.split(".", 1)[0]


# ---------- pasted tables of contents ----------

@dataclass
class TocChapter:
    number: str
    title: str = ""
    sections: list[tuple[str, str]] = field(default_factory=list)  # (number, title)


_TOC_LINE = re.compile(
    r"^(?:(?:chapter|kapittel|ch\.?)\s+)?"  # optional "Chapter 6"
    r"(?P<number>\d+(?:\.\d+)*|[A-Z](?:\.\d+)+)"  # 6, 6.1, 6.1.2, A.1
    r"\.?(?:[:\s]+|$)(?P<title>.*)$",
    re.IGNORECASE,
)
# A page number at the end: after dot leaders, a tab or two spaces, or after one space when it has 2+ digits.
_LEADER = r"\s*\.(?:\s?\.)+\s*"  # "....." or ". . ."
_PAGE = re.compile(rf"(?:{_LEADER}|\t+|\s{{2,}})\d+$|\s\d{{2,}}$")


def _title(text: str) -> str:
    text = _PAGE.sub("", text.strip())
    return re.sub(rf"{_LEADER}$", "", text).strip()


def parse_toc(text: str) -> list[TocChapter]:
    """Lines like '6 Kernel Methods' and '6.1 Dual representations ..... 293' become chapters and sections.

    Page numbers and dot leaders at the end are dropped. Sub-sections (6.1.2) count as sections of
    chapter 6. Lines without a number are skipped.
    """
    chapters: dict[str, TocChapter] = {}
    for raw in text.splitlines():
        m = _TOC_LINE.match(raw.strip())
        if not m:
            continue
        number, title = m.group("number"), _title(m.group("title"))
        entry = chapters.setdefault(chapter_of(number), TocChapter(chapter_of(number)))
        if "." in number:
            if number not in [n for n, _ in entry.sections]:
                entry.sections.append((number, title))
        elif title and not entry.title:
            entry.title = title
    if not chapters:
        raise ReadingParseError("No numbered lines found. Paste lines that start with a number, like '6.1 Dual representations'.")
    return list(chapters.values())


# ---------- progress ----------

@dataclass(frozen=True)
class ReadingProgress:
    read: int = 0  # required sections read
    required: int = 0
    optional_read: int = 0
    optional: int = 0

    @property
    def fraction(self) -> float:
        return self.read / self.required if self.required else 0.0

    @property
    def complete(self) -> bool:
        return self.required > 0 and self.read == self.required

    def __add__(self, other: ReadingProgress) -> ReadingProgress:
        return ReadingProgress(self.read + other.read, self.required + other.required,
                               self.optional_read + other.optional_read, self.optional + other.optional)


def progress(sections: Iterable[Section]) -> ReadingProgress:
    read = required = optional_read = optional = 0
    for s in sections:
        if s.required:
            required += 1
            read += s.read
        else:
            optional += 1
            optional_read += s.read
    return ReadingProgress(read, required, optional_read, optional)


def reading_units(chapter: Chapter, sections: list[Section]) -> list[Section]:
    """What there is to read in a chapter: its sections, or, for a chapter without sections, the chapter
    itself (always needed reading), so it can be ticked off and counts toward progress."""
    if sections:
        return sections
    return [Section(chapter_id=chapter.id or 0, number=chapter.number, title=chapter.title, required=True,
                    read=chapter.read, read_at=chapter.read_at)]
