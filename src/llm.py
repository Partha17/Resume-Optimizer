"""Gemini 2.0 Flash wrapper with structured output, retries, and graceful degradation.

The pipeline tolerates a missing GEMINI_API_KEY by skipping LLM-only steps and
returning sensible fallbacks. This lets users smoke-test the JD-fetching and
ranking layers without paying or signing up.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

load_dotenv()

_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

_genai = None
_model = None


def _lazy_init() -> bool:
    """Import google-generativeai only if a key is configured. Returns True on success."""
    global _genai, _model
    if _model is not None:
        return True
    if not _API_KEY or _API_KEY.startswith("your_"):
        return False
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=_API_KEY)
    _genai = genai
    _model = genai.GenerativeModel(_MODEL_NAME)
    return True


def is_available() -> bool:
    """Whether Gemini is configured. Modules use this to choose fallbacks."""
    return bool(_API_KEY) and not _API_KEY.startswith("your_")


class LLMError(RuntimeError):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(LLMError),
)
def _call(prompt: str, *, temperature: float = 0.3, response_mime_type: str | None = None) -> str:
    """Single Gemini call with retry on transient failures."""
    if not _lazy_init():
        raise LLMError("Gemini not configured (set GEMINI_API_KEY)")

    cfg: dict[str, Any] = {"temperature": temperature}
    if response_mime_type:
        cfg["response_mime_type"] = response_mime_type

    try:
        resp = _model.generate_content(prompt, generation_config=cfg)  # type: ignore[union-attr]
    except Exception as e:  # network, 429, 5xx, etc.
        raise LLMError(f"Gemini request failed: {e}") from e

    # Gemini sometimes returns no text on safety filter trips
    text = getattr(resp, "text", None)
    if not text:
        try:
            text = resp.candidates[0].content.parts[0].text  # type: ignore[union-attr,index]
        except Exception:
            text = ""
    if not text:
        raise LLMError("Empty response from Gemini")
    return text


def complete(prompt: str, *, temperature: float = 0.3) -> str:
    """Plain text completion."""
    return _call(prompt, temperature=temperature)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def complete_json(prompt: str, *, temperature: float = 0.2) -> Any:
    """JSON completion with fence-stripping and one repair attempt.

    We instruct the model to return JSON via mime type, but Gemini still
    occasionally returns markdown fences or trailing prose, so we defensively
    parse.
    """
    raw = _call(prompt, temperature=temperature, response_mime_type="application/json")
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Repair attempt: ask the model to fix only the JSON
    repair_prompt = (
        "The following text should be valid JSON but is not. "
        "Return ONLY the corrected JSON, no prose, no fences.\n\n"
        f"{cleaned}"
    )
    raw2 = _call(repair_prompt, temperature=0.0, response_mime_type="application/json")
    cleaned2 = _strip_fences(raw2)
    return json.loads(cleaned2)


def load_prompt(name: str, **kwargs: Any) -> str:
    """Load a markdown prompt template from prompts/ and substitute {placeholders}.

    Templates use plain `str.format` substitution; literal braces must be doubled
    `{{like this}}`. We deliberately avoid Jinja to keep prompts easy to read.
    """
    here = Path(__file__).resolve().parent.parent
    path = here / "prompts" / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    template = path.read_text(encoding="utf-8")
    if not kwargs:
        return template
    return template.format(**kwargs)


def throttle(seconds: float = 0.5) -> None:
    """Tiny sleep helper to keep us under Gemini free-tier RPM ceilings during batches."""
    time.sleep(seconds)
