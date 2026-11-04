"""The font and text size chosen in Settings: kept for this computer (prefs.json), like the theme."""

from __future__ import annotations

from test_exams import api  # noqa: F401  (fixture)


def test_font_and_text_size_are_kept_per_computer(api) -> None:
    assert api.get_type() == {"font": "source", "size": "normal"}
    api.set_type("atkinson", "large")
    assert api.get_type() == {"font": "atkinson", "size": "large"}


def test_unknown_choices_are_refused(api) -> None:
    assert not api.set_type("comic-sans", "large").get("ok")
    assert not api.set_type("serif", "huge").get("ok")
    assert api.get_type() == {"font": "source", "size": "normal"}
