"""Asking Google's Gemini to read exams and write new ones.

One call: `Gemini.ask(parts, schema)` sends text and files (PDFs, images) to the generateContent
endpoint and returns the answer as JSON, shaped by `schema`. Only the standard library is used,
like cloud.py. The API key is the person's own (free from Google AI Studio) and never leaves this
computer except to Google.
"""

from __future__ import annotations

import base64
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .cloud import _ssl_context

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-flash-latest"  # if the chosen model is retired, try the current Flash
# (model id, label) for the picker in Settings.
MODELS = (
    ("gemini-3.8-flash", "Gemini 3.8 Flash: fast, good for most exams"),
    ("gemini-4-argon", "Gemini 4: slower, best for hard maths and long exams"),
    ("gemini-flash-latest", "Newest Flash, whatever it is"),
)
KEY_URL = "https://aistudio.google.com/apikey"
MAX_UPLOAD = 45 * 1024 * 1024  # files sent with one request (Gemini takes up to 50 MB)


class GeminiError(Exception):
    """Something went wrong asking Gemini; the message is fit to show as it is."""


@dataclass
class File:
    name: str
    mime: str
    data: bytes


def _part(item: str | File) -> dict:
    if isinstance(item, File):
        return {"inline_data": {"mime_type": item.mime, "data": base64.b64encode(item.data).decode()}}
    return {"text": item}


def parse_json(text: str) -> Any:
    """The answer's JSON, also when it came wrapped in a ```json fence."""
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
    raise GeminiError("Gemini's answer came back garbled. Try again.")


class Gemini:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 600) -> None:
        self.api_key = api_key.strip()
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._ssl = _ssl_context()

    def ask(self, parts: list[str | File], schema: dict, system: str = "", temperature: float | None = None) -> Any:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [_part(p) for p in parts]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema},
        }
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            answer = self._post(self.model, body)
        except _ModelGone:
            if self.model == FALLBACK_MODEL:
                raise GeminiError(f"Gemini doesn't know the model “{self.model}”. Pick another in Settings.") from None
            answer = self._post(FALLBACK_MODEL, body)
        return parse_json(self._text(answer))

    def _post(self, model: str, body: dict, tries: int = 3) -> dict:
        url = ENDPOINT.format(model=urllib.parse.quote(model, safe=""))
        data = json.dumps(body).encode()
        for attempt in range(tries):
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("x-goog-api-key", self.api_key)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                error = self._error(e.code, e.read())
                # Busy right now: wait a little and try again.
                if e.code in (500, 503) and attempt < tries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise error from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                reason = getattr(e, "reason", e)
                if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
                    raise GeminiError("Gemini took too long to answer. Try again, or with fewer or smaller files.") from None
                raise GeminiError(f"Couldn't reach Gemini ({reason}). Check your internet connection.") from None
        raise GeminiError("Gemini is busy. Try again in a minute.")

    @staticmethod
    def _error(status: int, raw: bytes) -> Exception:
        try:
            err = json.loads(raw).get("error", {})
        except (ValueError, AttributeError):
            err = {}
        message = str(err.get("message", ""))
        reasons = json.dumps(err.get("details", []))
        if status == 404 or "is not found" in message:
            return _ModelGone()
        if "API_KEY_INVALID" in reasons or "API key not valid" in message or status in (401, 403):
            return GeminiError("Gemini didn't accept the API key. Check it in Settings (copy the whole key).")
        if status == 429:
            return GeminiError("You've hit Gemini's limit for now (free keys allow a few requests a minute and a "
                               "number per day). Wait a bit and try again.")
        if status == 400 and ("location" in message.lower() or "region" in message.lower()):
            return GeminiError("Gemini isn't available in your country with this key.")
        if status == 413 or "too large" in message.lower() or "exceeds" in message.lower():
            return GeminiError("The files are too big for Gemini in one go. Remove a few exams or use smaller files.")
        if status >= 500:
            return GeminiError("Gemini is having problems right now. Try again in a minute.")
        return GeminiError(f"Gemini said no: {message or status}")

    @staticmethod
    def _text(answer: dict) -> str:
        candidates = answer.get("candidates") or []
        if not candidates:
            reason = (answer.get("promptFeedback") or {}).get("blockReason")
            raise GeminiError(f"Gemini wouldn't answer ({reason})." if reason else "Gemini sent back nothing. Try again.")
        cand = candidates[0]
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
        if not text.strip():
            reason = cand.get("finishReason", "")
            if reason == "MAX_TOKENS":
                raise GeminiError("Gemini ran out of room before finishing. Ask for a shorter exam.")
            raise GeminiError(f"Gemini sent back nothing ({reason or 'no reason given'}). Try again.")
        if cand.get("finishReason") == "MAX_TOKENS":
            raise GeminiError("Gemini ran out of room before finishing. Ask for a shorter exam.")
        return text


class _ModelGone(Exception):
    pass
