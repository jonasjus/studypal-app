"""Research projects: storage, the calls the window makes, study time and syncing between computers."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from studypal.api import Api, guess_category, link_address
from studypal.core.demo import seed
from studypal.core.models import Project, ProjectNote, ProjectTask, Session
from studypal.core.storage import MIGRATIONS, StorageError, Store
from tests.test_api import add_course
from tests.test_cloud import FakeCloud, computer


@pytest.fixture
def api(tmp_path):
    a = Api(tmp_path / "studypal.db", notify=lambda title, body: True)
    yield a
    a._close()


def add_project(api: Api, title: str = "Thesis", **extra) -> int:
    r = api.save_project({"title": title, "status": "active", "tags": "ml, Thesis ,ml", "start_on": "", "end_on": "",
                          "color": "", "description": "", **extra})
    assert r.get("ok"), r
    return r["id"]


# ---------- storage ----------

def test_projects_and_everything_in_them(store: Store) -> None:
    p = store.add_project(Project(title="Thesis", tags=["ml"]))
    assert store.get_project(p.id).tags == ["ml"]
    note = store.add_note(ProjectNote(project_id=p.id, title="Ideas"))
    store.add_task(ProjectTask(project_id=p.id, text="Read related work"))
    store.log_session(Session(course_id=None, project_id=p.id, started_at=datetime(2026, 11, 2, 10), minutes=30))
    assert note.updated_at is not None
    assert store.project_minutes(p.id) == 30 and store.total_minutes() == 0  # course time stays separate
    store.delete_project(p.id)
    for table in ("project_note", "project_task", "project_session"):
        assert store.conn.execute(f"select count(*) from {table}").fetchone()[0] == 0


def test_a_project_needs_a_title_and_sensible_dates(store: Store) -> None:
    with pytest.raises(StorageError):
        store.add_project(Project(title=" "))
    with pytest.raises(StorageError):
        store.add_project(Project(title="X", start_on=date(2026, 5, 1), end_on=date(2026, 4, 1)))
    with pytest.raises(StorageError):
        store.add_project(Project(title="X", status="someday"))


def test_new_colours_skip_ones_projects_use(store: Store) -> None:
    first = store.next_color()
    store.add_project(Project(title="A", color=first))
    assert store.next_color() != first


def test_a_running_timer_survives_the_upgrade(tmp_path) -> None:
    """The timer tables are rebuilt so they can time projects too; a timer running at the time keeps going."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for i, script in enumerate(MIGRATIONS[:-1], start=1):
        conn.executescript(script)
        conn.execute(f"pragma user_version = {i}")
    conn.execute("insert into course (name, code, cram_start, exam_date, color) values ('ML', 'ML', '2026-01-01', '2026-12-01', '#5b8def')")
    conn.execute("insert into active_timer (id, course_id, started_at) values (1, 1, '2026-11-03T09:00:00')")
    conn.commit()
    conn.close()
    with Store(path) as s:
        assert s.schema_version == len(MIGRATIONS)
        timer = s.get_timer()
        assert timer.course_id == 1 and timer.project_id is None
        session = s.stop_timer(datetime(2026, 11, 3, 10))
        assert session.minutes == 60 and s.list_sessions()[0].course_id == 1


def test_timer_and_pomodoro_log_project_time(store: Store) -> None:
    p = store.add_project(Project(title="Thesis"))
    start = datetime(2026, 11, 3, 9)
    store.start_timer(None, project_id=p.id, now=start)
    with pytest.raises(StorageError):
        store.start_pomodoro(None, project_id=p.id)
    s = store.stop_timer(start + timedelta(minutes=40))
    assert s.project_id == p.id and store.list_sessions() == []
    store.start_pomodoro(None, now=start, project_id=p.id)
    assert store.get_pomodoro().project_id == p.id
    blocks = store.stop_pomodoro(start + timedelta(minutes=10))
    assert [b.project_id for b in blocks] == [p.id]
    assert store.project_minutes(p.id) == 50
    with pytest.raises(StorageError):
        store.start_timer(None)  # neither a course nor a project


def test_deleting_a_project_stops_its_timer(store: Store) -> None:
    p = store.add_project(Project(title="Thesis"))
    store.start_timer(None, project_id=p.id)
    store.delete_project(p.id)
    assert store.get_timer() is None


def test_ordered_lists(store: Store) -> None:
    p = store.add_project(Project(title="Thesis"))
    a, b, c = (store.add_task(ProjectTask(project_id=p.id, text=t)) for t in "abc")
    store.move_items("task", [c.id, a.id, b.id])
    assert [t.text for t in store.list_tasks(p.id)] == ["c", "a", "b"]
    with pytest.raises(StorageError):
        store.move_items("course", [1])
    store.toggle_task(a.id)
    assert store.get_task(a.id).done and store.get_task(a.id).done_at is not None


# ---------- the window's calls ----------

def test_courses_and_projects_share_one_list(api: Api) -> None:
    ml = add_course(api, "ML101", exam=20)
    db = add_course(api, "DB201", exam=5)
    thesis = add_project(api)
    order = lambda key="list": [(x["kind"], x["id"]) for x in api.overview()[key]]  # noqa: E731
    # Untouched: courses soonest exam first, then projects, exactly as before.
    assert order() == [("course", db), ("course", ml), ("project", thesis)]
    assert api.reorder([{"kind": "project", "id": thesis}, {"kind": "course", "id": ml},
                        {"kind": "course", "id": db}]) == {"ok": True}
    assert order() == [("project", thesis), ("course", ml), ("course", db)]
    # Once you've chosen an order, new things go at the end.
    later = add_course(api, "AI300", exam=1)
    assert order()[-1] == ("course", later)
    # A finished project moves to the finished list.
    api.set_project_status(thesis, "done")
    assert ("project", thesis) in order("done_list") and ("project", thesis) not in order()


def test_project_details(api: Api) -> None:
    pid = add_project(api, end_on=(date.today() + timedelta(days=10)).isoformat())
    d = api.research(pid)
    assert d["project"]["tags"] == ["ml", "Thesis"] and d["project"]["due_words"] == "due in 10 days"
    note = api.add_note(pid)
    saved = api.save_note({"id": note["id"], "title": "Ideas", "body": "**Try** $x^2$"})
    assert saved["title"] == "Ideas" and saved["updated_label"]
    assert api.save_entry({"project_id": pid, "day": "2026-11-02", "body": "Ran baseline"})["ok"]
    assert api.save_entry({"project_id": pid, "day": "2026-11-03", "body": " "})["error"]
    assert api.save_link({"project_id": pid, "name": "", "url": "github.com/ada/thesis", "category": "auto"})["ok"]
    assert api.save_project_source({"project_id": pid, "title": "Attention is all you need",
                                    "authors": "Vaswani, Ashish", "year": "2017", "link": "10.48550/arXiv.1706.03762",
                                    "status": "reading", "annotation": "Transformers"})["ok"]
    assert api.save_task({"project_id": pid, "text": "Write intro"})["ok"]
    d = api.research(pid)
    assert [n["title"] for n in d["notes"]] == ["Ideas"]
    assert d["entries"][0]["body"] == "Ran baseline"
    assert d["links"][0] | {"id": 0} == {"id": 0, "name": "github.com", "url": "https://github.com/ada/thesis",
                                         "category": "", "kind": "code", "host": "github.com"}
    src = d["sources"][0]
    assert src["link"] == "https://doi.org/10.48550/arXiv.1706.03762" and d["reading"]["reading"] == 1
    assert src["apa"] == "Vaswani, A. (2017). Attention is all you need. https://doi.org/10.48550/arXiv.1706.03762"
    json.dumps(d)
    card = api.overview()["list"][0]
    assert card["tasks_total"] == 1 and card["next_task"] == "Write intro" and "1 note" in card["facts"]


def test_deleted_note_says_so_while_typing(api: Api) -> None:
    pid = add_project(api)
    note = api.add_note(pid)
    api.delete_note(note["id"])
    assert "deleted" in api.save_note({"id": note["id"], "title": "x", "body": "y"})["error"]


@pytest.mark.parametrize("text, url", [
    ("https://www.overleaf.com/project/1", "https://www.overleaf.com/project/1"),
    ("arxiv.org/abs/1706.03762", "https://arxiv.org/abs/1706.03762"),
    ("doi:10.1000/xyz", "https://doi.org/10.1000/xyz"),
    ("zotero://select/library", "zotero://select/library"),
    ("localhost:8888/tree", "http://localhost:8888/tree"),
])
def test_link_addresses(text, url) -> None:
    assert link_address(text) == url


@pytest.mark.parametrize("text", ["file:///etc/passwd", "javascript:alert(1)", "my notes", "", "/Applications/Calc.app"])
def test_shortcuts_only_open_web_and_app_links(api: Api, text) -> None:
    assert "error" in api.open_link(text)


def test_shortcut_kinds_are_guessed() -> None:
    assert guess_category("https://www.overleaf.com/project/1") == "writing"
    assert guess_category("https://scholar.google.com/") == "search"
    assert guess_category("https://colab.research.google.com/drive/1") == "notebook"
    assert guess_category("https://huggingface.co/datasets/squad") == "data"
    assert guess_category("zotero://select") == "references"
    assert guess_category("https://example.org") == "other"


def test_project_time_is_stacked_in_the_week(api: Api) -> None:
    cid, pid = add_course(api), add_project(api)
    now = datetime.now().replace(second=0, microsecond=0)
    api.save_session({"course_id": cid, "hours": 1, "minutes": 0, "started_at": now.isoformat()})
    api.save_session({"project_id": pid, "hours": 0, "minutes": 30, "started_at": now.isoformat(), "note": "Coding"})
    today = next(x for x in api.overview()["week"] if x["today"])
    assert (today["course_minutes"], today["research_minutes"], today["minutes"]) == (60, 30, 90)
    assert api.overview()["week_has_research"] and api.overview()["week_total"] == "1h 30m"
    session = api.research(pid)["sessions"][0]
    assert api.save_session({"id": session["id"], "project_id": pid, "hours": 0, "minutes": 45,
                             "started_at": session["started_at"], "note": ""})["ok"]
    assert api.research(pid)["total"] == "45m"
    assert api.subject(cid)["total"] == "1h"  # the course's own time is untouched


def test_running_bar_names_the_project(api: Api) -> None:
    pid = add_project(api, title="Thesis")
    assert api.timer_start(None, None, pid) == {"ok": True}
    running = api.overview()["running"]
    assert running["label"] == "Thesis" and running["project_id"] == pid
    api.timer_cancel()
    assert api.pomo_start(None, None, pid) == {"ok": True}
    assert api.overview()["running"]["label"] == "Thesis"


def test_demo_has_a_project(api: Api) -> None:
    seed(api._store)
    projects = [x for x in api.overview()["list"] if x["kind"] == "project"]
    assert projects
    json.dumps(api.research(projects[0]["id"]))


# ---------- syncing ----------

def test_projects_sync_between_computers(tmp_path, ) -> None:
    fake = FakeCloud()
    laptop, desktop = computer(tmp_path, "laptop", fake), computer(tmp_path, "desktop", fake)
    try:
        laptop.sign_up("ada@example.com", "long enough")
        pid = add_project(laptop)
        note = laptop.add_note(pid)
        laptop.save_note({"id": note["id"], "title": "Ideas", "body": "First"})
        laptop.save_task({"project_id": pid, "text": "Write intro"})
        laptop.save_session({"project_id": pid, "hours": 1, "minutes": 0, "started_at": "2026-11-02T10:00"})
        course = add_course(laptop, "ML101")
        laptop.reorder([{"kind": "project", "id": pid}, {"kind": "course", "id": course}])
        laptop.cloud_sync()

        desktop.sign_in("ada@example.com", "long enough")
        listed = desktop.overview()["list"]
        assert [x["kind"] for x in listed] == ["project", "course"]
        d = desktop.research(listed[0]["id"])
        assert d["notes"][0]["body"] == "First" and d["tasks"][0]["text"] == "Write intro" and d["total"] == "1h"

        desktop.delete_project(listed[0]["id"])
        desktop.cloud_sync()
        laptop.cloud_sync()
        assert [x["kind"] for x in laptop.overview()["list"]] == ["course"]
    finally:
        laptop._close()
        desktop._close()


def test_markdown_export_includes_research(api: Api) -> None:
    from studypal.core.export import to_markdown

    seed(api._store)
    text = to_markdown(api._store)
    assert "## Research · Uncertainty in small language models (active)" in text
    assert "- [x] Baseline on SST-2" in text and "### Note: Research questions" in text
