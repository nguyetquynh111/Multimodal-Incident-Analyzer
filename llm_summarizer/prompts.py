"""Prompt template for the LLM summary (rules.md section 6, specs.md section 7).

The prompt is deliberately strict: the model may only narrate the fields it is
given, must never invent details, and must keep the summary short. It returns
plain chat-completion messages so ``summarizer.py`` can post them to any
OpenAI-compatible endpoint (OpenRouter here).
"""

from __future__ import annotations

from . import schemas


# Raw text can be long; only a leading window is needed for grounding context
# and it keeps the request small/fast for a free-tier model.
_RAW_TEXT_LIMIT = 1000


SYSTEM_PROMPT = (
    "You are a careful incident-report summarizer for a class prototype "
    "dashboard. Follow these rules strictly:\n"
    "- Summarize ONLY using the provided event, location, time, severity, "
    "source, and raw_text fields.\n"
    "- Never invent people, places, weapons, dates, or outcomes that are not "
    "present in those fields.\n"
    "- If a detail is missing or 'Unknown', write 'Unknown' or omit it -- "
    "never guess.\n"
    "- Do not restate or change the event, location, time, or severity "
    "values; only narrate them in plain prose.\n"
    "- Write 1 to 3 sentences, fewer than 80 words.\n"
    "- Output only the summary text, with no preamble, labels, or quotes."
)


def _field(incident_row: dict, key: str) -> str:
    value = incident_row.get(key, schemas.UNKNOWN)
    text = str(value).strip() if value is not None else ""
    return text or schemas.UNKNOWN


def build_user_prompt(incident_row: dict) -> str:
    """Render the integrated fields as a labelled block for the model."""

    raw_text = _field(incident_row, "raw_text")
    if len(raw_text) > _RAW_TEXT_LIMIT:
        raw_text = raw_text[:_RAW_TEXT_LIMIT].rstrip() + "..."

    lines = [
        "Summarize the following incident using only these fields:",
        f"- source: {_field(incident_row, 'source')}",
        f"- event: {_field(incident_row, 'event')}",
        f"- location: {_field(incident_row, 'location')}",
        f"- time: {_field(incident_row, 'time')}",
        f"- severity: {_field(incident_row, 'severity')}",
        f"- raw_text: {raw_text}",
    ]
    return "\n".join(lines)


def build_messages(incident_row: dict) -> list[dict]:
    """Build the chat-completion messages for the summary request."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(incident_row)},
    ]


__all__ = ["SYSTEM_PROMPT", "build_user_prompt", "build_messages"]
