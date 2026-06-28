"""Text processor for social posts, news blurbs, and crime-report rows.

The processor preserves ``Raw_Text`` and analyzes a cleaned copy. It uses spaCy
NER when an English model is installed, then applies deterministic regex/rule
fallbacks so the class demo works without downloading extra models. ``Entities``
is a semicolon-delimited set of label groups, for example::

    LOCATION: Oak Street, Chicago; ORGANIZATION: Police; DATE: 9pm tonight
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ARTIFACT_COLUMNS = [
    "Text_ID",
    "Source",
    "Raw_Text",
    "Sentiment",
    "Entities",
    "Topic",
]

TOPIC_LABELS = (
    "Theft / Robbery",
    "Assault / Violence",
    "Fire / Arson",
    "Traffic Accident",
    "Public Disturbance",
    "Other",
)

SENTIMENT_LABELS = ("Negative", "Neutral", "Positive")
UNKNOWN = "Unknown"

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".csv"}
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "text_output.csv"

_CSV_TEXT_COLUMNS = (
    "Raw_Text",
    "raw_text",
    "text",
    "Text",
    "description",
    "Description",
    "details",
    "Details",
    "report",
    "Report",
    "narrative",
    "Narrative",
    "content",
    "Content",
    "post",
    "Post",
    "tweet",
    "Tweet",
    "article",
    "Article",
    "summary",
    "Summary",
)
_CSV_SOURCE_COLUMNS = ("Source", "source", "dataset", "Dataset", "platform", "Platform")
_CSV_ID_COLUMNS = ("Text_ID", "text_id", "id", "ID", "Report_ID", "report_id")


# --- Text cleaning / tokenization -------------------------------------------

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION_PATTERN = re.compile(r"@\w+")
_HASHTAG_PATTERN = re.compile(r"#(\w+)")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9']+")


def preprocess_text(raw_text: str) -> str:
    """Return a cleaned analysis copy; ``Raw_Text`` is preserved separately."""

    text = html.unescape(str(raw_text or ""))
    text = _URL_PATTERN.sub(" ", text)
    text = _MENTION_PATTERN.sub(" ", text)
    text = _HASHTAG_PATTERN.sub(r"\1", text)
    text = _CONTROL_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    """Tokenize to lowercase word/number tokens for transparent rule scoring."""

    return [token.lower() for token in _TOKEN_PATTERN.findall(text)]


# --- Entity extraction -------------------------------------------------------

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_DATE_PATTERN = re.compile(
    rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b"
    rf"|\b\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}\b"
    rf"|\b(?:today|tonight|yesterday|tomorrow|this morning|this afternoon|"
    rf"this evening|last night)\b"
    rf"|\b(?:around|about|at)\s+\d{{1,2}}(?::\d{{2}})?\s*"
    rf"(?:a\.?m\.?|p\.?m\.?)\s*(?:today|tonight|yesterday|tomorrow)?\b",
    re.IGNORECASE,
)
_STREET_PATTERN = re.compile(
    r"\b(?:\d{1,6}\s+)?[A-Z][A-Za-z0-9.'-]*"
    r"(?:\s+[A-Z][A-Za-z0-9.'-]*){0,5}\s+"
    r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Boulevard|"
    r"Blvd\.?|Lane|Ln\.?|Highway|Hwy\.?|Parkway|Way|Court|Ct\.?)\b"
)
_CITY_STATE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,2},\s*[A-Z]{2})\b"
)
_PREP_LOCATION_PATTERN = re.compile(
    r"\b(?:at|near|in|inside|outside|toward|towards|to|from)\s+(?:the\s+)?"
    r"([A-Za-z0-9][A-Za-z0-9.'-]*(?:\s+[A-Za-z0-9][A-Za-z0-9.'-]*){0,6})",
    re.IGNORECASE,
)
_LOCATION_STOPWORDS = {
    "around",
    "about",
    "after",
    "before",
    "with",
    "where",
    "when",
    "while",
    "and",
    "but",
    "near",
    "at",
    "in",
    "inside",
    "outside",
    "toward",
    "towards",
    "to",
    "from",
    "police",
    "witnesses",
    "reported",
    "say",
    "says",
}
_GENERIC_LOCATION_CANDIDATES = {
    "area",
    "custody",
    "foot",
    "scene",
    "public",
    "injuries",
    "reported",
    "suspect",
    "suspects",
}
_ORG_PATTERN = re.compile(
    r"\b(?:[A-Z][A-Za-z&.'-]+\s+){0,5}"
    r"(?:Police Department|Sheriff(?:'s)? Office|Fire Department|"
    r"Emergency Medical Services|EMS|Hospital|University|School|Agency|"
    r"Company|Corporation|Corp\.?|Inc\.?)\b"
)
_STANDALONE_ORG_PATTERN = re.compile(r"\b(?:Police|EMS|FBI|ATF)\b")
_PERSON_PATTERN = re.compile(
    r"\b(?:Officer|Ofc\.?|Detective|Det\.?|Sgt\.?|Sergeant|Mr\.?|Ms\.?|Mrs\.?)\s+"
    r"[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,2}\b"
)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

_SPACY_MODEL: Any = False  # False = not loaded, None = unavailable.
_SPACY_CHUNK_CHARS = 4000


def _load_spacy_model() -> Any:
    """Load spaCy's small English model when available."""

    global _SPACY_MODEL
    if _SPACY_MODEL is not False:
        return _SPACY_MODEL
    try:
        import spacy  # type: ignore

        _SPACY_MODEL = spacy.load("en_core_web_sm")
    except Exception:
        _SPACY_MODEL = None
    return _SPACY_MODEL


def _entity_label(spacy_label: str) -> str | None:
    return {
        "PERSON": "PERSON",
        "GPE": "LOCATION",
        "LOC": "LOCATION",
        "FAC": "LOCATION",
        "ORG": "ORGANIZATION",
        "DATE": "DATE",
        "TIME": "DATE",
    }.get(spacy_label)


def _iter_text_chunks(text: str, max_chars: int = _SPACY_CHUNK_CHARS) -> Iterable[str]:
    """Yield bounded chunks so spaCy can scan long evidence text."""

    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            split = text.rfind(" ", start, end)
            if split > start:
                end = split
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        start = end + 1 if end < length and text[end:end + 1].isspace() else end


def _clean_candidate(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip(" ,.;:!?\"'()[]{}")).strip()


def _trim_location_candidate(text: str) -> str:
    words = _clean_candidate(text).split()
    kept: list[str] = []
    for word in words:
        if word.lower().strip(".,;:!?") in _LOCATION_STOPWORDS:
            break
        kept.append(word)
    candidate = _clean_candidate(" ".join(kept))
    if candidate.casefold() in _GENERIC_LOCATION_CANDIDATES:
        return ""
    return candidate


def _add_entity(
    entities: list[dict[str, str]],
    seen: set[tuple[str, str]],
    text: str,
    label: str,
) -> None:
    value = _clean_candidate(text)
    if not value:
        return
    key = (value.casefold(), label)
    if key not in seen:
        seen.add(key)
        entities.append({"text": value, "label": label})


def extract_entities(text: str) -> list[dict[str, str]]:
    """Extract people, locations, organizations, and dates from cleaned text."""

    entities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    nlp = _load_spacy_model()
    if nlp is not None:
        try:
            for chunk in _iter_text_chunks(text):
                doc = nlp(chunk)
                for ent in doc.ents:
                    label = _entity_label(ent.label_)
                    if label:
                        _add_entity(entities, seen, ent.text, label)
        except Exception:
            pass

    for match in _PERSON_PATTERN.finditer(text):
        _add_entity(entities, seen, match.group(0), "PERSON")
    for match in _STREET_PATTERN.finditer(text):
        _add_entity(entities, seen, match.group(0), "LOCATION")
    for match in _CITY_STATE_PATTERN.finditer(text):
        _add_entity(entities, seen, match.group(1), "LOCATION")
    for match in _PREP_LOCATION_PATTERN.finditer(text):
        candidate = _trim_location_candidate(match.group(1))
        if candidate:
            _add_entity(entities, seen, candidate, "LOCATION")
    for match in _ORG_PATTERN.finditer(text):
        _add_entity(entities, seen, match.group(0), "ORGANIZATION")
    for match in _STANDALONE_ORG_PATTERN.finditer(text):
        _add_entity(entities, seen, match.group(0), "ORGANIZATION")
    for match in _DATE_PATTERN.finditer(text):
        _add_entity(entities, seen, match.group(0), "DATE")

    return entities


def format_entities(entities: Iterable[dict[str, str]]) -> str:
    """Format entity groups in a CSV-friendly, documented text form."""

    groups: dict[str, list[str]] = {
        "PERSON": [],
        "LOCATION": [],
        "ORGANIZATION": [],
        "DATE": [],
    }
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        label = entity.get("label", "")
        text = _clean_candidate(entity.get("text", ""))
        key = (label, text.casefold())
        if label in groups and text and key not in seen:
            seen.add(key)
            groups[label].append(text)

    parts = [
        f"{label}: {', '.join(values)}"
        for label, values in groups.items()
        if values
    ]
    return "; ".join(parts) if parts else UNKNOWN


def parse_entities(value: Any) -> list[dict[str, str]]:
    """Parse ``format_entities`` output back into entity dictionaries."""

    text = _safe_field(value)
    if text == UNKNOWN:
        return []
    entities: list[dict[str, str]] = []
    for match in re.finditer(r"(?:^|;\s*)([A-Za-z_ ]+):\s*([^;]+)", text):
        label = match.group(1).strip().upper().replace("_", " ")
        for item in match.group(2).split(","):
            candidate = _clean_candidate(item)
            if candidate:
                entities.append({"text": candidate, "label": label})
    return entities


# --- Topic and sentiment -----------------------------------------------------

_TOPIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Theft / Robbery",
        (
            r"\brobber(?:y|ies)\b",
            r"\brobbed\b",
            r"\brobbing\b",
            r"\btheft\b",
            r"\bstolen\b",
            r"\bsteal(?:s|ing)?\b",
            r"\bburglar(?:y|ies|ized|s)?\b",
            r"\bbreak[ -]?in\b",
            r"\blarceny\b",
            r"\bshoplift(?:ing|ed)?\b",
        ),
    ),
    (
        "Assault / Violence",
        (
            r"\bassault(?:s|ed|ing)?\b",
            r"\battack(?:s|ed|ing)?\b",
            r"\bbattery\b",
            r"\bfight(?:s|ing)?\b",
            r"\bstabb(?:ing|ed)?\b",
            r"\bshoot(?:ing|s)?\b",
            r"\bshots fired\b",
            r"\bgun(?:s|fire)?\b",
            r"\bknife\b",
            r"\bhomicide\b",
            r"\bmurder\b",
        ),
    ),
    (
        "Fire / Arson",
        (
            r"\bfires?\b",
            r"\bsmoke\b",
            r"\bflames?\b",
            r"\bblaze\b",
            r"\bburn(?:ing|ed|s)?\b",
            r"\barson\b",
        ),
    ),
    (
        "Traffic Accident",
        (
            r"\btraffic accident\b",
            r"\bcar crash\b",
            r"\bvehicle crash\b",
            r"\bcrash(?:es|ed)?\b",
            r"\bcollision\b",
            r"\bhit[- ]and[- ]run\b",
            r"\bpileup\b",
            r"\broad accident\b",
        ),
    ),
    (
        "Public Disturbance",
        (
            r"\bdisturbance\b",
            r"\bdisorderly\b",
            r"\briot(?:s|ing)?\b",
            r"\bvandal(?:ism|ized)\b",
            r"\btrespass(?:ing|ed)?\b",
            r"\bpublic intoxication\b",
            r"\bnoise complaint\b",
            r"\bcrowd\b",
        ),
    ),
)
_NEGATIVE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:crime|incident|emergency|danger|urgent|threat|weapon)\b",
        r"\b(?:injur(?:y|ies|ed)|dead|death|fatal|trapped|victim)\b",
        r"\b(?:robber|theft|stolen|assault|attack|shoot|stab|fire|crash|disturbance)\b",
        r"\b(?:knife|gun|shots fired)\b",
    )
)
_POSITIVE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:safe|resolved|contained|rescued|recovered|all clear)\b",
        r"\bno injuries\b",
        r"\bno one hurt\b",
        r"\bunder control\b",
    )
)


def _pattern_score(text: str, patterns: Iterable[str]) -> int:
    return sum(len(re.findall(pattern, text, re.IGNORECASE)) for pattern in patterns)


def classify_topic(text: str) -> str:
    """Classify into the approved topic labels, or ``Other``."""

    scores = [
        (label, _pattern_score(text, patterns))
        for label, patterns in _TOPIC_PATTERNS
    ]
    best_label, best_score = max(scores, key=lambda item: item[1])
    return best_label if best_score > 0 else "Other"


def classify_sentiment(text: str) -> str:
    """Return a simple incident-oriented sentiment label."""

    negative = sum(1 for pattern in _NEGATIVE_PATTERNS if pattern.search(text))
    positive = sum(1 for pattern in _POSITIVE_PATTERNS if pattern.search(text))
    if classify_topic(text) != "Other":
        negative += 1
    if negative > positive:
        return "Negative"
    if positive > negative:
        return "Positive"
    return "Neutral"


# --- Public analysis / file processing --------------------------------------

def analyze_text(text_id: str, raw_text: str, source: str = "Text") -> dict[str, Any]:
    """Convert one raw text item into the exact six-field text draft row."""

    raw = str(raw_text or "").lstrip("\ufeff")
    raw_for_output = raw if raw.strip() else UNKNOWN
    cleaned = preprocess_text(raw)
    analysis_text = cleaned if cleaned else UNKNOWN
    entities = extract_entities(analysis_text if analysis_text != UNKNOWN else "")

    return {
        "Text_ID": str(text_id),
        "Source": str(source or "Text"),
        "Raw_Text": raw_for_output,
        "Sentiment": classify_sentiment(analysis_text),
        "Entities": format_entities(entities),
        "Topic": classify_topic(analysis_text),
    }


def _plain_source(value: Any) -> str:
    """Convert Twitter/Kaggle HTML source strings into readable text."""

    text = html.unescape(str(value or "")).strip()
    text = _HTML_TAG_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip() or UNKNOWN


def _metadata_entities(record: dict[str, Any]) -> list[dict[str, str]]:
    """Extract useful location/date metadata from one CrimeReport JSON row."""

    entities: list[dict[str, str]] = []
    place = record.get("place")
    if isinstance(place, dict):
        full_name = _safe_field(place.get("full_name"))
        if full_name != UNKNOWN:
            entities.append({"text": full_name, "label": "LOCATION"})

    user = record.get("user")
    if isinstance(user, dict):
        location = _safe_field(user.get("location"))
        if location != UNKNOWN:
            entities.append({"text": location, "label": "LOCATION"})
        name = _safe_field(user.get("name"))
        if name != UNKNOWN:
            entities.append({"text": name, "label": "PERSON"})

    created_at = _safe_field(record.get("created_at"))
    if created_at != UNKNOWN:
        entities.append({"text": created_at, "label": "DATE"})
    return entities


def _analyze_json_record(
    record: dict[str, Any],
    index: int,
    source: str | None,
) -> dict[str, Any]:
    """Analyze one JSON-lines CrimeReport/Twitter-style record."""

    raw_text = UNKNOWN
    for column in (
        "text",
        "Text",
        "Raw_Text",
        "raw_text",
        "summary",
        "Summary",
        "description",
        "Description",
        "details",
        "Details",
        "event",
        "Event",
    ):
        if column in record:
            raw_text = _safe_field(record.get(column))
            if raw_text != UNKNOWN:
                break
    row_source = source or "CrimeReport"
    row = analyze_text(f"TXT_{index:03d}", raw_text, row_source)
    merged_entities = parse_entities(row["Entities"]) + _metadata_entities(record)
    row["Entities"] = format_entities(merged_entities)
    return row


def _validate_text_path(input_path: str | Path) -> Path:
    path = Path(input_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Text input not found: {path}")
    if path.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_TEXT_EXTENSIONS))
        raise ValueError(
            f"Unsupported text input type '{path.suffix or '<none>'}'. Supported: {supported}"
        )
    return path


def _first_existing_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    available = {column.casefold(): column for column in columns}
    for candidate in candidates:
        found = available.get(candidate.casefold())
        if found is not None:
            return found
    return None


def _safe_field(value: Any) -> str:
    try:
        if pd.isna(value):
            return UNKNOWN
    except (TypeError, ValueError):
        pass
    text = str(value)
    return text if text.strip() else UNKNOWN


def _rows_from_json_lines(raw: str, source: str | None) -> list[dict[str, Any]] | None:
    """Return rows when a .txt file is JSON Lines; otherwise ``None``."""

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("{"):
        return None

    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(record, dict):
            return None
        rows.append(_analyze_json_record(record, index, source))
    return rows


def _rows_from_txt(path: Path, source: str | None) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    json_rows = _rows_from_json_lines(raw, source)
    if json_rows is not None:
        return json_rows
    return [analyze_text("TXT_001", raw, source or path.stem)]


def _rows_from_csv(
    path: Path,
    source: str | None,
    text_column: str | None,
) -> list[dict[str, Any]]:
    frame = pd.read_csv(path, keep_default_na=False)
    if frame.empty:
        return []

    selected_text_column = text_column or _first_existing_column(frame.columns, _CSV_TEXT_COLUMNS)
    if selected_text_column is None or selected_text_column not in frame.columns:
        candidates = ", ".join(_CSV_TEXT_COLUMNS)
        raise ValueError(f"Could not find a text column in {path.name}. Tried: {candidates}")

    source_column = _first_existing_column(frame.columns, _CSV_SOURCE_COLUMNS)
    id_column = _first_existing_column(frame.columns, _CSV_ID_COLUMNS)

    rows: list[dict[str, Any]] = []
    for index, record in frame.iterrows():
        text_id = _safe_field(record[id_column]) if id_column else f"TXT_{index + 1:03d}"
        row_source = _safe_field(record[source_column]) if source_column else (source or path.stem)
        rows.append(analyze_text(text_id, str(record[selected_text_column]), row_source))
    return rows


def _rows_from_json_file(path: Path, source: str | None) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("incidents") if isinstance(payload.get("incidents"), list) else [payload]
    else:
        records = [{"text": str(payload)}]

    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        if isinstance(record, dict):
            rows.append(_analyze_json_record(record, index, source))
        else:
            rows.append(analyze_text(f"TXT_{index:03d}", str(record), source or path.stem))
    return rows


def save_artifact(
    artifact_rows: list[dict[str, Any]],
    output_csv_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    """Write text rows with the exact column order and return the DataFrame."""

    output = Path(output_csv_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(artifact_rows, columns=ARTIFACT_COLUMNS)
    for column in ARTIFACT_COLUMNS:
        frame[column] = frame[column].map(_safe_field)
    frame.to_csv(output, index=False)
    return frame


def process_text(
    input_path: str | Path,
    output_csv_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    *,
    source: str | None = None,
    text_column: str | None = None,
) -> pd.DataFrame:
    """Process one text or CSV file into the six-column draft.

    ``.txt`` inputs produce one row unless they contain JSON Lines. ``.csv``
    inputs produce one row per record using a recognized text column such as
    ``Raw_Text``, ``text``, ``details``, or a user-provided ``text_column``.
    """

    path = _validate_text_path(input_path)
    rows = (
        _rows_from_csv(path, source, text_column)
        if path.suffix.lower() == ".csv"
        else _rows_from_txt(path, source)
    )
    if output_csv_path is not None:
        return save_artifact(rows, output_csv_path)

    frame = pd.DataFrame(rows, columns=ARTIFACT_COLUMNS)
    for column in ARTIFACT_COLUMNS:
        frame[column] = frame[column].map(_safe_field)
    return frame


def build_parser() -> argparse.ArgumentParser:
    """Build the text processor command-line parser."""

    parser = argparse.ArgumentParser(
        description="Extract entities, sentiment, and incident topic from text evidence."
    )
    parser.add_argument("input", help="A .txt social/news post or .csv text dataset")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Destination CSV path")
    parser.add_argument("--source", default=None, help="Override Source value")
    parser.add_argument("--text-column", default=None, help="CSV column containing raw text")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the text processor command-line interface."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    frame = process_text(
        args.input,
        output_csv_path=args.output,
        source=args.source,
        text_column=args.text_column,
    )
    preview = frame.head(10)
    print(preview.to_string(index=False))
    if len(frame) > len(preview):
        print(f"... {len(frame) - len(preview)} additional row(s) not shown")
    print(f"Saved {len(frame)} row(s) to {Path(args.output).expanduser()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_COLUMNS",
    "TOPIC_LABELS",
    "SENTIMENT_LABELS",
    "UNKNOWN",
    "SUPPORTED_TEXT_EXTENSIONS",
    "preprocess_text",
    "tokenize",
    "extract_entities",
    "format_entities",
    "classify_topic",
    "classify_sentiment",
    "analyze_text",
    "process_text",
    "save_artifact",
]
