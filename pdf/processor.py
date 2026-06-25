"""Public PDF processing API.

Produces two deliberately distinct outputs from one official document:

1. A demonstration *artifact* CSV with the exact PDF columns
   ``Report_ID, Incident_Type, Date, Location, Officer, Summary,
   Suspect_Description, Outcome`` written under ``pdf/output/``.
2. The shared *extractor contract* DataFrame
   ``source_filename, source_type, raw_event, raw_location, raw_time,
   raw_severity, confidence, raw_text`` returned in memory for Integration.

Text is extracted directly first (PyMuPDF, then pdfplumber). OCR
(pytesseract) is applied *page by page* and only to pages that have no
embedded text layer (scanned images); pages that already contain text are
read directly and never needlessly OCR'd. When pytesseract or its system
binary is unavailable, the scanned pages are skipped gracefully (with a
logged warning) rather than crashing. spaCy NER is used to help pull entities
when available, but no field is ever invented: a field with no real match
becomes ``Unknown``.

When one PDF bundles several agencies' stapled letters/proposals, the per-page
text is split into one row per document via content-based boundary detection
(:func:`segment_pages`) -- a new letterhead, cover letter, or policy/SOP title
page that names a different agency -- so each agency becomes its own
``RPT_NNN`` row with fields drawn only from that agency's pages.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
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

# Below this many characters, a page's direct extraction is treated as having
# no usable text layer (scanned-image page), making it a candidate for OCR.
# Also used for the document-level empty check on the injected-extractor path.
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
        # "battery" only counts in the violent phrase "assault and battery"; bare
        # "battery" matched hardware like "Battery Powered ... Unit" (a false hit).
        # "shooting" excludes the IT/maintenance phrase "trouble shooting", which
        # is pervasive in equipment training material and is not a crime; a real
        # "shooting" (e.g. a courthouse shooting) still matches.
        (r"\bassault(?:s|ed)?\b", r"\bassault and battery\b", r"\bstabb(?:ing|ed)\b",
         r"(?<!trouble )\bshooting\b", r"\bshots fired\b", r"\bhomicide\b", r"\bmurder\b"),
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

# Fallback label for official documents that are administrative rather than a
# reported crime (training plans, policies, 1033-program proposals, lesson
# plans). Triggered only after every crime category above has failed, so a
# genuine crime keyword always wins. These are document-type cues present in
# the text itself, so the label is still source-grounded, never invented.
ADMIN_INCIDENT_LABEL = "Training / Administrative"
_ADMIN_KEYWORDS: tuple[str, ...] = (
    r"\btraining\b", r"\bMRAP\b", r"\blesson plan\b", r"\boperations?\b",
    r"\bproposal\b", r"\b1033 program\b", r"\bLESO\b", r"\bpolic(?:y|ies)\b",
    r"\bprocedures?\b", r"\bcurriculum\b", r"\bcertification\b",
    r"\bstandard operating procedure\b", r"\bmemorandum\b",
)

# Document-type weighting. An official bundle can mention a past incident in
# passing ("a shooting in our courthouse in 2011") or carry crime-shaped words
# inside training material ("trouble shooting"). When administrative cues
# outnumber crime hits by at least this ratio, the document is treated as
# administrative rather than a crime report. A genuine crime report is crime-
# keyword dense, so this wide margin does not suppress real crime detection.
_ADMIN_DOMINANCE_RATIO = 5

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
    # Collapse any internal whitespace (the pattern can span an OCR line break,
    # e.g. "July 2,\n2014") so the field is a single clean line.
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


def _count_keyword_hits(text: str, patterns: Iterable[str]) -> int:
    """Total occurrences of every pattern in ``patterns`` within ``text``."""

    return sum(
        1
        for pattern in patterns
        for _ in re.finditer(pattern, text, re.IGNORECASE)
    )


def classify_incident(text: str) -> str:
    """Return an incident label for the document text.

    A crime-specific category wins whenever its keywords are genuinely present
    *and* not swamped by administrative cues. Document-type weighting guards
    against a stray crime word (e.g. an official bundle mentioning a past
    "shooting", or "trouble shooting" in training material) flipping an
    overwhelmingly administrative document: when administrative cues outnumber
    crime hits by ``_ADMIN_DOMINANCE_RATIO`` or more, the label falls back to
    ``ADMIN_INCIDENT_LABEL``. The margin is wide, so a genuine crime report
    (which is crime-keyword dense) is never misclassified. ``Unknown`` remains
    only for text that matches neither crime nor administrative cues.
    """

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
        # No crime keywords at all: administrative fallback when official cues
        # are present, else genuinely unknown.
        return ADMIN_INCIDENT_LABEL if admin_hits else UNKNOWN

    if admin_hits >= _ADMIN_DOMINANCE_RATIO * total_crime:
        # Crime word(s) present but incidental in an overwhelmingly
        # administrative document (e.g. a training/policy bundle).
        return ADMIN_INCIDENT_LABEL

    return crime_label


def severity_signal(text: str, incident_type: str) -> str:
    """Map severity only when a real *crime* incident was detected (rules.md 7).

    Administrative/training documents are not crimes, so crime-severity words
    they happen to mention (e.g. "gunfire", "weapons") must not be read as a
    High/Medium severity; they map to ``Unknown`` like the no-incident case.
    """

    if incident_type in (UNKNOWN, ADMIN_INCIDENT_LABEL):
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


# Letterhead/cover-page cues used to summarize the document's substance rather
# than its header block (names, address, phone numbers). A subject/``RE:`` line
# is the clearest one-line description when present; otherwise the first
# substantive body sentence after the letterhead is used.
_SUBJECT_LINE = re.compile(
    r"^[ \t]*(?:RE|Ref|Reference|Subject)\b[ \t]*[:.\-]?[ \t]*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_HEADER_LABEL = re.compile(
    r"^[ \t]*(?:To|From|Date|RE|Ref|Reference|Subject|Phone|Tel|Telephone|"
    r"Fax|Attn|Cell|E-?mail)\b",
    re.IGNORECASE,
)
# Address/contact lines that can be long enough to look like prose but are still
# letterhead, e.g. "440 Dee Dee Lane Lonoke, AR 72086 Office 501-676-3001".
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
    """Return a source-grounded lead summary (the LLM summary is separate).

    Prefers the document's subject/``RE:`` line when it is descriptive, since
    that is the clearest one-line statement of what a letter/memo is about.
    Otherwise it skips the letterhead block (names, address, phone numbers) and
    returns the first substantive body sentence, truncated. Falls back to the
    raw text only when no body line is found, and never returns bare letterhead.
    """

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


def analyze_document(report_id: str, text: str) -> dict[str, Any]:
    """Convert one document's text into the exact eight-field PDF artifact row."""

    normalized = _normalize_text(text)
    incident_type = classify_incident(normalized)
    # Suspect / outcome only make sense for an actual crime report. On an
    # administrative or unclassified document the literal words "suspect"/
    # "outcome" appear incidentally (e.g. boilerplate), so the keyword-context
    # grab yields meaningless fragments like "suspect."; suppress to Unknown.
    is_crime_report = incident_type not in (UNKNOWN, ADMIN_INCIDENT_LABEL)
    return {
        "Report_ID": str(report_id),
        "Incident_Type": incident_type,
        "Date": extract_date(normalized),
        "Location": extract_location(normalized),
        "Officer": extract_officer(normalized),
        "Summary": summarize_document(normalized),
        "Suspect_Description": _extract_context(normalized, "suspect") if is_crime_report else UNKNOWN,
        "Outcome": _extract_context(normalized, "outcome") if is_crime_report else UNKNOWN,
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


# --- Multi-document segmentation ---------------------------------------------
# One uploaded PDF can be a bundle of several agencies' stapled letters/
# proposals. Boundaries are detected from content (a new letterhead, cover
# letter, or policy/SOP title page that names a *different* agency), never a
# fixed page count, so agencies of differing lengths each become one row.

_AGENCY_NAME = re.compile(
    r"([A-Z][A-Za-z.'’]+(?:\s+[A-Z][A-Za-z.'’]+){0,3})\s+"
    r"(Police Department|Sheriff[’']?s?\s+(?:Office|Department)|County Sheriff)",
    re.IGNORECASE,
)
# Words that are never part of an agency's distinctive place name; stripped when
# building its identity key so OCR prose like "...for the police department"
# is not mistaken for a new agency.
_AGENCY_STOPWORDS = frozenset({
    "the", "by", "to", "of", "a", "at", "that", "this", "you", "our", "with",
    "from", "for", "in", "on", "office", "program", "agencies", "duties",
    "their", "and", "commander", "maintenance", "personnel", "be", "obtained",
    "members", "all", "general", "policies", "issuing", "local", "mrap",
    "asst.", "chief", "deputy", "sheriff", "county", "state", "arkansas", "is",
    "are", "as", "an", "or", "it", "will", "shall", "department", "officers",
    "officer", "city",
})
# Strong "a new stapled document starts here" cues.
_DOC_START = re.compile(
    r"To:?\s*Whom\s+it\s+may\s+[Cc]oncern"
    r"|\b(?:RE|Ref)[:.]?\s*MRAP\b"
    r"|\bMEMORANDUM\b"
    r"|POLICIES\s+AND\s+PROCEDURES"
    r"|DIVISIONAL\s+OPERATING\s+PROCEDURE"
    r"|Standard\s+Operating\s+Procedure"
    r"|\bCover\s+Sheet\b",
    re.IGNORECASE,
)
_CONTACT_HINT = re.compile(
    r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}|Tel:|Phone:|Fax", re.IGNORECASE
)
# Only the page header (first chars) is trusted for a boundary, so body prose
# that merely mentions another agency cannot split one long document.
_HEADER_WINDOW = 400


def _agency_identity(name: str) -> tuple[str, str]:
    """Reduce a matched org name to a ``(place, kind)`` boundary identity."""

    kind = "police" if re.search(r"police", name, re.IGNORECASE) else "sheriff"
    tokens = [
        token
        for token in re.split(r"\s+", name.strip())
        if token
        and token.lower() not in _AGENCY_STOPWORDS
        and not re.fullmatch(
            r"(?:police|department|sheriff|sheriff's|county|office)",
            token,
            re.IGNORECASE,
        )
    ]
    place = re.sub(r"[^a-z ]", "", " ".join(tokens).lower().replace("’", "'")).strip()
    return place, kind


def _first_agency(window: str) -> tuple[str, str] | None:
    for match in _AGENCY_NAME.finditer(window):
        place, kind = _agency_identity(match.group(1) + " " + match.group(2))
        if place:
            return place, kind
    return None


def _primary_agency(text: str) -> tuple[str, str] | None:
    """Best-effort agency identity for a page (header first, then whole page)."""

    return _first_agency(text[:_HEADER_WINDOW]) or _first_agency(text)


def _header_starts_document(head: str) -> bool:
    """True when the page header carries a new-document cue (cover/letterhead/title)."""

    if _DOC_START.search(head):
        return True
    first_line = head.lstrip().split("\n", 1)[0].strip()
    match = _AGENCY_NAME.search(first_line)
    if not match:
        return False
    # A letterhead with a phone, or a short line that is essentially just the
    # agency name (a title/cover page such as "CABOT POLICE DEPARTMENT").
    return bool(
        _CONTACT_HINT.search(head)
        or (match.start() <= 3 and len(first_line) <= 55)
    )


def _header_agency(text: str) -> tuple[str, str] | None:
    """Agency identity only when the header both names an agency and starts a doc."""

    head = text[:_HEADER_WINDOW]
    return _first_agency(head) if _header_starts_document(head) else None


def _same_agency(
    a: tuple[str, str] | None, b: tuple[str, str] | None
) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    (place_a, kind_a), (place_b, kind_b) = a, b
    return (
        kind_a == kind_b
        and bool(place_a)
        and bool(place_b)
        and (place_a in place_b or place_b in place_a)
    )


def segment_pages(pages: list[str]) -> list[list[int]]:
    """Group page texts into one index list per detected stapled document.

    A new segment begins at a page whose header both starts a new document and
    names a *different* agency than the running one; every other page (including
    OCR-only continuation pages) stays with the current segment. A single-page
    input, or one where no boundary is found, yields one segment covering all
    pages. Returns ``[]`` for empty input.
    """

    if len(pages) <= 1:
        return [list(range(len(pages)))] if pages else []

    groups: list[list[int]] = []
    current_agency: tuple[str, str] | None = None
    for index, text in enumerate(pages):
        header = _header_agency(text)
        starts_new = header is not None and (
            not groups or not _same_agency(header, current_agency)
        )
        if starts_new or not groups:
            groups.append([index])
            current_agency = header or _primary_agency(text)
        else:
            if current_agency is None:
                current_agency = _primary_agency(text)
            groups[-1].append(index)
    return groups


# --- Text extraction (page-aware: direct per page, OCR scanned pages only) ---

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


def _extract_pages_direct(pdf_path: str) -> list[str]:
    """Return per-page embedded text via PyMuPDF.

    The list has one entry per page; a page with no text layer yields ``""``.
    Returns ``[]`` if PyMuPDF cannot open or iterate the document, signalling
    the caller to fall back to whole-document direct extraction.
    """

    try:
        import fitz  # type: ignore  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            return [page.get_text() for page in doc]
    except Exception:
        return []


# Default install location of the Tesseract engine on Windows. Used as a last
# resort when the binary is not on PATH and no override is set.
_WINDOWS_TESSERACT_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _configure_tesseract_cmd(pytesseract: Any) -> None:
    """Point pytesseract at a runnable tesseract binary when it is not on PATH.

    Resolution order, most explicit first:
      1. the ``TESSERACT_CMD`` environment variable, so a teammate or grader can
         point at their own install without editing code;
      2. ``tesseract`` already discoverable on PATH (``shutil.which``);
      3. the default Windows install path.
    The first existing candidate is set as ``tesseract_cmd``. If none exist this
    is a no-op and the caller's version probe still decides OCR availability, so
    a missing engine degrades gracefully rather than crashing.
    """

    for candidate in (
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        _WINDOWS_TESSERACT_DEFAULT,
    ):
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            logger.debug("Using tesseract binary at %s", candidate)
            return


def _ocr_pages(pdf_path: str, page_indices: Iterable[int]) -> tuple[dict[int, str], bool]:
    """OCR only the given page indices.

    Returns ``(text_by_index, ocr_available)``. ``ocr_available`` is ``False``
    when pytesseract or its system ``tesseract`` binary is missing, in which
    case nothing is OCR'd and the caller skips the scanned pages instead of
    crashing. Pages not listed in ``page_indices`` are never rendered/OCR'd.
    """

    wanted = set(page_indices)
    if not wanted:
        return {}, True

    try:
        import fitz  # type: ignore  # PyMuPDF
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return {}, False

    # Locate the engine (PATH / TESSERACT_CMD / known Windows path) before the
    # probe; pytesseract defaults to a bare "tesseract" that fails when the
    # binary is installed but not on PATH.
    _configure_tesseract_cmd(pytesseract)

    # The Python binding can import even when the tesseract executable is not
    # installed; this probe confirms the binary is actually runnable.
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return {}, False

    import io

    result: dict[int, str] = {}
    try:
        with fitz.open(pdf_path) as doc:
            for index, page in enumerate(doc):
                if index not in wanted:
                    continue
                pix = page.get_pixmap(dpi=300)  # higher DPI improves OCR accuracy
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                result[index] = pytesseract.image_to_string(image)
    except Exception:
        # Partial OCR is still useful; the binary was available, so report so.
        return result, True
    return result, True


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
        i for i, page_text in enumerate(pages)
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
            len(scanned), text_pages, len(pages),
        )
        return pages, used_ocr

    for i in scanned:
        page_text = ocr_by_index.get(i, "")
        if page_text.strip():
            pages[i] = page_text
            used_ocr[i] = True
    logger.info(
        "Read %d page(s): %d from embedded text, %d via OCR.",
        len(pages), text_pages, sum(used_ocr),
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
    except Exception:
        return ""

    ocr_by_index, ocr_available = _ocr_pages(pdf_path, range(page_count))
    if not ocr_available:
        logger.warning("OCR unavailable; document-level OCR fallback produced no text.")
        return ""
    return "\n".join(ocr_by_index.get(i, "") for i in range(page_count))


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

    By default, extraction is page-aware: each page's embedded text is read
    directly and only pages with no text layer (scanned images) are OCR'd. The
    per-page text is then segmented into one row per stapled document/agency
    (see :func:`segment_pages`), and the eight-field pipeline runs independently
    on each segment, so a bundle of several agencies yields several rows
    (``RPT_001``, ``RPT_002``, ...) instead of one. OCR is skipped gracefully
    when its dependencies are missing. When ``write_artifact`` is true the
    eight-column demo artifact is also written under ``pdf/output/``. The
    returned DataFrame is the in-memory pipeline contract and is never the
    primary on-disk output.

    ``report_id`` is honoured only on the injected-extractor path below; the
    default page-aware path numbers its segments ``RPT_NNN`` automatically.

    Passing ``text_extractor`` and/or ``ocr_extractor`` switches to a
    document-level path: the whole document is read with ``text_extractor`` and
    OCR runs only when that result is empty/near-empty. That seam supplies
    whole-document text with no page boundaries, so it yields a single row and
    keeps custom pipelines and tests in control of both stages.
    """

    path = _validate_pdf_path(pdf_path)

    if text_extractor is None and ocr_extractor is None:
        # Default production path: page-aware extraction split into one row per
        # stapled document (agency). The whole document is never re-run per
        # segment; each segment's own page text drives its fields and raw_text.
        page_texts, page_ocr = _extract_pages_text(str(path))
        groups = segment_pages(page_texts) or [list(range(len(page_texts)))]
        artifact_rows = []
        frames: list[pd.DataFrame] = []
        for number, indices in enumerate(groups, start=1):
            segment_text = "\n".join(page_texts[i] for i in indices)
            segment_used_ocr = any(page_ocr[i] for i in indices)
            row = analyze_document(f"RPT_{number:03d}", segment_text)
            artifact_rows.append(row)
            frames.append(
                map_to_extractor([row], path.name, segment_text, segment_used_ocr)
            )
        extractor_df = (
            pd.concat(frames, ignore_index=True)
            if frames
            else map_to_extractor([], path.name, "", False)
        )
        logger.info("Detected %d document segment(s) in %s.", len(groups), path.name)
    else:
        # Injected-extractor path: document-level direct, OCR-on-empty fallback.
        # This seam supplies whole-document text (no page boundaries), so it
        # intentionally yields a single row and honours ``report_id``.
        text = (text_extractor or _extract_text_direct)(str(path))
        used_ocr = False
        if len(text.strip()) < _MIN_DIRECT_TEXT_CHARS:
            text = (ocr_extractor or _extract_text_ocr)(str(path))
            used_ocr = True
        artifact_rows = [analyze_document(report_id or "RPT_001", text)]
        extractor_df = map_to_extractor(artifact_rows, path.name, text, used_ocr)

    if write_artifact:
        save_artifact(artifact_rows, output_csv_path)

    return extractor_df


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

    # Surface the page/OCR extraction summary (and any OCR-skipped warning).
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
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
    "segment_pages",
    "summarize_document",
]
