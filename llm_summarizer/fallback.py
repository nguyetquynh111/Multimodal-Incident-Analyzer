"""Deterministic, dependency-free rule-based summary (rules.md section 6).

This is the always-available fallback used whenever the LLM is disabled,
unavailable, slow, or produces invalid output. It performs no network calls,
imports nothing heavy, and never raises -- even when every field is
``Unknown`` (which is exactly the shape the PDF processor emits for a
document with no extractable signals).
"""

from __future__ import annotations

from typing import Any

from . import schemas


_SUMMARY_FIELDS = ("severity", "event", "location", "time", "source")


def _clean(value: Any) -> str:
    """Return a stripped field value, or ``Unknown`` when missing/empty."""

    text = str(value).strip() if value is not None else ""
    return text or schemas.UNKNOWN


def _is_known(value: str) -> bool:
    """A field carries real information only when it is set and not Unknown."""

    return value != schemas.UNKNOWN


def _article(word: str) -> str:
    """Pick ``a``/``an`` for the leading descriptor word (cosmetic only)."""

    return "an" if word[:1].lower() in "aeiou" else "a"


def build_summary_text(incident_row: dict) -> str:
    """Build a grounded 1-2 sentence summary from the integrated fields.

    Only ``event``, ``location``, ``time``, ``severity``, and ``source`` are
    used; nothing is invented and missing fields are simply omitted rather
    than guessed. Always returns a non-empty string.
    """

    severity = _clean(incident_row.get("severity"))
    event = _clean(incident_row.get("event"))
    location = _clean(incident_row.get("location"))
    time = _clean(incident_row.get("time"))
    source = _clean(incident_row.get("source"))

    # Core noun phrase: "<severity>-severity <event>" with each part dropped
    # when it is Unknown, e.g. "High-severity Theft / Robbery" or just "event".
    descriptor_parts = []
    if _is_known(severity):
        descriptor_parts.append(f"{severity}-severity")
    if _is_known(event):
        descriptor_parts.append(event)

    if descriptor_parts:
        descriptor = " ".join(descriptor_parts)
        sentence = f"{_article(descriptor).capitalize()} {descriptor} incident was reported"
    else:
        sentence = "An incident was reported"

    if _is_known(source):
        sentence += f" via {source}"
    if _is_known(location):
        sentence += f" at {location}"
    sentence += "."

    if _is_known(time):
        sentence += f" The reported time was {time}."

    return sentence


def summarize_fallback(
    incident_row: dict,
    *,
    method: str = schemas.SUMMARY_METHOD_RULE_BASED,
    model: str = schemas.RULE_BASED_MODEL_LABEL,
) -> dict:
    """Return the full summary contract using the deterministic builder.

    Defaults to ``rule_based``; ``summarizer.py`` reuses the same text for the
    ``disabled`` and ``error`` cases by passing a different ``method``/``model``.
    """

    return {
        "incident_summary": build_summary_text(incident_row),
        "summary_method": method,
        "summary_model": model,
    }


__all__ = ["build_summary_text", "summarize_fallback"]
