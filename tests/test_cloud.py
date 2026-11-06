"""Accounts and cloud sync, against an in-memory stand-in for Supabase. Two Api objects with their own
folders play two computers signed in to the same account."""

from __future__ import annotations

import copy
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from studypal.api import Api
from studypal.core.cloud import AUTH_MESSAGES, Client, CloudError, Offline, Session, SignedOut, _quote
from studypal.core.logic.merge import empty


class FakeCloud:
    """Accounts and rows the way Supabase keeps them, plus switches to simulate trouble."""

    def __init__(self) -> None:
        self.users: dict[str, tuple[str, str]] = {}  # email -> (user id, password)
        self.rows: dict[str, dict] = {}  # user id -> dataset
        self.files: dict[str, dict[str, tuple[bytes, str]]] = {}  # user id -> {key: (data, uploaded at)}
        self.file_requests = 0
        self.refresh_tokens: dict[str, str] = {}  # token -> user id
        self.offline = False
        self.confirm_email = False

    def _session(self, user_id: str, email: str) -> Session:
        token = uuid.uuid4().hex
        self.refresh_tokens[token] = user_id
        return Session(user_id, email, "access-" + token, token, time.time() + 3600)

    def _up(self) -> None:
        if self.offline:
            raise Offline("Couldn't reach the cloud (no network).")

    def sign_up(self, email: str, password: str) -> Session | None:
        self._up()
        if email in self.users:
            raise CloudError(AUTH_MESSAGES["user_already_exists"])
        user_id = str(uuid.uuid4())
        self.users[email] = (user_id, password)
        self.rows[user_id] = empty()
        return None if self.confirm_email else self._session(user_id, email)

    def sign_in(self, email: str, password: str) -> Session:
        self._up()
        if self.users.get(email, ("", None))[1] != password:
            raise CloudError(AUTH_MESSAGES["invalid_credentials"])
        return self._session(self.users[email][0], email)

    def refresh(self, refresh_token: str) -> Session:
        self._up()
        user_id = self.refresh_tokens.pop(refresh_token, None)
        if user_id is None or user_id not in self.rows:
            raise SignedOut("You've been signed out. Sign in again to keep syncing.")
        email = next(e for e, (u, _) in self.users.items() if u == user_id)
        return self._session(user_id, email)

    def sign_out(self, session: Session) -> None:
        self.refresh_tokens.pop(session.refresh_token, None)

    def change_password(self, session: Session, password: str) -> None:
        self._up()
        self.users[session.email] = (session.user_id, password)

    def delete_account(self, session: Session) -> None:
        self._up()
        del self.users[session.email]
        del self.rows[session.user_id]
        self.files.pop(session.user_id, None)

    def fetch_rows(self, session: Session):
        self._up()
        return copy.deepcopy(self.rows[session.user_id])

    def upload_rows(self, session: Session, rows) -> None:
        self._up()
        for table, uid, data in rows:
            self.rows[session.user_id][table][uid] = copy.deepcopy(data)

    def delete_rows(self, session: Session, keys) -> None:
        self._up()
        for table, uid in keys:
            self.rows[session.user_id][table].pop(uid, None)

    def list_files(self, session: Session) -> dict[str, str]:
        self._up()
        self.file_requests += 1
        return {k: at for k, (_, at) in self.files.get(session.user_id, {}).items()}

    def upload_file(self, session: Session, key: str, data: bytes, mime: str) -> None:
        self._up()
        self.file_requests += 1
        self.files.setdefault(session.user_id, {})[key] = (data, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))

    def download_file(self, session: Session, key: str) -> bytes:
        self._up()
        self.file_requests += 1
        if key not in self.files.get(session.user_id, {}):
            raise CloudError("Object not found")
        return self.files[session.user_id][key][0]

    def delete_files(self, session: Session, keys: list[str]) -> None:
        self._up()
        self.file_requests += 1
        for k in keys:
            self.files.get(session.user_id, {}).pop(k, None)


@pytest.fixture
def fake() -> FakeCloud:
    return FakeCloud()


def computer(tmp_path: Path, name: str, fake: FakeCloud) -> Api:
    folder = tmp_path / name
    return Api(folder / "studypal.db", notify=lambda t, b: True, client=fake)  # type: ignore[arg-type]


@pytest.fixture
def laptop(tmp_path, fake):
    api = computer(tmp_path, "laptop", fake)
    yield api
    api._close()


@pytest.fixture
def desktop(tmp_path, fake):
    api = computer(tmp_path, "desktop", fake)
    yield api
    api._close()


def add_course(api: Api, code: str) -> int:
    today = date.today()
    r = api.save_course({"name": f"Course {code}", "code": code, "cram_start": today.isoformat(),
                         "exam_date": (today + timedelta(days=30)).isoformat()})
    assert r.get("ok"), r
    return r["id"]


def codes(api: Api) -> list[str]:
    return sorted(c["code"] for c in api.overview()["courses"])


def test_without_a_client_there_are_no_accounts(tmp_path) -> None:
    api = Api(tmp_path / "studypal.db")
    assert api.account()["configured"] is False
    assert api.cloud_sync()["changed"] is False
    assert "isn't connected" in api.sign_in("a@b.no", "password1")["error"]
    api._close()


def test_sign_up_moves_this_computers_data_into_the_account(laptop: Api, fake: FakeCloud) -> None:
    add_course(laptop, "KJM1100")
    assert laptop.account()["local_subjects"] == 1
    r = laptop.sign_up("ada@example.com", "correct horse", True)
    assert r == {"ok": True, "message": "Signed in as ada@example.com."}
    state = laptop.account()
    assert state["signed_in"] and state["email"] == "ada@example.com" and state["sync"]["status"] == "synced"
    assert codes(laptop) == ["KJM1100"]
    user_id = fake.users["ada@example.com"][0]
    assert [c["code"] for c in fake.rows[user_id]["course"].values()] == ["KJM1100"]
    assert len(fake.rows[user_id]["deadline"]) == 1  # the course's exam
    # Signing out shows this computer's own data again, which was moved, not copied.
    assert laptop.sign_out()["ok"]
    assert codes(laptop) == [] and not laptop.account()["signed_in"]


def test_password_and_email_checks(laptop: Api, fake: FakeCloud) -> None:
    assert "8 characters" in laptop.sign_up("ada@example.com", "short")["error"]
    assert "email" in laptop.sign_up("not an email", "long enough")["error"]
    laptop.sign_up("ada@example.com", "long enough")
    laptop.sign_out()
    assert laptop.sign_up("ada@example.com", "long enough")["error"].startswith("There's already an account")
    assert laptop.sign_in("ada@example.com", "wrong password")["error"] == "Wrong email or password."


def test_email_confirmation(laptop: Api, fake: FakeCloud) -> None:
    fake.confirm_email = True
    r = laptop.sign_up("ada@example.com", "long enough")
    assert r["confirm"] and "ada@example.com" in r["message"]
    assert not laptop.account()["signed_in"]


def test_two_computers_share_changes(laptop: Api, desktop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    course = add_course(laptop, "INF301")
    laptop.add_topics(course, "Kernels\nTrees")
    laptop.cloud_sync()

    assert desktop.sign_in("ada@example.com", "long enough")["ok"]
    assert codes(desktop) == ["INF301"]
    desk_course = desktop.overview()["courses"][0]["id"]
    topics = desktop.subject(desk_course)["topics"]
    assert [t["title"] for t in topics] == ["Kernels", "Trees"]

    # An edit on each side, then both sync: both edits survive.
    desktop.set_topic_status(topics[0]["id"], "confident")
    laptop_topics = laptop.subject(course)["topics"]
    laptop.delete_topic(laptop_topics[1]["id"])
    assert desktop.cloud_sync()["changed"] is False
    assert laptop.cloud_sync()["changed"] is True
    assert desktop.cloud_sync()["changed"] is True
    for api, cid in ((laptop, course), (desktop, desk_course)):
        assert [(t["title"], t["status"]) for t in api.subject(cid)["topics"]] == [("Kernels", "confident")]


def test_offline_changes_go_up_later(laptop: Api, desktop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    desktop.sign_in("ada@example.com", "long enough")
    fake.offline = True
    add_course(laptop, "STK310")
    r = laptop.cloud_sync()
    assert r["sync"]["status"] == "offline" and codes(laptop) == ["STK310"]
    fake.offline = False
    assert laptop.cloud_sync()["sync"]["status"] == "synced"
    desktop.cloud_sync()
    assert codes(desktop) == ["STK310"]


def test_signing_out_without_network_asks_first(laptop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    add_course(laptop, "DAT255")
    fake.offline = True
    r = laptop.sign_out()
    assert r["unsynced"] and "would be lost" in r["error"]
    assert laptop.account()["signed_in"]
    assert laptop.sign_out(True)["ok"] and not laptop.account()["signed_in"]


def test_stays_signed_in_between_launches(tmp_path: Path, fake: FakeCloud) -> None:
    first = computer(tmp_path, "laptop", fake)
    first.sign_up("ada@example.com", "long enough")
    add_course(first, "INF395")
    first._close()
    again = computer(tmp_path, "laptop", fake)
    assert again.account()["email"] == "ada@example.com" and codes(again) == ["INF395"]
    assert again.cloud_sync()["sync"]["status"] == "synced"
    again._close()


def test_a_revoked_sign_in_signs_out_and_keeps_working(tmp_path: Path, fake: FakeCloud) -> None:
    first = computer(tmp_path, "laptop", fake)
    first.sign_up("ada@example.com", "long enough")
    first._close()
    fake.refresh_tokens.clear()  # e.g. the password was changed on another computer
    again = computer(tmp_path, "laptop", fake)
    r = again.cloud_sync()
    assert r["signed_out"] and not again.account()["signed_in"]
    add_course(again, "LOCAL1")  # still usable, on this computer only
    again._close()


def test_delete_account(laptop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    add_course(laptop, "INF301")
    laptop.cloud_sync()
    assert laptop.delete_account()["ok"]
    assert fake.users == {} and fake.rows == {}
    assert not laptop.account()["signed_in"] and codes(laptop) == []
    assert not (laptop._local_path.parent / "accounts").exists() or not any((laptop._local_path.parent / "accounts").iterdir())


def test_signing_in_can_bring_local_data_along(laptop: Api, desktop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    add_course(laptop, "INF301")
    laptop.cloud_sync()
    add_course(desktop, "INF301")  # same code, made before signing in on the desktop
    add_course(desktop, "MAT100")
    desktop.sign_in("ada@example.com", "long enough", True)
    assert codes(desktop) == ["INF301", "INF301-2", "MAT100"]
    laptop.cloud_sync()
    assert codes(laptop) == ["INF301", "INF301-2", "MAT100"]


def test_running_timer_survives_a_sync(laptop: Api, desktop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    course = add_course(laptop, "INF301")
    laptop.cloud_sync()
    desktop.sign_in("ada@example.com", "long enough")
    laptop.timer_start(course, None)
    desktop.add_topics(desktop.overview()["courses"][0]["id"], "New topic")
    desktop.cloud_sync()
    laptop.cloud_sync()
    assert laptop.overview()["running"]["course_code"] == "INF301"
    assert laptop.timer_stop()["ok"]


# ---------- the HTTP client's small parts ----------

def test_quoting_for_postgrest() -> None:
    assert _quote('a"b\\c') == '"a\\"b\\\\c"'


@pytest.mark.parametrize("status, body, kind, text", [
    (400, b'{"error_code": "invalid_credentials", "msg": "Invalid login credentials"}', CloudError, "Wrong email"),
    (422, b'{"error_code": "user_already_exists"}', CloudError, "already an account"),
    (400, b'{"error_code": "refresh_token_not_found"}', SignedOut, "signed out"),
    (401, b'{"message": "JWT expired"}', SignedOut, "signed out"),
    (503, b"", Offline, "problem"),
    (409, b'{"message": "conflict here"}', CloudError, "conflict here"),
])
def test_error_messages(status, body, kind, text) -> None:
    e = Client._error(status, body)
    assert type(e) is kind and text in str(e)


def test_reading_details_and_topics_sync(laptop: Api, desktop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    course = add_course(laptop, "INF301")
    laptop.add_topics(course, "Kernels")
    topic = laptop.subject(course)["topics"][0]["id"]
    laptop.save_source({"course_id": course, "title": "Bishop", "author": "Bishop, Christopher", "year": "2006",
                        "publisher": "Springer", "topic_id": str(topic), "contents": "6 Kernels\n6.1 Dual"})
    laptop.cloud_sync()
    desktop.sign_in("ada@example.com", "long enough")
    desk_course = desktop.overview()["courses"][0]["id"]
    src = desktop.reading(desk_course)["sources"][0]
    assert src["topic"] == "Kernels" and src["publisher"] == "Springer"
    assert src["reference"]["text"] == "Bishop, C. (2006). Bishop. Springer."


def test_ticked_chapters_sync(laptop: Api, desktop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    course = add_course(laptop, "INF301")
    sid = laptop.save_source({"course_id": course, "title": "Bishop"})["id"]
    laptop.add_chapter({"source_id": sid, "number": "6", "sections": ""})
    chapter = laptop.reading(course)["sources"][0]["chapters"][0]["id"]
    laptop.set_chapter_read(chapter, True)
    laptop.cloud_sync()
    desktop.sign_in("ada@example.com", "long enough")
    desk_course = desktop.overview()["courses"][0]["id"]
    assert desktop.reading(desk_course)["sources"][0]["chapters"][0]["read"] is True


# ---------- several accounts on one computer ----------

def emails(api: Api) -> list[tuple[str, bool]]:
    return [(a["email"], a["active"]) for a in api.account()["accounts"]]


def test_switching_between_accounts(laptop: Api, fake: FakeCloud) -> None:
    add_course(laptop, "LOCAL1")  # belongs to this computer only
    laptop.sign_up("ada@example.com", "long enough", False)
    add_course(laptop, "ADA1")
    # Adding a second account keeps the first signed in, and never brings its data along.
    assert laptop.sign_up("bo@example.com", "long enough", True)["ok"]
    assert emails(laptop) == [("ada@example.com", False), ("bo@example.com", True)]
    assert codes(laptop) == []
    add_course(laptop, "BO1")

    assert laptop.switch_account(fake.users["ada@example.com"][0])["message"] == "Switched to ada@example.com."
    assert codes(laptop) == ["ADA1"] and laptop.account()["email"] == "ada@example.com"
    # Leaving an account saved its changes first.
    assert [c["code"] for c in fake.rows[fake.users["bo@example.com"][0]]["course"].values()] == ["BO1"]

    assert laptop.switch_account(None)["ok"]
    assert codes(laptop) == ["LOCAL1"] and not laptop.account()["signed_in"]
    assert len(laptop.account()["accounts"]) == 2  # still both signed in

    laptop.switch_account(fake.users["bo@example.com"][0])
    assert codes(laptop) == ["BO1"]
    assert "isn't signed in" in laptop.switch_account("00000000-0000-0000-0000-000000000000")["error"]


def test_signing_out_moves_on_to_the_next_account(laptop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    add_course(laptop, "ADA1")
    laptop.sign_up("bo@example.com", "long enough")
    r = laptop.sign_out()
    assert r["message"] == "Signed out of bo@example.com. Now using ada@example.com."
    assert emails(laptop) == [("ada@example.com", True)] and codes(laptop) == ["ADA1"]
    assert laptop.sign_out()["message"] == "Signed out of ada@example.com."
    assert not laptop.account()["signed_in"] and laptop.account()["accounts"] == []


def test_switching_offline_keeps_changes_for_later(laptop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    laptop.sign_up("bo@example.com", "long enough")
    ada = fake.users["ada@example.com"][0]
    laptop.switch_account(ada)
    fake.offline = True
    add_course(laptop, "OFF1")
    assert laptop.switch_account(None)["ok"]  # works without network
    fake.offline = False
    laptop.switch_account(ada)
    assert codes(laptop) == ["OFF1"]
    assert [c["code"] for c in fake.rows[ada]["course"].values()] == ["OFF1"]


def test_accounts_are_remembered_between_launches(tmp_path: Path, fake: FakeCloud) -> None:
    first = computer(tmp_path, "laptop", fake)
    first.sign_up("ada@example.com", "long enough")
    first.sign_up("bo@example.com", "long enough")
    first.switch_account(fake.users["ada@example.com"][0])
    first._close()
    again = computer(tmp_path, "laptop", fake)
    assert emails(again) == [("ada@example.com", True), ("bo@example.com", False)]
    again._close()


def test_single_account_file_from_earlier_versions_is_converted(tmp_path: Path, fake: FakeCloud) -> None:
    import json

    session = fake.sign_up("ada@example.com", "long enough")
    folder = tmp_path / "laptop"
    folder.mkdir()
    (folder / "account.json").write_text(json.dumps(
        {"user_id": session.user_id, "email": session.email, "refresh_token": session.refresh_token}))
    api = computer(tmp_path, "laptop", fake)
    assert emails(api) == [("ada@example.com", True)]
    assert not (folder / "account.json").exists() and (folder / "accounts.json").exists()
    assert api.cloud_sync()["sync"]["status"] == "synced"
    api._close()


def test_a_revoked_account_hands_over_to_the_next(laptop: Api, fake: FakeCloud) -> None:
    laptop.sign_up("ada@example.com", "long enough")
    laptop.sign_up("bo@example.com", "long enough")
    laptop._account.session.expires_at = 0  # force a refresh
    fake.refresh_tokens.pop(laptop._account.session.refresh_token)
    r = laptop.cloud_sync()
    assert r["signed_out"] and "bo@example.com" in r["error"]
    assert emails(laptop) == [("ada@example.com", True)]


def test_the_cloud_accepts_every_kind_of_row_the_app_syncs() -> None:
    """study_rows only takes the kinds of rows its check lists (the newest migration that sets it), so a new
    table needs a migration too, or signing in would stop syncing as soon as one of its rows exists."""
    import re
    from pathlib import Path

    from studypal.core.logic.merge import TABLES

    migrations = sorted((Path(__file__).resolve().parent.parent / "supabase" / "migrations").glob("*.sql"))
    newest = [m.read_text() for m in migrations if "study_rows_tbl_check" in m.read_text()][-1]
    allowed = set(re.findall(r"'([a-z_]+)'", newest.split("check (tbl in", 1)[1].split(")")[0]))
    assert set(TABLES) <= allowed, f"add these to a migration: {sorted(set(TABLES) - allowed)}"
