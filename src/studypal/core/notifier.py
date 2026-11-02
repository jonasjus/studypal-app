"""Desktop notifications.

On macOS, notifications go through `osascript`: desktop-notifier needs a signed app bundle there,
which an unsigned app isn't. Elsewhere desktop-notifier is tried first, then `notify-send`.
Set STUDYPAL_NOTIFIER=print to print notifications instead of showing them (handy for testing cron setups).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

APP_NAME = "StudyPal"


def _osascript(title: str, message: str) -> bool:
    def quote(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    script = f"display notification {quote(message)} with title {quote(APP_NAME)} subtitle {quote(title)}"
    return subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10).returncode == 0


def _notify_send(title: str, message: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    return subprocess.run(["notify-send", "--app-name", APP_NAME, title, message],
                          capture_output=True, timeout=10).returncode == 0


def _desktop_notifier(title: str, message: str) -> bool:
    from desktop_notifier import DesktopNotifierSync  # imported lazily: it's slow to load

    DesktopNotifierSync(app_name=APP_NAME).send(title=title, message=message)
    return True


def send(title: str, message: str) -> bool:
    """Show a notification. Returns False if no method worked, so the caller can try again later."""
    if os.environ.get("STUDYPAL_NOTIFIER") == "print":
        print(f"[notification] {title} — {message}")
        return True
    if sys.platform == "darwin":
        methods = (_osascript, _desktop_notifier)
    else:
        methods = (_desktop_notifier, _notify_send)
    for method in methods:
        try:
            if method(title, message):
                return True
        except Exception:  # a missing backend or notification daemon: try the next method
            continue
    return False
