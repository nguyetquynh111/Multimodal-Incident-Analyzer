"""Stage 4 integration: merge modality draft outputs into the final schema.

This module is owned by the Integration & Dashboard Lead (Student 6). It takes
the per-modality "draft" CSV that each processor produces and normalises it into
the single unified incident schema that is stored in Supabase and exported as the
final dataset.

Pipeline position::

    raw file -> modality processor -> DRAFT df -> integrate_records() -> FINAL df
             -> assign_incident_ids() -> Supabase insert -> dashboard / CSV export

Final (Supabase) columns are lower-case::

    incident_id, source, event, location, time, severity

The final CSV export uses the assignment's title-case headers::

    Incident_ID, Source, Event, Location, Time, Severity

Incident IDs are modality-prefixed strings (assignment section 4, step 1)::

    AUD-001  DOC-001  IMG-001  VID-001  TXT-001

Severity is graded Low / Medium / High from a 0-10 score (assignment section 4,
step 4). The documented rule used here is ``score = confidence * 10`` with
thresholds ``0-3 Low, 3-7 Medium, 7-10 High``. Modalities that do not expose a
numeric confidence default to ``Medium``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"

# Final Supabase column order (lower-case). Mirrors validators.INCIDENT_COLUMNS.
INCIDENT_COLUMNS: tuple[str, ...] = (
    "incident_id",
    "source",
    "event",
    "location",
    "time",
    "severity",
)

# Headers required by the assignment's final dataset / CSV export.
FINAL_CSV_COLUMNS: tuple[str, ...] = (
    "Incident_ID",
    "Source",
    "Event",
    "Location",
    "Time",
    "Severity",
)

# One canonical record per modality: human-readable source label + ID prefix.
# Prefixes follow the assignment (PDF uses the DOC- prefix).
MODALITIES: dict[str, dict[str, Any]] = {
    "audio": {"label": "Audio", "prefix": "AUD", "extensions": {".wav", ".mp3", ".m4a", ".flac"}},
    "pdf": {"label": "PDF", "prefix": "DOC", "extensions": {".pdf"}},
    "image": {"label": "Image", "prefix": "IMG", "extensions": {".jpg", ".jpeg", ".png"}},
    "video": {"label": "Video", "prefix": "VID", "extensions": {".mp4", ".mov", ".mpg", ".mpeg"}},
    "text": {"label": "Text", "prefix": "TXT", "extensions": {".txt"}},
}

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
    return MODALITIES[source_type]["label"]


def source_prefix(source_type: str) -> str:
    """Incident-ID prefix, e.g. ``audio`` -> ``AUD``."""
    return MODALITIES[source_type]["prefix"]


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


def _map_audio(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": _clean(row.get("Extracted_Event")),
        "location": _clean(row.get("Location")),
        "time": UNKNOWN,  # audio transcripts rarely carry a wall-clock time
        "severity": severity_from_confidence(row.get("Urgency_Score")),
    }


def _map_pdf(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": _clean(row.get("Incident_Type")),
        "location": _clean(row.get("Location")),
        "time": _clean(row.get("Date")),
        "severity": DEFAULT_SEVERITY,  # PDF draft carries no numeric confidence
    }


def _map_image(row: Mapping[str, Any]) -> dict[str, Any]:
    event = _clean(row.get("Scene_Type"))
    objects = _clean(row.get("Objects_Detected"))
    if event == UNKNOWN and objects != UNKNOWN:
        event = objects
    return {
        "event": event,
        # OCR text only becomes a location when it clearly is one; the draft
        # keeps it Unknown, so we default to Unknown here.
        "location": UNKNOWN,
        "time": UNKNOWN,
        "severity": severity_from_confidence(row.get("Confidence_Score")),
    }


def _map_video(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": _clean(row.get("Event_Detected")),
        "location": UNKNOWN,
        "time": _clean(row.get("Timestamp")),
        "severity": severity_from_confidence(row.get("Confidence")),
    }


def _map_text(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event": _clean(row.get("Topic")),
        "location": _clean(row.get("Entities")),  # location entities, if any
        "time": UNKNOWN,
        "severity": DEFAULT_SEVERITY,  # text draft carries no numeric confidence
    }


_MAPPERS = {
    "audio": _map_audio,
    "pdf": _map_pdf,
    "image": _map_image,
    "video": _map_video,
    "text": _map_text,
}


def integrate_records(draft_df: pd.DataFrame, source_type: str) -> pd.DataFrame:
    """Normalise one modality's draft DataFrame into the final schema.

    Args:
        draft_df: The DataFrame returned by a modality processor.
        source_type: One of ``audio, pdf, image, video, text``.

    Returns:
        A DataFrame with columns ``source, event, location, time, severity``
        (one row per draft row). ``incident_id`` is added later by
        :func:`assign_incident_ids`. An empty input yields an empty,
        correctly-typed frame so the app never crashes.
    """
    if source_type not in _MAPPERS:
        raise ValueError(f"Unsupported source_type {source_type!r}.")
    if not isinstance(draft_df, pd.DataFrame):
        raise TypeError("draft_df must be a pandas DataFrame.")

    label = source_label(source_type)
    mapper = _MAPPERS[source_type]
    rows = [{"source": label, **mapper(record)} for record in draft_df.to_dict("records")]
    columns = ["source", "event", "location", "time", "severity"]
    return pd.DataFrame(rows, columns=columns)


# --------------------------------------------------------------------------- #
# Incident-ID assignment (stored as a unique integer; the Supabase column is
# int8). The modality-prefixed label such as "AUD-005" is derived for display
# and CSV export from (source, incident_id) -- it is not stored.
# --------------------------------------------------------------------------- #
_PREFIX_BY_LABEL = {meta["label"]: meta["prefix"] for meta in MODALITIES.values()}


def next_incident_number(existing_ids: Iterable[Any]) -> int:
    """Return the next free integer incident_id given the IDs already stored."""
    highest = 0
    for value in existing_ids:
        try:
            highest = max(highest, int(value))
        except (TypeError, ValueError):
            continue
    return highest + 1


def assign_incident_ids(df: pd.DataFrame, start_number: int = 1) -> pd.DataFrame:
    """Prepend a unique integer incident_id (start_number, +1, +2, ...)."""
    out = df.copy()
    out.insert(0, "incident_id", [start_number + i for i in range(len(df))])
    return out


def build_incidents(
    draft_df: pd.DataFrame,
    source_type: str,
    existing_ids: Iterable[Any] = (),
) -> pd.DataFrame:
    """End-to-end: draft DataFrame -> final incident rows with integer IDs.

    Args:
        draft_df: Modality processor output.
        source_type: Modality key.
        existing_ids: integer incident_id values already in Supabase, used to
            continue numbering without collisions.
    """
    records = integrate_records(draft_df, source_type)
    start = next_incident_number(existing_ids)
    return assign_incident_ids(records, start)


# --------------------------------------------------------------------------- #
# Display label derivation + final CSV export
# --------------------------------------------------------------------------- #
def prefix_for_source(source_value: Any) -> str:
    """ID prefix for a source label ('Audio') or source_type key ('audio')."""
    if source_value in MODALITIES:
        return MODALITIES[source_value]["prefix"]
    return _PREFIX_BY_LABEL.get(str(source_value), "INC")


def display_id(source_value: Any, incident_id: Any, *, pad: int = 3) -> str:
    """Modality-prefixed label, e.g. ``display_id("Audio", 5) == "AUD-005"``."""
    try:
        number = int(incident_id)
    except (TypeError, ValueError):
        return str(incident_id)
    return f"{prefix_for_source(source_value)}-{number:0{pad}d}"


def with_display_ids(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Return Supabase rows with an extra title-case ``Incident_ID`` label column."""
    frame = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    if frame.empty:
        return frame
    labels = [
        display_id(s, i)
        for s, i in zip(frame.get("source"), frame.get("incident_id"))
    ]
    frame.insert(0, "Incident_ID", labels)
    return frame


def to_final_csv_frame(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Return the six assignment columns with title-case headers.

    The ``Incident_ID`` column holds the derived modality-prefixed label
    (e.g. ``AUD-005``). Accepts Supabase rows (list of dicts) or a final-schema
    DataFrame.
    """
    frame = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows.copy()
    for column in INCIDENT_COLUMNS:
        if column not in frame.columns:
            frame[column] = UNKNOWN
    labels = [
        display_id(s, i) for s, i in zip(frame["source"], frame["incident_id"])
    ]
    out = frame.loc[:, list(INCIDENT_COLUMNS)].copy()
    out["incident_id"] = labels
    out.columns = list(FINAL_CSV_COLUMNS)
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
    source record), then assign continuous integer incident IDs.
    """
    outputs = outputs or MODALITY_OUTPUTS
    frames = [
        integrate_records(frame, source_type)
        for source_type in MODALITIES  # stable order: audio, pdf, image, video, text
        if (frame := read_modality_output(source_type, outputs.get(source_type))) is not None
    ]
    columns = ["source", "event", "location", "time", "severity"]
    master = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
    return assign_incident_ids(master, next_incident_number(existing_ids))


def write_final_dataset(df: pd.DataFrame, path: str | Path | None = None) -> Path:
    """Write the title-case final dataset CSV (the assignment deliverable)."""
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
    transcript: str | None = None,
    output_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Run the processor for ``source_type`` and return its draft DataFrame.

    Processors are imported lazily so heavy optional dependencies (Whisper,
    OpenCV, ...) are only loaded for the modality actually used.

    For audio, pass ``transcript=`` to skip Whisper and analyse pasted text
    directly (useful when torch/Whisper is unavailable, e.g. on Python 3.13 or
    Streamlit Community Cloud).
    """
    if source_type == "audio":
        if transcript is not None:
            from audio.config import OUTPUT_COLUMNS
            from audio.extract import analyze_transcript

            call_id = Path(input_path).stem if input_path else "DEMO001"
            row = analyze_transcript(call_id, transcript)
            return pd.DataFrame([row], columns=OUTPUT_COLUMNS)

        from audio.config import OUTPUT_COLUMNS
        from audio.processor import process_audio_file

        row = process_audio_file(str(input_path))
        return pd.DataFrame([row], columns=OUTPUT_COLUMNS)

    if input_path is None:
        raise ValueError(f"{source_type} processing requires a file path.")

    if source_type == "pdf":
        from pdf.processor import process_pdf

        return process_pdf(input_path, output_csv) if output_csv else process_pdf(input_path)
    if source_type == "image":
        from images.processor import process_image

        return process_image(input_path, output_csv) if output_csv else process_image(input_path)
    if source_type == "video":
        from video.processor import process_video

        return process_video(input_path, output_csv) if output_csv else process_video(input_path)
    if source_type == "text":
        from text.processor import process_text

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

    for source_type, count in status.items():
        print(f"  {source_label(source_type):6} {count:>3} rows")
    print(
        f"Merged {len(master)} incidents from {master['source'].nunique()} "
        f"modalities -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INCIDENT_COLUMNS",
    "FINAL_CSV_COLUMNS",
    "MODALITIES",
    "SEVERITY_LEVELS",
    "detect_source_type",
    "supported_extensions",
    "source_label",
    "source_prefix",
    "severity_from_confidence",
    "integrate_records",
    "next_incident_number",
    "assign_incident_ids",
    "build_incidents",
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
