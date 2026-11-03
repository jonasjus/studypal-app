"""The calls the window makes: plain JSON in, plain JSON out, errors as {"error": ...}."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from studypal.api import Api
from studypal.core.demo import seed


@pytest.fixture
def api(tmp_path):
    sent: list[tuple[str, str]] = []
    played: list[str] = []
    a = Api(tmp_path / "studypal.db", notify=lambda title, body: sent.append((title, body)) or True,
            play=played.append)
    a.sent = sent  # type: ignore[attr-defined]
    a.played = played  # type: ignore[attr-defined]
    yield a
    a._close()


def add_course(api: Api, code: str = "ML101", start: int = -10, exam: int = 20) -> int:
    today = date.today()
    r = api.save_course({"name": "Machine Learning", "code": code, "cram_start": (today + timedelta(days=start)).isoformat(),
                         "exam_date": (today + timedelta(days=exam)).isoformat(), "color": "", "notes": ""})
    assert r["ok"], r
    return r["id"]


def test_empty_overview(api: Api) -> None:
    d = api.overview()
    assert d["courses"] == [] and d["deadlines"] == [] and d["running"] is None
    json.dumps(d)


def test_demo_data_serialises(api: Api) -> None:
    seed(api._store)
    d = api.overview()
    json.dumps(d)
    assert len(d["courses"]) == 4
    first = d["courses"][0]
    assert first["code"] == "DAT255" and first["progress"]["is_behind"]
    assert d["banner"]["overdue"][0]["title"] == "Pipeline project report"
    for c in d["courses"]:
        json.dumps(api.subject(c["id"]))
        json.dumps(api.reading(c["id"]))
    assert len(d["week"]) == 7


def test_course_errors_come_back_as_messages(api: Api) -> None:
    assert api.save_course({"name": "", "code": "X", "cram_start": "2026-01-01", "exam_date": "2026-02-01"})["error"]
    assert "Pick a date" in api.save_course({"name": "A", "code": "A", "cram_start": "", "exam_date": "2026-02-01"})["error"]
    add_course(api)
    assert "already" in api.save_course({"name": "B", "code": "ml101", "cram_start": "2026-01-01",
                                         "exam_date": "2026-02-01"})["error"]


def test_editing_a_course_keeps_it_done(api: Api) -> None:
    cid = add_course(api)
    api.set_course_done(cid, True)
    c = api.subject(cid)["course"]
    api.save_course({**c, "name": "Renamed"})
    d = api.overview()
    assert d["courses"] == [] and d["done_courses"][0]["name"] == "Renamed"


def test_topics(api: Api) -> None:
    cid = add_course(api)
    assert api.add_topics(cid, "Regression\n\n- Trees\n  • Kernels  ")["added"] == 3
    topics = api.subject(cid)["topics"]
    assert [t["title"] for t in topics] == ["Regression", "Trees", "Kernels"]
    api.set_topic_status(topics[0]["id"], "reviewed")
    api.set_confidence(topics[0]["id"], 9)
    s = api.subject(cid)
    assert s["topics"][0]["confidence"] == 5 and s["topics_done"] == 1
    assert s["course"]["progress"]["done"] == pytest.approx(1 / 3)
    api.save_topic({"id": topics[1]["id"], "title": "Boosted trees", "status": "in_progress", "confidence": "3"})
    assert api.subject(cid)["topics"][1]["title"] == "Boosted trees"
    assert api.add_topics(cid, "  \n")["error"]


def test_weak_spots_and_deadlines(api: Api) -> None:
    cid = add_course(api)
    assert api.save_weak({"course_id": str(cid), "description": "Dual form", "priority": "high", "topic_id": ""}) == {"ok": True}
    w = api.overview()["weak_spots"][0]
    assert w["priority"] == "high" and w["course_code"] == "ML101"
    api.toggle_weak(w["id"])
    assert api.overview()["weak_spots"] == []

    due = (datetime.now() + timedelta(hours=5)).isoformat(timespec="minutes")
    assert api.save_deadline({"title": "PS4", "due_at": due, "kind": "assignment", "course_id": str(cid)}) == {"ok": True}
    d = api.overview()
    assert [x["title"] for x in d["deadlines"]] == ["PS4", "ML101 exam"]
    assert d["banner"]["soon"][0]["title"] == "PS4"
    exam = d["deadlines"][1]
    assert "goes away with the course" in api.delete_deadline(exam["id"])["error"]


def test_moving_the_exam_deadline_moves_the_exam(api: Api) -> None:
    cid = add_course(api)
    exam = api.subject(cid)["deadlines"][0]
    new = (date.today() + timedelta(days=40)).isoformat()
    api.save_deadline({"id": exam["id"], "title": exam["title"], "due_at": f"{new}T10:00"})
    assert api.subject(cid)["course"]["exam_date"] == new


def test_logging_time(api: Api) -> None:
    cid = add_course(api)
    api.add_topics(cid, "Trees")
    tid = api.subject(cid)["topics"][0]["id"]
    assert "How long" in api.save_session({"course_id": cid, "hours": "0", "minutes": "", "started_at": "2026-10-01T10:00"})["error"]
    now = datetime.now().isoformat(timespec="minutes")
    assert api.save_session({"course_id": cid, "topic_id": str(tid), "hours": "1", "minutes": "30", "started_at": now,
                             "note": "ch 7"}) == {"ok": True}
    s = api.subject(cid)
    assert s["sessions"][0]["length"] == "1h 30m" and s["topics"][0]["status"] == "in_progress"
    api.save_session({**s["sessions"][0], "hours": 0, "minutes": 45})
    assert api.subject(cid)["total"] == "45m"


def test_timer(api: Api) -> None:
    cid = add_course(api)
    api.timer_start(cid, None)
    assert api.overview()["running"]["kind"] == "timer"
    assert "timer is running" in api.pomo_start(cid, None)["error"]
    api._store.conn.execute("update active_timer set started_at = ?",
                            ((datetime.now() - timedelta(minutes=20)).isoformat(timespec="seconds"),))
    assert api.timer_stop()["message"] == "Logged 20m."
    assert api.overview()["running"] is None


def test_stopping_a_pomodoro_straight_away(api: Api) -> None:
    cid = add_course(api)
    api.pomo_start(cid, None)
    assert "under a minute" in api.pomo_stop()["message"]


def _focus_started(api: Api, minutes_ago: float) -> None:
    ago = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    api._store.conn.execute("update pomodoro_run set phase_started_at = ?, block_started_at = ?", (ago, ago))


def test_focus_time_up_plings_and_waits_for_you(api: Api) -> None:
    cid = add_course(api)
    api.pomo_start(cid, None)
    r = api.overview()["running"]
    assert r["kind"] == "pomodoro" and r["phase"] == "focus" and r["remaining_seconds"] > 24 * 60 and not r["focus_done"]
    _focus_started(api, 26)  # time was up a minute ago
    t = api.tick()
    assert any("Time for a break" in m for m in t["messages"])
    assert api.played == ["focus_done"]  # type: ignore[attr-defined]
    assert api.sent[-1][0] == "Time for a break"  # type: ignore[attr-defined]
    api.tick()
    assert api.played == ["focus_done"]  # once, not on every tick  # type: ignore[attr-defined]
    # No break yet: still focus, counting the extra minute, nothing logged.
    r = api.overview()["running"]
    assert r["phase"] == "focus" and r["focus_done"] and 55 <= r["overtime_seconds"] <= 65
    assert api.subject(cid)["total"] == "0m"
    msg = api.pomo_break()["message"]
    assert msg == "Saved 26m of focus. Enjoy your 5-minute break."
    assert api.overview()["running"]["phase"] == "short_break" and api.subject(cid)["total"] == "26m"
    assert api.played == ["focus_done"]  # taking the break yourself makes no sound  # type: ignore[attr-defined]
    assert api.pomo_stop()["message"] == "Pomodoro stopped. Your focus time is saved."


def test_pling_when_a_break_is_over_and_it_can_be_turned_off(api: Api) -> None:
    cid = add_course(api)
    api.pomo_start(cid, None)
    api.pomo_break()
    ago = (datetime.now() - timedelta(minutes=6)).isoformat(timespec="seconds")
    api._store.conn.execute("update pomodoro_run set phase_started_at = ?", (ago,))
    api.tick()
    assert api.played == ["break_over"]  # type: ignore[attr-defined]
    api.pomo_next()
    assert api.save_settings({"sound": 0}) == {"ok": True}
    _focus_started(api, 26)
    assert api.tick()["messages"] and api.played == ["break_over"]  # type: ignore[attr-defined]
    assert api.get_settings()["sound"] == 0


def test_background_check_plings_without_the_window(api: Api) -> None:
    """The watcher thread's check plings and notifies by itself; the window's next tick shows the messages."""
    cid = add_course(api)
    api.pomo_start(cid, None)
    api.tick()
    _focus_started(api, 26)
    with api._lock:
        api._check_pomodoro(datetime.now().replace(microsecond=0))
    assert api.played == ["focus_done"] and api.sent  # type: ignore[attr-defined]
    t = api.tick()
    assert t["changed"] and any("Time for a break" in m for m in t["messages"])
    assert api.played == ["focus_done"] and api.tick()["messages"] == []  # type: ignore[attr-defined]


def test_notifications_can_be_turned_off(api: Api) -> None:
    cid = add_course(api)
    due = (datetime.now() + timedelta(hours=3)).isoformat(timespec="minutes")
    api.save_deadline({"title": "PS4", "due_at": due, "course_id": cid})
    api.save_settings({"notifications": 0})
    api.tick()
    assert api.sent == []  # type: ignore[attr-defined]
    api.save_settings({"notifications": 1})
    api.tick()
    api.tick()
    assert len(api.sent) == 1 and "PS4" in api.sent[0][0]  # type: ignore[attr-defined]


def test_settings(api: Api) -> None:
    assert api.get_settings()["focus_minutes"] == 25
    assert api.save_settings({"focus_minutes": "50", "week_start": "6"}) == {"ok": True}
    assert api.get_settings()["focus_minutes"] == 50
    assert api._config().week_start == 6
    assert "between" in api.save_settings({"focus_minutes": "0"})["error"]


def test_reading_list(api: Api) -> None:
    cid = add_course(api)
    api.add_topics(cid, "Kernels")
    tid = api.subject(cid)["topics"][0]["id"]
    sid = api.save_source({"course_id": cid, "title": "Bishop", "author": "",
                           "contents": "6 Kernel Methods\n6.1 Dual representations ..... 293\n6.2 Constructing kernels 294"})["id"]
    r = api.reading(cid)
    ch = r["sources"][0]["chapters"][0]
    assert ch["title"] == "Kernel Methods" and [s["number"] for s in ch["sections"]] == ["6.1", "6.2"]
    assert api.add_chapter({"source_id": sid, "number": "7", "title": "", "sections": "1-3", "topic_id": str(tid),
                            "optional": False})["added"] == 3
    assert "Added 0 chapters and 1 section." == api.import_contents(sid, "6.3 Kernels for graphs")["message"]
    api.save_chapter({"id": ch["id"], "number": "6", "title": "Kernels", "topic_id": str(tid)})
    api.set_chapter_read(ch["id"], True)
    r = api.reading(cid)
    assert r["progress"]["read"] == 3 and r["progress"]["required"] == 6
    assert api.subject(cid)["topics"][0]["reading"]["read"] == 3
    sec = r["sources"][0]["chapters"][1]["sections"][0]
    api.set_section_required(sec["id"], False)
    assert api.reading(cid)["progress"]["required"] == 5
    assert "No numbered lines" in api.import_contents(sid, "hello")["error"]


def test_unknown_subject(api: Api) -> None:
    assert api.subject(999)["error"]


def test_greeting_changes_between_launches(tmp_path) -> None:
    seen = []
    for _ in range(12):
        a = Api(tmp_path / "studypal.db", notify=lambda t, b: True)
        g = a.overview()["greeting"]
        assert g["hello"] and g["text"]
        seen.append(g["text"])
        a._close()
    assert all(x != y for x, y in zip(seen, seen[1:]))
    assert len(set(seen)) > 2


def test_overall_progress(api: Api) -> None:
    assert api.overview()["overall"] is None  # nothing to measure yet
    a = add_course(api, "A1", start=-10, exam=10)  # half the time used
    b = add_course(api, "B1", start=-10, exam=10)
    api.add_topics(a, "One\nTwo")
    api.add_topics(b, "Three\nFour")
    for t in api.subject(a)["topics"]:
        api.set_topic_status(t["id"], "reviewed")
    o = api.overview()["overall"]
    assert o["percent"] == 50 and o["elapsed"] == pytest.approx(0.5)
    assert o["mood"] == "on_track" and not o["is_behind"]
    assert o["words"].startswith("2 of 4 topics done across 2 subjects")
    api.set_topic_status(api.subject(a)["topics"][0]["id"], "in_progress")
    o = api.overview()["overall"]
    assert o["is_behind"] and o["mood_words"] == "behind by 25%"


def test_a_whole_source_can_belong_to_a_topic(api: Api) -> None:
    cid = add_course(api)
    api.add_topics(cid, "Kernels\nTrees")
    kernels, trees = (t["id"] for t in api.subject(cid)["topics"])
    sid = api.save_source({"course_id": cid, "title": "Kernel paper", "author": "Doe, Jane", "kind": "article",
                           "year": "2020", "journal": "JMLR", "topic_id": str(kernels),
                           "contents": "1 Intro\n1.1 Motivation\n1.2 Setup\n2 Method\n2.1 Model"})["id"]
    r = api.reading(cid)["sources"][0]
    assert r["topic"] == "Kernels" and r["kind"] == "article"
    assert r["reference"]["text"] == "Doe, J. (2020). Kernel paper. JMLR."
    assert {ch["group"] for ch in r["chapters"]} == {kernels}
    # A chapter can go to another topic, and a section to yet another.
    ch2 = r["chapters"][1]
    api.save_chapter({"id": ch2["id"], "number": "2", "title": "Method", "topic_id": str(trees)})
    r = api.reading(cid)["sources"][0]
    assert [ch["group"] for ch in r["chapters"]] == [kernels, trees]
    assert [s["group"] for s in r["chapters"][0]["sections"]] == [kernels, kernels]
    # Reading counts toward the topic through the source.
    api.set_chapter_read(r["chapters"][0]["id"], True)
    topics = {t["title"]: t for t in api.subject(cid)["topics"]}
    assert topics["Kernels"]["reading"]["read"] == 2 and topics["Kernels"]["status"] == "in_progress"
    assert topics["Trees"]["reading"]["read"] == 0
    # Editing keeps the details; unlinking the topic works.
    api.save_source({"id": sid, "title": "Kernel paper", "author": "Doe, Jane", "kind": "article", "year": "2021",
                     "journal": "JMLR", "topic_id": ""})
    r = api.reading(cid)["sources"][0]
    assert r["topic_id"] is None and r["year"] == "2021"


def test_apa_preview(api: Api) -> None:
    r = api.apa_preview({"title": "Book", "author": "Bishop, C.", "year": "2006", "publisher": "Springer"})
    assert r["html"] == "Bishop, C. (2006). <i>Book</i>. Springer."
    assert api.apa_preview({"title": "x", "kind": "poem"})["error"]


def test_a_chapter_without_sections_can_be_ticked_off(api: Api) -> None:
    cid = add_course(api)
    api.add_topics(cid, "Kernels")
    tid = api.subject(cid)["topics"][0]["id"]
    sid = api.save_source({"course_id": cid, "title": "Bishop", "topic_id": str(tid)})["id"]
    api.add_chapter({"source_id": sid, "number": "6", "title": "Kernels", "sections": ""})
    api.add_chapter({"source_id": sid, "number": "7", "title": "Sparse", "sections": "1-2"})
    r = api.reading(cid)
    six = r["sources"][0]["chapters"][0]
    assert six["sections"] == [] and six["progress"]["required"] == 1 and not six["read"]
    assert r["progress"]["required"] == 3  # chapter 6 itself, plus 7.1 and 7.2

    api.set_chapter_read(six["id"], True)
    r = api.reading(cid)
    assert r["sources"][0]["chapters"][0]["read"] and r["sources"][0]["chapters"][0]["progress"]["complete"]
    assert r["progress"]["read"] == 1
    topic = api.subject(cid)["topics"][0]
    assert topic["reading"] == {"read": 1, "required": 3, "optional_read": 0, "optional": 0,
                                "fraction": pytest.approx(1 / 3), "complete": False}
    assert topic["last_studied"] == "today" and topic["status"] == "not_started"  # 7 is still unread

    api.set_chapter_read(r["sources"][0]["chapters"][1]["id"], True)
    assert api.subject(cid)["topics"][0]["status"] == "in_progress"  # all needed reading done

    api.set_chapter_read(six["id"], False)
    assert api.reading(cid)["progress"]["read"] == 2

    # Once a chapter gets sections, they're what counts.
    api.set_chapter_read(six["id"], True)
    api.add_chapter({"source_id": sid, "number": "6", "sections": "1-3"})
    six = api.reading(cid)["sources"][0]["chapters"][0]
    assert six["progress"] == {"read": 0, "required": 3, "optional_read": 0, "optional": 0, "fraction": 0.0, "complete": False}


def test_theme_is_kept_for_the_computer(tmp_path) -> None:
    a = Api(tmp_path / "studypal.db", notify=lambda t, b: True)
    assert a.get_theme() == "system"
    assert a.set_theme("nord", "#2e3440") == {"ok": True}
    assert a.set_theme("../evil", "")["error"]
    a._close()
    again = Api(tmp_path / "studypal.db", notify=lambda t, b: True)
    assert again.get_theme() == "nord" and again._prefs()["background"] == "#2e3440"
    again._close()


def test_the_pling_is_a_short_fading_sound() -> None:
    from studypal.core import sound

    one, two = sound.samples(sound.FOCUS_DONE), sound.samples(sound.BREAK_OVER)
    assert 0.2 < max(abs(x) for x in one) < 0.6 and len(two) > len(one)
    assert max(abs(x) for x in one[-500:]) < 0.01  # faded out by the end
