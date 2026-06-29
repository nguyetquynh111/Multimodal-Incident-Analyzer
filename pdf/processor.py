"""PDF processing API for the eight-column Integration draft.

The processor reads embedded text first and OCRs scanned pages when possible.
Missing evidence is preserved as ``Unknown`` rather than inferred.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable

import pandas as pd


logger = logging.getLogger(__name__)


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

UNKNOWN = "Unknown"
SUPPORTED_PDF_EXTENSIONS = {".pdf"}

# Below this threshold, direct extraction is treated as unusable.
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

# Ranked law-enforcement title followed by a proper name.
_OFFICER_PATTERN = re.compile(
    r"\b(?:Cpl|Sgt|Lt|Capt|Det|Ofc|Officer|Patrolman|Deputy|Sergeant|"
    r"Corporal|Lieutenant|Captain|Chief)\.?[ ]+"
    r"[A-Z][A-Za-z.'-]+(?:[ ]+[A-Z][A-Za-z.'-]+){0,2}"
)

# Place name before a law-enforcement organization, e.g. "Fort Smith Police".
_ORG_LOCATION_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})\s+"
    r"(?:Police Department|Sheriff(?:'s)? Office|Fire Department|"
    r"County Sheriff)\b"
)
# "City, ST" style location.
_CITY_STATE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)?,\s*[A-Z]{2})\b"
)

# Crime-specific keywords; broad administrative terms are handled separately.
_INCIDENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Theft / Robbery",
        (
            r"\brobber(?:y|ies)\b",
            r"\brobbed\b",
            r"\bburglar(?:y|ies|s)?\b",
            r"\btheft\b",
            r"\bstolen\b",
            r"\bshoplift(?:ing|ed)?\b",
            r"\blarceny\b",
        ),
    ),
    (
        "Assault / Violence",
        # Avoid equipment false positives.
        (
            r"\bassault(?:s|ed)?\b",
            r"\bassault and battery\b",
            r"\bstabb(?:ing|ed)\b",
            r"(?<!trouble )\bshooting\b",
            r"\bshots fired\b",
            r"\bhomicide\b",
            r"\bmurder\b",
        ),
    ),
    ("Fire / Arson", (r"\barson(?:ist)?\b",)),
    (
        "Traffic Accident",
        (
            r"\bcollision\b",
            r"\btraffic accident\b",
            r"\bcar crash\b",
            r"\bvehicle crash\b",
            r"\bhit[- ]and[- ]run\b",
        ),
    ),
    (
        "Public Disturbance",
        (
            r"\briot(?:ing|s)?\b",
            r"\bvandalism\b",
            r"\bdisturbance\b",
            r"\btrespass(?:ing)?\b",
        ),
    ),
)

# Administrative documents are labeled separately from reported crimes.
ADMIN_INCIDENT_LABEL = "Training / Administrative"
_ADMIN_KEYWORDS: tuple[str, ...] = (
    r"\btraining\b",
    r"\bMRAP\b",
    r"\blesson plan\b",
    r"\boperations?\b",
    r"\bproposal\b",
    r"\b1033 program\b",
    r"\bLESO\b",
    r"\bpolic(?:y|ies)\b",
    r"\bprocedures?\b",
    r"\bcurriculum\b",
    r"\bcertification\b",
    r"\bstandard operating procedure\b",
    r"\bmemorandum\b",
)

# Treat crime mentions as incidental when administrative cues dominate.
_ADMIN_DOMINANCE_RATIO = 5

# Severity signals keyed to a detected incident.
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
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else UNKNOWN


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
    except ImportError as exc:
        logger.info("spaCy import unavailable for PDF location extraction: %s", exc)
        return UNKNOWN
    try:
        nlp = _load_spacy_model(spacy)
        if nlp is None:
            return UNKNOWN
        doc = nlp(text[:5000])
        for ent in doc.ents:
            if ent.label_ in {"GPE", "LOC", "FAC"} and ent.text.strip():
                return ent.text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("spaCy PDF location extraction failed: %s", exc)
        return UNKNOWN
    return UNKNOWN


_SPACY_MODEL: Any = False  # False = not yet loaded; None = unavailable.


def _load_spacy_model(spacy: Any) -> Any:
    global _SPACY_MODEL
    if _SPACY_MODEL is not False:
        return _SPACY_MODEL
    try:
        _SPACY_MODEL = spacy.load("en_core_web_sm")
    except OSError as exc:
        logger.info("spaCy model unavailable for PDF extraction: %s", exc)
        _SPACY_MODEL = None
    return _SPACY_MODEL


def _count_keyword_hits(text: str, patterns: Iterable[str]) -> int:
    """Total occurrences of every pattern in ``patterns`` within ``text``."""

    return sum(
        1 for pattern in patterns for _ in re.finditer(pattern, text, re.IGNORECASE)
    )


def classify_incident(text: str) -> str:
    """Classify source text, favoring administrative context when it dominates."""

    crime_label: str | None = None
    total_crime = 0
    for label, patterns in _INCIDENT_KEYWORDS:
        hits = _count_keyword_hits(text, patterns)
        if hits:
            total_crime += hits
            if crime_label is None:
                crime_label = label  # first category in priority order wins

    admin_hits = _count_keyword_hits(text, _ADMIN_KEYWORDS)

    if crime_label is None:
        # Use the administrative label only when source text supports it.
        return ADMIN_INCIDENT_LABEL if admin_hits else UNKNOWN

    if admin_hits >= _ADMIN_DOMINANCE_RATIO * total_crime:
        # Administrative context outweighs incidental crime terms.
        return ADMIN_INCIDENT_LABEL

    return crime_label


def severity_signal(text: str, incident_type: str) -> str:
    """Map severity, using Low when the event cannot be identified."""

    if incident_type in (UNKNOWN, ADMIN_INCIDENT_LABEL):
        return "Low"
    if _HIGH_SEVERITY.search(text):
        return "High"
    if _MEDIUM_SEVERITY.search(text):
        return "Medium"
    return "Low"


def _extract_context(text: str, keyword: str) -> str:
    """Return a short grounded snippet around a keyword, else Unknown."""

    match = re.search(rf".{{0,80}}\b{keyword}\b.{{0,120}}", text, re.IGNORECASE)
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else UNKNOWN


# Prefer subject/body text over letterhead in summaries.
_SUBJECT_LINE = re.compile(
    r"^[ \t]*(?:RE|Ref|Reference|Subject)\b[ \t]*[:.\-]?[ \t]*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_HEADER_LABEL = re.compile(
    r"^[ \t]*(?:To|From|Date|RE|Ref|Reference|Subject|Phone|Tel|Telephone|"
    r"Fax|Attn|Cell|E-?mail)\b",
    re.IGNORECASE,
)
# Address/contact lines can look like prose but are still letterhead.
_LETTERHEAD_NOISE = re.compile(
    r"\bP\.?\s*O\.?\s*Box\b|\bFax\b|\bTel\b|\bPhone\b|\bSuite\b"
    r"|\d{3}[)\-.\s]\s*\d{3}[\-.\s]\d{4}|\b[A-Z]{2}\s+\d{5}\b|\b\d{5}(?:-\d{4})?\b"
    r"|www\.|\.com\b|@",
    re.IGNORECASE,
)


def _truncate_summary(text: str, max_chars: int) -> str:
    """Collapse whitespace and cut at a sentence boundary near ``max_chars``."""

    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= max_chars:
        return flat
    truncated = flat[:max_chars]
    cut = truncated.rfind(". ")
    if cut >= max_chars // 2:
        return truncated[: cut + 1]
    return truncated.rstrip() + "..."


def _looks_like_body(line: str) -> bool:
    """True for a substantive prose line, not a name/address/contact header."""

    if len(line.split()) < 8 or not re.search(r"[a-z]{3,}", line):
        return False
    return not _LETTERHEAD_NOISE.search(line)


def _strip_letterhead(text: str) -> str:
    """Drop the leading header block, returning text from the first body line."""

    lines = text.split("\n")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _looks_like_body(stripped) and not _HEADER_LABEL.match(stripped):
            return "\n".join(lines[index:])
    return text


def _subject_summary(text: str) -> str | None:
    """Return a descriptive subject/``RE:`` line, else None (absent or too terse)."""

    match = _SUBJECT_LINE.search(text)
    if not match:
        return None
    subject = re.sub(r"\s+", " ", match.group(1)).strip(" .:-")
    if len(subject) < 10 or subject.upper() in {"MRAP", "N/A", "NA"}:
        return None
    return subject


def summarize_document(text: str, *, max_chars: int = 240) -> str:
    """Return a source-grounded lead summary for the PDF draft."""

    normalized = str(text or "")
    if not normalized.strip():
        return UNKNOWN
    subject = _subject_summary(normalized)
    if subject:
        return _truncate_summary(subject, max_chars)
    body = _strip_letterhead(normalized)
    flat = re.sub(r"\s+", " ", body).strip()
    if not flat:
        return UNKNOWN
    return _truncate_summary(flat, max_chars)


def _extract_keyword_sentence(
    text: str, keywords: tuple[str, ...], *, max_chars: int = 180
) -> str:
    """Return the first sentence containing one of the requested keywords."""

    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return UNKNOWN
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    pattern = re.compile("|".join(keywords), re.IGNORECASE)
    for sentence in sentences:
        clean = sentence.strip(" ;:-")
        if clean and pattern.search(clean):
            return _truncate_summary(clean, max_chars)
    return UNKNOWN


def extract_suspect_description(text: str) -> str:
    """Extract a source-grounded suspect description sentence when present."""

    return _extract_keyword_sentence(
        text,
        (
            r"\bsuspect\b",
            r"\bsuspects\b",
            r"\boffender\b",
            r"\bperpetrator\b",
            r"\bdescription\b",
        ),
    )


def extract_outcome(text: str) -> str:
    """Extract a source-grounded outcome/disposition sentence when present."""

    return _extract_keyword_sentence(
        text,
        (
            r"\boutcome\b",
            r"\bdisposition\b",
            r"\barrest(?:ed)?\b",
            r"\bcharged\b",
            r"\bcited\b",
            r"\bcleared\b",
            r"\brecovered\b",
            r"\btransported\b",
            r"\bclosed\b",
        ),
    )


def analyze_document(report_id: str, text: str) -> dict[str, Any]:
    """Convert one document's text into the exact eight-field PDF artifact row."""

    normalized = _normalize_text(text)
    incident_type = classify_incident(normalized)
    # Suspect/outcome fields only apply to classified crime reports.
    is_crime_report = incident_type not in (UNKNOWN, ADMIN_INCIDENT_LABEL)
    return {
        "Report_ID": str(report_id),
        "Incident_Type": incident_type,
        "Date": extract_date(normalized),
        "Location": extract_location(normalized),
        "Officer": extract_officer(normalized),
        "Summary": summarize_document(normalized),
        "Suspect_Description": (
            extract_suspect_description(normalized) if is_crime_report else UNKNOWN
        ),
        "Outcome": extract_outcome(normalized) if is_crime_report else UNKNOWN,
    }


# --- Text extraction (direct first, OCR fallback) ----------------------------


def _extract_text_direct(pdf_path: str) -> str:
    """Extract embedded text with PyMuPDF, falling back to pdfplumber."""

    try:
        import fitz  # type: ignore  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            text = "\n".join(page.get_text() for page in doc)
        if text.strip():
            return text
    except Exception as exc:  # noqa: BLE001
        logger.debug("PyMuPDF direct extraction failed for %s: %s", pdf_path, exc)

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pdfplumber direct extraction failed for %s: %s", pdf_path, exc)
        return ""


def _extract_pages_direct(pdf_path: str) -> list[str]:
    """Return per-page embedded text via PyMuPDF."""

    try:
        import fitz  # type: ignore  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            return [page.get_text() for page in doc]
    except Exception as exc:  # noqa: BLE001
        logger.debug("PyMuPDF page extraction failed for %s: %s", pdf_path, exc)
        return []


# Windows fallback when Tesseract is not on PATH.
_WINDOWS_TESSERACT_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_DEFAULT_PDF_OCR_WORKERS = 8


def _configure_tesseract_cmd(pytesseract: Any) -> None:
    """Configure pytesseract with the first available Tesseract binary."""

    for candidate in (
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        _WINDOWS_TESSERACT_DEFAULT,
    ):
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            logger.debug("Using tesseract binary at %s", candidate)
            return


def _pdf_ocr_worker_count(page_count: int) -> int:
    """Return a bounded OCR worker count for scanned PDF pages."""

    if page_count <= 1:
        return 1

    raw = os.environ.get("PDF_OCR_WORKERS", "").strip()
    if raw:
        try:
            requested = int(raw)
        except ValueError:
            logger.warning("Ignoring invalid PDF_OCR_WORKERS=%r; using default.", raw)
            requested = _DEFAULT_PDF_OCR_WORKERS
    else:
        requested = min(_DEFAULT_PDF_OCR_WORKERS, os.cpu_count() or 1)

    return max(1, min(requested, page_count))


def _pdf_ocr_dependencies() -> tuple[Any, Any, Any] | None:
    try:
        import fitz  # type: ignore  # PyMuPDF
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        logger.info("PDF OCR dependencies are unavailable: %s", exc)
        return None
    return fitz, pytesseract, Image


def _tesseract_available(pytesseract: Any) -> bool:
    _configure_tesseract_cmd(pytesseract)
    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:  # noqa: BLE001
        logger.info("Tesseract is unavailable for PDF OCR: %s", exc)
        return False
    return True


def _ocr_one_pdf_page(
    pdf_path: str,
    index: int,
    *,
    fitz: Any,
    image_cls: Any,
    pytesseract: Any,
) -> tuple[int, str]:
    import io

    with fitz.open(pdf_path) as doc:
        if index >= doc.page_count:
            return index, ""
        page = doc.load_page(index)
        pix = page.get_pixmap(dpi=300)
        with image_cls.open(io.BytesIO(pix.tobytes("png"))) as image:
            image.load()
            return index, pytesseract.image_to_string(image)


def _ocr_pages_sequential(
    wanted: list[int],
    ocr_one_page: Callable[[int], tuple[int, str]],
) -> dict[int, str]:
    result: dict[int, str] = {}
    for index in wanted:
        try:
            page_index, text = ocr_one_page(index)
            result[page_index] = text
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR failed for PDF page %d: %s", index + 1, exc)
    return result


def _ocr_pages_parallel(
    wanted: list[int],
    workers: int,
    ocr_one_page: Callable[[int], tuple[int, str]],
) -> dict[int, str]:
    result: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(ocr_one_page, index): index for index in wanted}
        for future in as_completed(futures):
            index = futures[future]
            try:
                page_index, text = future.result()
                result[page_index] = text
            except Exception as exc:  # noqa: BLE001
                logger.warning("OCR failed for PDF page %d: %s", index + 1, exc)
    return result


def _ocr_pages(
    pdf_path: str, page_indices: Iterable[int]
) -> tuple[dict[int, str], bool]:
    """OCR selected pages and report whether OCR is available."""

    wanted = sorted(set(page_indices))
    if not wanted:
        return {}, True

    dependencies = _pdf_ocr_dependencies()
    if dependencies is None:
        return {}, False
    fitz, pytesseract, image_cls = dependencies
    if not _tesseract_available(pytesseract):
        return {}, False

    workers = _pdf_ocr_worker_count(len(wanted))
    logger.info(
        "OCR'ing %d scanned PDF page(s) with %d worker(s).", len(wanted), workers
    )

    def ocr_one_page(index: int) -> tuple[int, str]:
        return _ocr_one_pdf_page(
            pdf_path,
            index,
            fitz=fitz,
            image_cls=image_cls,
            pytesseract=pytesseract,
        )

    if workers == 1:
        return _ocr_pages_sequential(wanted, ocr_one_page), True
    return _ocr_pages_parallel(wanted, workers, ocr_one_page), True


def _extract_pages_text(pdf_path: str) -> tuple[list[str], list[bool]]:
    """Read embedded text per page and OCR only the scanned (text-less) pages.

    Returns ``(page_texts, page_used_ocr)`` with one entry per page, preserving
    page boundaries so the document can be segmented into per-agency rows. Pages
    with an embedded text layer are read directly and never OCR'd. When OCR is
    unavailable the scanned pages are left empty and a warning is logged rather
    than crashing. Returns a single whole-document "page" when PyMuPDF cannot
    open the file (whole-doc direct extraction, which also tries pdfplumber).
    """

    pages = _extract_pages_direct(pdf_path)
    if not pages:
        return [_extract_text_direct(pdf_path)], [False]

    scanned = [
        i
        for i, page_text in enumerate(pages)
        if len(page_text.strip()) < _MIN_DIRECT_TEXT_CHARS
    ]
    text_pages = len(pages) - len(scanned)
    used_ocr = [False] * len(pages)

    if not scanned:
        logger.info("Read %d page(s), all from an embedded text layer.", len(pages))
        return pages, used_ocr

    ocr_by_index, ocr_available = _ocr_pages(pdf_path, scanned)
    if not ocr_available:
        logger.warning(
            "OCR unavailable (pytesseract or the tesseract binary is not "
            "installed): %d scanned page(s) skipped; only %d text-layer "
            "page(s) of %d were read.",
            len(scanned),
            text_pages,
            len(pages),
        )
        return pages, used_ocr

    for i in scanned:
        page_text = ocr_by_index.get(i, "")
        if page_text.strip():
            pages[i] = page_text
            used_ocr[i] = True
    logger.info(
        "Read %d page(s): %d from embedded text, %d via OCR.",
        len(pages),
        text_pages,
        sum(used_ocr),
    )
    return pages, used_ocr


def _extract_text_ocr(pdf_path: str) -> str:
    """OCR every page (whole-document fallback for the injected-extractor path).

    Used only when a caller passes no ``ocr_extractor`` but the document-level
    path needs OCR. Returns ``""`` when OCR is unavailable.
    """

    try:
        import fitz  # type: ignore  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not open %s for document-level OCR: %s", pdf_path, exc)
        return ""

    ocr_by_index, ocr_available = _ocr_pages(pdf_path, range(page_count))
    if not ocr_available:
        logger.warning("OCR unavailable; document-level OCR fallback produced no text.")
        return ""
    return "\n".join(ocr_by_index.get(i, "") for i in range(page_count))


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract text from every PDF page, OCR'ing scanned pages when possible."""

    pages, _used_ocr = _extract_pages_text(str(pdf_path))
    return "\n".join(page for page in pages if page.strip())


def _validate_pdf_path(pdf_path: str | Path) -> Path:
    path = Path(pdf_path).expanduser()
    if path.is_dir():
        raise IsADirectoryError(f"Expected a PDF file, but got a directory: {path}")
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
    """Process one PDF and return the eight-column PDF draft.

    Direct text extraction is tried per page; scanned or near-empty pages are
    OCR'd when possible. When ``write_artifact`` is true, the same eight-column
    result is written under ``pdf/output/``.
    """

    path = _validate_pdf_path(pdf_path)

    if text_extractor is None and ocr_extractor is None:
        text = extract_pdf_text(path)
    else:
        text = (text_extractor or _extract_text_direct)(str(path))
        if len(text.strip()) < _MIN_DIRECT_TEXT_CHARS:
            text = (ocr_extractor or _extract_text_ocr)(str(path))

    artifact_rows = [analyze_document(report_id or "RPT_001", text)]

    if write_artifact:
        return save_artifact(artifact_rows, output_csv_path)
    return pd.DataFrame(artifact_rows, columns=ARTIFACT_COLUMNS).fillna(UNKNOWN)


def process_pdf(
    pdf_path: str | Path,
    output_csv_path: str | Path | None = None,
    report_id: str | None = None,
) -> pd.DataFrame:
    """Process one PDF file or folder and return the eight-column draft."""

    path = Path(pdf_path).expanduser()
    if path.is_dir():
        return process_pdf_folder(path, output_csv_path)
    return process_pdf_file(
        str(path),
        report_id=report_id,
        write_artifact=True,
        output_csv_path=output_csv_path,
    )


def process_pdf_folder(
    folder_path: str | Path,
    output_csv_path: str | Path | None = None,
    *,
    text_extractor: Callable[[str], str] | None = None,
    ocr_extractor: Callable[[str], str] | None = None,
    write_artifact: bool = True,
) -> pd.DataFrame:
    """Process supported top-level PDFs in a folder into one draft CSV."""

    folder = Path(folder_path).expanduser()
    if not folder.is_dir():
        raise NotADirectoryError(f"PDF folder not found: {folder}")

    pdf_files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS
    )
    if not pdf_files:
        supported = ", ".join(sorted(SUPPORTED_PDF_EXTENSIONS))
        raise ValueError(
            f"No supported PDF files found in {folder}. Expected: {supported}"
        )

    frames = [
        process_pdf_file(
            str(path),
            report_id=f"RPT_{index:03d}",
            text_extractor=text_extractor,
            ocr_extractor=ocr_extractor,
            write_artifact=False,
        )
        for index, path in enumerate(pdf_files, start=1)
    ]
    frame = pd.concat(frames, ignore_index=True)
    if write_artifact:
        return save_artifact(frame.to_dict("records"), output_csv_path)
    return frame


def save_artifact(
    artifact_rows: list[dict[str, Any]],
    output_csv_path: str | Path | None = None,
) -> pd.DataFrame:
    """Write artifact rows with the exact PDF column order and return them."""

    output = (
        Path(output_csv_path).expanduser()
        if output_csv_path
        else (_DEFAULT_OUTPUT_DIR / _DEFAULT_ARTIFACT_NAME)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(artifact_rows, columns=ARTIFACT_COLUMNS).fillna(UNKNOWN)
    frame.to_csv(output, index=False)
    return frame


def build_parser() -> argparse.ArgumentParser:
    """Build the PDF processor command-line parser."""

    parser = argparse.ArgumentParser(
        description="Extract incident fields from official PDF documents."
    )
    parser.add_argument(
        "--input", required=True, help="A supported .pdf file or folder"
    )
    parser.add_argument(
        "--report-id", default=None, help="Optional Report_ID for the artifact row"
    )
    parser.add_argument("--output", default=None, help="Optional artifact CSV path")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the PDF processor command-line interface."""

    # Surface page/OCR extraction details.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = Path(args.input).expanduser()
    try:
        if input_path.is_dir():
            frame = process_pdf_folder(input_path, output_csv_path=args.output)
        elif input_path.is_file():
            frame = process_pdf_file(
                str(input_path),
                report_id=args.report_id,
                output_csv_path=args.output,
            )
        else:
            parser.error(f"Input path does not exist: {input_path}")
    except (NotADirectoryError, ValueError) as exc:
        parser.error(str(exc))
    print(frame.to_string(index=False))
    print(f"Returned {len(frame)} PDF row(s) for {input_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_COLUMNS",
    "analyze_document",
    "classify_incident",
    "extract_pdf_text",
    "process_pdf",
    "process_pdf_file",
    "process_pdf_folder",
    "save_artifact",
    "summarize_document",
]
