"""Asking Groq to read exams and write new ones.

One call: `Groq.ask(parts, schema)` sends text and page images to the OpenAI-style chat completions
endpoint and returns the answer as JSON, shaped by `schema` (strict structured output, so the shape is
guaranteed). Only the standard library is used, like cloud.py. The API key is the person's own (free
from the Groq console) and never leaves this computer except to Groq.

Groq can't read PDFs, and only its vision model takes images, at most three per request. So exams are
turned into page images first (core/pages.py) and read a few pages at a time (api.py). Practice exams
are written by a text model from the questions already read from past exams.
"""

from __future__ import annotations

import base64
import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .cloud import _ssl_context

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
VISION_MODEL = "qwen/qwen3.8-27b"  # the one model that reads images; reads every exam
DEFAULT_MODEL = "openai/gpt-oss-120b"  # writes practice exams and answers
# (model id, label) for the picker in Settings: the model that writes.
MODELS = (
    ("openai/gpt-oss-120b", "GPT-OSS 120B: best for exams and worked solutions"),
    ("openai/gpt-oss-20b", "GPT-OSS 20B: faster, for simpler courses"),
    ("qwen/qwen3.8-27b", "Qwen 3.8 27B (preview)"),
)
KEY_URL = "https://console.groq.com/keys"
IMAGES_PER_REQUEST = 3  # Groq's limit for its vision model
MAX_REQUEST = 18 * 1024 * 1024  # Groq takes requests up to 20 MB


class GroqError(Exception):
    """Something went wrong asking Groq; the message is fit to show as it is."""


@dataclass
class Image:
    """A page or photo, as JPEG."""

    name: str
    data: bytes


def _part(item: str | Image) -> dict:
    if isinstance(item, Image):
        return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(item.data).decode()}}
    return {"type": "text", "text": item}


def parse_json(text: str) -> Any:
    """The answer's JSON, also when it came wrapped in a ```json fence or after the model's thinking."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
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
    raise GroqError("Groq's answer came back garbled. Try again.")


class Groq:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 300) -> None:
        self.api_key = api_key.strip()
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._ssl = _ssl_context()

    def ask(self, parts: list[str | Image], schema: dict, system: str = "", temperature: float | None = None,
            model: str | None = None) -> Any:
        """`model` overrides the chosen one for this call (reading pages always uses VISION_MODEL)."""
        model = model or self.model
        images = sum(1 for p in parts if isinstance(p, Image))
        if images > IMAGES_PER_REQUEST:
            raise GroqError(f"Groq reads at most {IMAGES_PER_REQUEST} pages at a time.")
        content: str | list[dict] = (parts[0] if len(parts) == 1 and isinstance(parts[0], str)
                                     else [_part(p) for p in parts])
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
        }
        if temperature is not None:
            body["temperature"] = temperature
        if model.startswith("qwen/"):
            body["reasoning_format"] = "hidden"  # JSON only in the answer; no <think> block
        elif model.startswith("openai/gpt-oss"):
            body["include_reasoning"] = False
            body["reasoning_effort"] = "medium"
        data = json.dumps(body).encode()
        if len(data) > MAX_REQUEST:
            raise GroqError("These pages are too big to send to Groq. Use smaller scans.")
        return parse_json(self._text(self._post(data)))

    def _post(self, data: bytes, tries: int = 4) -> dict:
        for attempt in range(tries):
            req = urllib.request.Request(ENDPOINT, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            req.add_header("User-Agent", "StudyPal")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                raw = e.read()
                error = self._error(e.code, raw)
                last = attempt == tries - 1
                # Over the per-minute limit: wait as long as Groq says (up to a minute) and try again.
                if e.code == 429 and not last and "per day" not in str(error):
                    time.sleep(min(60.0, _retry_after(e.headers.get("retry-after"), raw) + 0.5))
                    continue
                if e.code in (500, 502, 503, 498) and not last:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise error from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                reason = getattr(e, "reason", e)
                if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
                    raise GroqError("Groq took too long to answer. Try again.") from None
                raise GroqError(f"Couldn't reach Groq ({reason}). Check your internet connection.") from None
        raise GroqError("Groq is busy. Try again in a minute.")

    @staticmethod
    def _error(status: int, raw: bytes) -> GroqError:
        try:
            err = json.loads(raw).get("error", {})
        except (ValueError, AttributeError):
            err = {}
        message = str(err.get("message", ""))
        code = str(err.get("code", ""))
        if status == 401 or code == "invalid_api_key":
            return GroqError("Groq didn't accept the API key. Check it in Settings (copy the whole key).")
        if status == 404 or code == "model_not_found" or "decommissioned" in message:
            return GroqError("Groq no longer offers that model. Pick another in Settings.")
        if status == 429:
            if "per day" in message or "TPD" in message or "RPD" in message:
                return GroqError("You've used up today's Groq allowance for this model. Try again tomorrow, or pick "
                                 "another model in Settings.")
            return GroqError("You've hit Groq's per-minute limit. Wait a minute and try again.")
        if status == 413 or "too large" in message.lower():
            return GroqError("That's more than Groq takes in one go on your plan. Try a shorter practice exam, or "
                             "fewer past exams.")
        if status == 403:
            return GroqError(f"Groq refused: {message or 'not allowed with this key'}")
        if code == "json_validate_failed":
            return GroqError("Groq's answer didn't come out in the right shape. Try again.")
        if status >= 500 or status == 498:
            return GroqError("Groq is having problems right now. Try again in a minute.")
        return GroqError(f"Groq said no: {message or status}")

    @staticmethod
    def _text(answer: dict) -> str:
        choices = answer.get("choices") or []
        if not choices:
            raise GroqError("Groq sent back nothing. Try again.")
        choice = choices[0]
        text = str((choice.get("message") or {}).get("content") or "")
        if choice.get("finish_reason") == "length":
            raise GroqError("Groq ran out of room before finishing. Ask for a shorter exam.")
        if not text.strip():
            raise GroqError("Groq sent back nothing. Try again.")
        return text


def _retry_after(header: str | None, raw: bytes) -> float:
    """Seconds to wait before trying again: the Retry-After header, or "try again in 7.5s" in the message."""
    try:
        return float(header) if header else 0.0
    except ValueError:
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", raw.decode(errors="replace"))
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 5.0
