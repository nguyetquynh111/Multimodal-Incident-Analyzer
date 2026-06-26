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
import re
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

def _llm_configured() -> bool:
    """Return whether an OpenRouter key is available for summary generation."""

    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


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

def _summary_fields_only(incident_row: dict) -> dict:
    """Return only the cleaned fields allowed to enter summary generation."""

    return {
        "source": incident_row.get("source", schemas.UNKNOWN),
        "event": incident_row.get("event", schemas.UNKNOWN),
        "location": incident_row.get("location", schemas.UNKNOWN),
        "time": incident_row.get("time", schemas.UNKNOWN),
        "severity": incident_row.get("severity", schemas.UNKNOWN),
    }


def _build_request(incident_row: dict, model: str) -> dict:
    """Assemble everything an ``llm_call`` needs, transport-agnostic."""

    summary_row = _summary_fields_only(incident_row)
    return {
        "model": model,
        "messages": prompts.build_messages(summary_row),
        "timeout": _timeout_seconds(),
    }


def _build_location_request(text: str, model: str) -> dict:
    """Assemble a focused image-OCR location extraction request."""

    return {
        "model": model,
        "messages": prompts.build_location_messages(text),
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
    """Reject empty, over-length, or non-prose model output.

    Raw/OCR text is removed before the summary request is built; the raw-text
    phrase check below is only a defense-in-depth guard against a model adding
    that wording on its own.
    """

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
    if re.search(r"\b(raw|ocr)\s+text\b|\braw_text\b|\btext\s+reads\b|\breads\s*:", stripped, re.IGNORECASE):
        return False
    return True


def _title_location(text: str) -> str:
    """Readable title-case for OCR locations, preserving common abbreviations."""

    titled = text.strip(" \t\r\n\"'`.,;:-").title()
    replacements = {
        " Us ": " US ",
        " Usa ": " USA ",
        " Hwy": " Highway",
        " Rd": " Road",
        " St": " Street",
        " Ave": " Avenue",
        " Blvd": " Boulevard",
        " Dr": " Drive",
        " Ln": " Lane",
        " Pkwy": " Parkway",
    }
    padded = f" {titled} "
    for old, new in replacements.items():
        padded = padded.replace(old, f" {new.strip()} ")
    return re.sub(r"\s+", " ", padded).strip()


def _looks_like_domain_or_source(text: str) -> bool:
    return bool(
        re.search(
            r"(?:https?://|www\.|\b[\w-]+\.(?:com|net|org|edu|gov|io|co|cn)\b)",
            text,
            re.IGNORECASE,
        )
    )


def _rule_based_location_from_text(text: str) -> str:
    """Extract obvious OCR locations without requiring an LLM call."""

    cleaned = re.sub(r"[_|]+", " ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or cleaned.casefold() in {"unknown", "none", "n/a"}:
        return schemas.UNKNOWN
    if _looks_like_domain_or_source(cleaned):
        return schemas.UNKNOWN

    # Addresses and named roads/highways are the most common useful image OCR
    # locations. Keep only the explicit road phrase and stop before OCR noise.
    road_suffixes = (
        "street|st|avenue|ave|road|rd|highway|hwy|boulevard|blvd|drive|dr|"
        "lane|ln|route|freeway|parkway|pkwy|way|court|ct|place|pl"
    )
    word = r"[A-Za-z][A-Za-z'.-]*"
    address_match = re.search(
        rf"\b(\d{{1,6}}\s+(?:{word}\s+){{1,5}}(?:{road_suffixes}))\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if address_match:
        return _title_location(address_match.group(1))

    road_match = re.search(
        rf"\b((?:{word}\s+){{1,5}}(?:{road_suffixes}))\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if road_match:
        return _title_location(road_match.group(1))

    county_match = re.search(
        rf"\b((?:{word}\s+){{1,4}}County)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if county_match:
        return _title_location(county_match.group(1))

    city_state_match = re.search(
        r"\b([A-Za-z][A-Za-z'. -]{1,60},\s*[A-Z]{2})\b",
        cleaned,
    )
    if city_state_match:
        return _title_location(city_state_match.group(1))

    return schemas.UNKNOWN


def _clean_location_output(text: str) -> str:
    """Validate and normalize one LLM-extracted location string."""

    if not isinstance(text, str):
        return schemas.UNKNOWN
    stripped = re.sub(r"\s+", " ", text).strip(" \t\r\n\"'`.,;:")
    if not stripped:
        return schemas.UNKNOWN
    if stripped.casefold() == schemas.UNKNOWN.casefold():
        return schemas.UNKNOWN
    if len(stripped) > 120:
        return schemas.UNKNOWN
    if "\n" in stripped or ";" in stripped:
        return schemas.UNKNOWN
    if _looks_like_domain_or_source(stripped):
        return schemas.UNKNOWN
    if not any(char.isalpha() for char in stripped):
        return schemas.UNKNOWN
    return _title_location(stripped)


# --- Public API --------------------------------------------------------------

def summarize_incident(
    incident_row: dict,
    *,
    llm_call: Optional[Callable[[dict], dict]] = None,
) -> dict:
    """Summarize one cleaned integrated incident row.

    Input keys expected (specs.md §7): source, source_type, event, location,
    time, severity, confidence. ``raw_text`` may be present on the row, but it
    is not included in the summary prompt.

    Returns exactly: incident_summary (str), summary_method
    ("llm" | "rule_based" | "disabled" | "error"), summary_model (str).

    ``llm_call`` is an injectable ``Callable[[request_dict], response_dict]``
    used in place of the real OpenRouter HTTP call (tests pass a fake).
    """

    summary_row = _summary_fields_only(incident_row)

    # No key means the deterministic fallback is the active summary path.
    if not _llm_configured():
        return fallback.summarize_fallback(
            summary_row,
            method=schemas.SUMMARY_METHOD_DISABLED,
            model=schemas.DISABLED_MODEL_LABEL,
        )

    model = _model_name()
    caller = llm_call or _default_llm_call

    # 2-5. Try the LLM; any error, timeout, or invalid output -> error fallback.
    try:
        response = caller(_build_request(summary_row, model))
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
            summary_row,
            method=schemas.SUMMARY_METHOD_ERROR,
            model=schemas.ERROR_MODEL_LABEL,
        )


def _extract_location_from_text(
    text: str,
    *,
    llm_call: Optional[Callable[[dict], dict]] = None,
) -> str:
    """Extract one explicit location from OCR text.

    The image Integration path should use the LLM when it is configured. Strict
    rule-based extraction remains as the fallback so demos still work when the
    LLM key is absent or the model returns an unusable answer.
    """

    cleaned_input = str(text or "").strip()
    if not cleaned_input or cleaned_input.casefold() in {"unknown", "none", "n/a"}:
        return schemas.UNKNOWN

    if _llm_configured() or llm_call is not None:
        model = _model_name()
        caller = llm_call or _default_llm_call
        try:
            location = _clean_location_output(_extract_text(caller(_build_location_request(cleaned_input, model))))
            if location != schemas.UNKNOWN:
                return location
        except Exception:
            pass

    return _rule_based_location_from_text(cleaned_input)


def update_image_location(
    image_row: dict,
    *,
    llm_call: Optional[Callable[[dict], dict]] = None,
) -> dict:
    """Return a copy of an image row with Location filled from OCR text when possible.

    This is the second public capability of this package. It is intentionally
    scoped to image drafts: it reads ``Text_Extracted``/``text_extracted`` and
    writes ``Location`` when that field is missing. It never changes event,
    time, severity, IDs, or summaries.
    """

    out = dict(image_row or {})
    existing = str(out.get("Location") or out.get("location") or "").strip()
    if existing and existing.casefold() not in {"unknown", "none", "n/a"}:
        return out

    text = out.get("Text_Extracted", out.get("text_extracted", ""))
    location = _extract_location_from_text(str(text or ""), llm_call=llm_call)
    if location != schemas.UNKNOWN:
        out["Location"] = location
    return out


__all__ = [
    "summarize_incident",
    "update_image_location",
    "OPENROUTER_URL",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_TIMEOUT_SECONDS",
]
