"""Stage 4 integration: merge modality draft outputs into the final schema.

This module is owned by the Integration & Dashboard Lead (Student 6). It takes
the per-modality "draft" CSV that each processor produces and normalises it into
the single unified incident schema that is stored in Supabase and exported as the
final dataset.

Pipeline position::

    raw file -> modality processor -> DRAFT df -> integrate_records()
             -> build_incidents() -> Supabase insert -> dashboard / CSV export

Integration output columns are title-case::

    Incident_ID, Source, Event, Location, Time, Severity, LLM_Summary

Supabase upload/export uses the dashboard/Supabase field names::

    id, created_at, incident_id, source, event, location, time, severity,
    summary_by_llm

Incident IDs are generated in the project-documented format::

    INC_AUD_001  INC_PDF_001  INC_IMG_001  INC_VID_001  INC_TXT_001

Severity is graded Low / Medium / High from a 0-10 score (assignment section 4,
step 4). The documented rule used here is ``score = confidence * 10`` with
thresholds ``0-3 Low, 3-7 Medium, 7-10 High``. Modalities that do not expose a
numeric confidence default to ``Medium``.
"""

from __future__ import annotations

import json
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
    "LLM_Summary",
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
    "summary_by_llm",
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
    "summary_by_llm",
)

_SUPABASE_ALIASES: dict[str, tuple[str, ...]] = {
    "incident_id": ("incident_id", "Incident_ID"),
    "source": ("source", "Source"),
    "event": ("event", "Event"),
    "location": ("location", "Location"),
    "time": ("time", "Time"),
    "severity": ("severity", "Severity"),
    "summary_by_llm": ("summary_by_llm", "LLM_Summary"),
}

# One canonical record per modality: human-readable source label + ID type.
MODALITIES: dict[str, dict[str, Any]] = {
    "audio": {"label": "Audio", "prefix": "AUD", "extensions": {".wav", ".mp3", ".m4a", ".flac"}},
    "pdf": {"label": "PDF", "prefix": "PDF", "extensions": {".pdf"}},
    "image": {"label": "Image", "prefix": "IMG", "extensions": {".jpg", ".jpeg", ".png"}},
    "video": {"label": "Video", "prefix": "VID", "extensions": {".mp4", ".mov", ".mpg", ".mpeg"}},
    "text": {"label": "Text", "prefix": "TXT", "extensions": {".txt", ".csv", ".json"}},
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


SEVERITY_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")
# score < LOW_MAX -> Low, score < MEDIUM_MAX -> Medium, else High (score on 0-10).
SEVERITY_LOW_MAX = 3.0
SEVERITY_MEDIUM_MAX = 7.0
DEFAULT_SEVERITY = "Medium"  # used when a modality has no numeric confidence


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
    if candidate.casefold() in {"csv", "json"}:
        return "text"
    if candidate in MODALITIES:
        return candidate
    upper = candidate.upper()
    for key, meta in MODALITIES.items():
        if meta["prefix"] == upper:
            return key
    raise ValueError(f"Unsupported source_type {source_type!r}.")


# --------------------------------------------------------------------------- #
# Severity
# --------------------------------------------------------------------------- #
def severity_from_confidence(confidence: Any) -> str:
    """Map a 0-1 confidence/urgency value to Low / Medium / High.

    Uses ``score = confidence * 10`` with the documented thresholds. Invalid or
    missing values fall back to the default severity.
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
    canonical = value.title()
    if canonical in SEVERITY_LEVELS:
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


def _map_image(row: Mapping[str, Any]) -> dict[str, Any]:
    event = normalize_event(_first_known(row, "Scene_Type"))
    objects = _clean(row.get("Objects_Detected"))
    if event == UNKNOWN and objects != UNKNOWN:
        event = normalize_event(objects)
    return {
        "event": event,
        # OCR text only becomes a location when it clearly is one; the draft
        # keeps it Unknown, so we default to Unknown here.
        "location": _first_known(row, "Location"),
        "time": _first_known(row, "Time", "Timestamp"),
        "confidence": _confidence(row, "Confidence_Score"),
        "raw_text": _first_known(row, "Text_Extracted", "Objects_Detected"),
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


def _json_text(row: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(row), ensure_ascii=False, default=str)
    except TypeError:
        return str(dict(row))


def _map_structured(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map CSV/JSON records that already carry incident-like fields."""

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
        raw_text = _json_text(row)
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
    """Return true for CSV/JSON text inputs that already carry incident fields."""

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


def integrate_records(
    draft_df: pd.DataFrame,
    source_type: str,
    *,
    source_filename: str | None = None,
) -> pd.DataFrame:
    """Normalise one modality's draft DataFrame into the final schema.

    Args:
        draft_df: The DataFrame returned by a modality processor.
        source_type: One of ``audio, pdf, image, video, text``. CSV and JSON
            files are structured text inputs and normalize to ``text``.

    Returns:
        A DataFrame with the required integration columns plus documented
        metadata needed by the summarizer/Supabase payload. ``incident_id`` and
        summary fields are added later. An empty input yields an empty,
        correctly-typed frame so the app never crashes.
    """
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
        rows.append(
            {
                "source": label,
                "event": mapped["event"],
                "location": mapped["location"],
                "time": mapped["time"],
                "severity": mapped["severity"],
                "source_filename": _first_known(record, "source_filename", "Source_Filename") if source_filename is None else filename,
                "source_type": source_code,
                "confidence": mapped.get("confidence", 0.0),
                "raw_text": mapped.get("raw_text", UNKNOWN),
            }
        )
    return pd.DataFrame(rows, columns=list(INTEGRATION_COLUMNS))


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
        out["summary_by_llm"] = []
        return out

    from llm_summarizer.summarizer import summarize_incident

    rows = []
    for row in df.to_dict("records"):
        enriched = dict(row)
        enriched["summary_by_llm"] = summarize_incident(enriched)["incident_summary"]
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
    out["event"] = out["event"].map(normalize_event)
    out["severity"] = out["severity"].map(lambda value: str(value).strip().title())
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
            "LLM_Summary": payload["summary_by_llm"],
        },
        columns=list(INTEGRATION_OUTPUT_COLUMNS),
    )


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
    records = integrate_records(draft_df, source_type, source_filename=source_filename)
    summarized = add_incident_summaries(records)
    with_ids = assign_incident_ids(summarized, existing_ids)
    return to_integration_output_frame(with_ids)


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
    out["event"] = out["event"].map(normalize_event)
    return out


# --------------------------------------------------------------------------- #
# Stage 4 (Final Integration Task): UNION every modality's output CSV into one
# unified master dataset -- the assignment's central deliverable.
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Conventional output CSV that each modality processor writes.
MODALITY_OUTPUTS: dict[str, Path] = {
    "audio": PROJECT_ROOT / "audio" / "output" / "audio_output.csv",
    "pdf": PROJECT_ROOT / "pdf" / "output" / "pdf_output.csv",
    "image": PROJECT_ROOT / "images" / "output" / "image_output.csv",
    "video": PROJECT_ROOT / "video" / "output" / "video_output.csv",
    "text": PROJECT_ROOT / "text" / "output" / "text_output.csv",
}
FINAL_DATASET_PATH = PROJECT_ROOT / "integration" / "output" / "final_incident_dataset.csv"


def read_modality_output(source_type: str, path: str | Path | None = None) -> pd.DataFrame | None:
    """Read one modality's output CSV, or ``None`` if missing/empty."""
    target = Path(path) if path is not None else MODALITY_OUTPUTS[source_type]
    if not target.exists():
        return None
    try:
        frame = pd.read_csv(target)
    except (pd.errors.EmptyDataError, OSError):
        return None
    return frame if not frame.empty else None


def modality_output_status(outputs: Mapping[str, Path] | None = None) -> dict[str, int]:
    """Return ``{source_type: row_count}`` for each modality output (0 if absent)."""
    outputs = outputs or MODALITY_OUTPUTS
    return {
        source_type: (
            0 if (frame := read_modality_output(source_type, outputs.get(source_type))) is None
            else len(frame)
        )
        for source_type in MODALITIES
    }


def build_master_dataset(
    existing_ids: Iterable[Any] = (),
    outputs: Mapping[str, Path] | None = None,
) -> pd.DataFrame:
    """UNION every available modality output into one unified incident dataset.

    Implements the Final Integration Task: read each modality output CSV,
    normalise it to the common schema, ``pandas.concat`` them (one row per
    source record), then assign documented ``INC_TYPE_NUMBER`` incident IDs.
    """
    outputs = outputs or MODALITY_OUTPUTS
    frames = [
        integrate_records(frame, source_type)
        for source_type in MODALITIES  # stable order follows the MODALITIES mapping
        if (frame := read_modality_output(source_type, outputs.get(source_type))) is not None
    ]
    columns = ["source", "event", "location", "time", "severity"]
    master = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
    summarized = add_incident_summaries(master)
    with_ids = assign_incident_ids(summarized, existing_ids)
    return to_integration_output_frame(with_ids)


def write_final_dataset(df: pd.DataFrame, path: str | Path | None = None) -> Path:
    """Write the nine-field final dataset CSV (the assignment deliverable)."""
    target = Path(path) if path is not None else FINAL_DATASET_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    to_final_csv_frame(df).to_csv(target, index=False)
    return target


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
        if suffix == ".json":
            path = Path(input_path)
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            payload = json.loads(text)
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                rows = payload.get("incidents") if isinstance(payload.get("incidents"), list) else [payload]
            else:
                rows = [{"raw_text": str(payload)}]
            return pd.DataFrame(rows)
        return process_text(input_path, output_csv) if output_csv else process_text(input_path)

    raise ValueError(f"Unsupported source_type {source_type!r}.")


def main(argv: list[str] | None = None) -> int:
    """Data-engineering entry point: merge every modality output into the final dataset.

        python -m integration.integration [--output PATH]
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Merge all modality output CSVs into the unified incident dataset."
    )
    parser.add_argument("--output", default=str(FINAL_DATASET_PATH), help="Destination CSV path")
    args = parser.parse_args(argv)

    status = modality_output_status()
    master = build_master_dataset()
    path = write_final_dataset(master, args.output)
    payload = to_supabase_payload_frame(master)

    for source_type, count in status.items():
        print(f"  {source_label(source_type):6} {count:>3} rows")
    print(
        f"Merged {len(master)} incidents from {payload['source'].nunique()} "
        f"modalities -> {path}"
    )
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
    "MODALITY_OUTPUTS",
    "FINAL_DATASET_PATH",
    "read_modality_output",
    "modality_output_status",
    "build_master_dataset",
    "write_final_dataset",
    "run_modality",
    "main",
]
