"""Public PDF processing API.

Produces two deliberately distinct outputs from one official document:

1. A demonstration *artifact* CSV with the exact PDF columns
   ``Report_ID, Incident_Type, Date, Location, Officer, Summary,
   Suspect_Description, Outcome`` written under ``pdf/output/``.
2. The shared *extractor contract* DataFrame
   ``source_filename, source_type, raw_event, raw_location, raw_time,
   raw_severity, confidence, raw_text`` returned in memory for Integration.

Text is extracted directly first (PyMuPDF, then pdfplumber). OCR
(pytesseract) is only attempted when direct extraction yields empty or
near-empty text. spaCy NER is used to help pull entities when available, but
no field is ever invented: a field with no real match becomes ``Unknown``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Callable

import pandas as pd


ARTIFACT_COLUMNS = [
    "Report_ID",
    "Incident_Type",
    "Date",
    "Location",
    "Officer",
    "Summary",
    "Suspect_Description",
    "Outcome",
]

EXTRACTOR_COLUMNS = [
    "source_filename",
    "source_type",
    "raw_event",
    "raw_location",
    "raw_time",
    "raw_severity",
    "confidence",
    "raw_text",
]

SOURCE_TYPE = "PDF"
UNKNOWN = "Unknown"
SUPPORTED_PDF_EXTENSIONS = {".pdf"}

# Below this many non-whitespace characters, direct extraction is treated as
# empty and the OCR fallback is attempted (scanned document case).
_MIN_DIRECT_TEXT_CHARS = 20

_DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"
_DEFAULT_ARTIFACT_NAME = "pdf_output.csv"


# --- Field extraction helpers ------------------------------------------------

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_DATE_PATTERN = re.compile(
    rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"
    rf"|\b\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}\b",
    re.IGNORECASE,
)

# Ranked law-enforcement title followed by a proper name. Name tokens are
# separated by spaces only (not \s) so the match never bleeds across a line
# break into the next, unrelated line.
_OFFICER_PATTERN = re.compile(
    r"\b(?:Cpl|Sgt|Lt|Capt|Det|Ofc|Officer|Patrolman|Deputy|Sergeant|"
    r"Corporal|Lieutenant|Captain|Chief)\.?[ ]+"
    r"[A-Z][A-Za-z.'-]+(?:[ ]+[A-Z][A-Za-z.'-]+){0,2}"
)

# A place name that precedes a law-enforcement org, e.g. "Fort Smith Police
# Department" -> "Fort Smith". Source-grounded, so it never invents a place.
_ORG_LOCATION_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+"
    r"(?:Police Department|Sheriff(?:'s)? Office|Fire Department|"
    r"County Sheriff)\b"
)
# "City, ST" style location.
_CITY_STATE_PATTERN = re.compile(r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)?,\s*[A-Z]{2})\b")

# Strong, crime-specific incident keywords. Generic words such as "accident",
# "emergency", or "fire" are intentionally excluded to avoid mislabelling
# administrative or training documents that merely mention them.
_INCIDENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Theft / Robbery",
        (r"\brobber(?:y|ies)\b", r"\brobbed\b", r"\bburglar(?:y|ies|s)?\b",
         r"\btheft\b", r"\bstolen\b", r"\bshoplift(?:ing|ed)?\b", r"\blarceny\b"),
    ),
    (
        "Assault / Violence",
        (r"\bassault(?:s|ed)?\b", r"\bbattery\b", r"\bstabb(?:ing|ed)\b",
         r"\bshooting\b", r"\bshots fired\b", r"\bhomicide\b", r"\bmurder\b"),
    ),
    ("Fire / Arson", (r"\barson(?:ist)?\b",)),
    (
        "Traffic Accident",
        (r"\bcollision\b", r"\btraffic accident\b", r"\bcar crash\b",
         r"\bvehicle crash\b", r"\bhit[- ]and[- ]run\b"),
    ),
    (
        "Public Disturbance",
        (r"\briot(?:ing|s)?\b", r"\bvandalism\b", r"\bdisturbance\b", r"\btrespass(?:ing)?\b"),
    ),
)

# Severity signals keyed to a detected incident, per rules.md section 7.
_HIGH_SEVERITY = re.compile(
    r"\b(?:fire|weapon|gun|shoot|shot|trapped|collapse|fighting|stabb|"
    r"homicide|murder|arson)\b",
    re.IGNORECASE,
)
_MEDIUM_SEVERITY = re.compile(
    r"\b(?:theft|robber|burglar|stolen|disturbance|vandalism|property damage)\b",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", str(text or ""))).strip()


def extract_date(text: str) -> str:
    """Return the first explicit date found in the document, else Unknown."""

    match = _DATE_PATTERN.search(text)
    return match.group(0).strip() if match else UNKNOWN


def extract_officer(text: str) -> str:
    """Return the first ranked officer name found in the document, else Unknown."""

    match = _OFFICER_PATTERN.search(text)
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else UNKNOWN


def extract_location(text: str) -> str:
    """Return a source-grounded location, optionally aided by spaCy NER."""

    location = _spacy_location(text)
    if location != UNKNOWN:
        return location
    match = _ORG_LOCATION_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    match = _CITY_STATE_PATTERN.search(text)
    return match.group(1).strip() if match else UNKNOWN


def _spacy_location(text: str) -> str:
    """Use spaCy GPE/LOC entities when spaCy and a model are installed."""

    try:  # spaCy is optional; never a hard dependency for this module.
        import spacy  # type: ignore
    except Exception:
        return UNKNOWN
    try:
        nlp = _load_spacy_model(spacy)
        if nlp is None:
            return UNKNOWN
        doc = nlp(text[:5000])
        for ent in doc.ents:
            if ent.label_ in {"GPE", "LOC", "FAC"} and ent.text.strip():
                return ent.text.strip()
    except Exception:
        return UNKNOWN
    return UNKNOWN


_SPACY_MODEL: Any = False  # False = not yet loaded; None = unavailable.


def _load_spacy_model(spacy: Any) -> Any:
    global _SPACY_MODEL
    if _SPACY_MODEL is not False:
        return _SPACY_MODEL
    try:
        _SPACY_MODEL = spacy.load("en_core_web_sm")
    except Exception:
        _SPACY_MODEL = None
    return _SPACY_MODEL


def classify_incident(text: str) -> str:
    """Return the first crime-specific incident label that matches, else Unknown."""

    for label, patterns in _INCIDENT_KEYWORDS:
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            return label
    return UNKNOWN


def severity_signal(text: str, incident_type: str) -> str:
    """Map severity only when a real incident was detected (rules.md section 7)."""

    if incident_type == UNKNOWN:
        return UNKNOWN
    if _HIGH_SEVERITY.search(text):
        return "High"
    if _MEDIUM_SEVERITY.search(text):
        return "Medium"
    return "Low"


def _extract_context(text: str, keyword: str) -> str:
    """Return a short grounded snippet around a keyword, else Unknown."""

    match = re.search(rf".{{0,80}}\b{keyword}\b.{{0,120}}", text, re.IGNORECASE)
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else UNKNOWN


def summarize_document(text: str, *, max_chars: int = 240) -> str:
    """Return a source-grounded lead summary (the LLM summary is separate)."""

    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return UNKNOWN
    if len(flat) <= max_chars:
        return flat
    truncated = flat[:max_chars]
    cut = truncated.rfind(". ")
    if cut >= max_chars // 2:
        return truncated[: cut + 1]
    return truncated.rstrip() + "..."


def analyze_document(report_id: str, text: str) -> dict[str, Any]:
    """Convert one document's text into the exact eight-field PDF artifact row."""

    normalized = _normalize_text(text)
    incident_type = classify_incident(normalized)
    return {
        "Report_ID": str(report_id),
        "Incident_Type": incident_type,
        "Date": extract_date(normalized),
        "Location": extract_location(normalized),
        "Officer": extract_officer(normalized),
        "Summary": summarize_document(normalized),
        "Suspect_Description": _extract_context(normalized, "suspect"),
        "Outcome": _extract_context(normalized, "outcome"),
    }


# --- Confidence and extractor mapping ----------------------------------------

def _confidence(artifact_row: dict[str, Any], used_ocr: bool) -> float:
    """Confidence in [0, 1]: lower when OCR was needed or fields are Unknown."""

    signal_fields = ("Incident_Type", "Date", "Location")
    filled = sum(1 for field in signal_fields if artifact_row.get(field, UNKNOWN) != UNKNOWN)
    score = 0.3 + 0.2 * filled  # 0.3 .. 0.9
    if used_ocr:
        score *= 0.6
    return round(max(0.0, min(1.0, score)), 2)


def map_to_extractor(
    artifact_rows: list[dict[str, Any]],
    source_filename: str,
    raw_text: str,
    used_ocr: bool,
) -> pd.DataFrame:
    """Map zero or more artifact rows onto the shared extractor contract."""

    normalized_text = _normalize_text(raw_text) or UNKNOWN
    extractor_rows = [
        {
            "source_filename": source_filename,
            "source_type": SOURCE_TYPE,
            "raw_event": row.get("Incident_Type", UNKNOWN) or UNKNOWN,
            "raw_location": row.get("Location", UNKNOWN) or UNKNOWN,
            "raw_time": row.get("Date", UNKNOWN) or UNKNOWN,
            "raw_severity": severity_signal(
                normalized_text, row.get("Incident_Type", UNKNOWN)
            ),
            "confidence": _confidence(row, used_ocr),
            "raw_text": normalized_text,
        }
        for row in artifact_rows
    ]
    return pd.DataFrame(extractor_rows, columns=EXTRACTOR_COLUMNS)


# --- Text extraction (direct first, OCR fallback) ----------------------------

def _extract_text_direct(pdf_path: str) -> str:
    """Extract embedded text with PyMuPDF, falling back to pdfplumber."""

    try:
        import fitz  # type: ignore  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            text = "\n".join(page.get_text() for page in doc)
        if text.strip():
            return text
    except Exception:
        pass

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""


def _extract_text_ocr(pdf_path: str) -> str:
    """Render pages to images and OCR them with pytesseract (scanned PDFs)."""

    try:
        import fitz  # type: ignore  # PyMuPDF
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""

    import io

    chunks: list[str] = []
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                pix = page.get_pixmap()
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                chunks.append(pytesseract.image_to_string(image))
    except Exception:
        return ""
    return "\n".join(chunks)


def _validate_pdf_path(pdf_path: str | Path) -> Path:
    path = Path(pdf_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_PDF_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_PDF_EXTENSIONS))
        raise ValueError(
            f"Unsupported document type '{path.suffix or '<none>'}'. Supported: {supported}"
        )
    return path


# --- Public API --------------------------------------------------------------

def process_pdf_file(
    pdf_path: str,
    report_id: str | None = None,
    *,
    text_extractor: Callable[[str], str] | None = None,
    ocr_extractor: Callable[[str], str] | None = None,
    write_artifact: bool = True,
    output_csv_path: str | Path | None = None,
) -> pd.DataFrame:
    """Process one PDF and return the extractor-contract DataFrame.

    Direct text extraction is tried first; OCR runs only when direct
    extraction is empty or near-empty. When ``write_artifact`` is true the
    eight-column demo artifact is also written under ``pdf/output/``. The
    returned DataFrame is the in-memory pipeline contract and is never the
    primary on-disk output.
    """

    path = _validate_pdf_path(pdf_path)

    text = (text_extractor or _extract_text_direct)(str(path))
    used_ocr = False
    if len(text.strip()) < _MIN_DIRECT_TEXT_CHARS:
        text = (ocr_extractor or _extract_text_ocr)(str(path))
        used_ocr = True

    artifact_rows = [analyze_document(report_id or "RPT_001", text)]

    if write_artifact:
        save_artifact(artifact_rows, output_csv_path)

    return map_to_extractor(artifact_rows, path.name, text, used_ocr)


def save_artifact(
    artifact_rows: list[dict[str, Any]],
    output_csv_path: str | Path | None = None,
) -> pd.DataFrame:
    """Write artifact rows with the exact PDF column order and return them."""

    output = Path(output_csv_path).expanduser() if output_csv_path else (
        _DEFAULT_OUTPUT_DIR / _DEFAULT_ARTIFACT_NAME
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(artifact_rows, columns=ARTIFACT_COLUMNS).fillna(UNKNOWN)
    frame.to_csv(output, index=False)
    return frame


def build_parser() -> argparse.ArgumentParser:
    """Build the PDF processor command-line parser."""

    parser = argparse.ArgumentParser(
        description="Extract incident fields from one official PDF document."
    )
    parser.add_argument("--input", required=True, help="A supported .pdf file")
    parser.add_argument("--report-id", default=None, help="Optional Report_ID for the artifact row")
    parser.add_argument("--output", default=None, help="Optional artifact CSV path")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the PDF processor command-line interface."""

    args = build_parser().parse_args(argv)
    frame = process_pdf_file(
        args.input,
        report_id=args.report_id,
        output_csv_path=args.output,
    )
    print(frame.to_string(index=False))
    print(f"Returned {len(frame)} extractor row(s) for {Path(args.input).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_COLUMNS",
    "EXTRACTOR_COLUMNS",
    "analyze_document",
    "classify_incident",
    "map_to_extractor",
    "process_pdf_file",
    "save_artifact",
]
