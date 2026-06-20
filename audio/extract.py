"""Rule-based incident, location, urgency, and sentiment extraction."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .config import LOCATION_LABELS, UNKNOWN


_INCIDENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "building fire",
        (r"\bfires?\b", r"\bsmokes?\b", r"\bburn(?:s|ed|ings?)?\b"),
    ),
    (
        "trapped person",
        (
            r"\btrapp(?:ed|ing)\b",
            r"\bstuck\b",
            r"\bsecond floors?\b",
            r"\bcannot get out\b",
        ),
    ),
    ("shooting", (r"\bguns?\b", r"\bshoot(?:s|ings?)?\b", r"\bshots?\b")),
    (
        "car accident",
        (r"\bcrash(?:es)?\b", r"\baccidents?\b", r"\bcollisions?\b"),
    ),
    (
        "medical emergency",
        (
            r"\bbleed(?:s|ings?)?\b",
            r"\bunconscious\b",
            r"\bnot breathing\b",
            r"\bheart attacks?\b",
        ),
    ),
    ("overdose", (r"\boverdoses?\b", r"\bdrugs?\b", r"\bpills?\b")),
    (
        "burglary/robbery",
        (
            r"\bbreak[ -]?ins?\b",
            r"\bburglar(?:y|ies)\b",
            r"\brobber(?:y|ies)\b",
            r"\brob(?:s|bed|bing)?\b",
            r"\bsteal(?:s|ing)?\b",
            r"\bstole(?:n)?\b",
        ),
    ),
    (
        "assault",
        (
            r"\bfight(?:s|ing)?\b",
            r"\bassault(?:s|ed|ing)?\b",
            r"\bhit(?:s|ting)?\b",
            r"\battack(?:s|ed|ing)?\b",
        ),
    ),
    ("missing person", (r"\bmissing\b", r"\bcannot find\b")),
)

_ADDRESS_PATTERN = re.compile(
    r"\b(?:\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){0,5}|"
    r"(?:[A-Z][A-Za-z0-9.'-]*\s+){1,5})"
    r"(?i:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Boulevard|Blvd\.?|Lane|Ln\.?)\b"
)
_PHRASE_LOCATION_PATTERN = re.compile(
    r"\b(?:at|near|on|inside)\s+(?:the\s+)?"
    r"([A-Za-z0-9][A-Za-z0-9'-]*(?:\s+[A-Za-z0-9][A-Za-z0-9'-]*){0,5}?)"
    r"(?=\s*(?:[,.;!?]|$|\b(?:and|where|with|while|but|at|near|on|inside)\b))",
    re.IGNORECASE,
)
_FLOOR_PATTERN = re.compile(r"\b(?:first|second|third) floors?\b", re.IGNORECASE)
_GENERIC_LOCATIONS = {"floor"}

_LIFE_THREATENING_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bnot breathing\b",
        r"\bunconscious\b",
        r"\btrapp(?:ed|ing)\b",
        r"\bfires?\b",
        r"\bguns?\b",
        r"\bshoot(?:s|ings?)?\b",
    )
)
_URGENT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bbleed(?:s|ings?)?\b",
        r"\bhelp me\b",
        r"\bhurry\b",
        r"\bemergenc(?:y|ies)\b",
        r"\bsmokes?\b",
    )
)


def _matches_any(transcript: str, patterns: Iterable[re.Pattern[str]]) -> bool:
    return any(pattern.search(transcript) for pattern in patterns)


def classify_incident(transcript: str) -> str:
    """Return the first incident label whose ordered keyword rule matches."""

    for label, patterns in _INCIDENT_PATTERNS:
        if any(re.search(pattern, transcript, re.IGNORECASE) for pattern in patterns):
            return label
    return "unknown emergency"


def extract_entities(transcript: str) -> list[dict[str, Any]]:
    """Extract location entities with regular expressions."""

    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(text: str, label: str) -> None:
        cleaned = text.strip(" ,.;")
        key = (cleaned.casefold(), label)
        if cleaned and cleaned.casefold() not in _GENERIC_LOCATIONS and key not in seen:
            seen.add(key)
            entities.append({"text": cleaned, "label": label, "score": 1.0})

    for match in _ADDRESS_PATTERN.finditer(transcript):
        add(match.group(0), "street address")
    for match in _FLOOR_PATTERN.finditer(transcript):
        add(match.group(0), "floor")
    for match in _PHRASE_LOCATION_PATTERN.finditer(transcript):
        add(match.group(1), "location")
    return entities


def extract_location(entities: Iterable[Mapping[str, Any]]) -> str:
    """Join unique location entities in extraction order."""

    locations: list[str] = []
    seen: set[str] = set()
    for entity in entities:
        if str(entity.get("label", "")).lower() not in LOCATION_LABELS:
            continue
        text = str(entity.get("text", "")).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            locations.append(text)
    return "; ".join(locations) if locations else UNKNOWN


def score_urgency(transcript: str) -> float:
    """Apply the additive urgency rules and return a score from 0.0 to 1.0."""

    score = 0.30
    if _matches_any(transcript, _LIFE_THREATENING_PATTERNS):
        score += 0.30
    if _matches_any(transcript, _URGENT_PATTERNS):
        score += 0.20
    if classify_incident(transcript) != "unknown emergency":
        score += 0.10
    return round(min(1.0, score), 2)


def sentiment_from_urgency(urgency_score: float) -> str:
    if urgency_score >= 0.65:
        return "Distressed"
    if urgency_score >= 0.40:
        return "Concerned"
    return "Calm"


def analyze_transcript(call_id: str, transcript: str) -> dict[str, Any]:
    """Convert one transcript into the exact six-field audio record."""

    cleaned = re.sub(r"\s+", " ", str(transcript or "")).strip() or UNKNOWN
    entities = extract_entities(cleaned)
    urgency_score = score_urgency(cleaned)
    return {
        "Call_ID": str(call_id),
        "Transcript": cleaned,
        "Extracted_Event": classify_incident(cleaned),
        "Location": extract_location(entities),
        "Sentiment": sentiment_from_urgency(urgency_score),
        "Urgency_Score": urgency_score,
    }


__all__ = [
    "analyze_transcript",
    "classify_incident",
    "extract_entities",
    "extract_location",
    "score_urgency",
    "sentiment_from_urgency",
]
