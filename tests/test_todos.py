from __future__ import annotations

from datetime import date, timedelta

from studypal.api import Api
from tests.test_api import api  # noqa: F401  (the fixture)
from tests.test_cloud import FakeCloud, computer

TODAY = date.today()


def day(n: int = 0) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


def test_a_day_starts_empty(api: Api) -> None:
    d = api.todos()
    assert d["day"] == day() and d["is_today"] and d["name"] == "Today"
    assert d["items"] == [] and d["total"] == 0 and len(d["week"]) == 7
    assert [w["selected"] for w in d["week"]].count(True) == 1


def test_add_tick_and_finish_the_day(api: Api) -> None:
    api.add_todo(day(), "Problem set 3")
    api.add_todo(day(), "Chapter 6")
    first, second = (t["id"] for t in api.todos()["items"])
    r = api.toggle_todo(first)
    assert r["done"] and not r["all_done"] and r["left"] == 1
    r = api.toggle_todo(second)
    assert r["all_done"]
    assert api.todo_today() == {"done": 2, "total": 2}
    assert api.toggle_todo(second)["done"] is False  # ticking again undoes it


def test_pasted_lines_become_separate_to_dos(api: Api) -> None:
    api.add_todo(day(), "- One\n- Two\n\n• Three")
    assert [t["text"] for t in api.todos()["items"]] == ["One", "Two", "Three"]
    assert "error" in api.add_todo(day(), "   ")


def test_other_days_and_moving(api: Api) -> None:
    api.add_todo(day(1), "Tomorrow's thing")
    d = api.todos(day(1))
    assert d["name"] == "Tomorrow" and not d["is_today"] and d["total"] == 1
    api.add_todo(day(-2), "Left behind")
    api.add_todo(day(-1), "Done yesterday")
    api.toggle_todo(api.todos(day(-1))["items"][0]["id"])
    assert api.todos()["left_behind"] == 1
    assert api.bring_todos_forward()["message"] == "Moved 1 unfinished to-do to today."
    assert [t["text"] for t in api.todos()["items"]] == ["Left behind"]
    assert api.todos()["left_behind"] == 0
    tid = api.todos()["items"][0]["id"]
    assert api.move_todo(tid, day(1))["message"] == "Moved to tomorrow."
    assert [t["text"] for t in api.todos(day(1))["items"]] == ["Tomorrow's thing", "Left behind"]


def test_edit_reorder_delete(api: Api) -> None:
    api.add_todo(day(), "A\nB")
    a, b = (t["id"] for t in api.todos()["items"])
    api.edit_todo(a, "A, better")
    api.move_items("todo", [b, a])
    assert [t["text"] for t in api.todos()["items"]] == ["B", "A, better"]
    api.delete_todo(b)
    assert [t["text"] for t in api.todos()["items"]] == ["A, better"]


def test_to_dos_sync_between_computers(tmp_path) -> None:
    fake = FakeCloud()
    laptop, desktop = computer(tmp_path, "laptop", fake), computer(tmp_path, "desktop", fake)
    try:
        laptop.sign_up("ada@example.com", "long enough")
        laptop.add_todo(day(), "Synced")
        laptop.toggle_todo(laptop.todos()["items"][0]["id"])
        laptop.cloud_sync()
        desktop.sign_in("ada@example.com", "long enough")
        items = desktop.todos()["items"]
        assert [(t["text"], t["done"]) for t in items] == [("Synced", True)]
    finally:
        laptop._close()
        desktop._close()
