"""Accounts and cloud sync through Supabase.

The app always works on its local SQLite database, so it's fast and keeps working offline. When
someone is signed in, `sync` merges that database with their rows in Supabase:

  1. fetch every row of the account from Supabase (network, nothing locked),
  2. merge it with the local database against the last synced version, row by row (logic/merge.py,
     the same merge `study` uses for git sync), and write the result into the local database,
  3. upload the rows that differ from what Supabase has, and delete the ones that are gone,
  4. remember the result as the last synced version.

Anything changed locally while 3 is running is newer than the remembered version, so it goes up next
time. A sync that fails halfway is safe to repeat: nothing is remembered until the upload is done.

Only the standard library is used for HTTP (plus certifi for certificates, which a packaged app
can't take from the system's Python).
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dataset import apply_dataset, export_dataset
from .logic.merge import TABLES, Dataset, MergeReport, _same, changed_rows, empty, merge3
from .storage import Store

PAGE = 1000  # Supabase returns at most this many rows per request
UPLOAD_BATCH = 500
DELETE_BATCH = 50  # uids go in the URL, so keep it short
BUCKET = "exam-files"


class CloudError(Exception):
    """Something went wrong with the account or the cloud; the message is fit to show as it is."""


class Offline(CloudError):
    """The cloud couldn't be reached. Work carries on locally and syncs later."""


class SignedOut(CloudError):
    """The sign-in is no longer valid (password changed elsewhere, account deleted, ...)."""


# GoTrue error codes -> what to tell the person.
AUTH_MESSAGES = {
    "invalid_credentials": "Wrong email or password.",
    "user_already_exists": "There's already an account with that email. Sign in instead.",
    "email_exists": "There's already an account with that email. Sign in instead.",
    "weak_password": "Pick a longer password: at least 8 characters.",
    "email_address_invalid": "That doesn't look like an email address.",
    "validation_failed": "Check the email address and password.",
    "over_request_rate_limit": "Too many attempts. Wait a minute and try again.",
    "over_email_send_rate_limit": "Too many attempts. Wait a minute and try again.",
    "email_not_confirmed": "Confirm your email address first: open the link in the email we sent you.",
    "same_password": "That's already your password.",
    "signup_disabled": "New accounts can't be created right now.",
}


@dataclass
class Session:
    user_id: str
    email: str
    access_token: str
    refresh_token: str
    expires_at: float  # unix time

    @classmethod
    def from_auth(cls, body: dict) -> Session:
        user = body.get("user") or {}
        return cls(user_id=user["id"], email=user.get("email", ""), access_token=body["access_token"],
                   refresh_token=body["refresh_token"],
                   expires_at=float(body.get("expires_at") or time.time() + float(body.get("expires_in", 3600))))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _quote(value: str) -> str:
    """A value inside PostgREST's in.(...) list."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Client:
    """Talks to one Supabase project: GoTrue for accounts, PostgREST for rows."""

    def __init__(self, url: str, anon_key: str, timeout: float = 20) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.timeout = timeout
        self._ssl = _ssl_context()

    def _request(self, method: str, path: str, body: Any = None, token: str | None = None,
                 headers: dict[str, str] | None = None) -> tuple[Any, dict[str, str]]:
        data = None
        headers = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        raw, response_headers = self._send(method, path, data, token, headers)
        return (json.loads(raw) if raw else None), response_headers

    def _send(self, method: str, path: str, data: bytes | None, token: str | None,
              headers: dict[str, str]) -> tuple[bytes, dict[str, str]]:
        req = urllib.request.Request(f"{self.url}{path}", method=method)
        req.add_header("apikey", self.anon_key)
        if token:  # a publishable key (sb_publishable_...) isn't a JWT, so it only goes in apikey
            req.add_header("Authorization", f"Bearer {token}")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, data, timeout=self.timeout if data is None or len(data) < 1_000_000 else 300,
                                        context=self._ssl) as resp:
                return resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            raise self._error(e.code, e.read()) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            raise Offline(f"Couldn't reach the cloud ({reason}).") from None

    @staticmethod
    def _error(status: int, raw: bytes) -> CloudError:
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        code = body.get("error_code") or body.get("code") or body.get("error") or ""
        message = body.get("msg") or body.get("message") or body.get("error_description") or ""
        if code in ("refresh_token_not_found", "refresh_token_already_used", "session_not_found",
                    "user_not_found", "bad_jwt") or (status == 401 and code != "invalid_credentials"):
            return SignedOut("You've been signed out. Sign in again to keep syncing.")
        if code in AUTH_MESSAGES:
            return CloudError(AUTH_MESSAGES[code])
        if code == "invalid_grant" and "Invalid login" in message:
            return CloudError(AUTH_MESSAGES["invalid_credentials"])
        if status >= 500:
            return Offline(f"The cloud had a problem ({status}). Your work is safe on this computer.")
        return CloudError(message or f"The cloud said no ({status}).")

    # ---------- accounts ----------

    def sign_up(self, email: str, password: str) -> Session | None:
        """Creates the account. Returns None when the project wants the email confirmed first."""
        body, _ = self._request("POST", "/auth/v1/signup", {"email": email, "password": password})
        return Session.from_auth(body) if body and body.get("access_token") else None

    def sign_in(self, email: str, password: str) -> Session:
        body, _ = self._request("POST", "/auth/v1/token?grant_type=password", {"email": email, "password": password})
        return Session.from_auth(body)

    def refresh(self, refresh_token: str) -> Session:
        body, _ = self._request("POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": refresh_token})
        return Session.from_auth(body)

    def sign_out(self, session: Session) -> None:
        self._request("POST", "/auth/v1/logout", {}, token=session.access_token)

    def change_password(self, session: Session, password: str) -> None:
        self._request("PUT", "/auth/v1/user", {"password": password}, token=session.access_token)

    def delete_account(self, session: Session) -> None:
        # Files first: the database can't remove them itself.
        keys = sorted(self.list_files(session))  # names
        if keys:
            self.delete_files(session, keys)
        self._request("POST", "/rest/v1/rpc/delete_my_account", {}, token=session.access_token)

    # ---------- rows ----------

    def fetch_rows(self, session: Session) -> Dataset:
        data = empty()
        start = 0
        while True:
            rows, _ = self._request(
                "GET", "/rest/v1/study_rows?select=tbl,uid,data&order=tbl.asc,uid.asc", token=session.access_token,
                headers={"Range-Unit": "items", "Range": f"{start}-{start + PAGE - 1}"})
            for r in rows or []:
                if r["tbl"] in data:
                    data[r["tbl"]][r["uid"]] = r["data"]
            if not rows or len(rows) < PAGE:
                return data
            start += PAGE

    def upload_rows(self, session: Session, rows: list[tuple[str, str, dict]]) -> None:
        for i in range(0, len(rows), UPLOAD_BATCH):
            batch = [{"user_id": session.user_id, "tbl": t, "uid": u, "data": d} for t, u, d in rows[i:i + UPLOAD_BATCH]]
            self._request("POST", "/rest/v1/study_rows?on_conflict=user_id,tbl,uid", batch, token=session.access_token,
                          headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def delete_rows(self, session: Session, keys: list[tuple[str, str]]) -> None:
        by_table: dict[str, list[str]] = {}
        for table, uid in keys:
            by_table.setdefault(table, []).append(uid)
        for table, uids in by_table.items():
            for i in range(0, len(uids), DELETE_BATCH):
                values = ",".join(_quote(u) for u in uids[i:i + DELETE_BATCH])
                query = urllib.parse.urlencode({"tbl": f"eq.{table}", "uid": f"in.({values})"})
                self._request("DELETE", f"/rest/v1/study_rows?{query}", token=session.access_token,
                              headers={"Prefer": "return=minimal"})


    # ---------- exam files (Supabase Storage) ----------
    # Each account's files are in its own folder of the private bucket: <user id>/<key>.

    def list_files(self, session: Session) -> dict[str, str]:
        """The account's files, with when each was uploaded."""
        names: dict[str, str] = {}
        offset = 0
        while True:
            rows, _ = self._request("POST", f"/storage/v1/object/list/{BUCKET}",
                                    {"prefix": session.user_id, "limit": PAGE, "offset": offset}, token=session.access_token)
            names.update({r["name"]: str(r.get("created_at") or "") for r in rows or [] if r.get("id")})  # folders have no id
            if not rows or len(rows) < PAGE:
                return names
            offset += PAGE

    def upload_file(self, session: Session, key: str, data: bytes, mime: str) -> None:
        self._send("POST", f"/storage/v1/object/{BUCKET}/{session.user_id}/{key}", data, session.access_token,
                   {"Content-Type": mime, "x-upsert": "true"})

    def download_file(self, session: Session, key: str) -> bytes:
        data, _ = self._send("GET", f"/storage/v1/object/authenticated/{BUCKET}/{session.user_id}/{key}", None,
                             session.access_token, {})
        return data

    def delete_files(self, session: Session, keys: list[str]) -> None:
        for i in range(0, len(keys), 100):
            self._request("DELETE", f"/storage/v1/object/{BUCKET}",
                          {"prefixes": [f"{session.user_id}/{k}" for k in keys[i:i + 100]]}, token=session.access_token)


# ---------- the signed-in accounts, remembered between launches ----------

class Accounts:
    """Everyone signed in on this computer, saved in accounts.json so they stay signed in, and which of
    them is in use (None: nobody, the data that belongs to this computer only). Refreshes the active
    access token when it's about to run out, and saves the new refresh token each time (Supabase
    rotates them). Reads the single-account account.json of earlier versions once and replaces it."""

    def __init__(self, path: Path, client: Client) -> None:
        self.path = path
        self.client = client
        self.sessions: dict[str, Session] = {}  # user id -> session, in the order they were added
        self.active: str | None = None
        legacy = path.with_name("account.json")
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                for a in saved.get("accounts", []):
                    self.sessions[a["user_id"]] = Session(a["user_id"], a["email"], "", a["refresh_token"], 0)
                self.active = saved.get("active") if saved.get("active") in self.sessions else None
            except (ValueError, KeyError, TypeError):
                self.sessions, self.active = {}, None
        elif legacy.exists() and legacy != path:
            try:
                saved = json.loads(legacy.read_text(encoding="utf-8"))
                self.sessions[saved["user_id"]] = Session(saved["user_id"], saved["email"], "", saved["refresh_token"], 0)
                self.active = saved["user_id"]
                self._save()
            except (ValueError, KeyError):
                pass
            legacy.unlink(missing_ok=True)

    @property
    def session(self) -> Session | None:
        return self.sessions.get(self.active) if self.active else None

    @property
    def signed_in(self) -> bool:
        return self.session is not None

    def listing(self) -> list[dict]:
        return [{"user_id": u, "email": s.email, "active": u == self.active} for u, s in self.sessions.items()]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "active": self.active,
            "accounts": [{"user_id": s.user_id, "email": s.email, "refresh_token": s.refresh_token}
                         for s in self.sessions.values()],
        }), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def remember(self, session: Session, make_active: bool = True) -> None:
        self.sessions[session.user_id] = session
        if make_active:
            self.active = session.user_id
        self._save()

    def use(self, user_id: str | None) -> None:
        if user_id is not None and user_id not in self.sessions:
            raise CloudError("That account isn't signed in on this computer.")
        self.active = user_id
        self._save()

    def forget(self, user_id: str | None = None) -> None:
        """Remove an account (the active one by default). If it was active, nobody is."""
        user_id = user_id or self.active
        if user_id is None:
            return
        self.sessions.pop(user_id, None)
        if self.active == user_id:
            self.active = None
        self._save()

    def fresh(self) -> Session:
        """The active session, with an access token good for at least another minute."""
        session = self.session
        if session is None:
            raise SignedOut("Not signed in.")
        if session.expires_at - time.time() < 60:
            self.remember(self.client.refresh(session.refresh_token))
        return self.session  # type: ignore[return-value]


# ---------- syncing ----------

@dataclass
class SyncResult:
    pulled: int = 0  # local rows changed by what came from the cloud
    pushed: int = 0  # rows uploaded or deleted in the cloud
    report: MergeReport = field(default_factory=MergeReport)


def load_base(path: Path) -> Dataset:
    """The data as it was after the last successful sync (empty before the first one)."""
    if not path.exists():
        return empty()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return empty()  # a damaged file only means the next merge treats everything as new
    return {t: saved.get(t, {}) for t in TABLES}


def save_base(path: Path, data: Dataset) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def sync(store: Store, client: Client, session: Session, base_path: Path,
         locked: Callable[[], Any] | None = None) -> SyncResult:
    """Merge the local database with the account's rows in the cloud (see the module docstring).
    `locked` is a context manager factory the caller uses to keep other writers out while the local
    database is read and rewritten; the network steps run outside it."""
    remote = client.fetch_rows(session)
    base = load_base(base_path)
    with (locked() if locked else _nothing()):
        with store.sync_lock() as conn:
            local = export_dataset(conn)
            merged, report = merge3(base, local, remote)
            pulled = changed_rows(local, merged)
            if pulled:
                apply_dataset(conn, merged)
    uploads = [(t, uid, row) for t in TABLES for uid, row in merged[t].items() if not _same(row, remote[t].get(uid))]
    deletes = [(t, uid) for t in TABLES for uid in remote[t] if uid not in merged[t]]
    if uploads:
        client.upload_rows(session, uploads)
    if deletes:
        client.delete_rows(session, deletes)
    save_base(base_path, merged)
    return SyncResult(pulled=pulled, pushed=len(uploads) + len(deletes), report=report)


def sync_files(store: Store, client: Client, session: Session, folder: Path, known_path: Path,
               locked: Callable[[], Any] | None = None) -> None:
    """Make the account's exam files the same here and in the cloud: upload new ones, download the ones
    added on another computer, and remove the ones no exam uses any more. `known_path` remembers which
    files the cloud has, so a sync with nothing new to move makes no requests."""
    from . import files

    with (locked() if locked else _nothing()):
        wanted = store.file_keys()
        mimes = dict(store.conn.execute("select key, mime from exam_file").fetchall())
    try:
        known = set(json.loads(known_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        known = None
    here = {f.name for f in folder.iterdir()} if folder.is_dir() else set()
    if known is not None and wanted <= here and wanted <= known and not (known - wanted):
        return
    listing = client.list_files(session)
    remote = set(listing)
    for key in sorted(wanted - remote):
        if key in here:
            client.upload_file(session, key, (folder / key).read_bytes(), mimes.get(key, "application/octet-stream"))
            remote.add(key)
    for key in sorted((wanted & remote) - here):
        folder.mkdir(parents=True, exist_ok=True)
        try:
            data = client.download_file(session, key)
        except Offline:
            raise
        except CloudError:
            continue  # gone from the cloud; the exam just shows the file as missing
        tmp = files.path(folder, key).with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(folder / key)
    # Another computer uploads an exam's rows just before its files, so a file can show up here before the
    # exam that uses it: only files that have been there a while are taken as unused.
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 15 * 60))
    unused = sorted(k for k in remote - wanted if files.KEY.fullmatch(k) and listing.get(k, "") < cutoff)
    if unused:
        client.delete_files(session, unused)
        remote -= set(unused)
    with (locked() if locked else _nothing()):  # a file added meanwhile must stay
        files.tidy(folder, store.file_keys())
    tmp = known_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(remote)), encoding="utf-8")
    tmp.replace(known_path)


def move_into(store: Store, other: Store) -> None:
    """Move everything in `other` into `store`, keeping what `store` already has (for bringing the data
    made before signing in into an account). Rows have unique ids, so nothing is overwritten; a course
    code both have is renamed (INF301-2). `other` is emptied afterwards, so signing out later doesn't
    show the same subjects twice."""
    with other.sync_lock() as conn:
        extra = export_dataset(conn)
    with store.sync_lock() as conn:
        mine = export_dataset(conn)
        merged, _ = merge3(empty(), mine, extra)
        apply_dataset(conn, merged)
    with other.sync_lock() as conn:
        apply_dataset(conn, empty())
        conn.execute("delete from active_timer")
        conn.execute("delete from pomodoro_run")


class _nothing:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        return None
