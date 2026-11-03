"""The Pomodoro's pling, played by the system so it's heard while the window is in the background.

The sound is made here (a bell-like tone with two quiet overtones that fades out), written once to a WAV
file in the temp folder, and played without waiting: `afplay` on macOS, winsound on Windows, and
`paplay` or `aplay` on Linux if there. One pling when a focus block ends; two, a little higher, when a
break is over. Set STUDYPAL_SOUND=print to print instead of playing (for testing).

`KeepAwake` stops macOS from napping the app while a Pomodoro runs (App Nap slows a background app's
timers down to minutes), so the pling comes on time.
"""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

RATE = 22050
FOCUS_DONE, BREAK_OVER = "focus_done", "break_over"
# (frequency, how many plings): E6 for "take a break", G6 twice for "back to work".
SOUNDS = {FOCUS_DONE: (1319.0, 1), BREAK_OVER: (1568.0, 2)}
_files: dict[str, Path] = {}


def samples(kind: str) -> list[float]:
    base, times = SOUNDS[kind]
    out = [0.0] * int(RATE * (1.4 + 0.22 * (times - 1)))
    for i in range(times):
        start = 0.02 + 0.22 * i
        for ratio, level, length in ((1, 1.0, 1.3), (2, 0.22, 0.7), (3, 0.07, 0.4)):
            step = 2 * math.pi * base * ratio / RATE
            for n in range(int(length * RATE)):
                t = n / RATE
                # A 6 ms rise, then an exponential fade to silence over `length`.
                env = level * t / 0.006 if t < 0.006 else level * (0.0001 / level) ** ((t - 0.006) / (length - 0.006))
                out[int(start * RATE) + n] += 0.3 * env * math.sin(step * n)
    return out


def wav_file(kind: str) -> Path:
    if kind not in _files or not _files[kind].exists():
        path = Path(tempfile.gettempdir()) / f"studypal-{kind}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x)) * 32767)) for x in samples(kind)))
        _files[kind] = path
    return _files[kind]


def play(kind: str) -> None:
    """Start the sound and return straight away. Never raises: no sound is better than a crash."""
    if os.environ.get("STUDYPAL_SOUND") == "print":
        print(f"[sound] {kind}")
        return
    try:
        path = wav_file(kind)
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            player = shutil.which("paplay") or shutil.which("aplay")
            if player:
                subprocess.Popen([player, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


class KeepAwake:
    """While on, macOS keeps running the app at full speed in the background (the screen may still sleep)."""

    def __init__(self) -> None:
        self._token = None

    def set(self, on: bool) -> None:
        if sys.platform != "darwin" or on == (self._token is not None):
            return
        try:
            from Foundation import NSActivityUserInitiatedAllowingIdleSystemSleep, NSProcessInfo

            info = NSProcessInfo.processInfo()
            if on:
                self._token = info.beginActivityWithOptions_reason_(
                    NSActivityUserInitiatedAllowingIdleSystemSleep, "A Pomodoro is running")
            else:
                info.endActivity_(self._token)
                self._token = None
        except Exception:  # no pyobjc (tests, Linux): the pling may just come a little late
            self._token = None
