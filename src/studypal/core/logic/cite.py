"""APA 7 reference-list entries for reading-list sources.

    Book:     Bishop, C. M. (2006). *Pattern recognition and machine learning*. Springer.
    Article:  Vaswani, A., Shazeer, N., & Parmar, N. (2017). Attention is all you need. *Advances in
              Neural Information Processing Systems*, *30*, 5998–6008. https://doi.org/10.xxxx
    Web page: World Health Organization. (2024). *Malaria*. https://www.who.int/...
    Notes:    Hansen, K. (2025). *Week 3: Kernels* [Lecture notes]. University of Bergen.

Titles are used as typed: APA wants sentence case for book and article titles, but changing case
automatically would break names and acronyms. Each entry comes as plain text and as HTML with the
italics, so pasting into a word processor keeps the formatting.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from ..models import Source

KINDS = ("book", "article", "web", "notes")

# Words that mark an author as an organisation rather than a person, when typed without a comma.
_GROUP_WORDS = re.compile(
    r"\b(university|universitet|organi[sz]ation|institute|institutt|association|society|department|committee|"
    r"agency|council|ministry|group|foundation|centre|center|office|board|bureau|commission|inc|ltd|as)\b\.?",
    re.IGNORECASE)


@dataclass(frozen=True)
class Reference:
    text: str  # plain text, italics dropped
    html: str  # with <i> for the parts APA sets in italics


def _initials(given: str) -> str:
    """'Christopher Michael' -> 'C. M.', 'Jean-Paul' -> 'J.-P.'"""
    out = []
    for part in given.replace(".", " ").split():
        out.append("-".join(f"{p[0].upper()}." for p in part.split("-") if p))
    return " ".join(out)


def format_author(name: str) -> str:
    """'Bishop, Christopher M.' or 'Christopher M. Bishop' -> 'Bishop, C. M.'. An organisation, or a
    single name, is kept as written."""
    name = " ".join(name.split()).strip(" ,;")
    if not name:
        return ""
    if "," in name:
        surname, given = (p.strip() for p in name.split(",", 1))
        return f"{surname}, {_initials(given)}" if given else surname
    if _GROUP_WORDS.search(name) or " " not in name:
        return name
    *given, surname = name.split()
    # Keep particles with the surname: "Ludwig van Beethoven" -> "van Beethoven, L."
    while given and given[-1].lower() in ("van", "von", "de", "der", "den", "da", "di", "du", "la", "le"):
        surname = f"{given.pop()} {surname}"
    return f"{surname}, {_initials(' '.join(given))}" if given else surname


def split_authors(text: str) -> list[str]:
    """Authors separated by semicolons or new lines. ("and" can't be used: it's part of many
    organisations' names.)"""
    parts = re.split(r"\s*[;\n]\s*", text.strip())
    return [p for p in (p.strip() for p in parts) if p]


def author_list(text: str) -> str:
    """APA's list: 'A', 'A, & B', 'A, B, & C'; with 21 or more, the first 19, an ellipsis, then the last."""
    names = [format_author(a) for a in split_authors(text)]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) >= 21:
        return ", ".join(names[:19]) + ", . . . " + names[-1]
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _edition(text: str) -> str:
    """'2' / '2nd' / '2nd ed.' -> '2nd ed.'; anything else ('Rev.') gets ' ed.' added."""
    t = text.strip().rstrip(".")
    if not t:
        return ""
    t = re.sub(r"\s*ed(ition)?$", "", t, flags=re.IGNORECASE).strip()
    m = re.fullmatch(r"(\d+)(st|nd|rd|th)?", t, re.IGNORECASE)
    return f"{_ordinal(int(m.group(1)))} ed." if m else f"{t} ed."


def _link(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    t = re.sub(r"^(doi:\s*|https?://(dx\.)?doi\.org/)", "", t, flags=re.IGNORECASE)
    return f"https://doi.org/{t}" if t.startswith("10.") else text.strip()


def _end(text: str) -> str:
    """A full stop, unless the text already ends with punctuation."""
    return text if text.endswith((".", "?", "!")) else text + "."


class _Builder:
    def __init__(self) -> None:
        self.text: list[str] = []
        self.html: list[str] = []

    def add(self, text: str, italic: bool = False) -> None:
        self.text.append(text)
        escaped = html.escape(text, quote=False)
        self.html.append(f"<i>{escaped}</i>" if italic else escaped)

    def done(self) -> Reference:
        return Reference("".join(self.text).strip(), "".join(self.html).strip())


def apa(source: Source) -> Reference:
    kind = source.kind if source.kind in KINDS else "book"
    authors = author_list(source.author)
    year = f"({source.year.strip()})" if source.year.strip() else "(n.d.)"
    title = source.title.strip()
    b = _Builder()

    # Author and date; without an author the title moves to the front.
    if authors:
        b.add(f"{_end(authors)} {year}. ")
    if kind == "article":
        if not authors:
            b.add(f"{_end(title)} {year}. ")
        else:
            b.add(f"{_end(title)} ")
        if source.journal.strip():
            b.add(source.journal.strip(), italic=True)
            if source.volume.strip():
                b.add(", ")
                b.add(source.volume.strip(), italic=True)
            if source.issue.strip():
                b.add(f"({source.issue.strip()})")
            if source.pages.strip():
                b.add(", " + re.sub(r"\s*[-–—]\s*", "–", source.pages.strip()))
            b.add(". ")
    else:
        extra = {"notes": "[Lecture notes]"}.get(kind, "")
        edition = _edition(source.edition) if kind == "book" else ""
        b.add(title.rstrip("."), italic=True)
        after = " ".join(p for p in (f"({edition})" if edition else "", extra) if p)
        b.add(f" {after}" if after else "")
        b.add(f". {year}. " if not authors else ". ")
        publisher = source.publisher.strip()
        # APA leaves the publisher out when it's the same as the author.
        if publisher and publisher.lower() != source.author.strip().lower():
            b.add(_end(publisher) + " ")
    link = _link(source.link)
    if link:
        b.add(link)
    return b.done()
