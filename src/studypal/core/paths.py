"""Where StudyPal keeps its data: the usual per-user application folder for each platform.

    macOS    ~/Library/Application Support/StudyPal
    Windows  %APPDATA%\\StudyPal
    Linux    ~/.local/share/studypal (XDG_DATA_HOME)

STUDYPAL_DB overrides the database file (used by --demo and tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "StudyPal"


def data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg) if xdg and os.path.isabs(xdg) else Path.home() / ".local" / "share") / APP.lower()


def db_path() -> Path:
    override = os.environ.get("STUDYPAL_DB", "").strip()
    return Path(override) if override else data_dir() / "studypal.db"


def config_path() -> Path:
    """Not used by the app (settings live in the database), but config.load() expects it."""
    return data_dir() / "config.toml"
