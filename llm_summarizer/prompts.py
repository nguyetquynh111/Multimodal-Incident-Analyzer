"""Prompt template for the LLM summary (rules.md section 6, specs.md section 7).

The prompt is deliberately strict: the model may only narrate the fields it is
given, must never invent details, and must keep the summary short. It returns
plain chat-completion messages so ``summarizer.py`` can post them to any
OpenAI-compatible endpoint (OpenRouter here).
"""

from __future__ import annotations

from . import schemas


# OCR text can be long; only a leading window is needed for focused image
# location extraction, and it keeps the request small/fast for a free-tier model.
_RAW_TEXT_LIMIT = 1000


SYSTEM_PROMPT = (
    "You are a careful incident-report summarizer for a class prototype "
    "dashboard. Follow these rules strictly:\n"
    "- Summarize ONLY using the provided event, location, time, severity, "
    "and source fields.\n"
    "- Never invent people, places, weapons, dates, or outcomes that are not "
    "present in those fields.\n"
    "- If a detail is missing or 'Unknown', write 'Unknown' or omit it -- "
    "never guess.\n"
    "- Do not restate or change the event, location, time, or severity "
    "values; only narrate them in plain prose.\n"
    "- Write 1 to 3 sentences, fewer than 80 words.\n"
    "- Output only the summary text, with no preamble, labels, or quotes."
)

LOCATION_EXTRACTION_SYSTEM_PROMPT = (
    "You extract explicit locations from OCR text for an incident-analysis "
    "prototype. Follow these rules strictly:\n"
    "- Return a location only if the text clearly contains a place, address, "
    "facility, city, county, street, intersection, landmark, or venue.\n"
    "- Do not treat publisher names, website domains, usernames, slogans, "
    "or decorative captions as locations.\n"
    "- Use only words present in the OCR text; do not guess or infer.\n"
    "- If no explicit location is present, return exactly Unknown.\n"
    "- Output only the location string or Unknown, with no explanation."
)


def _field(incident_row: dict, key: str) -> str:
    value = incident_row.get(key, schemas.UNKNOWN)
    text = str(value).strip() if value is not None else ""
    return text or schemas.UNKNOWN


def build_user_prompt(incident_row: dict) -> str:
    """Render only cleaned integrated fields for the summary model."""

    lines = [
        "Summarize the following incident using only these fields:",
        f"- source: {_field(incident_row, 'source')}",
        f"- event: {_field(incident_row, 'event')}",
        f"- location: {_field(incident_row, 'location')}",
        f"- time: {_field(incident_row, 'time')}",
        f"- severity: {_field(incident_row, 'severity')}",
    ]
    return "\n".join(lines)


def build_messages(incident_row: dict) -> list[dict]:
    """Build the chat-completion messages for the summary request."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(incident_row)},
    ]


def build_location_prompt(text: str) -> str:
    """Render image OCR text for a focused location-extraction request."""

    text = str(text or "").strip()
    if len(text) > _RAW_TEXT_LIMIT:
        text = text[:_RAW_TEXT_LIMIT].rstrip() + "..."
    return "\n".join(
        [
            "Extract one explicit location from this image OCR text.",
            "Return exactly Unknown if it does not contain a location.",
            f"OCR text: {text or schemas.UNKNOWN}",
        ]
    )


def build_location_messages(text: str) -> list[dict]:
    """Build chat-completion messages for image OCR location extraction."""

    return [
        {"role": "system", "content": LOCATION_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": build_location_prompt(text)},
    ]


__all__ = [
    "SYSTEM_PROMPT",
    "LOCATION_EXTRACTION_SYSTEM_PROMPT",
    "build_user_prompt",
    "build_messages",
    "build_location_prompt",
    "build_location_messages",
]
