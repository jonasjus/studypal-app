"""The files people add to exams (PDFs, photos), kept in a `files` folder next to the database.

Each file is stored under the hash of its contents (<sha256>.pdf), so the same file added twice is
stored once, and the name is the same on every computer the account syncs to.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

# What Gemini can read, by extension.
TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".txt": "text/plain",
    ".md": "text/plain",
}
MAX_SIZE = 40 * 1024 * 1024
KEY = re.compile(r"[0-9a-f]{64}\.[a-z0-9]{1,5}")


class FileError(Exception):
    """A file that can't be used; the message says why."""


def folder_for(db_path: Path) -> Path:
    return Path(db_path).parent / "files"


def check(name: str, size: int) -> str:
    """The file's type, if StudyPal can use it."""
    ext = Path(name).suffix.lower()
    if ext not in TYPES:
        hint = " Save it as a PDF first." if ext in (".doc", ".docx", ".odt", ".pages", ".ppt", ".pptx", ".key") else ""
        raise FileError(f"“{name}” can't be used: add PDFs, photos (JPG, PNG, HEIC) or text files.{hint}")
    if size > MAX_SIZE:
        raise FileError(f"“{name}” is too big ({size / 1024 / 1024:.0f} MB). Files can be up to {MAX_SIZE // 1024 // 1024} MB.")
    if size == 0:
        raise FileError(f"“{name}” is empty.")
    return TYPES[ext]


def store(folder: Path, name: str, data: bytes) -> tuple[str, str]:
    """Save a file's contents; returns (key, mime type)."""
    mime = check(name, len(data))
    key = f"{hashlib.sha256(data).hexdigest()}{Path(name).suffix.lower()}"
    path = folder / key
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return key, mime


def path(folder: Path, key: str) -> Path:
    if not KEY.fullmatch(key):
        raise FileError("That file's name isn't one StudyPal made.")
    return folder / key


def tidy(folder: Path, keep: set[str]) -> None:
    """Remove files no exam uses any more."""
    if not folder.is_dir():
        return
    for f in folder.iterdir():
        if KEY.fullmatch(f.name) and f.name not in keep:
            try:
                os.remove(f)
            except OSError:
                pass


def copy_all(source: Path, target: Path) -> None:
    """Copy every stored file from one folder to another (when bringing data into an account)."""
    if not source.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    for f in source.iterdir():
        if KEY.fullmatch(f.name) and not (target / f.name).exists():
            (target / f.name).write_bytes(f.read_bytes())
