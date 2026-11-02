from __future__ import annotations

import pytest

from studypal.core.logic.cite import apa, author_list, format_author
from studypal.core.models import Source


@pytest.mark.parametrize("name, expected", [
    ("Bishop, Christopher M.", "Bishop, C. M."),
    ("Christopher M. Bishop", "Bishop, C. M."),
    ("Jean-Paul Sartre", "Sartre, J.-P."),
    ("Ludwig van Beethoven", "van Beethoven, L."),
    ("World Health Organization", "World Health Organization"),
    ("University of Bergen", "University of Bergen"),
    ("Bishop", "Bishop"),
    ("  Bishop ,  C  ", "Bishop, C."),
])
def test_author_names(name: str, expected: str) -> None:
    assert format_author(name) == expected


def test_author_lists() -> None:
    assert author_list("Bishop, C.") == "Bishop, C."
    assert author_list("Casella, George; Berger, Roger L.") == "Casella, G., & Berger, R. L."
    assert author_list("A, A\nB, B\nC, C") == "A, A., B, B., & C, C."
    many = "; ".join(f"Name{i}, X" for i in range(1, 25))
    assert author_list(many) == ", ".join(f"Name{i}, X." for i in range(1, 20)) + ", . . . Name24, X."


def src(**kw) -> Source:
    return Source(course_id=1, **kw)


def test_book() -> None:
    r = apa(src(title="Pattern recognition and machine learning", author="Bishop, Christopher M.", year="2006",
                publisher="Springer"))
    assert r.text == "Bishop, C. M. (2006). Pattern recognition and machine learning. Springer."
    assert r.html == "Bishop, C. M. (2006). <i>Pattern recognition and machine learning</i>. Springer."


def test_book_with_edition_and_doi() -> None:
    r = apa(src(title="Statistical inference", author="Casella, George; Berger, Roger L.", year="2002",
                edition="2", publisher="Duxbury", link="doi:10.1201/9781003456285"))
    assert r.text == ("Casella, G., & Berger, R. L. (2002). Statistical inference (2nd ed.). Duxbury. "
                      "https://doi.org/10.1201/9781003456285")
    assert "<i>Statistical inference</i> (2nd ed.)" in r.html


def test_article() -> None:
    r = apa(src(kind="article", title="Attention is all you need", author="Vaswani, Ashish; Shazeer, Noam",
                year="2017", journal="Advances in Neural Information Processing Systems", volume="30", issue="",
                pages="5998-6008"))
    assert r.text == ("Vaswani, A., & Shazeer, N. (2017). Attention is all you need. "
                      "Advances in Neural Information Processing Systems, 30, 5998–6008.")
    assert "<i>Advances in Neural Information Processing Systems</i>, <i>30</i>, 5998–6008." in r.html


def test_article_with_issue() -> None:
    r = apa(src(kind="article", title="A title?", author="Doe, J.", year="2020", journal="Journal", volume="4",
                issue="2", pages="1–9", link="https://doi.org/10.1/abc"))
    assert r.text == "Doe, J. (2020). A title? Journal, 4(2), 1–9. https://doi.org/10.1/abc"


def test_web_page_by_organisation_without_date() -> None:
    r = apa(src(kind="web", title="Malaria", author="World Health Organization", link="https://www.who.int/malaria"))
    assert r.text == "World Health Organization. (n.d.). Malaria. https://www.who.int/malaria"


def test_publisher_same_as_author_is_left_out() -> None:
    r = apa(src(kind="web", title="Report", author="World Health Organization", year="2024",
                publisher="World Health Organization"))
    assert r.text == "World Health Organization. (2024). Report."


def test_lecture_notes() -> None:
    r = apa(src(kind="notes", title="Week 3: Kernels", author="Hansen, Kari", year="2025", publisher="University of Bergen"))
    assert r.text == "Hansen, K. (2025). Week 3: Kernels [Lecture notes]. University of Bergen."
    assert r.html.startswith("Hansen, K. (2025). <i>Week 3: Kernels</i> [Lecture notes].")


def test_no_author() -> None:
    assert apa(src(title="Some book", year="2001", publisher="Pub")).text == "Some book. (2001). Pub."
    assert apa(src(kind="article", title="Some article", year="2001", journal="J")).text == "Some article. (2001). J."


def test_html_is_escaped() -> None:
    assert "&lt;b&gt;" in apa(src(title="<b>", author="A, B")).html
