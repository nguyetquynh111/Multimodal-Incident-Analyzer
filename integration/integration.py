"""Integration utilities for the documented multimodal incident pipeline.

``integrate_records`` is the public in-memory workflow: it standardizes one
extractor DataFrame, calls the separate summary module, assigns IDs, and returns
the seven documented display fields. Supabase conversion remains at the cloud
boundary and the final CSV is derived from Supabase rows.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"

# Public integration output column order.
INCIDENT_COLUMNS: tuple[str, ...] = (
    "Incident_ID",
    "Source",
    "Event",
    "Location",
    "Time",
    "Severity",
    "Incident_Summary",
)
INTEGRATION_OUTPUT_COLUMNS = INCIDENT_COLUMNS

# App-owned Supabase payload column order (lower-case). Mirrors validators.INCIDENT_COLUMNS.
SUPABASE_PAYLOAD_COLUMNS: tuple[str, ...] = (
    "incident_id",
    "source",
    "event",
    "location",
    "time",
    "severity",
    "incident_summary",
)

INTEGRATION_COLUMNS: tuple[str, ...] = (
    "source",
    "event",
    "location",
    "time",
    "severity",
    "source_filename",
    "source_type",
    "confidence",
    "raw_text",
)

# Columns required by the dashboard/export contract.
FINAL_CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "created_at",
    "incident_id",
    "source",
    "event",
    "location",
    "time",
    "severity",
    "incident_summary",
)

_SUPABASE_ALIASES: dict[str, tuple[str, ...]] = {
    "incident_id": ("incident_id", "Incident_ID"),
    "source": ("source", "Source"),
    "event": ("event", "Event"),
    "location": ("location", "Location"),
    "time": ("time", "Time"),
    "severity": ("severity", "Severity"),
    "incident_summary": ("incident_summary", "Incident_Summary"),
}

# One canonical record per modality: human-readable source label + ID type.
MODALITIES: dict[str, dict[str, Any]] = {
    "audio": {"label": "Audio", "prefix": "AUD", "extensions": {".wav", ".mp3", ".m4a"}},
    "pdf": {"label": "PDF", "prefix": "PDF", "extensions": {".pdf"}},
    "image": {"label": "Image", "prefix": "IMG", "extensions": {".jpg", ".jpeg", ".png"}},
    "video": {"label": "Video", "prefix": "VID", "extensions": {".mp4", ".mov", ".mpg", ".mpeg"}},
    "text": {"label": "Text", "prefix": "TXT", "extensions": {".txt", ".csv"}},
}

ID_PATTERN = re.compile(r"^INC_([A-Z]+)_(\d{3,})$")

def _to_float(value: Any) -> float | None:
    """Best-effort float conversion; returns ``None`` for blanks/non-numbers."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


SEVERITY_LEVELS: tuple[str, ...] = ("Low", "Medium", "High", "Unknown")
# score < LOW_MAX -> Low, score < MEDIUM_MAX -> Medium, else High (score on 0-10).
SEVERITY_LOW_MAX = 3.0
SEVERITY_MEDIUM_MAX = 7.0
DEFAULT_SEVERITY = "Unknown"


# --------------------------------------------------------------------------- #
# File-type detection
# --------------------------------------------------------------------------- #
def detect_source_type(filename: str | Path) -> str | None:
    """Return the modality key for a filename, or ``None`` if unsupported."""
    suffix = Path(str(filename)).suffix.lower()
    for source_type, meta in MODALITIES.items():
        if suffix in meta["extensions"]:
            return source_type
    return None


def supported_extensions() -> list[str]:
    """Return every supported file extension, for the Streamlit uploader."""
    return sorted(ext.lstrip(".") for meta in MODALITIES.values() for ext in meta["extensions"])


def source_label(source_type: str) -> str:
    """Human-readable Source value, e.g. ``audio`` -> ``Audio``."""
    return MODALITIES[normalize_source_type(source_type)]["label"]


def source_prefix(source_type: str) -> str:
    """Incident-ID prefix, e.g. ``audio`` -> ``AUD``."""
    return MODALITIES[normalize_source_type(source_type)]["prefix"]


def normalize_source_type(source_type: str) -> str:
    """Accept either code keys (``pdf``) or documented types (``PDF``)."""

    candidate = str(source_type).strip()
    if candidate.casefold() == "csv":
        return "text"
    if candidate in MODALITIES:
        return candidate
    upper = candidate.upper()
    for key, meta in MODALITIES.items():
        if meta["prefix"] == upper or meta["label"].casefold() == candidate.casefold():
            return key
    raise ValueError(f"Unsupported source_type {source_type!r}.")


# --------------------------------------------------------------------------- #
# Severity
# --------------------------------------------------------------------------- #
def severity_from_confidence(confidence: Any) -> str:
    """Map a 0-1 confidence/urgency value to Low / Medium / High.

    Uses ``score = confidence * 10`` with the documented thresholds. Invalid or
    missing values fall back to ``Unknown``.
    """
    score = _to_float(confidence)
    if score is None:
        return DEFAULT_SEVERITY
    # Accept either a 0-1 confidence or an already-scaled 0-10 score.
    score_10 = score * 10 if score <= 1.0 else score
    if score_10 < SEVERITY_LOW_MAX:
        return "Low"
    if score_10 < SEVERITY_MEDIUM_MAX:
        return "Medium"
    return "High"


# --------------------------------------------------------------------------- #
# Draft -> final mapping (one mapper per modality)
# --------------------------------------------------------------------------- #
def _clean(value: Any) -> str:
    """Normalise a single field to a non-empty display string."""
    if value is None:
        return UNKNOWN
    try:
        if pd.isna(value):
            return UNKNOWN
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else UNKNOWN


def normalize_severity(value: Any) -> str:
    """Return one documented severity label, defaulting to ``Unknown``."""

    text = _clean(value).title()
    return text if text in SEVERITY_LEVELS else UNKNOWN


def _severity_from_event(event: str, current: str) -> str:
    """Apply documented event safety rules without downgrading evidence."""

    normalized = normalize_severity(current)
    if event == UNKNOWN:
        # An unknown event is explicitly treated as the lowest-risk fallback.
        # Do this before preserving an upstream severity so a stale or inferred
        # High/Medium value cannot contradict the normalized event.
        return "Low"
    text = event.casefold()
    if text in {"other", "no activity"}:
        return "Low"
    if any(token in text for token in (
        "fire", "arson", "assault", "violence", "weapon", "gun", "knife",
        "trapped", "collapse", "collapsing", "fight", "altercation",
        "severe crash",
    )):
        return "High"
    if any(token in text for token in (
        "theft", "robbery", "burglary", "disturbance", "property damage",
    )):
        return "High" if normalized == "High" else "Medium"
    if normalized != UNKNOWN:
        return normalized
    return "Low"


def normalize_event(value: Any) -> str:
    """Return one consistent, title-cased event label.

    Missing values and labels beginning with ``unknown`` collapse to the
    single canonical label ``Unknown``. Separators are spaced for display.
    """

    text = _clean(value)
    if text == UNKNOWN or re.match(r"^unknown(?:\b|[_/-])", text, re.IGNORECASE):
        return UNKNOWN
    text = re.sub(r"\s*/\s*", " / ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.title()


def _first_known(row: Mapping[str, Any], *columns: str) -> str:
    """Return the first populated, non-Unknown value from candidate columns."""

    for column in columns:
        value = _clean(row.get(column))
        if value.casefold() != UNKNOWN.casefold():
            return value
    return UNKNOWN


def _text_entity_group(entities: Any, *labels: str) -> str:
    """Extract one label group from text ``Entities`` values.

    Student 5 stores entities as semicolon-delimited groups such as
    ``LOCATION: Oak Street; DATE: 9pm tonight``. Older/simple outputs may store
    only a plain location string, so callers can still fall back to the raw
    ``Entities`` field when no labeled group is present.
    """

    text = _clean(entities)
    if text == UNKNOWN:
        return UNKNOWN
    wanted = {label.upper() for label in labels}
    values: list[str] = []
    for match in re.finditer(r"(?:^|;\s*)([A-Za-z_ ]+):\s*([^;]+)", text):
        label = match.group(1).strip().upper().replace("_", " ")
        if label in wanted:
            value = _clean(match.group(2))
            if value != UNKNOWN:
                values.append(value)
    return ", ".join(values) if values else UNKNOWN


def _mapped_severity(
    row: Mapping[str, Any],
    *,
    explicit: tuple[str, ...] = (),
    confidence: tuple[str, ...] = (),
    default: str = DEFAULT_SEVERITY,
) -> str:
    """Prefer a valid explicit severity, then derive one from confidence."""

    value = _first_known(row, *explicit)
    canonical = normalize_severity(value)
    if canonical != UNKNOWN:
        return canonical
    score = _first_known(row, *confidence)
    return severity_from_confidence(score) if score != UNKNOWN else default


def _map_audio(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": normalize_event(_first_known(row, "Extracted_Event")),
        "location": _first_known(row, "Location"),
        "time": _first_known(row, "Time", "Timestamp"),
        "confidence": _confidence(row, "Urgency_Score"),
        "raw_text": _first_known(row, "Transcript"),
        "severity": _mapped_severity(
            row,
            explicit=("Severity",),
            confidence=("Urgency_Score",),
        ),
    }


def _map_pdf(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_text_parts = [
        _first_known(row, "Summary"),
        _first_known(row, "Suspect_Description"),
        _first_known(row, "Outcome"),
    ]
    raw_text = " | ".join(part for part in raw_text_parts if part != UNKNOWN) or UNKNOWN
    return {
        "event": normalize_event(_first_known(row, "Incident_Type")),
        "location": _first_known(row, "Location"),
        "time": _first_known(row, "Date"),
        "confidence": _confidence(row, "Confidence", default=0.0),
        "raw_text": raw_text,
        "severity": _mapped_severity(
            row,
            explicit=("Severity",),
            confidence=("Confidence",),
        ),
    }


def update_image_location_with_llm(row: Mapping[str, Any]) -> dict[str, Any]:
    """Use llm_summarizer's image helper to fill Location from OCR text."""

    try:
        from llm_summarizer.summarizer import update_image_location

        return update_image_location(dict(row))
    except Exception as exc:  # noqa: BLE001
        logger.info("Image OCR location update skipped: %s", type(exc).__name__)
        return dict(row)


def _map_image(row: Mapping[str, Any]) -> dict[str, Any]:
    def image_value(value: Any) -> str:
        """Treat image-artifact placeholders as missing Integration evidence."""

        cleaned = _clean(value)
        return UNKNOWN if cleaned.casefold() in {"none", "n/a"} else cleaned

    row = update_image_location_with_llm(row)
    event = normalize_event(image_value(row.get("Scene_Type")))
    objects = image_value(row.get("Objects_Detected"))
    if event == UNKNOWN and objects != UNKNOWN:
        event = normalize_event(objects)
    text = image_value(row.get("Text_Extracted"))
    raw_text = text if text != UNKNOWN else objects
    location = _first_known(row, "Location")
    return {
        "event": event,
        "location": location,
        "time": _first_known(row, "Time", "Timestamp"),
        "confidence": _confidence(row, "Confidence_Score"),
        "raw_text": raw_text,
        "severity": _mapped_severity(
            row,
            explicit=("Severity",),
            confidence=("Confidence_Score",),
        ),
    }


def _map_video(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": normalize_event(_first_known(row, "Event_Detected")),
        "location": _first_known(row, "Location"),
        "time": _first_known(row, "Timestamp"),
        "confidence": _confidence(row, "Confidence"),
        "raw_text": _first_known(row, "Objects", "Event_Detected"),
        "severity": _mapped_severity(
            row,
            explicit=("Severity",),
            confidence=("Confidence",),
        ),
    }


def _map_text(row: Mapping[str, Any]) -> dict[str, Any]:
    if _looks_like_structured_text(row):
        return _map_structured(row)

    entities = row.get("Entities")
    location = _first_known(row, "Location")
    if location == UNKNOWN:
        location = _text_entity_group(entities, "LOCATION", "LOC", "GPE", "FAC")
    if location == UNKNOWN:
        location = _first_known(row, "Entities")

    time = _first_known(row, "Time", "Timestamp")
    if time == UNKNOWN:
        time = _text_entity_group(entities, "DATE", "TIME")

    return {
        "event": normalize_event(_first_known(row, "Topic")),
        "location": location,
        "time": time,
        "confidence": _confidence(row, "Confidence", default=0.0),
        "raw_text": _first_known(row, "Raw_Text"),
        "severity": _mapped_severity(
            row,
            explicit=("Severity",),
            confidence=("Confidence",),
        ),
    }


def _confidence(row: Mapping[str, Any], *columns: str, default: float = 0.0) -> float:
    value = _first_known(row, *columns)
    score = _to_float(value)
    if score is None:
        return default
    return max(0.0, min(1.0, score if score <= 1.0 else score / 10.0))


def _map_structured(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map CSV records that already carry incident-like fields."""

    raw_text = _first_known(
        row,
        "raw_text",
        "Raw_Text",
        "summary",
        "Summary",
        "description",
        "Description",
        "details",
        "Details",
        "text",
        "Text",
    )
    if raw_text == UNKNOWN:
        raw_text = str(dict(row))
    return {
        "event": normalize_event(
            _first_known(row, "event", "Event", "incident_type", "Incident_Type", "type", "Type", "category", "Category")
        ),
        "location": _first_known(row, "location", "Location", "place", "Place", "address", "Address"),
        "time": _first_known(row, "time", "Time", "date", "Date", "timestamp", "Timestamp", "created_at", "Created_At"),
        "confidence": _confidence(row, "confidence", "Confidence", "score", "Score"),
        "raw_text": raw_text,
        "severity": _mapped_severity(row, explicit=("severity", "Severity"), confidence=("confidence", "Confidence")),
    }


_STRUCTURED_TEXT_COLUMNS = {
    "event",
    "Event",
    "incident_type",
    "Incident_Type",
    "location",
    "Location",
    "time",
    "Time",
    "date",
    "Date",
    "severity",
    "Severity",
}


def _looks_like_structured_text(row: Mapping[str, Any]) -> bool:
    """Return true for CSV text inputs that already carry incident fields."""

    return any(column in row for column in _STRUCTURED_TEXT_COLUMNS)


def _looks_like_structured_text_frame(frame: pd.DataFrame) -> bool:
    return any(column in frame.columns for column in _STRUCTURED_TEXT_COLUMNS)


_MAPPERS = {
    "audio": _map_audio,
    "pdf": _map_pdf,
    "image": _map_image,
    "video": _map_video,
    "text": _map_text,
}


def _standardize_records(
    draft_df: pd.DataFrame,
    source_type: str,
    *,
    source_filename: str | None = None,
) -> pd.DataFrame:
    """Normalize one modality draft into internal standardized records."""

    source_type = normalize_source_type(source_type)
    if not isinstance(draft_df, pd.DataFrame):
        raise TypeError("draft_df must be a pandas DataFrame.")

    label = source_label(source_type)
    mapper = _MAPPERS[source_type]
    source_code = source_prefix(source_type)
    filename = source_filename or UNKNOWN
    rows = []
    for record in draft_df.to_dict("records"):
        mapped = mapper(record)
        event = mapped["event"]
        rows.append(
            {
                "source": label,
                "event": event,
                "location": mapped["location"],
                "time": mapped["time"],
                "severity": _severity_from_event(event, mapped["severity"]),
                "source_filename": _first_known(record, "source_filename", "Source_Filename") if source_filename is None else filename,
                "source_type": source_code,
                "confidence": mapped.get("confidence", 0.0),
                "raw_text": mapped.get("raw_text", UNKNOWN),
            }
        )
    return pd.DataFrame(rows, columns=list(INTEGRATION_COLUMNS))


def integrate_records(
    draft_df: pd.DataFrame,
    source_type: str,
    existing_ids: Iterable[Any] = (),
    *,
    source_filename: str | None = None,
) -> pd.DataFrame:
    """Run the documented Integration workflow and return final incident rows.

    Args:
        draft_df: The DataFrame returned by a modality processor.
        source_type: One of ``audio, pdf, image, video, text``. CSV files are
            structured text inputs and normalize to ``text``.
        existing_ids: Current Supabase incident IDs used to avoid collisions.

    Returns:
        ``Incident_ID, Source, Event, Location, Time, Severity,
        Incident_Summary`` in documented order.
    """
    standardized = _standardize_records(
        draft_df, source_type, source_filename=source_filename
    )
    return _finalize_records(standardized, existing_ids)


# --------------------------------------------------------------------------- #
# Incident-ID assignment. Rows store the documented INC_TYPE_NUMBER string.
# --------------------------------------------------------------------------- #
_PREFIX_BY_LABEL = {meta["label"]: meta["prefix"] for meta in MODALITIES.values()}


def _source_type_from_row(row: Mapping[str, Any]) -> str:
    value = row.get("source_type")
    if value and _clean(value) != UNKNOWN:
        return normalize_source_type(str(value))
    return normalize_source_type(str(row.get("source", "")))


def next_incident_number(existing_ids: Iterable[Any], source_type: str | None = None) -> int:
    """Return the next number, optionally scoped to one source type."""

    source_key = normalize_source_type(source_type) if source_type is not None else None
    source_code = source_prefix(source_key) if source_key else None
    highest = 0
    for value in existing_ids:
        text = str(value or "").strip()
        match = ID_PATTERN.match(text)
        if match:
            if source_code is None or match.group(1) == source_code:
                highest = max(highest, int(match.group(2)))
    return highest + 1


def generate_incident_id(source_type: str, number: int) -> str:
    """Format one documented incident ID."""

    return f"INC_{source_prefix(normalize_source_type(source_type))}_{number:03d}"


def generate_next_incident_id(source_type: str, existing_ids: Iterable[Any] = ()) -> str:
    """Return the next ``INC_TYPE_NUMBER`` ID for one source type."""

    return generate_incident_id(source_type, next_incident_number(existing_ids, source_type))


def assign_incident_ids(df: pd.DataFrame, existing_ids: Iterable[Any] = ()) -> pd.DataFrame:
    """Prepend documented incident IDs, incrementing independently by source type."""

    out = df.copy()
    counters = {
        source_type: next_incident_number(existing_ids, source_type) - 1
        for source_type in MODALITIES
    }
    incident_ids = []
    for row in out.to_dict("records"):
        source_type = _source_type_from_row(row)
        counters[source_type] += 1
        incident_ids.append(generate_incident_id(source_type, counters[source_type]))
    out.insert(0, "incident_id", incident_ids)
    return out


def add_incident_summaries(df: pd.DataFrame) -> pd.DataFrame:
    """Call the separate summarizer for every integrated row."""

    if df.empty:
        out = df.copy()
        out["incident_summary"] = []
        return out

    from llm_summarizer.summarizer import summarize_incident

    rows = []
    for row in df.to_dict("records"):
        enriched = dict(row)
        result = summarize_incident(enriched)
        enriched["incident_summary"] = result["incident_summary"]
        logger.info(
            "Generated incident summary with method=%s model=%s.",
            result["summary_method"], result["summary_model"],
        )
        rows.append(enriched)
    return pd.DataFrame(rows)


def _first_present_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def to_supabase_payload_frame(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Return the seven lower-case app-owned fields accepted by Supabase upload."""

    frame = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    out = pd.DataFrame(index=frame.index)
    for target, aliases in _SUPABASE_ALIASES.items():
        source = _first_present_column(frame, aliases)
        out[target] = frame[source] if source is not None else UNKNOWN
    for column in ("incident_id", "source", "location", "time", "incident_summary"):
        out[column] = out[column].map(_clean)
    out["event"] = out["event"].map(normalize_event)
    out["severity"] = out["severity"].map(normalize_severity)
    out.loc[out["event"] == UNKNOWN, "severity"] = "Low"
    return out.loc[:, list(SUPABASE_PAYLOAD_COLUMNS)].copy()


def to_integration_output_frame(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Return the seven public Integration output columns."""

    payload = to_supabase_payload_frame(rows)
    return pd.DataFrame(
        {
            "Incident_ID": payload["incident_id"],
            "Source": payload["source"],
            "Event": payload["event"],
            "Location": payload["location"],
            "Time": payload["time"],
            "Severity": payload["severity"],
            "Incident_Summary": payload["incident_summary"],
        },
        columns=list(INTEGRATION_OUTPUT_COLUMNS),
    )


def _finalize_records(
    standardized_df: pd.DataFrame,
    existing_ids: Iterable[Any] = (),
) -> pd.DataFrame:
    """Add summaries and IDs to standardized records in documented order."""

    summarized = add_incident_summaries(standardized_df)
    with_ids = assign_incident_ids(summarized, existing_ids)
    return to_integration_output_frame(with_ids)


def build_incidents(
    draft_df: pd.DataFrame,
    source_type: str,
    existing_ids: Iterable[Any] = (),
    *,
    source_filename: str | None = None,
) -> pd.DataFrame:
    """End-to-end: draft DataFrame -> summarized incident rows with IDs.

    Args:
        draft_df: Modality processor output.
        source_type: Modality key.
        existing_ids: incident_id values already in Supabase, used to continue
            numbering without collisions.
    """
    return integrate_records(
        draft_df,
        source_type,
        existing_ids,
        source_filename=source_filename,
    )


# --------------------------------------------------------------------------- #
# Display label derivation + final CSV export
# --------------------------------------------------------------------------- #
def prefix_for_source(source_value: Any) -> str:
    """ID prefix for a source label ('Audio') or source_type key ('audio')."""
    if source_value in MODALITIES:
        return MODALITIES[source_value]["prefix"]
    return _PREFIX_BY_LABEL.get(str(source_value), "INC")


def display_id(source_value: Any, incident_id: Any, *, pad: int = 3) -> str:
    """Display label for a documented incident ID."""
    text = str(incident_id)
    if ID_PATTERN.match(text):
        return text
    return str(incident_id)


def with_display_ids(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Return Supabase rows with an extra display ``Incident_ID`` label column."""
    frame = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    if frame.empty:
        return frame
    if "event" in frame.columns:
        frame["event"] = frame["event"].map(normalize_event)
        if "severity" in frame.columns:
            frame["severity"] = frame["severity"].map(normalize_severity)
            frame.loc[frame["event"] == UNKNOWN, "severity"] = "Low"
    labels = [
        display_id(s, i)
        for s, i in zip(frame.get("source"), frame.get("incident_id"))
    ]
    if "Incident_ID" in frame.columns:
        frame["Incident_ID"] = labels
    else:
        frame.insert(0, "Incident_ID", labels)
    return frame


def to_final_csv_frame(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Return the nine dashboard/export columns."""
    frame = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    payload = to_supabase_payload_frame(frame)
    out = pd.DataFrame(index=frame.index)
    out["id"] = frame["id"] if "id" in frame.columns else UNKNOWN
    out["created_at"] = frame["created_at"] if "created_at" in frame.columns else UNKNOWN
    for column in SUPABASE_PAYLOAD_COLUMNS:
        out[column] = payload[column]
    out = out.loc[:, list(FINAL_CSV_COLUMNS)].copy()
    out["id"] = out["id"].map(_clean)
    out["created_at"] = out["created_at"].map(_clean)
    out["event"] = out["event"].map(normalize_event)
    return out


# --------------------------------------------------------------------------- #
# Modality dispatch (Stage 1-3): run the correct processor for a raw file
# --------------------------------------------------------------------------- #
def run_modality(
    source_type: str,
    input_path: str | Path | None = None,
    *,
    output_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Run the processor for ``source_type`` and return its draft DataFrame.

    Processors are imported lazily so heavy optional dependencies (Whisper,
    OpenCV, ...) are only loaded for the modality actually used.

    Audio files are always transcribed before analysis; uploaded audio never
    falls back to user-supplied transcript text.
    """
    if input_path is None:
        raise ValueError(f"{source_type} processing requires a file path.")
    source_type = normalize_source_type(source_type)

    if source_type == "audio":
        from audio.config import OUTPUT_COLUMNS
        from audio.processor import process_audio_file

        row = process_audio_file(str(input_path))
        frame = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
        if output_csv:
            output = Path(output_csv)
            output.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(output, index=False)
        return frame

    if source_type == "pdf":
        from pdf.processor import process_pdf

        return process_pdf(str(input_path), output_csv_path=output_csv)
    if source_type == "image":
        from images.processor import process_image

        return process_image(input_path, output_csv) if output_csv else process_image(input_path)
    if source_type == "video":
        from video.processor import process_video

        return process_video(str(input_path), output_csv) if output_csv else process_video(str(input_path))
    if source_type == "text":
        from text.processor import process_text

        suffix = Path(input_path).suffix.lower()
        if suffix == ".csv":
            frame = pd.read_csv(input_path, keep_default_na=False)
            if _looks_like_structured_text_frame(frame):
                return frame
        return process_text(input_path, output_csv) if output_csv else process_text(input_path)

    raise ValueError(f"Unsupported source_type {source_type!r}.")


def main(argv: list[str] | None = None) -> int:
    """Explain that the MVP integration workflow runs through Streamlit."""

    del argv
    print("Use the Streamlit single-file upload workflow; local batch merging is not part of this MVP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INCIDENT_COLUMNS",
    "INTEGRATION_OUTPUT_COLUMNS",
    "SUPABASE_PAYLOAD_COLUMNS",
    "FINAL_CSV_COLUMNS",
    "MODALITIES",
    "SEVERITY_LEVELS",
    "INTEGRATION_COLUMNS",
    "detect_source_type",
    "supported_extensions",
    "source_label",
    "source_prefix",
    "severity_from_confidence",
    "normalize_severity",
    "normalize_event",
    "integrate_records",
    "next_incident_number",
    "generate_incident_id",
    "generate_next_incident_id",
    "assign_incident_ids",
    "add_incident_summaries",
    "build_incidents",
    "to_supabase_payload_frame",
    "to_integration_output_frame",
    "prefix_for_source",
    "display_id",
    "with_display_ids",
    "to_final_csv_frame",
    "run_modality",
    "main",
]
