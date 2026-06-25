"""Public LLM summary API (tickets T-022/T-023/T-024).

``summarize_incident(incident_row)`` is the single entry point the platform
calls after Integration and before Supabase insert. It returns a short,
grounded ``incident_summary`` plus the ``summary_method``/``summary_model``
provenance fields.

Design mirrors ``pdf/processor.py``: the side-effecting dependency (here the
LLM HTTP call) is injectable via ``llm_call=`` so tests exercise every branch
-- success, network failure, invalid output -- without a real API key or any
network access. The default caller uses OpenRouter's free tier and is the only
code that imports ``requests``, kept inside the function so importing this
module never requires it.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from . import fallback, prompts, schemas


# OpenRouter is OpenAI-compatible. Any ":free" model works here; the default is
# a small, fast free-tier instruct model verified against OpenRouter's live API
# (clean prose, no fabrication, within length limits). Override with the
# LLM_MODEL_NAME env var (e.g. "mistralai/mistral-7b-instruct:free").
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL_NAME = "openai/gpt-oss-20b:free"
DEFAULT_TIMEOUT_SECONDS = 6.0


# --- Environment helpers -----------------------------------------------------

def _llm_enabled() -> bool:
    """LLM runs only when explicitly enabled and a key is present."""

    if os.getenv("ENABLE_LLM_SUMMARY", "").strip().lower() != "true":
        return False
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        return False
    return True


def _model_name() -> str:
    return os.getenv("LLM_MODEL_NAME", "").strip() or DEFAULT_MODEL_NAME


def _timeout_seconds() -> float:
    raw = os.getenv("LLM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


# --- LLM call + response handling --------------------------------------------

def _build_request(incident_row: dict, model: str) -> dict:
    """Assemble everything an ``llm_call`` needs, transport-agnostic."""

    return {
        "model": model,
        "messages": prompts.build_messages(incident_row),
        "timeout": _timeout_seconds(),
    }


def _default_llm_call(request: dict) -> dict:
    """Post the chat-completion request to OpenRouter and return parsed JSON."""

    import requests  # local import: only the real network path needs it

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": request["model"], "messages": request["messages"]}
    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=request["timeout"],
    )
    response.raise_for_status()
    return response.json()


def _extract_text(response: dict) -> str:
    """Pull the assistant message text out of an OpenAI-style response."""

    if not isinstance(response, dict):
        return ""
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _is_valid_summary(text: str) -> bool:
    """Reject empty, absurdly long, over-length, or non-prose model output."""

    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > schemas.MAX_SUMMARY_CHARS:
        return False
    words = stripped.split()
    if not words or len(words) > schemas.MAX_SUMMARY_WORDS:
        return False
    if not any(char.isalpha() for char in stripped):
        return False
    return True


# --- Public API --------------------------------------------------------------

def summarize_incident(
    incident_row: dict,
    *,
    llm_call: Optional[Callable[[dict], dict]] = None,
) -> dict:
    """Summarize one cleaned integrated incident row.

    Input keys expected (specs.md §7): source, source_type, event, location,
    time, severity, confidence, raw_text.

    Returns exactly: incident_summary (str), summary_method
    ("llm" | "rule_based" | "disabled" | "error"), summary_model (str).

    ``llm_call`` is an injectable ``Callable[[request_dict], response_dict]``
    used in place of the real OpenRouter HTTP call (tests pass a fake).
    """

    # 1. Disabled or no key -> skip the call entirely, deterministic fallback.
    if not _llm_enabled():
        return fallback.summarize_fallback(
            incident_row,
            method=schemas.SUMMARY_METHOD_DISABLED,
            model=schemas.DISABLED_MODEL_LABEL,
        )

    model = _model_name()
    caller = llm_call or _default_llm_call

    # 2-5. Try the LLM; any error, timeout, or invalid output -> error fallback.
    try:
        response = caller(_build_request(incident_row, model))
        summary = _extract_text(response).strip()
        if not _is_valid_summary(summary):
            raise ValueError("LLM output failed validation")
        return {
            "incident_summary": summary,
            "summary_method": schemas.SUMMARY_METHOD_LLM,
            "summary_model": model,
        }
    except Exception:
        return fallback.summarize_fallback(
            incident_row,
            method=schemas.SUMMARY_METHOD_ERROR,
            model=schemas.ERROR_MODEL_LABEL,
        )


__all__ = [
    "summarize_incident",
    "OPENROUTER_URL",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_TIMEOUT_SECONDS",
]
