from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from studypal.core.models import Course
from studypal.core.storage import Store


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """Tests never play the Pomodoro's pling out loud."""
    monkeypatch.setenv("STUDYPAL_SOUND", "print")


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "study.db"


@pytest.fixture
def store(db_file: Path):
    s = Store(db_file)
    yield s
    s.close()


@pytest.fixture
def ml(store: Store) -> Course:
    return store.add_course(Course("Machine Learning", "ML101", date(2026, 11, 1), date(2026, 12, 10)))
