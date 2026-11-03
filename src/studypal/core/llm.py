"""Asking a language model to read exams and write new ones, through one small interface.

Every provider is reached through the OpenAI-compatible chat completions API, so one client serves them
all; a `Preset` holds what differs (address, default models, where the key comes from, how many images
fit in a request). Gemini is the default; Groq and Ollama (a model running on this computer) are a
switch in Settings. Only the standard library is used, like cloud.py.

`ask(parts, schema)` sends text and page images and returns JSON shaped by `schema` (structured output).
The caller validates it (core/logic/questions.py uses Pydantic). Rate limits (429) and busy servers are
retried with exponential backoff, waiting longer if the server says so.
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .cloud import _ssl_context


class LLMError(Exception):
    """Something went wrong asking the model; the message is fit to show as it is."""


class TooMuch(LLMError):
    """The answer would be (or was) cut off: more than the model may write in one answer, or more than the
    plan allows per minute. Ask for less (fewer pages) and it can work."""


@dataclass
class Image:
    """A page or photo, as JPEG."""

    name: str
    data: bytes


@dataclass(frozen=True)
class Preset:
    name: str  # what the person sees
    base_url: str
    model: str  # writes questions, answers and practice exams
    vision_model: str  # transcribes scanned pages
    key_env: str | None  # the environment variable with the key (it wins over Settings)
    key_url: str = ""
    key_pattern: str = ""  # what a real key looks like, to catch a wrong paste
    max_images: int = 6  # page images per request
    chunk_chars: int = 12_000  # Markdown per request when finding questions: what fits in one answer
    max_output: int | None = None  # tokens an answer may have, asked for explicitly (else the provider's default)
    example_chars: int = 40_000  # past-question examples in a practice-exam prompt (they make most of it)


PROVIDERS: dict[str, Preset] = {
    "gemini": Preset("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash",
                     "gemini-3.8-flash", "GEMINI_API_KEY", "https://aistudio.google.com/apikey",
                     r"AIza[0-9A-Za-z_\-]{30,60}", max_images=10, chunk_chars=60_000),
    "groq": Preset("Groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "qwen/qwen3.8-27b",
                   "GROQ_API_KEY", "https://console.groq.com/keys", r"gsk_[A-Za-z0-9]{20,200}", max_images=3,
                   chunk_chars=4_000, max_output=8_192, example_chars=10_000),  # left alone, Groq quietly stops answers at 1,024 tokens
    "ollama": Preset("Ollama (on this computer)", "http://localhost:11434/v1", "gemma3", "gemma3", None, max_images=4,
                     chunk_chars=8_000),
}
DEFAULT_PROVIDER = "gemini"
MAX_WAIT = 240.0  # seconds of rate-limit waiting for one request before giving up (free plans wait a lot)


class Provider(Protocol):
    """What the rest of StudyPal needs from a model provider."""

    name: str
    max_images: int
    chunk_chars: int

    def ask(self, parts: list[str | Image], schema: dict, system: str = "", temperature: float | None = None,
            vision: bool = False, effort: str = "medium") -> Any:
        """JSON shaped like `schema`. `vision` picks the model that reads images; `effort` is how hard it
        thinks first (low for copying out, medium for writing). Raises TooMuch when the answer won't fit."""
        ...


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
    raise LLMError("The model's answer came back garbled. Try again.")


def backoff(attempt: int, retry_after: float | None) -> float:
    """Seconds to wait before try number `attempt + 2`: what the server asked for, else 2, 4, 8, 16 s
    (capped at a minute), with a little jitter so two windows don't retry in step."""
    if retry_after is not None:
        return min(60.0, retry_after + 0.5)
    return min(60.0, 2.0 * 2 ** attempt) + random.uniform(0, 0.5)


class OpenAICompatible:
    """A Provider for any OpenAI-compatible chat completions API."""

    def __init__(self, preset: Preset, api_key: str = "", model: str = "", vision_model: str = "",
                 base_url: str = "", timeout: float = 300, tries: int = 8, sleep=time.sleep) -> None:
        self.preset = preset
        self.name = preset.name
        self.max_images = preset.max_images
        self.chunk_chars = preset.chunk_chars
        self.example_chars = preset.example_chars
        self.api_key = api_key.strip()
        self.model = model or preset.model
        self.vision_model = vision_model or preset.vision_model
        self.base_url = (base_url or preset.base_url).rstrip("/")
        self.timeout = timeout
        self.tries = tries
        self._sleep = sleep
        self._ssl = _ssl_context()
        self.on_wait = lambda seconds: None  # told before waiting out a rate limit, to say so in the window

    def ask(self, parts: list[str | Image], schema: dict, system: str = "", temperature: float | None = None,
            vision: bool = False, effort: str = "medium") -> Any:
        model = self.vision_model if vision else self.model
        if sum(isinstance(p, Image) for p in parts) > self.max_images:
            raise LLMError(f"{self.name} reads at most {self.max_images} pages at a time.")
        content: str | list[dict] = (parts[0] if len(parts) == 1 and isinstance(parts[0], str)
                                     else [_part(p) for p in parts])
        body: dict[str, Any] = {
            "model": model,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
        }
        if temperature is not None:
            body["temperature"] = temperature
        if self.preset.max_output:
            body["max_completion_tokens"] = self.preset.max_output
        # Per-provider extras: no reasoning text mixed into the JSON, and thinking only as much as needed
        # (it counts toward what the model may write, which is little on free plans).
        if model.startswith("qwen/"):
            body["reasoning_format"] = "hidden"
            body["reasoning_effort"] = "none" if effort == "low" else "default"
        elif model.startswith("openai/gpt-oss"):
            body["include_reasoning"] = False
            body["reasoning_effort"] = effort
        answer = self._post(body)
        # An answer that used every token it was allowed was cut off, even if it's called finished (strict
        # JSON output closes the document neatly, losing whatever didn't fit).
        used = (answer.get("usage") or {}).get("completion_tokens") or 0
        allowed = body.get("max_completion_tokens")
        if allowed and used >= allowed - 2:
            raise TooMuch(f"{self.name} ran out of room before finishing its answer.")
        return parse_json(self._text(answer))

    def _post(self, body: dict) -> dict:
        """Send the request, waiting out rate limits (up to `tries` waits and MAX_WAIT seconds in all), asking
        for a shorter answer when one request is over the plan's per-minute limit, and once more when the answer
        broke its shape."""
        waits = shrinks = broken = 0
        waited = 0.0
        while True:
            req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(), method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {self.api_key or 'none'}")
            req.add_header("User-Agent", "StudyPal")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                raw = e.read()
                error = self.error(e.code, raw)
                if isinstance(error, TooMuch):
                    # More than the plan allows per minute in one request: ask for a shorter answer that fits and
                    # try again straight away. If the answer then doesn't fit, the caller asks for less.
                    lower = _lower_output(raw, body.get("max_completion_tokens"))
                    if lower and shrinks < 3:
                        body["max_completion_tokens"] = lower
                        shrinks += 1
                        continue
                    raise error from None
                # An answer that broke its shape (a model stuck repeating itself) usually comes out fine once more;
                # if not, asking for less (fewer pages) helps, so it counts as too much.
                if b"json_validate_failed" in raw:
                    if broken == 0:
                        broken += 1
                        continue
                    raise TooMuch(f"{self.name}'s answer didn't come out in the right shape.") from None
                if e.code in (429, 500, 502, 503, 504, 498) and "today" not in str(error) and waits < self.tries:
                    wait = backoff(waits, _retry_after(e.headers.get("retry-after"), raw))
                    if waited + wait <= MAX_WAIT:
                        waits += 1
                        waited += wait
                        self.on_wait(wait)
                        self._sleep(wait)
                        continue
                raise error from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                reason = getattr(e, "reason", e)
                if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
                    raise LLMError(f"{self.name} took too long to answer. Try again.") from None
                if self.preset is PROVIDERS["ollama"]:
                    raise LLMError("Couldn't reach Ollama. Is it running? Start the Ollama app, then try again.") from None
                raise LLMError(f"Couldn't reach {self.name} ({reason}). Check your internet connection.") from None

    def error(self, status: int, raw: bytes) -> LLMError:
        try:
            body = json.loads(raw)
            err = body[0].get("error", {}) if isinstance(body, list) else body.get("error", {})
            if isinstance(err, str):
                err = {"message": err}
        except (ValueError, AttributeError, IndexError):
            err = {}
        message = str(err.get("message", ""))
        code = str(err.get("code", "") or err.get("status", ""))
        low = message.lower()
        name = self.name
        if status in (401, 403) and ("key" in low or code in ("invalid_api_key", "PERMISSION_DENIED")) or "api key not valid" in low:
            return LLMError(f"{name} didn't accept the API key. Check it in Settings (copy the whole key).")
        if status == 404 or code == "model_not_found" or "decommissioned" in low or "not found" in low:
            return LLMError(f"{name} doesn't have the model “{self.model}”. Pick another in Settings"
                            + (" (or download it with `ollama pull`)." if self.preset is PROVIDERS["ollama"] else "."))
        if "request too large" in low and ("per minute" in low or "tpm" in low or "otpm" in low):
            return TooMuch(f"That's more than {name} allows per minute on your plan. Fewer pages at a time can work.")
        if code == "json_validate_failed" and ("max completion tokens" in low or "truncated" in low):
            return TooMuch(f"{name} ran out of room before finishing its answer.")
        if status == 429:
            if "per day" in low or "tpd" in low or "rpd" in low or "daily" in low:
                return LLMError(f"You've used up today's {name} allowance. Try again tomorrow, or switch provider in Settings.")
            return LLMError(f"You've hit {name}'s rate limit. Wait a minute and try again.")
        if status == 413 or "too large" in low or "exceeds" in low:
            return LLMError(f"That's more than {name} takes in one go. Try fewer or smaller files.")
        if code == "json_validate_failed":
            return LLMError(f"{name}'s answer didn't come out in the right shape. Try again.")
        if status >= 500 or status == 498:
            return LLMError(f"{name} is having problems right now. Try again in a minute.")
        return LLMError(f"{name} said no: {message or status}")

    def _text(self, answer: dict) -> str:
        choices = answer.get("choices") or []
        if not choices:
            raise LLMError(f"{self.name} sent back nothing. Try again.")
        choice = choices[0]
        text = str((choice.get("message") or {}).get("content") or "")
        if choice.get("finish_reason") == "length":
            raise TooMuch(f"{self.name} ran out of room before finishing its answer.")
        if not text.strip():
            raise LLMError(f"{self.name} sent back nothing. Try again.")
        return text


def _lower_output(raw: bytes, current: int | None) -> int | None:
    """A shorter answer limit that fits a "Request too large" error's per-minute limit, or None if there's
    none that leaves room for a useful answer. Two kinds: output alone ("(OTPM): Limit 1000, Requested 1010"),
    or the prompt and the answer together ("(TPM): Limit 8000, Requested 9960")."""
    text = raw.decode(errors="replace")
    if current is None:
        return None
    m = re.search(r"output tokens per minute[^:]*:\s*Limit (\d+)", text)
    if m:
        new = int(int(m.group(1)) * 0.9)
    else:
        m = re.search(r"tokens per minute[^:]*:\s*Limit (\d+), Requested (\d+)", text)
        if not m:
            return None
        new = current - (int(m.group(2)) - int(m.group(1))) - 100
    return new if 300 <= new < current else None


def _retry_after(header: str | None, raw: bytes) -> float | None:
    """The wait the server asked for: a Retry-After header, or "try again in 7.5s" / "retryDelay": "7s"."""
    try:
        if header:
            return float(header)
    except ValueError:
        pass
    text = raw.decode(errors="replace")
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", text) or re.search(r'"retryDelay":\s*"(?:(\d+)m)?([\d.]+)s"', text)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return None


def chosen(prefs: dict) -> str:
    """The provider picked in Settings. Before there was a choice, StudyPal used Groq: someone with only a
    Groq key carries on with Groq rather than being asked for a Gemini key."""
    which = str(prefs.get("ai_provider") or "")
    if which in PROVIDERS:
        return which
    if prefs.get("groq_key") and not prefs.get("gemini_key") and not os.environ.get("GEMINI_API_KEY"):
        return "groq"
    return DEFAULT_PROVIDER


def provider_from(prefs: dict) -> OpenAICompatible:
    """The provider chosen in Settings, with its key: the environment variable first, then Settings."""
    which = chosen(prefs)
    preset = PROVIDERS[which]
    key = (os.environ.get(preset.key_env, "") if preset.key_env else "") or str(prefs.get(f"{which}_key") or "")
    if preset.key_env and not key.strip():
        raise LLMError(f"Add your {preset.name} API key in Settings first.")
    if which == "ollama":
        model = str(prefs.get("ollama_model") or "")
        return OpenAICompatible(preset, model=model, vision_model=model, base_url=str(prefs.get("ollama_url") or ""))
    # Groq's writing model could be picked in Settings before; that choice still counts.
    model = str(prefs.get("groq_model") or "") if which == "groq" else ""
    return OpenAICompatible(preset, key, model=model)
