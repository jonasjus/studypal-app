"""What the window can ask for. Every public method here is callable from JavaScript as
`pywebview.api.<name>(...)` and takes and returns plain JSON values.

Dates go to the page as ISO strings ("2026-12-10", "2026-12-10T09:00") so they drop straight into
<input type="date"> / <input type="datetime-local">, alongside ready-made labels for display.

Actions return {"ok": true, ...} or {"error": "message to show"}; nothing raises into the page.
"""

from __future__ import annotations

import base64
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .core import alerts, cloud, files, notifier, sound
from .core.files import FileError
from .core import ingest
from .core.generate import generate_exam
from .core.grade import grade as grade_answers
from .core.llm import PROVIDERS, LLMError, provider_from
from .core.llm import chosen as llm_chosen
from .core.logic import questions as question_logic
from .core.pages import PageError
from .core.logic import exams as exam_logic
from .core.logic import attempts as attempt_logic
from .core.cloud import Accounts, Client, CloudError, Offline, SignedOut
from .core.config import DEFAULT_THRESHOLDS, Config
from .core.dashboard import CourseSummary, build
from .core.export import to_markdown
from .core.logic.cite import KINDS, apa
from .core.logic.countdown import Urgency, countdown, describe_days, urgency
from .core.logic.dates import DateParseError
from .core.logic.notify import banner_groups
from .core.logic.pomodoro import PomodoroRun, PomodoroSettings, focus_done, overtime, phase_length, remaining
from .core.logic.reading import ReadingParseError, ReadingProgress, parse_section_ranges, parse_toc
from .core.logic.stats import days_since, format_minutes, is_stale, minutes_per_day, week_range
from .core.logic.timeline import CramProgress, Phase, cram_progress
from .core.models import (
    COURSE_COLORS,
    Course,
    Deadline,
    DeadlineKind,
    Exam,
    ExamAttempt,
    ExamFile,
    ExamQuestion,
    FILE_ROLES,
    LINK_CATEGORIES,
    PROJECT_STATUSES,
    READING_STATUSES,
    RESULTS,
    Priority,
    Project,
    ProjectEntry,
    ProjectLink,
    CourseNote,
    ProjectNote,
    ProjectSource,
    ProjectTask,
    Section,
    Session,
    Source,
    Topic,
    TopicStatus,
    WeakSpot,
)
from .core.storage import StorageError, Store

TYPE_LABELS = {"short_answer": "Short answer", "calculation": "Calculation", "proof": "Proof",
               "multiple_choice": "Multiple choice", "true_false": "True or false", "essay": "Essay", "code": "Code"}
CITE_FIELDS = ("kind", "year", "publisher", "edition", "journal", "volume", "issue", "pages", "link")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Settings the window can change, stored in the database's setting table: key -> (default, lowest, highest).
SETTINGS: dict[str, tuple[int, int, int]] = {
    "focus_minutes": (25, 1, 180),
    "short_break_minutes": (5, 1, 60),
    "long_break_minutes": (15, 1, 120),
    "long_break_every": (4, 1, 12),
    "week_start": (0, 0, 6),
    "stale_after_days": (7, 1, 90),
    "notifications": (1, 0, 1),
    "sound": (1, 0, 1),  # a pling when a Pomodoro focus block or break ends
}


# One is picked each time the app opens, never the same as the time before.
GREETINGS = (
    "Small steps every day add up to big results.",
    "You don't have to do it all today. Just start with one topic.",
    "Twenty-five focused minutes beats two distracted hours.",
    "Every topic you tick off is one less thing to worry about.",
    "Progress, not perfection.",
    "The hardest part is starting. You've already opened the app.",
    "Future you will be glad you studied today.",
    "One weak spot at a time. That's how they stop being weak.",
    "Consistency beats cramming. A little today keeps the panic away.",
    "You know more than you did last week. Keep going.",
    "Pick the topic you've been avoiding. It's probably smaller than it looks.",
    "Take breaks. A rested brain remembers more.",
    "Explaining it to yourself out loud is studying too.",
    "Don't compare your chapter 2 to someone else's chapter 10.",
    "A short session still counts. Log it and be proud of it.",
    "Doubt kills more exams than lack of knowledge. You've got this.",
    "Make today's goal small enough that you can't say no to it.",
    "Old topics fade. Ten minutes of revisiting brings them back.",
)


def _hello(now: datetime) -> str:
    if now.hour < 5:
        return "Studying late"
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"


def _overall(summaries: list[CourseSummary]) -> dict | None:
    """All active subjects together: the share of all their topics that's done, against how far into
    their cram periods you are (each subject counts in proportion to its number of topics)."""
    with_topics = [s for s in summaries if s.topics]
    total = sum(len(s.topics) for s in with_topics)
    if not total:
        return None
    done_topics = sum(round(s.progress.done * len(s.topics)) for s in with_topics)
    done = done_topics / total
    elapsed = sum(s.progress.elapsed * len(s.topics) for s in with_topics) / total
    behind = max(0.0, elapsed - done)
    started = any(s.progress.phase is not Phase.BEFORE for s in with_topics)
    words = f"{done_topics} of {total} topics done across {len(with_topics)} subject{'s' if len(with_topics) != 1 else ''}"
    if started:
        words += f" · {round(elapsed * 100)}% of the time used"
    if behind > 0.005 and started:
        mood, mood_words = "behind", f"behind by {round(behind * 100)}%"
    elif started and done - elapsed > 0.05:
        mood, mood_words = "ahead", "ahead of schedule"
    else:
        mood, mood_words = "on_track", "on track" if started else ""
    return {"done": done, "elapsed": elapsed, "behind": behind, "is_behind": mood == "behind",
            "show_today": started, "percent": round(done * 100), "words": words, "mood": mood,
            "mood_words": mood_words, "total_time": format_minutes(sum(s.total_minutes for s in summaries))}


# The fonts and text sizes in Settings (the page knows what each looks like: themes.js).
FONTS = ("source", "atkinson", "system", "serif")
TEXT_SIZES = ("small", "normal", "large", "larger")


class UserError(ValueError):
    """Something the person typed can't be used; the message says why."""


def action(method: Callable[..., Any]) -> Callable[..., Any]:
    """Run under the store lock, and turn problems into {"error": ...} for the page to show."""

    @functools.wraps(method)
    def wrapper(self: Api, *args: Any) -> Any:
        with self._lock:
            try:
                result = method(self, *args)
            except (StorageError, DateParseError, ReadingParseError, UserError, CloudError, FileError) as e:
                return {"error": str(e)}
            except Exception as e:  # a bug: say so instead of leaving the page waiting
                return {"error": f"Something went wrong: {e}"}
        return {"ok": True} if result is None else result

    return wrapper


# ---------- reading what the page sends ----------

def _text(data: dict, key: str) -> str:
    return str(data.get(key) or "").strip()


def _int(data: dict, key: str) -> int | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise UserError(f"{key.replace('_', ' ').capitalize()} must be a whole number.") from None


def _date(data: dict, key: str, label: str) -> date:
    value = _text(data, key)
    if not value:
        raise UserError(f"Pick a date for {label}.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UserError(f"{value!r} isn't a date.") from None


def _datetime(data: dict, key: str, label: str) -> datetime:
    value = _text(data, key)
    if not value:
        raise UserError(f"Pick a date and time for {label}.")
    try:
        return datetime.fromisoformat(value).replace(second=0, microsecond=0)
    except ValueError:
        raise UserError(f"{value!r} isn't a date and time.") from None


# ---------- turning things into JSON ----------

def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


def _day(d: date) -> str:
    """'Tue 10 Nov'"""
    return f"{d:%a} {d.day} {d:%b}"


def _when(dt: datetime) -> str:
    """'Tue 10 Nov 09:00'"""
    return f"{_day(dt)} {dt:%H:%M}"


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    return value.isoformat()


def _reading(r: ReadingProgress) -> dict:
    return {"read": r.read, "required": r.required, "optional_read": r.optional_read, "optional": r.optional,
            "fraction": r.fraction, "complete": r.complete}


def _progress(p: CramProgress) -> dict:
    done = f"{round(p.done * 100)}% done"
    if p.topic_count == 0:
        words = "No topics yet"
    elif p.phase is Phase.BEFORE:
        words = f"{done} · cramming starts {describe_days(p.days_left - p.days_total)}"
    elif p.phase is Phase.AFTER:
        words = f"{done} · exam was {describe_days(p.days_left)}"
    else:
        words = f"{done} · {round(p.elapsed * 100)}% of the time used"
    return {
        "elapsed": p.elapsed, "done": p.done, "behind": p.behind, "is_behind": p.is_behind,
        "phase": p.phase.value, "days_left": p.days_left, "words": words,
        "behind_words": f"behind by {round(p.behind * 100)}%" if p.is_behind else "",
        "show_today": p.phase in (Phase.CRAMMING, Phase.EXAM_DAY),
    }


def _exam_words(course: Course, p: CramProgress) -> str:
    if p.days_left < 0:
        return f"Exam was {describe_days(p.days_left)}"
    when = "today" if p.days_left == 0 else describe_days(p.days_left)
    return f"Exam {when}"


def _course(c: Course) -> dict:
    return {"id": c.id, "name": c.name, "code": c.code, "color": c.color, "notes": c.notes, "done": c.done,
            "banner": c.banner,
            "cram_start": _iso(c.cram_start), "exam_date": _iso(c.exam_date),
            "cram_start_label": _day(c.cram_start), "exam_label": _day(c.exam_date)}


def _summary(s: CourseSummary) -> dict:
    facts = [f"{len(s.topics)} topic{'s' if len(s.topics) != 1 else ''}"]
    if s.stale_topics:
        facts.append(f"{s.stale_topics} not looked at lately")
    if s.open_weak:
        facts.append(f"{s.open_weak} weak spot{'s' if s.open_weak != 1 else ''}")
    facts.append(f"{format_minutes(s.week_minutes)} this week")
    return {
        **_course(s.course),
        "progress": _progress(s.progress),
        "exam_words": _exam_words(s.course, s.progress),
        "facts": " · ".join(facts),
        "week_minutes": s.week_minutes,
        "total_minutes": s.total_minutes,
        "reading": _reading(s.reading),
    }


def _deadline(d: Deadline, now: datetime, codes: dict[int, str]) -> dict:
    u = urgency(d.due_at, now, d.done)
    if u is Urgency.DONE:
        when = "done"
    elif u is Urgency.OVERDUE:
        when = f"overdue by {countdown(d.due_at, now).removeprefix('overdue by ')}"
    else:
        when = countdown(d.due_at, now)
    return {"id": d.id, "title": d.title, "kind": d.kind.value, "course_id": d.course_id,
            "course_code": codes.get(d.course_id) if d.course_id is not None else None,
            "due_at": _iso(d.due_at), "due_label": _when(d.due_at), "when": when, "urgency": u.value,
            "done": d.done, "is_course_exam": d.is_course_exam}


def _weak(w: WeakSpot, now: datetime, codes: dict[int, str], topics: dict[int, str]) -> dict:
    age = (now.date() - w.created_at.date()).days
    return {"id": w.id, "course_id": w.course_id, "course_code": codes.get(w.course_id),
            "topic_id": w.topic_id, "topic": topics.get(w.topic_id) if w.topic_id else None,
            "description": w.description, "priority": w.priority.value, "resolved": w.resolved,
            "age": "today" if age == 0 else f"{age}d ago"}


def _session(s: Session, codes: dict[int, str], topics: dict[int, str]) -> dict:
    return {"id": s.id, "course_id": s.course_id, "course_code": codes.get(s.course_id),
            "topic_id": s.topic_id, "topic": topics.get(s.topic_id) if s.topic_id else None,
            "started_at": _iso(s.started_at), "started_label": _when(s.started_at),
            "minutes": s.minutes, "length": format_minutes(s.minutes), "note": s.note}


def _optional_date(data: dict, key: str) -> date | None:
    value = _text(data, key)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UserError(f"{value!r} isn't a date.") from None


STATUS_LABELS = {"idea": "Idea", "active": "Active", "paused": "Paused", "done": "Done"}
READING_LABELS = {"to_read": "To read", "reading": "Reading", "read": "Read"}
# Addresses a shortcut may open: web pages, and apps that register their own kind of link.
LINK_SCHEMES = ("http", "https", "zotero", "obsidian")
# (piece of the address, kind of shortcut), for guessing a shortcut's icon. First match wins.
LINK_GUESSES = (
    ("overleaf.", "writing"), ("sharelatex.", "writing"),
    ("zotero", "references"), ("mendeley.", "references"),
    ("scholar.google.", "search"), ("arxiv.org", "search"), ("semanticscholar.", "search"), ("pubmed", "search"),
    ("researchgate.", "search"), ("dblp.", "search"), ("connectedpapers.", "search"),
    ("colab.research.google.", "notebook"), ("jupyter", "notebook"), ("kaggle.com/code", "notebook"),
    ("github.", "code"), ("gitlab.", "code"), ("bitbucket.", "code"),
    ("huggingface.co/datasets", "data"), ("kaggle.", "data"), ("zenodo.", "data"), ("figshare.", "data"),
    ("data.", "data"), ("huggingface.", "code"),
    ("docs.google.", "docs"), ("drive.google.", "docs"), ("notion.", "docs"), ("dropbox.", "docs"),
    ("onedrive.", "docs"), ("sharepoint.", "docs"),
)


def link_address(text: str) -> str:
    """What a shortcut or reference opens: a DOI becomes its doi.org page, a bare "github.com/me" gets https://.
    Raises UserError for anything else, so a shortcut can never run a program or open a local file."""
    t = text.strip()
    if not t:
        raise UserError("Paste the address to open.")
    doi = re.match(r"^(?:doi:\s*)?(10\.\d{4,9}/\S+)$", t, re.IGNORECASE)
    if doi:
        return f"https://doi.org/{doi.group(1)}"
    scheme = re.match(r"^([a-z][a-z0-9+.-]*):", t, re.IGNORECASE)
    if scheme and not re.match(r"^[^/]+:\d+", t):  # "localhost:8888" is a host and port, not a scheme
        if scheme.group(1).lower() not in LINK_SCHEMES:
            raise UserError("Shortcuts open web addresses (https://…) or Zotero and Obsidian links.")
        return t
    if t.startswith(("localhost", "127.0.0.1")):  # a notebook server on this computer
        return f"http://{t}"
    if " " in t or "." not in t.split("/")[0]:
        raise UserError(f"“{t}” doesn't look like a web address.")
    return f"https://{t}"


def guess_category(url: str) -> str:
    low = url.lower()
    if low.startswith("zotero:"):
        return "references"
    if low.startswith("obsidian:"):
        return "docs"
    return next((kind for piece, kind in LINK_GUESSES if piece in low), "other")


def _host(url: str) -> str:
    """Where a shortcut goes, in short: "github.com", or the app for a zotero:// or obsidian:// link."""
    if not url.lower().startswith(("http:", "https:")):
        return f"{url.split(':', 1)[0].capitalize()} app"
    m = re.match(r"^[a-z]+://([^/?#]+)", url, re.IGNORECASE)
    return m.group(1).removeprefix("www.") if m else url.split(":", 1)[0]


def _project(p: Project) -> dict:
    today = date.today()
    if p.end_on:
        days = (p.end_on - today).days
        due = f"due {describe_days(days)}" if days >= 0 else f"was due {describe_days(days)}"
    else:
        due = ""
    return {"id": p.id, "title": p.title, "description": p.description, "status": p.status,
            "status_label": STATUS_LABELS.get(p.status, p.status), "tags": p.tags, "tags_text": ", ".join(p.tags),
            "start_on": _iso(p.start_on), "end_on": _iso(p.end_on), "color": p.color, "done": p.done,
            "start_label": _day(p.start_on) if p.start_on else "", "end_label": _day(p.end_on) if p.end_on else "",
            "due_words": due, "due_days": (p.end_on - today).days if p.end_on else None}


def _project_session(s: Session) -> dict:
    return {"id": s.id, "project_id": s.project_id, "started_at": _iso(s.started_at),
            "started_label": _when(s.started_at), "minutes": s.minutes, "length": format_minutes(s.minutes),
            "note": s.note}


class Api:
    """`db_path` is the database used while nobody is signed in. With a cloud `client`, a signed-in account
    gets its own database next to it (accounts/<user id>/studypal.db), synced with the cloud."""

    def __init__(self, db_path: Path | str, notify: Callable[[str, str], bool] = notifier.send,
                 client: Client | None = None, account_file: Path | None = None,
                 play: Callable[[str], None] = sound.play) -> None:
        self._lock = threading.RLock()  # one caller at a time on the database
        self._sync_lock = threading.Lock()  # one sync (or sign-in/out) at a time
        self._local_path = Path(db_path)
        self._client = client
        self._account = Accounts(account_file or self._local_path.parent / "accounts.json", client) if client else None
        self._store = Store(self._account_db() if self._signed_in else self._local_path)
        self._sync: dict[str, Any] = {"status": "idle", "message": "", "at": None}
        self._notify = notify
        self._window = None  # set by the app once the window exists (for the save dialog)
        self._last_pomo_phase: tuple[str, int, bool] | None = None
        self._play = play
        self._pending: list[str] = []  # messages from the background check, for the window's next tick
        self._pending_changed = False
        self._awake = sound.KeepAwake()
        # Model jobs running in the background ("read:<exam id>", "make:<course id>") -> what they're doing now.
        self._jobs: dict[str, str] = {}
        self._greeting = self._pick_greeting()

    def _pick_greeting(self) -> str:
        """A different encouragement from last time the app opened (remembered on this computer)."""
        import random

        try:
            last = int(self._store.get_setting("app.last_greeting", "-1"))  # type: ignore[arg-type]
        except ValueError:
            last = -1
        choice = random.choice([i for i in range(len(GREETINGS)) if i != last])
        self._store.set_setting("app.last_greeting", str(choice))
        return GREETINGS[choice]

    def _close(self) -> None:
        with self._lock:
            self._store.close()

    # ---------- account and cloud sync ----------

    @property
    def _signed_in(self) -> bool:
        return self._account is not None and self._account.signed_in

    def _account_dir(self, user_id: str | None = None) -> Path:
        user_id = user_id or self._account.session.user_id  # type: ignore[union-attr]
        if not re.fullmatch(r"[0-9a-fA-F-]{1,64}", user_id):
            raise CloudError("The cloud sent back an account id StudyPal doesn't understand.")
        return self._local_path.parent / "accounts" / user_id

    def _account_db(self, user_id: str | None = None) -> Path:
        return self._account_dir(user_id) / "studypal.db"

    def _use_db(self, path: Path) -> None:
        with self._lock:
            self._store.close()
            self._store = Store(path)
            self._last_pomo_phase = None

    def _leave_account(self, delete_local_copy: bool) -> str | None:
        """Take the active account off this computer and carry on with the next signed-in account, or with
        the data that belongs to nobody. Returns the email of the account now in use, if any."""
        user_dir = self._account_dir() if self._signed_in else None
        self._account.forget()  # type: ignore[union-attr]
        if delete_local_copy and user_dir is not None:
            self._use_db(self._local_path)  # close the account's database before removing it
            shutil.rmtree(user_dir, ignore_errors=True)
        nxt = next(iter(self._account.sessions), None)  # type: ignore[union-attr]
        self._account.use(nxt)  # type: ignore[union-attr]
        self._use_db(self._account_db(nxt) if nxt else self._local_path)
        self._sync = {"status": "idle", "message": "", "at": None}
        return self._account.session.email if nxt else None  # type: ignore[union-attr]

    @action
    def account(self) -> dict:
        local_subjects = 0
        if not self._signed_in:
            local_subjects = len(self._store.list_courses())
        return {"configured": self._client is not None, "signed_in": self._signed_in,
                "email": self._account.session.email if self._signed_in else None,  # type: ignore[union-attr]
                "accounts": self._account.listing() if self._account else [],
                "local_subjects": local_subjects, "sync": dict(self._sync)}

    def _sync_quietly(self) -> None:
        """Save the active account's changes before moving away from it. Nothing is lost if it fails:
        the account's copy stays on this computer and syncs next time it's used."""
        if self._signed_in:
            try:
                cloud.sync(self._store, self._client, self._account.fresh(), self._base_path(),  # type: ignore[arg-type, union-attr]
                           locked=lambda: self._lock)
                self._sync_files()
            except (CloudError, StorageError, OSError):
                pass

    def switch_account(self, user_id: str | None) -> dict:
        """Change to another account signed in on this computer (or, with no id, to the data that
        belongs to nobody), without signing anyone out."""
        with self._sync_lock:
            user_id = user_id or None
            if self._account is None:
                return {"error": "This copy of StudyPal isn't connected to the cloud."}
            if user_id == self._account.active:
                return {"ok": True}
            try:
                self._sync_quietly()
                self._account.use(user_id)
            except CloudError as e:
                return {"error": str(e)}
            target = self._account_db(user_id) if user_id else self._local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            self._use_db(target)
            self._sync = {"status": "idle", "message": "", "at": None}
            if not user_id:
                return {"ok": True, "message": "Using this computer only."}
            result = self._run_sync()
            if "error" in result:
                return {"ok": True, "message": result["error"]}
            return {"ok": True, "message": f"Switched to {self._account.session.email}."}  # type: ignore[union-attr]

    def _enter(self, session: cloud.Session, bring_local: bool) -> dict:
        """Switch to the account's database, optionally adding this computer's data to it, then sync.
        Another account already in use stays signed in; its changes are saved first."""
        target = self._account_db(session.user_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._sync_quietly()
        with self._lock:
            # Only data that belongs to nobody can be brought along, never another account's.
            if bring_local and not self._signed_in and self._store.list_courses():
                with Store(target) as account_store:
                    cloud.move_into(account_store, self._store)
                files.copy_all(self._files_dir(), files.folder_for(target))
                files.tidy(self._files_dir(), set())
            self._account.remember(session)  # type: ignore[union-attr]
            self._use_db(target)
            self._sync = {"status": "idle", "message": "", "at": None}
        result = self._run_sync()
        if "error" in result:
            # Signed in, but the first sync didn't go through: say so, it retries by itself.
            return {"ok": True, "message": result["error"]}
        return {"ok": True, "message": f"Signed in as {session.email}."}

    def _check_credentials(self, email: str, password: str) -> tuple[str, str]:
        if self._client is None:
            raise CloudError("This copy of StudyPal isn't connected to the cloud.")
        email = str(email or "").strip()
        if "@" not in email:
            raise UserError("Enter your email address.")
        if len(str(password or "")) < 8:
            raise UserError("The password needs at least 8 characters.")
        return email, str(password)

    def sign_up(self, email: str, password: str, bring_local: bool = True) -> dict:
        with self._sync_lock:
            try:
                email, password = self._check_credentials(email, password)
                session = self._client.sign_up(email, password)  # type: ignore[union-attr]
                if session is None:
                    return {"ok": True, "confirm": True,
                            "message": f"Almost done: open the link we emailed to {email}, then sign in here."}
                return self._enter(session, bool(bring_local))
            except (CloudError, UserError, StorageError) as e:
                return {"error": str(e)}

    def sign_in(self, email: str, password: str, bring_local: bool = False) -> dict:
        with self._sync_lock:
            try:
                email, password = self._check_credentials(email, password)
                return self._enter(self._client.sign_in(email, password), bool(bring_local))  # type: ignore[union-attr]
            except (CloudError, UserError, StorageError) as e:
                return {"error": str(e)}

    def sign_out(self, anyway: bool = False) -> dict:
        """Syncs one last time, then removes this computer's copy of the account's data (it's in the
        cloud). If the last sync can't happen, asks before going ahead, since recent changes would be lost."""
        with self._sync_lock:
            if not self._signed_in:
                return {"ok": True}
            if not anyway:
                try:
                    cloud.sync(self._store, self._client, self._account.fresh(), self._base_path(),  # type: ignore[arg-type, union-attr]
                               locked=lambda: self._lock)
                except SignedOut:
                    pass  # nothing more can be saved anyway
                except CloudError as e:
                    return {"error": f"{e} Changes since the last sync would be lost if you sign out now.",
                            "unsynced": True}
            try:
                self._client.sign_out(self._account.session)  # type: ignore[union-attr, arg-type]
            except CloudError:
                pass  # the session ends locally either way
            email = self._account.session.email  # type: ignore[union-attr]
            now_using = self._leave_account(delete_local_copy=True)
            return {"ok": True, "message": f"Signed out of {email}." + (f" Now using {now_using}." if now_using else "")}

    def change_password(self, password: str) -> dict:
        with self._sync_lock:
            try:
                if len(str(password or "")) < 8:
                    raise UserError("The password needs at least 8 characters.")
                self._client.change_password(self._account.fresh(), str(password))  # type: ignore[union-attr]
                return {"ok": True, "message": "Password changed."}
            except (CloudError, UserError) as e:
                return {"error": str(e)}

    def delete_account(self) -> dict:
        with self._sync_lock:
            try:
                self._client.delete_account(self._account.fresh())  # type: ignore[union-attr]
            except CloudError as e:
                return {"error": str(e)}
            now_using = self._leave_account(delete_local_copy=True)
            return {"ok": True, "message": "Your account and its data are deleted." + (f" Now using {now_using}." if now_using else "")}

    def _base_path(self) -> Path:
        return self._account_dir() / "cloud-base.json"

    def _sync_files(self) -> None:
        """Exam files, after the rows (so this computer knows which files the exams need)."""
        with self._lock:
            store = self._store
            wanted = store.file_keys()
        if not wanted and not (self._account_dir() / "cloud-files.json").exists():
            return  # never had any files: nothing to ask the cloud
        cloud.sync_files(store, self._client, self._account.fresh(), self._files_dir(store),  # type: ignore[arg-type, union-attr]
                         self._account_dir() / "cloud-files.json", locked=lambda: self._lock)

    def cloud_sync(self) -> dict:
        """Called a few seconds after each change and every minute. Never blocks the window: if a sync is
        already running, this one is skipped."""
        if not self._signed_in:
            return {"ok": True, "changed": False, "sync": dict(self._sync)}
        if not self._sync_lock.acquire(blocking=False):
            return {"ok": True, "changed": False, "sync": dict(self._sync)}
        try:
            return self._run_sync()
        finally:
            self._sync_lock.release()

    def _run_sync(self) -> dict:
        """A sync, with the outcome recorded for the status in the top bar. Caller holds _sync_lock."""
        now = datetime.now()
        try:
            result = cloud.sync(self._store, self._client, self._account.fresh(), self._base_path(),  # type: ignore[arg-type, union-attr]
                                locked=lambda: self._lock)
            self._sync_files()
        except SignedOut:
            email = self._account.session.email  # type: ignore[union-attr]
            self._leave_account(delete_local_copy=False)
            return {"error": f"{email} was signed out. Sign in again to keep syncing it.", "signed_out": True}
        except Offline as e:
            self._sync = {"status": "offline", "message": str(e), "at": self._sync.get("at")}
            return {"ok": True, "changed": False, "sync": dict(self._sync)}
        except (CloudError, StorageError) as e:
            self._sync = {"status": "error", "message": str(e), "at": self._sync.get("at")}
            return {"ok": True, "changed": False, "sync": dict(self._sync)}
        except Exception as e:  # a bug: keep working locally and say so
            self._sync = {"status": "error", "message": f"Sync failed: {e}", "at": self._sync.get("at")}
            return {"ok": True, "changed": False, "sync": dict(self._sync)}
        notes = result.report.notes()
        self._sync = {"status": "synced", "message": "; ".join(notes), "at": f"{now:%H:%M}"}
        return {"ok": True, "changed": result.pulled > 0, "sync": dict(self._sync)}

    # ---------- settings ----------

    def _setting(self, key: str) -> int:
        default, lo, hi = SETTINGS[key]
        try:
            value = int(self._store.get_setting(f"app.{key}", str(default)))  # type: ignore[arg-type]
        except ValueError:
            return default
        return min(hi, max(lo, value))

    def _config(self) -> Config:
        return Config(
            thresholds=DEFAULT_THRESHOLDS,
            week_start=self._setting("week_start"),
            stale_after_days=self._setting("stale_after_days"),
            pomodoro=self._pomodoro_settings(),
        )

    def _pomodoro_settings(self) -> PomodoroSettings:
        return PomodoroSettings(
            focus=timedelta(minutes=self._setting("focus_minutes")),
            short_break=timedelta(minutes=self._setting("short_break_minutes")),
            long_break=timedelta(minutes=self._setting("long_break_minutes")),
            long_break_every=self._setting("long_break_every"),
        )

    # The theme belongs to the computer, not to whichever account is in use, so it lives in prefs.json.

    def _prefs_path(self) -> Path:
        return self._local_path.parent / "prefs.json"

    def _prefs(self) -> dict:
        try:
            return json.loads(self._prefs_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @action
    def get_theme(self) -> str:
        return str(self._prefs().get("theme") or "system")

    @action
    def set_theme(self, name: str, background: str = "") -> None:
        if not re.fullmatch(r"[a-z0-9-]{1,40}", str(name or "")):
            raise UserError("That isn't a theme.")
        prefs = self._prefs()
        prefs["theme"] = name
        # The window's colour before the page has loaded, so it opens without a flash.
        prefs["background"] = background if re.fullmatch(r"#[0-9a-fA-F]{6}", str(background or "")) else ""
        self._write_prefs(prefs)

    @action
    def get_type(self) -> dict:
        """The font and text size chosen on this computer."""
        prefs = self._prefs()
        return {"font": str(prefs.get("font") or "source"), "size": str(prefs.get("text_size") or "normal")}

    @action
    def set_type(self, font: str, size: str) -> None:
        if font not in FONTS or size not in TEXT_SIZES:
            raise UserError("That isn't a font or text size StudyPal offers.")
        prefs = self._prefs()
        prefs["font"], prefs["text_size"] = font, size
        self._write_prefs(prefs)

    def _write_prefs(self, prefs: dict) -> None:
        path = self._prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(prefs), encoding="utf-8")
        os.chmod(tmp, 0o600)  # it can hold API keys
        tmp.replace(path)

    @action
    def get_settings(self) -> dict:
        return {key: self._setting(key) for key in SETTINGS}

    @action
    def save_settings(self, data: dict) -> None:
        for key, (_, lo, hi) in SETTINGS.items():
            if key not in data:
                continue
            value = _int(data, key)
            if value is None or not lo <= value <= hi:
                raise UserError(f"{key.replace('_', ' ').capitalize()} must be between {lo} and {hi}.")
            self._store.set_setting(f"app.{key}", str(value))

    # ---------- the overview ----------

    def _codes(self) -> dict[int, str]:
        return {c.id: c.code for c in self._store.list_courses()}  # type: ignore[misc]

    def _topic_titles(self) -> dict[int, str]:
        return {t.id: t.title for t in self._store.list_topics()}  # type: ignore[misc]

    def _running(self, now: datetime) -> dict | None:
        """The plain timer or the Pomodoro, whichever is going, with what the page needs to count."""
        codes, topics = self._codes(), self._topic_titles()
        timer = self._store.get_timer()
        if timer is not None:
            return {"kind": "timer", "course_id": timer.course_id, "course_code": codes.get(timer.course_id),
                    **self._running_label(timer.course_id, timer.project_id, codes),
                    "topic": topics.get(timer.topic_id) if timer.topic_id else None,
                    "started_at": timer.started_at.isoformat(timespec="seconds"),
                    "elapsed_seconds": int((now - timer.started_at).total_seconds())}
        run = self._store.get_pomodoro()
        if run is not None:
            return self._pomodoro_json(run, now, codes, topics)
        return None

    def _running_label(self, course_id: int | None, project_id: int | None, codes: dict[int, str]) -> dict:
        """What's being worked on, for the bar at the top: a course's code or a project's title."""
        if project_id is not None:
            p = self._store.get_project(project_id)
            return {"project_id": project_id, "label": p.title if p else "Research"}
        return {"project_id": None, "label": codes.get(course_id) if course_id is not None else ""}

    def _pomodoro_json(self, run: PomodoroRun, now: datetime, codes: dict[int, str], topics: dict[int, str]) -> dict:
        settings = self._pomodoro_settings()
        left = remaining(run, now, settings)
        length = phase_length(run.phase, settings)
        return {"kind": "pomodoro", "course_id": run.course_id, "course_code": codes.get(run.course_id),
                **self._running_label(run.course_id, run.project_id, codes),
                "topic": topics.get(run.topic_id) if run.topic_id else None,
                "phase": run.phase.value, "phase_label": run.phase.label, "paused": run.paused,
                "completed": run.completed, "focus_done": focus_done(run, now, settings),
                "overtime_seconds": int(overtime(run, now, settings).total_seconds()),
                "remaining_seconds": int(left.total_seconds()) if left is not None else None,
                "length_seconds": int(length.total_seconds()) if length is not None else None}

    @action
    def overview(self) -> dict:
        now = datetime.now().replace(microsecond=0)
        self._store.settle_pomodoro(now, self._pomodoro_settings())
        dash = build(self._store, self._config(), now)
        codes, topics = self._codes(), self._topic_titles()
        overdue, soon = banner_groups(dash.deadlines, now)
        projects = self._store.list_projects()
        first_day = dash.week_days[0]
        research_week = minutes_per_day(self._store.list_project_sessions(
            since=datetime.combine(first_day, datetime.min.time()),
            until=datetime.combine(first_day + timedelta(days=7), datetime.min.time())), first_day)
        return {
            "today": f"{now:%A} {now.day} {now:%B}",
            "greeting": {"hello": _hello(now), "text": self._greeting},
            "overall": _overall(dash.courses),
            "courses": [_summary(s) for s in dash.courses],
            "done_courses": [_summary(s) for s in dash.done_courses],
            "deadlines": [_deadline(d, now, codes) for d in dash.deadlines],
            "weak_spots": [_weak(w, now, codes, topics) for w in dash.weak_spots],
            "list": self._overview_list(dash.courses, projects, False, now),
            "done_list": self._overview_list(dash.done_courses, projects, True, now),
            "week": [{"label": f"{d:%a}", "minutes": m + r, "course_minutes": m, "research_minutes": r,
                      "length": format_minutes(m + r) if m + r else "", "today": d == now.date()}
                     for d, m, r in zip(dash.week_days, dash.week_minutes, research_week)],
            "week_total": format_minutes(sum(dash.week_minutes) + sum(research_week)),
            "week_has_research": any(research_week),
            "banner": {"overdue": [_deadline(d, now, codes) for d in overdue],
                       "soon": [_deadline(d, now, codes) for d in soon]},
            "running": self._running(now),
            "colors": list(COURSE_COLORS),
            "next_color": self._store.next_color(),
        }

    def _overview_list(self, courses: list[CourseSummary], projects: list[Project], done: bool, now: datetime) -> list[dict]:
        """Courses and research projects in one list, in the order you've dragged them into. Until you have,
        courses come first (soonest exam first), then projects in the order they were added."""
        week_start, week_end = week_range(now.date(), self._config().week_start)
        items: list[tuple[tuple[int, int, int], dict]] = []
        for i, s in enumerate(courses):
            items.append(((s.course.position, 0, i), {"kind": "course", **_summary(s)}))
        mine = [p for p in projects if p.done == done]
        for i, p in enumerate(mine):
            items.append(((p.position, 1, i), {"kind": "project", **self._project_card(p, week_start, week_end)}))
        return [item for _, item in sorted(items, key=lambda kv: kv[0])]

    def _project_card(self, p: Project, week_start: datetime, week_end: datetime) -> dict:
        tasks = self._store.list_tasks(p.id)  # type: ignore[arg-type]
        sources = self._store.list_project_sources(p.id)  # type: ignore[arg-type]
        week = sum(s.minutes for s in self._store.list_project_sessions(p.id, since=week_start, until=week_end))
        notes = len(self._store.list_notes(p.id))  # type: ignore[arg-type]
        facts = []
        if notes:
            facts.append(f"{notes} note{'s' if notes != 1 else ''}")
        if sources:
            facts.append(f"{sum(1 for x in sources if x.status == 'read')}/{len(sources)} read")
        facts.append(f"{format_minutes(week)} this week")
        open_tasks = [t for t in tasks if not t.done]
        return {**_project(p), "tasks_done": len(tasks) - len(open_tasks), "tasks_total": len(tasks),
                "next_task": open_tasks[0].text if open_tasks else "", "facts": " · ".join(facts),
                "week_minutes": week}

    @action
    def subject(self, course_id: int) -> dict:
        now = datetime.now().replace(microsecond=0)
        course = self._store.get_course(course_id)
        if course is None:
            raise UserError("That subject no longer exists.")
        cfg = self._config()
        topics = self._store.list_topics(course_id)
        reading = self._store.reading_by_topic(course_id)
        codes, titles = self._codes(), self._topic_titles()
        week_start, week_end = week_range(now.date(), cfg.week_start)
        progress = cram_progress(course, topics, now.date())
        week = sum(s.minutes for s in self._store.list_sessions(course_id, since=week_start, until=week_end))
        notes = self._store.list_course_notes(course_id)
        topic_notes: dict[int, int] = {}
        for n in notes:
            if n.topic_id is not None:
                topic_notes[n.topic_id] = topic_notes.get(n.topic_id, 0) + 1
        topic_rows = []
        for t in topics:
            since = days_since(t.last_studied, now.date())
            topic_rows.append({
                "id": t.id, "title": t.title, "status": t.status.value, "status_label": t.status.label,
                "confidence": t.confidence, "stale": is_stale(t, now.date(), cfg.stale_after_days),
                "last_studied": "never" if since is None else "today" if since == 0
                else "yesterday" if since == 1 else f"{since} days ago",
                "reading": _reading(reading[t.id]) if t.id in reading else None,
                "notes": topic_notes.get(t.id, 0),  # type: ignore[arg-type]
            })
        return {
            "course": {**_course(course), "progress": _progress(progress),
                       "exam_words": _exam_words(course, progress)},
            "topics": topic_rows,
            "topics_done": sum(1 for t in topics if t.status.is_done),
            "weak_spots": [_weak(w, now, codes, titles)
                           for w in self._store.list_weak_spots(course_id, include_resolved=True)],
            "deadlines": [_deadline(d, now, codes) for d in self._store.list_deadlines(course_id, include_done=True)],
            "sessions": [_session(s, codes, titles) for s in self._store.list_sessions(course_id, limit=50)],
            "week_total": format_minutes(week),
            "total": format_minutes(self._store.total_minutes(course_id)),
            "reading": _reading(self._store.reading_progress(course_id)),
            "exams": len(self._store.list_exams(course_id)),
            "notes": len(notes),
            "running": self._running(now),
        }

    # ---------- a subject's notes: saved while you type, like a project's ----------

    @action
    def notes(self, course_id: int) -> dict:
        course = self._store.get_course(course_id)
        if course is None:
            raise UserError("That subject no longer exists.")
        topics = self._store.list_topics(course_id)
        titles = {t.id: t.title for t in topics}
        return {"course": _course(course), "topics": [{"id": t.id, "title": t.title} for t in topics],
                "notes": [self._course_note_json(n, titles) for n in self._store.list_course_notes(course_id)]}

    @staticmethod
    def _course_note_json(n: CourseNote, titles: dict[int, str]) -> dict:
        updated = n.updated_at or n.created_at
        return {"id": n.id, "title": n.title, "body": n.body, "topic_id": n.topic_id,
                "topic": titles.get(n.topic_id, "") if n.topic_id else "",  # type: ignore[arg-type]
                "created_label": _when(n.created_at), "updated_label": _when(updated), "updated": _iso(updated)}

    def _note_topic(self, course_id: int, topic_id: Any) -> int | None:
        """A topic a note may point to: one of its own subject's, or none."""
        if topic_id in (None, "", 0, "0"):
            return None
        topic = self._store.get_topic(int(topic_id))
        if topic is None or topic.course_id != course_id:
            raise UserError("That topic isn't part of this subject any more.")
        return topic.id

    @action
    def add_course_note(self, course_id: int, topic_id: int | None = None) -> dict:
        if self._store.get_course(course_id) is None:
            raise UserError("That subject no longer exists.")
        note = self._store.add_course_note(CourseNote(course_id=course_id, topic_id=self._note_topic(course_id, topic_id)))
        return self._course_note_json(note, self._topic_titles())

    @action
    def save_course_note(self, data: dict) -> dict:
        """Saves the title and text; the topic too, when `topic_id` is given (the text saves leave it be)."""
        note_id = _int(data, "id")
        old = self._store.get_course_note(note_id) if note_id else None
        if old is None:
            raise UserError("That note was deleted (maybe on another computer). Copy your text before leaving.")
        topic_id = self._note_topic(old.course_id, data["topic_id"]) if "topic_id" in data else old.topic_id
        note = self._store.update_course_note(replace(old, title=_text(data, "title") if "title" in data else old.title,
                                                       body=str(data["body"] or "") if "body" in data else old.body,
                                                       topic_id=topic_id))
        return self._course_note_json(note, self._topic_titles())

    @action
    def delete_course_note(self, note_id: int) -> None:
        self._store.delete_course_note(note_id)

    @action
    def courses(self) -> list[dict]:
        """Every subject with its topics, for the pickers in forms."""
        return [{**_course(c), "topics": [{"id": t.id, "title": t.title} for t in self._store.list_topics(c.id)]}
                for c in self._store.list_courses()]

    def _check_pomodoro(self, now: datetime) -> None:
        """Log finished focus blocks and, when a phase has ended since the last look, pling and send its
        notification. Runs every second on its own thread (see `watch`), so this happens on time even
        while the window is in the background; the window's tick also calls it. Call with the lock held."""
        settings = self._pomodoro_settings()
        run, logged = self._store.settle_pomodoro(now, settings)
        phase = self._phase_key(run, now)
        # Only the two things that happen by themselves: focus time running out, and a break ending.
        if run and self._last_pomo_phase and phase != self._last_pomo_phase and (phase[2] or run.phase.value == "ready"):
            if run.phase.value == "ready":
                title, body, kind = "Break's over", "Press Start focus when you're ready.", sound.BREAK_OVER
            else:
                title, body, kind = ("Time for a break", f"Focus block {run.completed + 1} done. Keep going, or take "
                                     "a break when you're ready.", sound.FOCUS_DONE)
            self._pending.append(f"{title}. {body}")
            if self._setting("sound"):
                self._play(kind)
            if self._setting("notifications"):
                self._notify(title, body)
        self._last_pomo_phase = phase
        if logged:
            self._pending.append(f"Logged {sum(s.minutes for s in logged)} minutes of focus.")
            self._pending_changed = True
        self._awake.set(run is not None)

    def _phase_key(self, run: PomodoroRun | None, now: datetime) -> tuple[str, int, bool] | None:
        """What the Pomodoro is doing, to notice when it changes: (phase, blocks done, focus time up)."""
        if run is None:
            return None
        return run.phase.value, run.completed, focus_done(run, now, self._pomodoro_settings())

    def watch(self) -> None:
        """Start checking the Pomodoro every second in the background, for as long as the app runs."""
        def loop() -> None:
            while True:
                time.sleep(1)
                with self._lock:
                    try:
                        self._check_pomodoro(datetime.now().replace(microsecond=0))
                    except Exception:  # a closed or switching database: try again in a second
                        pass

        threading.Thread(target=loop, name="pomodoro-watch", daemon=True).start()

    @action
    def tick(self) -> dict:
        """Called every few seconds while the window is open: catches up on the Pomodoro and sends the
        deadline alerts that are due. Returns messages to show in the window, including ones from the
        background check since the last tick."""
        now = datetime.now().replace(microsecond=0)
        self._check_pomodoro(now)
        if self._setting("notifications"):
            alerts.send_due(self._store, self._config(), now, send=self._notify)
        messages, changed = self._pending, self._pending_changed
        self._pending, self._pending_changed = [], False
        return {"messages": messages, "changed": changed or bool(messages)}

    @action
    def preview_sound(self) -> None:
        """Play the pling, so Settings can show what it sounds like."""
        self._play(sound.FOCUS_DONE)

    # ---------- subjects ----------

    @action
    def save_course(self, data: dict) -> dict:
        course_id = _int(data, "id")
        old = self._store.get_course(course_id) if course_id else None
        course = Course(
            name=_text(data, "name"), code=_text(data, "code"),
            cram_start=_date(data, "cram_start", "when you start studying"),
            exam_date=_date(data, "exam_date", "the exam"),
            color=_text(data, "color") or self._store.next_color(), notes=_text(data, "notes"),
            done=old.done if old else False, id=course_id,
        )
        if old is not None:
            self._store.update_course(course)
        else:
            self._store.add_course(course)
        return {"ok": True, "id": course.id}

    @action
    def delete_course(self, course_id: int) -> None:
        self._store.delete_course(course_id)

    @action
    def set_course_done(self, course_id: int, done: bool) -> None:
        self._store.set_course_done(course_id, bool(done))

    # ---------- course banners ----------

    @action
    def choose_banner_image(self) -> dict:
        """The system's open dialog for a banner picture. In a plain browser the page uses its own picker."""
        import webview

        if self._window is None:
            return {"ok": True, "browser": True, "path": ""}
        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                                 file_types=("Pictures (*.jpg;*.jpeg;*.png;*.webp;*.heic;*.heif)",))
        return {"ok": True, "path": str(chosen[0]) if chosen else ""}

    @action
    def set_course_banner(self, course_id: int, data: dict) -> dict:
        """data: {path} (from the dialog) or {name, data as base64} for your own picture, {generated: n} for
        the pattern made from the course (n picks another one), or {} to go back to the first pattern."""
        if self._store.get_course(course_id) is None:
            raise UserError("That subject no longer exists.")
        data = data or {}
        if data.get("path") or data.get("data"):
            if data.get("path"):
                path = Path(str(data["path"]))
                if not path.is_file():
                    raise UserError(f"Can't find “{path.name}” any more.")
                name, raw = path.name, path.read_bytes()
            else:
                name, raw = _text(data, "name") or "banner.jpg", base64.b64decode(str(data.get("data") or ""))
            mime = files.check(name, len(raw))
            if not mime.startswith("image/"):
                raise UserError("Pick a picture (JPG, PNG, WebP or HEIC) for the banner.")
            from .core.pages import image_page

            key, _ = files.store(self._files_dir(), "banner.jpg", image_page(name, mime, raw))
            self._store.set_course_banner(course_id, key)
            return {"ok": True}
        n = _int(data, "generated") or 0
        self._store.set_course_banner(course_id, f"gen:{n}" if n else "")
        return {"ok": True}

    @action
    def banner_image(self, key: str) -> dict:
        """A banner picture as a data URL, or "" if it hasn't arrived on this computer yet."""
        try:
            path = files.path(self._files_dir(), str(key))
        except FileError:
            return {"ok": True, "url": ""}
        if not path.exists():
            return {"ok": True, "url": ""}
        mime = files.TYPES.get(path.suffix.lower(), "image/jpeg")
        return {"ok": True, "url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"}

    # ---------- topics ----------

    @action
    def save_topic(self, data: dict) -> dict:
        topic_id = _int(data, "id")
        old = self._store.get_topic(topic_id) if topic_id else None
        try:
            status = TopicStatus(_text(data, "status") or "not_started")
        except ValueError:
            raise UserError("Pick a status for the topic.") from None
        topic = Topic(course_id=old.course_id if old else _int(data, "course_id"),  # type: ignore[arg-type]
                      title=_text(data, "title"), status=status, confidence=_int(data, "confidence") or 1,
                      last_studied=old.last_studied if old else None, id=topic_id)
        if old is not None:
            self._store.update_topic(topic)
        else:
            if topic.course_id is None:
                raise UserError("Pick which subject the topic belongs to.")
            self._store.add_topic(topic)
        return {"ok": True, "id": topic.id}

    @action
    def add_topics(self, course_id: int, text: str) -> dict:
        """Several topics at once, one per line."""
        titles = [line.strip(" \t-•*") for line in str(text).splitlines()]
        titles = [t for t in titles if t]
        if not titles:
            raise UserError("Type at least one topic.")
        for title in titles:
            self._store.add_topic(Topic(course_id=course_id, title=title))
        return {"ok": True, "added": len(titles)}

    @action
    def set_topic_status(self, topic_id: int, status: str) -> None:
        topic = self._store.get_topic(topic_id)
        if topic is None:
            raise UserError("That topic no longer exists.")
        self._store.update_topic(replace(topic, status=TopicStatus(status)))

    @action
    def set_confidence(self, topic_id: int, confidence: int) -> None:
        topic = self._store.get_topic(topic_id)
        if topic is None:
            raise UserError("That topic no longer exists.")
        self._store.update_topic(replace(topic, confidence=max(1, min(5, int(confidence)))))

    @action
    def delete_topic(self, topic_id: int) -> None:
        self._store.delete_topic(topic_id)

    # ---------- weak spots ----------

    @action
    def save_weak(self, data: dict) -> None:
        weak_id = _int(data, "id")
        old = self._store.get_weak_spot(weak_id) if weak_id else None
        course_id = _int(data, "course_id") or (old.course_id if old else None)
        if course_id is None:
            raise UserError("Pick which subject the weak spot is in.")
        try:
            priority = Priority(_text(data, "priority") or "med")
        except ValueError:
            raise UserError("Pick how important it is.") from None
        weak = WeakSpot(course_id=course_id, description=_text(data, "description"), priority=priority,
                        topic_id=_int(data, "topic_id"))
        if old is not None:
            self._store.update_weak_spot(replace(old, course_id=course_id, description=weak.description,
                                                 priority=priority, topic_id=weak.topic_id))
        else:
            self._store.add_weak_spot(weak)

    @action
    def toggle_weak(self, weak_id: int) -> None:
        self._store.toggle_weak_spot(weak_id)

    @action
    def delete_weak(self, weak_id: int) -> None:
        self._store.delete_weak_spot(weak_id)

    # ---------- deadlines ----------

    @action
    def save_deadline(self, data: dict) -> None:
        deadline_id = _int(data, "id")
        old = self._store.get_deadline(deadline_id) if deadline_id else None
        try:
            kind = DeadlineKind(_text(data, "kind") or "assignment")
        except ValueError:
            raise UserError("Pick what kind of deadline it is.") from None
        due = _datetime(data, "due_at", "when it's due")
        if old is not None:
            course_id = old.course_id if old.is_course_exam else _int(data, "course_id")
            self._store.update_deadline(replace(old, title=_text(data, "title"), due_at=due,
                                                kind=DeadlineKind.EXAM if old.is_course_exam else kind,
                                                course_id=course_id))
        else:
            self._store.add_deadline(Deadline(title=_text(data, "title"), due_at=due, kind=kind,
                                              course_id=_int(data, "course_id")))

    @action
    def toggle_deadline(self, deadline_id: int) -> None:
        self._store.toggle_deadline(deadline_id)

    @action
    def delete_deadline(self, deadline_id: int) -> None:
        self._store.delete_deadline(deadline_id)

    # ---------- study time ----------

    @action
    def save_session(self, data: dict) -> None:
        session_id = _int(data, "id")
        minutes = (_int(data, "hours") or 0) * 60 + (_int(data, "minutes") or 0)
        if minutes <= 0:
            raise UserError("How long did you study? Enter some hours or minutes.")
        started = _datetime(data, "started_at", "when you studied")
        project_id = _int(data, "project_id")
        if project_id is not None:  # time on a research project
            if session_id:
                old = self._store.get_project_session(session_id)
                if old is None:
                    raise UserError("That study session no longer exists.")
                self._store.update_session(replace(old, started_at=started, minutes=minutes, note=_text(data, "note")))
            else:
                self._store.log_session(Session(course_id=None, project_id=project_id, started_at=started,
                                                minutes=minutes, note=_text(data, "note")))
            return
        if session_id:
            old = self._store.get_session(session_id)
            if old is None:
                raise UserError("That study session no longer exists.")
            self._store.update_session(replace(old, topic_id=_int(data, "topic_id"), started_at=started,
                                               minutes=minutes, note=_text(data, "note")))
        else:
            course_id = _int(data, "course_id")
            if course_id is None:
                raise UserError("Pick which subject you studied.")
            self._store.log_session(Session(course_id=course_id, started_at=started, minutes=minutes,
                                            topic_id=_int(data, "topic_id"), note=_text(data, "note")))

    @action
    def delete_session(self, session_id: int) -> None:
        self._store.delete_session(session_id)

    @action
    def timer_start(self, course_id: int | None, topic_id: int | None = None, project_id: int | None = None) -> None:
        self._store.start_timer(course_id, topic_id, project_id=project_id)

    @action
    def timer_stop(self) -> dict:
        session = self._store.stop_timer()
        if session is None:
            return {"ok": True, "message": "Stopped. It was under a minute, so nothing was logged."}
        return {"ok": True, "message": f"Logged {format_minutes(session.minutes)}."}

    @action
    def timer_cancel(self) -> None:
        self._store.cancel_timer()

    @action
    def pomo_start(self, course_id: int | None, topic_id: int | None = None, project_id: int | None = None) -> None:
        self._store.start_pomodoro(course_id, topic_id, project_id=project_id)
        self._last_pomo_phase = ("focus", 0, False)

    @action
    def pomo_pause(self) -> None:
        run = self._store.get_pomodoro()
        if run is not None and run.paused:
            self._store.resume_pomodoro(settings=self._pomodoro_settings())
        else:
            self._store.pause_pomodoro(settings=self._pomodoro_settings())

    @action
    def pomo_next(self) -> None:
        run, _ = self._store.pomodoro_next(settings=self._pomodoro_settings())
        self._last_pomo_phase = self._phase_key(run, datetime.now())

    @action
    def pomo_break(self) -> dict:
        """You're done with this focus block: log it (extra minutes included) and start the break."""
        run, sessions = self._store.pomodoro_break(settings=self._pomodoro_settings())
        self._last_pomo_phase = self._phase_key(run, datetime.now())
        minutes = sum(s.minutes for s in sessions)
        length = {"short_break": self._setting("short_break_minutes"), "long_break": self._setting("long_break_minutes")}
        rest = f"{length.get(run.phase.value, 0)}-minute break" if run.phase.is_break else "break"
        return {"ok": True, "message": f"Saved {format_minutes(minutes)} of focus. Enjoy your {rest}." if minutes
                else f"Enjoy your {rest}."}

    @action
    def pomo_stop(self) -> dict:
        run = self._store.get_pomodoro()
        sessions = self._store.stop_pomodoro(settings=self._pomodoro_settings())
        self._last_pomo_phase = None
        minutes = sum(s.minutes for s in sessions)
        if minutes:
            return {"ok": True, "message": f"Pomodoro stopped. Saved the last {format_minutes(minutes)} of focus."}
        if run is not None and run.completed:
            return {"ok": True, "message": "Pomodoro stopped. Your focus time is saved."}
        return {"ok": True, "message": "Pomodoro stopped. It was under a minute, so nothing was logged."}

    # ---------- reading lists ----------

    @action
    def reading(self, course_id: int) -> dict:
        course = self._store.get_course(course_id)
        if course is None:
            raise UserError("That subject no longer exists.")
        topics = {t.id: t.title for t in self._store.list_topics(course_id)}

        def section(s: Section, chapter_topic: int | None) -> dict:
            # "group" is the topic it counts toward: its own, else its chapter's, else its book's.
            return {"id": s.id, "number": s.number, "title": s.title, "required": s.required, "read": s.read,
                    "topic_id": s.topic_id, "topic": topics.get(s.topic_id) if s.topic_id else None,
                    "own_topic": s.topic_id is not None and s.topic_id != chapter_topic,
                    "group": s.topic_id if s.topic_id is not None else chapter_topic}

        sources = []
        from .core.logic.reading import progress, reading_units
        for src, chapters in self._store.reading_list(course_id):
            all_sections = [s for ch, ss in chapters for s in reading_units(ch, ss)]
            ref = apa(src)
            sources.append({
                "id": src.id, "title": src.title, "author": src.author, "topic_id": src.topic_id,
                "topic": topics.get(src.topic_id) if src.topic_id else None,
                **{f: getattr(src, f) for f in CITE_FIELDS},
                "reference": {"text": ref.text, "html": ref.html},
                "progress": _reading(progress(all_sections)),
                "chapters": [{"id": ch.id, "number": ch.number, "title": ch.title, "topic_id": ch.topic_id,
                              "topic": topics.get(ch.topic_id) if ch.topic_id else None,
                              "group": ch.topic_id if ch.topic_id is not None else src.topic_id,
                              "progress": _reading(progress(reading_units(ch, ss))), "read": ch.read,
                              "sections": [section(s, ch.topic_id if ch.topic_id is not None else src.topic_id)
                                           for s in ss]} for ch, ss in chapters],
            })
        return {"course": _course(course), "sources": sources,
                "topics": [{"id": i, "title": t} for i, t in topics.items()],
                "progress": _reading(self._store.reading_progress(course_id))}

    @staticmethod
    def _source_fields(data: dict) -> dict:
        kind = _text(data, "kind") or "book"
        if kind not in KINDS:
            raise UserError("Pick what kind of source it is.")
        return {"title": _text(data, "title"), "author": _text(data, "author"), "topic_id": _int(data, "topic_id"),
                **{f: _text(data, f) for f in CITE_FIELDS if f != "kind"}, "kind": kind}

    @action
    def apa_preview(self, data: dict) -> dict:
        """The reference as the form stands, to show while typing."""
        ref = apa(Source(course_id=0, **self._source_fields(data)))
        return {"text": ref.text, "html": ref.html}

    @action
    def save_source(self, data: dict) -> dict:
        source_id = _int(data, "id")
        fields = self._source_fields(data)
        if source_id:
            old = self._store.get_source(source_id)
            if old is None:
                raise UserError("That book no longer exists.")
            self._store.update_source(replace(old, **fields))
            return {"ok": True, "id": source_id}
        source = self._store.add_source(Source(course_id=_int(data, "course_id"), **fields))  # type: ignore[arg-type]
        contents = str(data.get("contents") or "").strip()
        if contents:
            self._store.import_toc(source.id, parse_toc(contents))  # type: ignore[arg-type]
        return {"ok": True, "id": source.id}

    @action
    def delete_source(self, source_id: int) -> None:
        self._store.delete_source(source_id)

    @action
    def add_chapter(self, data: dict) -> dict:
        source_id = _int(data, "source_id")
        number = _text(data, "number").rstrip(".")
        if not number:
            raise UserError("Give the chapter a number, like 6.")
        sections = parse_section_ranges(_text(data, "sections"), number) if _text(data, "sections") else []
        _, added = self._store.add_chapter(source_id, number, _text(data, "title"), sections,  # type: ignore[arg-type]
                                           _int(data, "topic_id"), required=not data.get("optional"))
        return {"ok": True, "added": added}

    @action
    def import_contents(self, source_id: int, text: str) -> dict:
        chapters, sections = self._store.import_toc(source_id, parse_toc(str(text)))
        return {"ok": True, "message": f"Added {chapters} chapter{'s' if chapters != 1 else ''} and "
                                       f"{sections} section{'s' if sections != 1 else ''}."}

    @action
    def save_chapter(self, data: dict) -> None:
        chapter = self._store.get_chapter(_int(data, "id"))  # type: ignore[arg-type]
        if chapter is None:
            raise UserError("That chapter no longer exists.")
        self._store.update_chapter(replace(chapter, number=_text(data, "number"), title=_text(data, "title"),
                                           topic_id=_int(data, "topic_id")))

    @action
    def delete_chapter(self, chapter_id: int) -> None:
        self._store.delete_chapter(chapter_id)

    @action
    def toggle_section(self, section_id: int) -> None:
        self._store.toggle_section_read(section_id)

    @action
    def set_chapter_read(self, chapter_id: int, read: bool) -> None:
        self._store.set_chapter_read(chapter_id, bool(read))

    @action
    def set_section_required(self, section_id: int, required: bool) -> None:
        self._store.set_required([section_id], bool(required))

    @action
    def delete_section(self, section_id: int) -> None:
        self._store.delete_section(section_id)

    # ---------- exams ----------

    def _files_dir(self, store: Store | None = None) -> Path:
        return files.folder_for((store or self._store).path)

    def _exam_json(self, exam: Exam, topics: dict[int, str]) -> dict:
        folder = self._files_dir()
        questions = self._store.list_questions(exam.id)  # type: ignore[arg-type]
        counts = {r: sum(1 for q in questions if q.result == r) for r in RESULTS}
        exam_files = self._store.list_exam_files(exam.id)  # type: ignore[arg-type]
        return {
            "id": exam.id, "title": exam.title, "kind": exam.kind, "taken_on": exam.taken_on, "score": exam.score,
            "notes": exam.notes, "created_label": _day(exam.created_at.date()),
            "files": [{"id": f.id, "name": f.name, "role": f.role, "size": _size(f.size),
                       "available": (folder / f.key).exists()} for f in exam_files],
            "has_solution": any(f.role == "solution" for f in exam_files),
            "questions": [{"id": q.id, "number": q.number, "prompt": q.prompt, "answer": q.answer, "marks": q.marks,
                           "topic_id": q.topic_id if q.topic_id in topics else None,
                           "topic": topics.get(q.topic_id) if q.topic_id else None,
                           "result": q.result, "note": q.note, "why": q.why, "parent_number": q.parent_number,
                           "question_type": q.question_type, "type_label": TYPE_LABELS.get(q.question_type, ""),
                           "tags": [t for t in q.topic_tags if t != topics.get(q.topic_id)],
                           "has_figure": q.has_figure} for q in questions],
            "counts": {**counts, "unmarked": len(questions) - sum(counts.values()), "total": len(questions)},
            "attempts": self._attempts_brief(exam.id),  # type: ignore[arg-type]
        }

    def _attempts_brief(self, exam_id: int) -> dict:
        """For the exam's card: how many times it's been taken, the latest and best score, and one being taken."""
        attempts = self._store.list_attempts(exam_id)
        done = [a for a in attempts if a.finished_at]
        scores = [p for p in (attempt_logic.score(a)["percent"] for a in done) if p is not None]
        latest = next((attempt_logic.score(a)["percent"] for a in done), None)
        open_ = next((a.id for a in attempts if not a.finished_at), None)
        return {"count": len(done), "latest": latest, "best": max(scores) if scores else None, "open": open_}

    def _attempt_json(self, a: ExamAttempt, now: datetime, full: bool = False) -> dict:
        left = attempt_logic.seconds_left(a, now)
        used = a.seconds if a.finished_at else attempt_logic.elapsed(a, now)
        out = {"id": a.id, "exam_id": a.exam_id, "started_label": _when(a.started_at), "minutes": a.minutes,
               "finished": a.finished_at is not None, "seconds_left": None if a.finished_at else left,
               "elapsed": used, "time_label": attempt_logic.format_seconds(used), "graded": a.graded,
               "score": attempt_logic.score(a), "answered": sum(1 for i in a.items if (i.get("answer") or "").strip()),
               "questions": len(a.items)}
        if full:
            worth = attempt_logic.max_points(a.items)
            out["summary"] = a.summary
            out["items"] = [{**i, "worth": worth[n], "index": n} for n, i in enumerate(a.items)]
            if any(not i.get("question_type") for i in a.items):
                # Attempts started before items carried the question type: take it from the exam's questions.
                types = {q.number: q.question_type for q in self._store.list_questions(a.exam_id)}
                for i in out["items"]:
                    i["question_type"] = i.get("question_type") or types.get(i.get("number"), "") or ""
        return out

    def _marked_questions(self, course_id: int, store: Store | None = None) -> list[tuple[str, ExamQuestion]]:
        store = store or self._store
        return [(e.title, q) for e in store.list_exams(course_id) for q in store.list_questions(e.id)]  # type: ignore[arg-type]

    @action
    def exams(self, course_id: int) -> dict:
        course = self._store.get_course(course_id)
        if course is None:
            raise UserError("That subject no longer exists.")
        topic_list = self._store.list_topics(course_id)
        topics = {t.id: t.title for t in topic_list}
        exams = self._store.list_exams(course_id)
        tallies = exam_logic.tally(self._marked_questions(course_id), topics)  # type: ignore[arg-type]
        return {
            "course": _course(course),
            "topics": [{"id": i, "title": t} for i, t in topics.items()],
            "past": [self._exam_json(e, topics) for e in exams if e.kind == "past"],  # type: ignore[arg-type]
            "practice": [self._exam_json(e, topics) for e in exams if e.kind == "practice"],  # type: ignore[arg-type]
            "tally": [{"topic_id": t.topic_id, "title": t.title, "missed": t.missed, "partial": t.partial, "ok": t.ok}
                      for t in tallies],
            "weak_open": len(self._store.list_weak_spots(course_id)),
            "shaky_topics": [t.title for t in topic_list if t.confidence <= 2],
            "ai": self._ai_ready(),
        }

    @action
    def choose_exam_files(self) -> dict:
        """The system's open dialog. In a plain browser (the dev server) the page uses its own file picker."""
        import webview

        if self._window is None:
            return {"ok": True, "browser": True, "files": []}
        kinds = ";".join(f"*{ext}" for ext in files.TYPES)
        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                 file_types=(f"Exams and photos ({kinds})",))
        out = []
        for p in chosen or []:
            path = Path(p)
            files.check(path.name, path.stat().st_size)
            out.append({"path": str(path), "name": path.name, "size": _size(path.stat().st_size)})
        return {"ok": True, "files": out}

    def _add_files(self, exam_id: int, added: list[dict]) -> None:
        for item in added:
            role = _text(item, "role") or "exam"
            if role not in FILE_ROLES:
                raise UserError("Say what each file is: the exam, its solutions or your answers.")
            if item.get("path"):
                path = Path(str(item["path"]))
                if not path.is_file():
                    raise UserError(f"Can't find “{path.name}” any more.")
                name, data = path.name, path.read_bytes()
            else:
                name, data = _text(item, "name"), base64.b64decode(str(item.get("data") or ""))
            key, mime = files.store(self._files_dir(), name, data)
            self._store.add_exam_file(ExamFile(exam_id=exam_id, name=name, key=key, mime=mime, size=len(data), role=role))

    @action
    def save_exam(self, data: dict) -> dict:
        """A past exam's details, with files to add ({role, path} from the dialog, or {role, name, data} as
        base64 from the browser) and file ids to remove."""
        exam_id = _int(data, "id")
        fields = {"title": _text(data, "title"), "taken_on": _text(data, "taken_on"), "score": _text(data, "score"),
                  "notes": _text(data, "notes")}
        for item in data.get("add") or []:  # check them all before saving anything
            if not item.get("path"):
                files.check(_text(item, "name"), len(str(item.get("data") or "")) * 3 // 4)
        if exam_id:
            old = self._store.get_exam(exam_id)
            if old is None:
                raise UserError("That exam no longer exists.")
            self._store.update_exam(replace(old, **fields))
        else:
            exam_id = self._store.add_exam(Exam(course_id=_int(data, "course_id"), kind="past", **fields)).id  # type: ignore[arg-type]
        for file_id in data.get("remove") or []:
            self._store.delete_exam_file(int(file_id))
        self._add_files(exam_id, data.get("add") or [])  # type: ignore[arg-type]
        files.tidy(self._files_dir(), self._store.file_keys())
        return {"ok": True, "id": exam_id}

    @action
    def delete_exam(self, exam_id: int) -> None:
        self._store.delete_exam(exam_id)
        files.tidy(self._files_dir(), self._store.file_keys())

    @action
    def open_exam_file(self, file_id: int) -> None:
        """Opens the file in the computer's own viewer (Preview, Photos, ...)."""
        import subprocess
        import sys

        f = self._store.get_exam_file(file_id)
        if f is None:
            raise UserError("That file is gone.")
        path = files.path(self._files_dir(), f.key)
        if not path.exists():
            raise UserError(f"“{f.name}” hasn't arrived on this computer yet. It downloads when StudyPal syncs.")
        # Opened under its own name, so the viewer's title says what it is.
        view = Path(tempfile.gettempdir()) / "StudyPal" / f"{f.id}" / re.sub(r"[/\\:]", "_", f.name)
        view.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, view)
        if sys.platform == "darwin":
            subprocess.run(["open", str(view)], check=False)
        elif sys.platform == "win32":
            os.startfile(str(view))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(view)], check=False)

    def _question_fields(self, data: dict) -> dict:
        result = _text(data, "result")
        if result and result not in RESULTS:
            raise UserError("That isn't a way a question can go.")
        return {"number": _text(data, "number"), "prompt": _text(data, "prompt"), "answer": _text(data, "answer"),
                "marks": _text(data, "marks"), "topic_id": _int(data, "topic_id"), "result": result,
                "note": _text(data, "note")}

    @action
    def save_question(self, data: dict) -> dict:
        question_id = _int(data, "id")
        fields = self._question_fields(data)
        if not fields["number"] and not fields["prompt"]:
            raise UserError("Give the question a number, like 2b.")
        if question_id:
            old = self._store.get_question(question_id)
            if old is None:
                raise UserError("That question no longer exists.")
            self._store.update_question(replace(old, **fields))
            return {"ok": True, "id": question_id}
        q = self._store.add_question(ExamQuestion(exam_id=_int(data, "exam_id"), **fields))  # type: ignore[arg-type]
        return {"ok": True, "id": q.id}

    @action
    def set_question_result(self, question_id: int, result: str) -> None:
        q = self._store.get_question(question_id)
        if q is None:
            raise UserError("That question no longer exists.")
        result = str(result or "")
        if result and result not in RESULTS:
            raise UserError("That isn't a way a question can go.")
        self._store.update_question(replace(q, result=result))

    @action
    def delete_question(self, question_id: int) -> None:
        self._store.delete_question(question_id)

    @action
    def question_to_weak(self, question_id: int) -> dict:
        """Note a question that went badly as a weak spot, so it shows on the subject page."""
        q = self._store.get_question(question_id)
        exam = self._store.get_exam(q.exam_id) if q else None
        if q is None or exam is None:
            raise UserError("That question no longer exists.")
        what = q.note or " ".join(q.prompt.split())[:160]
        self._store.add_weak_spot(WeakSpot(course_id=exam.course_id, topic_id=q.topic_id,
                                           priority=Priority.HIGH if q.result == "missed" else Priority.MED,
                                           description=f"{exam.title}, question {q.number}: {what}"))
        return {"ok": True, "message": "Added to weak spots."}

    # The model: the provider and its API key belong to the computer (prefs.json), like the theme, and
    # aren't synced. GEMINI_API_KEY / GROQ_API_KEY in the environment win over Settings.

    def _provider_name(self) -> str:
        return llm_chosen(self._prefs())

    def _key(self, which: str) -> str:
        """A provider's key: the environment variable first (GEMINI_API_KEY, GROQ_API_KEY), then Settings."""
        env = PROVIDERS[which].key_env
        return ((os.environ.get(env, "") if env else "") or str(self._prefs().get(f"{which}_key") or "")).strip()

    def _ai_ready(self) -> bool:
        which = self._provider_name()
        return which == "ollama" or bool(self._key(which))

    def _llm(self):
        try:
            return provider_from(self._prefs())
        except LLMError as e:
            raise UserError(str(e)) from None

    # ---------- taking an exam ----------

    @action
    def exam(self, exam_id: int) -> dict:
        """One exam's own page: its questions and files, and the times it's been taken."""
        exam = self._store.get_exam(exam_id)
        course = self._store.get_course(exam.course_id) if exam else None
        if exam is None or course is None:
            raise UserError("That exam no longer exists.")
        topic_list = self._store.list_topics(course.id)  # type: ignore[arg-type]
        topics = {t.id: t.title for t in topic_list}
        now = datetime.now()
        n = len(self._store.list_questions(exam_id))
        return {
            "course": _course(course),
            "topics": [{"id": i, "title": t} for i, t in topics.items()],
            "exam": self._exam_json(exam, topics),  # type: ignore[arg-type]
            "attempt_list": [self._attempt_json(a, now) for a in self._store.list_attempts(exam_id)],
            "suggested_minutes": attempt_logic.suggested_minutes(n),
            "ai": self._ai_ready(),
        }

    @action
    def start_attempt(self, data: dict) -> dict:
        """Start taking an exam (data: exam_id, minutes; 0 for no limit). If it's already being taken, that
        attempt carries on instead."""
        exam_id = _int(data, "exam_id")
        exam = self._store.get_exam(exam_id) if exam_id else None  # type: ignore[arg-type]
        if exam is None:
            raise UserError("That exam no longer exists.")
        going = next((a for a in self._store.list_attempts(exam_id) if not a.finished_at), None)  # type: ignore[arg-type]
        if going:
            return {"ok": True, "id": going.id}
        items = attempt_logic.items_from(self._store.list_questions(exam_id))  # type: ignore[arg-type]
        if not items:
            raise UserError("This exam has no questions yet. Read them from the exam paper or add them first.")
        minutes = _int(data, "minutes") or 0
        if not 0 <= minutes <= 600:
            raise UserError("The time limit should be between 1 minute and 10 hours.")
        a = self._store.add_attempt(ExamAttempt(exam_id=exam_id, started_at=datetime.now().replace(microsecond=0),  # type: ignore[arg-type]
                                                minutes=minutes, items=items))
        return {"ok": True, "id": a.id}

    def _get_attempt(self, attempt_id: int) -> tuple[ExamAttempt, Exam, Course]:
        a = self._store.get_attempt(attempt_id)
        exam = self._store.get_exam(a.exam_id) if a else None
        course = self._store.get_course(exam.course_id) if exam else None
        if a is None or exam is None or course is None:
            raise UserError("That attempt no longer exists.")
        return a, exam, course

    @action
    def attempt(self, attempt_id: int) -> dict:
        a, exam, course = self._get_attempt(attempt_id)
        folder = self._files_dir()
        return {
            "course": _course(course),
            "exam": {"id": exam.id, "title": exam.title, "kind": exam.kind,
                     "files": [{"id": f.id, "name": f.name, "role": f.role, "available": (folder / f.key).exists()}
                               for f in self._store.list_exam_files(exam.id) if f.role == "exam"]},  # type: ignore[arg-type]
            "attempt": self._attempt_json(a, datetime.now(), full=True),
            "ai": self._ai_ready(),
        }

    @staticmethod
    def _put_answers(a: ExamAttempt, answers: dict) -> None:
        for key, text in (answers or {}).items():
            try:
                i = int(key)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(a.items):
                a.items[i]["answer"] = str(text or "")[:20000]

    @action
    def save_answers(self, attempt_id: int, answers: dict) -> None:
        """Keep what's been written so far ({question index: text}), while the exam is being taken."""
        a, _, _ = self._get_attempt(attempt_id)
        if a.finished_at:
            return
        self._put_answers(a, answers)
        self._store.update_attempt(a)

    @action
    def hand_in(self, attempt_id: int, answers: dict) -> dict:
        """Finish taking the exam. The time taken stops at the limit, even if the window was closed past it."""
        a, _, _ = self._get_attempt(attempt_id)
        if a.finished_at:
            return {"ok": True, "grade": False}
        self._put_answers(a, answers)
        now = datetime.now().replace(microsecond=0)
        used = attempt_logic.elapsed(a, now)
        a.seconds = min(used, a.minutes * 60) if a.minutes else used
        a.finished_at = now
        self._store.update_attempt(a)
        return {"ok": True, "grade": self._ai_ready()}

    def _apply_attempt(self, store: Store, a: ExamAttempt) -> None:
        """How each answer went becomes how the exam's question went (the latest attempt counts), so practice
        exams aim at it. The grader's feedback becomes the question's note if it has none of its own."""
        by_number = {question_logic.number_key(q.number): q for q in store.list_questions(a.exam_id)}
        for item in a.items:
            q = by_number.get(question_logic.number_key(item.get("number", "")))
            verdict = item.get("verdict") or ""
            if q is None or not verdict:
                continue
            note = q.note
            if not note and verdict != "ok" and item.get("feedback"):
                note = str(item["feedback"])[:500]
            if q.result != verdict or note != q.note:
                store.update_question(replace(q, result=verdict, note=note))

    def grade_attempt(self, attempt_id: int) -> dict:
        """Have the model grade a handed-in attempt (core/grade.py). Runs in the background like reading an exam."""
        job = f"grade:{attempt_id}"

        def work() -> dict:
            with self._lock:
                store = self._store
                a, exam, course = self._get_attempt(attempt_id)
                if not a.finished_at:
                    raise UserError("Hand the exam in first.")
            provider = self._llm()

            def progress(text: str) -> None:
                self._jobs[job] = text

            grade_answers(provider, f"{course.code} {course.name}", exam.title, a, progress)
            with self._lock:
                if self._store is not store or store.get_attempt(attempt_id) is None:
                    raise UserError("The attempt changed while it was being graded. Try again.")
                store.update_attempt(a)
                self._apply_attempt(store, a)
            sc = attempt_logic.score(a)
            percent = f" ({sc['percent']}%)" if sc["percent"] is not None else ""
            return {"ok": True, "message": f"{exam.title}: graded, {sc['got']:g} of {sc['max']:g} points{percent}."}
        return self._ai_call(job, work)

    @action
    def set_attempt_verdict(self, attempt_id: int, index: int, verdict: str) -> None:
        """Mark one answer by hand (or change the model's mark)."""
        a, _, _ = self._get_attempt(attempt_id)
        try:
            attempt_logic.set_verdict(a, int(index), str(verdict or ""))
        except ValueError as e:
            raise UserError(str(e)) from None
        self._store.update_attempt(a)
        self._apply_attempt(self._store, a)

    @action
    def delete_attempt(self, attempt_id: int) -> None:
        self._store.delete_attempt(attempt_id)

    @action
    def ai_settings(self) -> dict:
        prefs = self._prefs()
        keys = {}
        for which, preset in PROVIDERS.items():
            if not preset.key_env:
                continue
            key = self._key(which)
            from_env = bool(os.environ.get(preset.key_env, "").strip())
            keys[which] = {"has_key": bool(key), "key_hint": f"…{key[-4:]}" if len(key) > 8 else "",
                           "from_env": from_env, "env": preset.key_env, "key_url": preset.key_url, "name": preset.name}
        return {"provider": self._provider_name(),
                "providers": [[k, f"{p.name} ({p.model})" if p.key_env else p.name] for k, p in PROVIDERS.items()],
                "keys": keys, "ollama_model": str(prefs.get("ollama_model") or PROVIDERS["ollama"].model),
                "ollama_url": str(prefs.get("ollama_url") or PROVIDERS["ollama"].base_url)}

    @action
    def save_ai(self, data: dict) -> None:
        """data: provider, keys {gemini: "...", groq: "..."} (blank keeps the saved one), forget [providers],
        ollama_model, ollama_url."""
        prefs = self._prefs()
        which = _text(data, "provider") or self._provider_name()
        if which not in PROVIDERS:
            raise UserError("Pick a provider.")
        prefs["ai_provider"] = which
        for name in data.get("forget") or []:
            prefs.pop(f"{name}_key", None)
        for name, key in (data.get("keys") or {}).items():
            key = str(key or "").strip()
            if not key or name not in PROVIDERS or not PROVIDERS[name].key_env:
                continue
            preset = PROVIDERS[name]
            if preset.key_pattern and not re.fullmatch(preset.key_pattern, key):
                raise UserError(f"That doesn't look like a {preset.name} API key. Copy the whole key from {preset.key_url}.")
            prefs[f"{name}_key"] = key
        model = _text(data, "ollama_model")
        if model:
            if not re.fullmatch(r"[A-Za-z0-9._:/\-]{2,80}", model):
                raise UserError("That isn't an Ollama model name (like gemma3 or qwen2.5vl:7b).")
            prefs["ollama_model"] = model
        url = _text(data, "ollama_url")
        if url:
            if not re.fullmatch(r"https?://[^\s]+", url):
                raise UserError("Ollama's address should look like http://localhost:11434/v1.")
            prefs["ollama_url"] = url
        self._write_prefs(prefs)

    def _ai_call(self, job: str, work: Callable[[], dict]) -> dict:
        """Run a model job in the background: like @action, but the lock is only held for the database parts
        inside `work`, not while the model works (reading an exam can take several requests), so the window
        keeps working. `ai_jobs` tells the window how far it's got."""
        if job in self._jobs:
            return {"error": "That's already being worked on. Wait for it to finish."}
        self._jobs[job] = "Starting…"
        try:
            return work()
        except (LLMError, PageError, UserError, StorageError, FileError, CloudError) as e:
            return {"error": str(e)}
        except Exception as e:  # a bug: say so instead of leaving the page waiting
            return {"error": f"Something went wrong: {e}"}
        finally:
            self._jobs.pop(job, None)

    def ai_jobs(self) -> dict:
        """The model jobs running now, with what each is doing ("Transcribing pages 4–6 of 8"). No lock: it's
        asked every second while a job runs, and must answer even while a sync holds the database."""
        return dict(self._jobs)

    @staticmethod
    def _topic_by_title(topics: list[Topic], title: str) -> int | None:
        wanted = " ".join(title.split()).casefold()
        if not wanted:
            return None
        for t in topics:
            if " ".join(t.title.split()).casefold() == wanted:
                return t.id
        return None

    def _read_bytes(self, store: Store, f: ExamFile) -> bytes:
        path = files.path(self._files_dir(store), f.key)
        if not path.exists():
            raise UserError(f"“{f.name}” hasn't arrived on this computer yet. Wait for StudyPal to sync, then try again.")
        return path.read_bytes()

    def read_exam(self, exam_id: int) -> dict:
        """Read a past exam into questions (core/ingest.py): the files become Markdown (scanned pages and
        maths read by the model), the model lists the questions and the solutions' answers, and they're matched
        by number; your own answers, if added, mark how each went. Replaces the questions listed before."""
        job = f"read:{exam_id}"

        def work() -> dict:
            with self._lock:
                store = self._store
                exam = store.get_exam(exam_id)
                if exam is None:
                    raise UserError("That exam no longer exists.")
                course = store.get_course(exam.course_id)
                topics = store.list_topics(exam.course_id)
                order = {"exam": 0, "solution": 1, "attempt": 2}
                exam_files = sorted(store.list_exam_files(exam_id), key=lambda f: order.get(f.role, 3))
                if not any(f.role == "exam" for f in exam_files):
                    raise UserError("Add the exam paper itself first (a PDF or photos).")
                sources = [ingest.SourceFile(f.name, f.mime, self._read_bytes(store, f), f.role) for f in exam_files]
            provider = self._llm()

            def progress(text: str) -> None:
                self._jobs[job] = text

            result = ingest.ingest(provider, course, topics, sources, exam_id, progress)  # type: ignore[arg-type]
            questions = []
            for q in result.questions:
                result_, note = result.results.get(question_logic.number_key(q.number), ("", ""))
                topic_id = next((t for t in (self._topic_by_title(topics, tag) for tag in q.topic_tags) if t), None)
                questions.append(ExamQuestion(
                    exam_id=exam_id, number=q.number, prompt=q.text, answer=q.answer,
                    marks=f"{q.points:g}" if q.points is not None else "", topic_id=topic_id, result=result_,
                    note=note, parent_number=q.parent_number or "", question_type=q.question_type,
                    topic_tags=q.topic_tags, has_figure=q.has_figure))
            with self._lock:
                if self._store is not store or store.get_exam(exam_id) is None:
                    raise UserError("The exam changed while it was being read. Try again.")
                store.replace_questions(exam_id, questions)
                if result.score and not exam.score:
                    store.update_exam(replace(exam, score=result.score))
            answered = sum(1 for q in questions if q.answer)
            marked = sum(1 for q in questions if q.result)
            has_solutions = any(f.role == "solution" for f in sources)
            parts = [f"{exam.title}: found {len(questions)} question{'s' if len(questions) != 1 else ''}"]
            if has_solutions:
                parts.append(f"{answered} with an answer from the solutions")
            if marked:
                parts.append(f"marked {marked} from your answers")
            message = ", ".join(parts) + "."
            if result.unmatched:
                message += (f" The solutions also answer {', '.join(result.unmatched[:5])}, which didn't match a question"
                            " number: check the numbering.")
            if result.dropped:
                message += f" {result.dropped} came back incomplete and were left out."
            if result.kept_text:
                message += (f" {result.kept_text} page{'s' if result.kept_text != 1 else ''} with maths had more than "
                            f"{provider.name} can write out in one answer on your plan, so {'their' if result.kept_text != 1 else 'its'}"
                            " maths is plain text instead of formulas.")
            return {"ok": True, "message": message}
        return self._ai_call(job, work)

    def _weak_topics(self, topics: list[Topic], tallies: list, focus: str, chosen: list[str]) -> list[str]:
        """The topics a practice exam is about, most important first."""
        if focus == "topics":
            return chosen
        titles = [t.title for t in topics]
        if focus == "struggles":
            weak = [t.title for t in tallies if t.weight > 0 and t.title]
            weak += [t.title for t in sorted(topics, key=lambda t: t.confidence) if t.confidence <= 2 and t.title not in weak]
            if weak:
                return weak[:6] + [t for t in titles if t not in weak][:2]  # and a little of the rest
        return titles

    def make_exam(self, data: dict) -> dict:
        """Write a practice exam with `generate_exam`: past questions on each weak topic as examples, aimed at
        what went badly before. data: course_id, size (short/half/full), focus (struggles/balanced/topics),
        topic_ids, wishes."""
        def work() -> dict:
            course_id = _int(data, "course_id")
            size = _text(data, "size") or "full"
            focus = _text(data, "focus") or "struggles"
            if size not in exam_logic.SIZES or focus not in exam_logic.FOCUSES:
                raise UserError("Pick how long the exam should be and what it should focus on.")
            with self._lock:
                store = self._store
                course = store.get_course(course_id)  # type: ignore[arg-type]
                if course is None:
                    raise UserError("That subject no longer exists.")
                topics = store.list_topics(course_id)  # type: ignore[arg-type]
                wanted_ids = {int(i) for i in data.get("topic_ids") or []}
                chosen = [t.title for t in topics if t.id in wanted_ids]
                if focus == "topics" and not chosen:
                    raise UserError("Pick the topics the exam should be about.")
                exams = store.list_exams(course_id)  # type: ignore[arg-type]
                marked = self._marked_questions(course_id, store)  # type: ignore[arg-type]
                struggles = exam_logic.struggle_summary(marked, topics, store.list_weak_spots(course_id))
                tallies = exam_logic.tally(marked, {t.id: t.title for t in topics})  # type: ignore[misc]
                earlier = [q.prompt for e in exams if e.kind == "practice" for q in store.list_questions(e.id)]  # type: ignore[arg-type]
                number = sum(1 for e in exams if e.kind == "practice") + 1
                past: list[tuple[str, ExamQuestion]] = []
                counts: list[int] = []
                unread = 0
                for e in exams:  # newest first
                    if e.kind != "past":
                        continue
                    qs = store.list_questions(e.id)  # type: ignore[arg-type]
                    past += [(e.title, q) for q in qs]
                    if qs:
                        counts.append(len(qs))
                    else:
                        unread += 1
            typical = round(sum(counts) / len(counts)) if counts else 10
            n = {"short": 5, "half": max(3, round(typical / 2)), "full": max(4, typical)}[size]
            self._jobs[f"make:{course_id}"] = "Writing the questions and solutions"
            made = generate_exam(self._weak_topics(topics, tallies, focus, chosen), n, provider=self._llm(),
                                 course=course, topics=topics, past=past, struggles=struggles,
                                 wishes=_text(data, "wishes"), earlier=earlier, number=number)
            questions = [ExamQuestion(
                exam_id=0, number=q.number, prompt=q.text, answer=q.answer, why=q.why or "",
                marks=f"{q.points:g}" if q.points is not None else "", parent_number=q.parent_number or "",
                question_type=q.question_type, topic_tags=q.topic_tags, has_figure=q.has_figure,
                topic_id=next((t for t in (self._topic_by_title(topics, tag) for tag in q.topic_tags) if t), None),
            ) for q in made.questions]
            with self._lock:
                if self._store is not store or store.get_course(course_id) is None:  # type: ignore[arg-type]
                    raise UserError("The subject changed while the exam was being written. Try again.")
                exam = store.add_exam(Exam(course_id=course_id, title=made.title, kind="practice",  # type: ignore[arg-type]
                                           notes=made.intro))
                store.replace_questions(exam.id, questions)  # type: ignore[arg-type]
            note = (f" ({unread} past exam{'s' if unread != 1 else ''} not used: press Read questions on "
                    f"{'them' if unread != 1 else 'it'} first)") if unread else ""
            return {"ok": True, "id": exam.id, "course_id": course_id, "message": f"“{made.title}” is ready{note}."}
        return self._ai_call(f"make:{_int(data, 'course_id')}", work)

    @action
    def save_printable(self, title: str, html: str) -> dict:
        """Save a practice exam as a web page (drawn by the window, with its maths), and open it in the
        browser to print or keep."""
        import webview

        if self._window is None:
            raise UserError("Can't open a save dialog right now.")
        safe = re.sub(r'[/\\:*?"<>|]+', "-", str(title)).strip() or "Practice exam"
        chosen = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{safe}.html")
        if not chosen:
            return {"ok": True, "message": ""}
        path = Path(chosen if isinstance(chosen, str) else chosen[0])
        path.write_text(str(html), encoding="utf-8")
        webbrowser.open(path.as_uri())
        return {"ok": True, "message": f"Saved {path.name}. It opens in your browser, ready to print."}

    # ---------- backup ----------

    # ---------- research projects ----------

    @action
    def projects(self) -> list[dict]:
        """Every research project, for the pickers in forms."""
        return [_project(p) for p in self._store.list_projects()]

    @action
    def research(self, project_id: int) -> dict:
        now = datetime.now().replace(microsecond=0)
        p = self._store.get_project(project_id)
        if p is None:
            raise UserError("That project no longer exists.")
        week_start, week_end = week_range(now.date(), self._config().week_start)
        tasks = self._store.list_tasks(project_id)
        sources = self._store.list_project_sources(project_id)
        return {
            "project": _project(p),
            "notes": [self._note_json(n) for n in self._store.list_notes(project_id)],
            "entries": [{"id": e.id, "day": _iso(e.day), "day_label": f"{_day(e.day)} {e.day.year}", "body": e.body}
                        for e in self._store.list_entries(project_id)],
            "links": [{"id": x.id, "name": x.name, "url": x.url, "category": x.category,
                       "kind": x.category or guess_category(x.url), "host": _host(x.url)}
                      for x in self._store.list_links(project_id)],
            "sources": [{"id": x.id, "title": x.title, "authors": x.authors, "year": x.year, "link": x.link,
                         "status": x.status, "status_label": READING_LABELS[x.status], "annotation": x.annotation,
                         "apa": apa(Source(course_id=0, title=x.title, author=x.authors, kind="article", year=x.year,
                                           link=x.link)).text}
                        for x in sources],
            "reading": {s: sum(1 for x in sources if x.status == s) for s in READING_STATUSES},
            "tasks": [{"id": t.id, "text": t.text, "done": t.done,
                       "done_label": _day(t.done_at.date()) if t.done_at else ""} for t in tasks],
            "tasks_done": sum(1 for t in tasks if t.done),
            "sessions": [_project_session(x) for x in self._store.list_project_sessions(project_id, limit=50)],
            "week_total": format_minutes(sum(x.minutes for x in self._store.list_project_sessions(
                project_id, since=week_start, until=week_end))),
            "total": format_minutes(self._store.project_minutes(project_id)),
            "statuses": [[s, STATUS_LABELS[s]] for s in PROJECT_STATUSES],
            "categories": list(LINK_CATEGORIES),
            "running": self._running(now),
        }

    @action
    def save_project(self, data: dict) -> dict:
        project_id = _int(data, "id")
        old = self._store.get_project(project_id) if project_id else None
        status = _text(data, "status") or "active"
        if status not in PROJECT_STATUSES:
            raise UserError("Pick a status for the project.")
        tags = [t.strip() for t in str(data.get("tags") or "").split(",")]
        fields = {"title": _text(data, "title"), "description": str(data.get("description") or "").strip(),
                  "status": status, "tags": [t for i, t in enumerate(tags) if t and t.lower() not in
                                             (x.lower() for x in tags[:i])],
                  "start_on": _optional_date(data, "start_on"), "end_on": _optional_date(data, "end_on"),
                  "color": _text(data, "color") or (old.color if old else self._store.next_color())}
        if old is not None:
            self._store.update_project(replace(old, **fields))
            return {"ok": True, "id": project_id}
        return {"ok": True, "id": self._store.add_project(Project(**fields)).id}

    @action
    def set_project_status(self, project_id: int, status: str) -> None:
        if status not in PROJECT_STATUSES:
            raise UserError("Pick a status for the project.")
        self._store.set_project_status(project_id, status)

    @action
    def delete_project(self, project_id: int) -> None:
        self._store.delete_project(project_id)

    @action
    def reorder(self, items: list[dict]) -> None:
        """The overview's list after dragging: [{kind: "course"|"project", id}, ...] from top to bottom."""
        self._store.reorder([(str(x.get("kind")), int(x.get("id"))) for x in items])

    @action
    def move_items(self, kind: str, ids: list[int]) -> None:
        self._store.move_items(kind, [int(i) for i in ids])

    # notes: saved while you type, so these answer with the note instead of making the page redraw

    @staticmethod
    def _note_json(n: ProjectNote) -> dict:
        updated = n.updated_at or n.created_at
        return {"id": n.id, "title": n.title, "body": n.body, "created_label": _when(n.created_at),
                "updated_label": _when(updated), "updated": _iso(updated)}

    @action
    def add_note(self, project_id: int) -> dict:
        if self._store.get_project(project_id) is None:
            raise UserError("That project no longer exists.")
        return self._note_json(self._store.add_note(ProjectNote(project_id=project_id)))

    @action
    def save_note(self, data: dict) -> dict:
        note_id = _int(data, "id")
        old = self._store.get_note(note_id) if note_id else None
        if old is None:
            raise UserError("That note was deleted (maybe on another computer). Copy your text before leaving.")
        return self._note_json(self._store.update_note(replace(old, title=_text(data, "title"),
                                                                body=str(data.get("body") or ""))))

    @action
    def delete_note(self, note_id: int) -> None:
        self._store.delete_note(note_id)

    # journal

    @action
    def save_entry(self, data: dict) -> dict:
        entry_id = _int(data, "id")
        day = _date(data, "day", "the entry")
        body = str(data.get("body") or "")
        if entry_id:
            old = self._store.get_entry(entry_id)
            if old is None:
                raise UserError("That entry no longer exists.")
            self._store.update_entry(replace(old, day=day, body=body))
            return {"ok": True, "id": entry_id}
        return {"ok": True, "id": self._store.add_entry(ProjectEntry(project_id=_int(data, "project_id"),  # type: ignore[arg-type]
                                                                     day=day, body=body)).id}

    @action
    def delete_entry(self, entry_id: int) -> None:
        self._store.delete_entry(entry_id)

    # shortcuts

    @action
    def save_link(self, data: dict) -> dict:
        link_id = _int(data, "id")
        category = _text(data, "category")
        fields = {"name": _text(data, "name"), "url": link_address(_text(data, "url")),
                  "category": "" if category == "auto" else category}
        if not fields["name"]:
            fields["name"] = _host(fields["url"])
        if link_id:
            old = self._store.get_link(link_id)
            if old is None:
                raise UserError("That shortcut no longer exists.")
            self._store.update_link(replace(old, **fields))
            return {"ok": True, "id": link_id}
        return {"ok": True, "id": self._store.add_link(ProjectLink(project_id=_int(data, "project_id"), **fields)).id}  # type: ignore[arg-type]

    @action
    def delete_link(self, link_id: int) -> None:
        self._store.delete_link(link_id)

    @action
    def open_link(self, url: str) -> None:
        """Open a shortcut, a reference or a link in a note in the computer's browser (or Zotero), never in
        this window."""
        url = link_address(str(url))
        if url.lower().startswith(("http:", "https:")):
            webbrowser.open(url)
        elif sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", url])

    # references

    @action
    def save_project_source(self, data: dict) -> dict:
        source_id = _int(data, "id")
        status = _text(data, "status") or "to_read"
        link = _text(data, "link")
        fields = {"title": _text(data, "title"), "authors": _text(data, "authors"), "year": _text(data, "year"),
                  "link": link_address(link) if link else "", "status": status,
                  "annotation": str(data.get("annotation") or "").strip()}
        if status not in READING_STATUSES:
            raise UserError("Pick to read, reading or read.")
        if source_id:
            old = self._store.get_project_source(source_id)
            if old is None:
                raise UserError("That reference no longer exists.")
            self._store.update_project_source(replace(old, **fields))
            return {"ok": True, "id": source_id}
        return {"ok": True, "id": self._store.add_project_source(
            ProjectSource(project_id=_int(data, "project_id"), **fields)).id}  # type: ignore[arg-type]

    @action
    def set_source_status(self, source_id: int, status: str) -> None:
        old = self._store.get_project_source(source_id)
        if old is None:
            raise UserError("That reference no longer exists.")
        self._store.update_project_source(replace(old, status=status))

    @action
    def delete_project_source(self, source_id: int) -> None:
        self._store.delete_project_source(source_id)

    # tasks

    @action
    def save_task(self, data: dict) -> dict:
        task_id = _int(data, "id")
        if task_id:
            old = self._store.get_task(task_id)
            if old is None:
                raise UserError("That task no longer exists.")
            self._store.update_task(replace(old, text=_text(data, "text")))
            return {"ok": True, "id": task_id}
        return {"ok": True, "id": self._store.add_task(ProjectTask(project_id=_int(data, "project_id"),  # type: ignore[arg-type]
                                                                   text=_text(data, "text"))).id}

    @action
    def toggle_task(self, task_id: int) -> None:
        self._store.toggle_task(task_id)

    @action
    def delete_task(self, task_id: int) -> None:
        self._store.delete_task(task_id)

    @action
    def delete_project_session(self, session_id: int) -> None:
        self._store.delete_project_session(session_id)

    @action
    def export_markdown(self) -> dict:
        """Ask where to save, then write everything as one readable document."""
        import webview

        if self._window is None:
            raise UserError("Can't open a save dialog right now.")
        name = f"StudyPal backup {datetime.now():%Y-%m-%d}.md"
        chosen = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name)
        if not chosen:
            return {"ok": True, "message": ""}
        path = Path(chosen if isinstance(chosen, str) else chosen[0])
        path.write_text(to_markdown(self._store), encoding="utf-8")
        return {"ok": True, "message": f"Saved to {path.name}."}

    @action
    def copy_to_clipboard(self, text: str, html: str) -> None:
        """Put a reference on the system clipboard, formatted where the system allows it. The window
        tries its own ways first; this is the fallback."""
        import subprocess
        import sys

        if sys.platform == "darwin":
            try:
                from AppKit import NSPasteboard, NSPasteboardTypeHTML, NSPasteboardTypeString

                board = NSPasteboard.generalPasteboard()
                board.clearContents()
                board.setString_forType_(html, NSPasteboardTypeHTML)
                board.setString_forType_(text, NSPasteboardTypeString)
                return
            except ImportError:
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
                return
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
            return
        raise UserError("Copying isn't supported here. Select the reference and copy it by hand.")

    @action
    def data_location(self) -> str:
        return str(self._store.path)
