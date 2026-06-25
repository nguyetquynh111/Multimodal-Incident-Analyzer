# Multimodal Incident Analyzer

Class prototype for converting incident evidence into structured records. The audio module uses local Whisper transcription plus keyword, regex, and urgency rules. It does not use an LLM or download Hugging Face models.

## Setup

Python 3.10 and FFmpeg are required for audio files.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Audio Processor

Run commands from the repository root. If your terminal is inside `audio/`, run `cd ..` first.

Process one file:

```bash
python -m audio.processor \
  --input audio/sample_data/call_75_0.wav \
  --output audio/output/audio_results.csv
```

Process the sample folder:

```bash
python -m audio.processor \
  --input audio/sample_data/ \
  --output audio/output/audio_results.csv
```

Test extraction without Whisper:

```bash
python -m audio.processor \
  --demo-transcript "There are guns near Central Station." \
  --output audio/output/audio_results.csv
```

Audio CSV columns are exactly:

```text
Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score
```

## PDF Processor (Student 2 — Document Analyst)

Tickets T-009 / T-010. Extracts structured fields from a PDF police/incident
report — incident type, date, location, officer, suspect description, and
outcome — and converts one document into two distinct outputs, per
[specs](docs/specs.md) section 5.2:

- An 8-column demo artifact CSV at `pdf/output/pdf_output.csv`
  (`Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome`).
- An in-memory extractor DataFrame consumed by Integration
  (`source_filename, source_type, raw_event, raw_location, raw_time, raw_severity, confidence, raw_text`).

Text is extracted directly first with PyMuPDF (`fitz`), falling back to
pdfplumber. Extraction is **page-aware**: each page's embedded text layer is
read directly, and OCR (pytesseract) is applied **only to the scanned, text-less
pages** — pages that already carry a text layer are never re-OCR'd. When
pytesseract or its system binary is unavailable, the scanned pages are skipped
with a logged warning rather than crashing. Field details and the design
rationale are documented in
[docs/student2-document-analyst.md](docs/student2-document-analyst.md).

The document `Summary` field describes the document's *substance*: it prefers
the subject/`RE:` line when present (e.g. "Mine Resistant Ambush Protected
vehicle acquired through 1033 Program") and otherwise the first body sentence,
skipping the letterhead block of names, address, and phone numbers.

### Multi-document bundles (one row per agency)

`LESO2.pdf` is not a single report — it is a **bundle of ~17 agencies' stapled
1033/MRAP proposals** in one file. The processor detects document boundaries
**from content, not a fixed page count**: a new letterhead, cover letter, or
policy/SOP title page that names a *different* agency starts a new segment
(`segment_pages()`), and the eight-field pipeline runs independently on each
segment. So the bundle produces **one `RPT_NNN` row per agency** (Benton County
Sheriff = `RPT_001`, Benton PD = `RPT_002`, Bryant PD = `RPT_003`, …), each with
a `Location`/`Officer`/`Summary` drawn only from that agency's pages and a
segment-scoped `raw_text`.

Known boundary-detection / extraction caveats (OCR-driven, documented honestly):
- **Mississippi County Sheriff** shares a row with Lonoke County, because its
  OCR'd letterhead reads "County of Mississippi / State of Arkansas / SHERIFF'S
  DEPARTMENT" — a form the agency-name matcher does not catch.
- **RPT_012 (Little Rock) has the weakest extraction in the dataset.** Its
  source is a 30-page aviation SOP — an aircraft procedure structurally unlike
  the other agencies' MRAP letters — so *both* of its free-text fields are
  degraded: `Officer` reads "Sergeant Responsibilities" and `Summary` is the
  bare fragment "to the following restrictions". (The Crawford cover page also
  yields a noisier `Summary` than the cleaner agencies.)
- Three rows leak a leading article into `Location` from OCR — RPT_011
  ("The Jefferson"), RPT_015 ("The Rogers"), and RPT_016 ("The Union County").
  Cosmetic and harmless; the agency identity is still correct.

### Source document

The sample document is `tests/fixtures/LESO2.pdf` — a MuckRock FOIA bundle of
Arkansas law-enforcement agencies' 1033 / MRAP training proposals (Benton
County, Fort Smith, Hot Springs, Jacksonville, Little Rock, Lonoke, Union, …).
Every agency is correctly classified as `Training / Administrative` (not a crime
report), so `Suspect_Description` and `Outcome` are `Unknown` by design.

### Performance note (read before a live demo)

This document is **75 pages, of which ~65 are scanned images** with no text
layer. Those pages go through OCR at 300 DPI, so a full run takes **several
minutes** (~5 min on a typical laptop). This is expected — do **not** mistake it
for a hang during a presentation. Pre-generate `pdf/output/pdf_output.csv`
before demoing rather than running OCR live.

Run it (CLI):

```bash
python -m pdf.processor --input tests/fixtures/LESO2.pdf
```

Run it (Python):

```python
from pdf.processor import process_pdf_file

extractor_df = process_pdf_file("tests/fixtures/LESO2.pdf")  # one row per agency; also writes the CSV
```

### Test status

`tests/test_extractor_schema.py` and `tests/test_modality_output_schemas.py` —
passing. Coverage includes the extractor-contract columns, the OCR fallback
path, the artifact CSV schema with no nulls, **deterministic unit tests for the
multi-document `segment_pages()` splitter and the subject-line summary** (these
two run without OCR), and an end-to-end run over the real scanned pages of
`LESO2.pdf` (the full run takes ~5 min because of the ~65 OCR'd pages).

### Design decision (intentional, not open for debate)

On documents with no actual incident, the `Officer` field returns the document's
signer/author name (e.g. `Cpl. Monty McMillen`) rather than `Unknown`, because the
name is real and source-grounded, not fabricated. This is intentional behavior.

### Open items needing team sign-off

1. **Multi-agency bundle — resolved.** The test PDF bundles ~17 agencies'
   stapled proposals. The processor now splits it into **one row per agency**
   via content-based boundary detection (`segment_pages()`), so each agency's
   fields are broken out instead of only the first. Two OCR-driven caveats
   remain (Mississippi County merged into the Lonoke row; weaker fields on the
   Crawford and Little Rock sections) — see "Multi-document bundles" above.
2. **All-Unknown rows.** Every agency in this bundle classifies as
   `Training / Administrative` with `severity` = `Unknown`, so the rows carry
   `Unknown` event/severity at `confidence` ≈ 0.5–0.9. Integration (T-019+)
   needs to decide whether to insert or drop such rows.
3. **OCR verified on real scans.** Previously the OCR path was unit-tested with a
   mocked result only. It has since been exercised end-to-end against the ~65
   real scanned pages of `LESO2.pdf` with a real pytesseract install (Tesseract
   5.5.0); the full suite passes. The mocked unit test for the fallback seam
   remains in `tests/test_extractor_schema.py`.

## LLM Summarizer (Bonus / Optional)

> **This is the team's optional bonus deliverable** (LLM-based summarization),
> not a required modality. It is owned by Student 2 alongside the Document
> Analyst work.

Generates a short, human-readable narrative summary of an incident from the
**structured** integrated fields (`event`, `location`, `time`, `severity`,
`source`, `raw_text`) — never from raw unprocessed text. It is a separate
package (`llm_summarizer/`) called after Integration and before insert, exactly
one entry point:

```python
from llm_summarizer.summarizer import summarize_incident

result = summarize_incident(incident_row)  # dict with the integrated fields
# -> {"incident_summary": str, "summary_method": str, "summary_model": str}
```

It makes a **real LLM call** — an OpenRouter chat completion
([`llm_summarizer/summarizer.py`](llm_summarizer/summarizer.py)) — with a strict
anti-hallucination system prompt and post-hoc validation (rejects empty,
over-length, or non-prose output). If the LLM is disabled, unavailable, slow, or
returns invalid output, it falls back to a deterministic, dependency-free
rule-based summary ([`llm_summarizer/fallback.py`](llm_summarizer/fallback.py)),
so it always returns a valid result.

### Configuration (env vars)

| Variable | Purpose |
| --- | --- |
| `ENABLE_LLM_SUMMARY` | `true` to attempt the real LLM call; otherwise the deterministic fallback is used (`summary_method = disabled`). |
| `OPENROUTER_API_KEY` | OpenRouter API key for the free-tier model. **Never commit a real key** — `.env` is gitignored; `.env.example` shows the expected format only. |
| `LLM_MODEL_NAME` | Optional model override (default `openai/gpt-oss-20b:free`). |

No paid API is required: with the LLM disabled or unreachable, the rule-based
fallback produces a grounded summary on its own.

### Sample input → output

Crime-style row, **real LLM** output (`summary_method = llm`, model
`openai/gpt-oss-20b:free`):

```text
input:  {event: "Theft / Robbery", location: "Main Street", time: "June 20, 2026",
         severity: "High", source: "pdf",
         raw_text: "A robbery occurred near Main Street on June 20, 2026."}
output: "A high severity theft / robbery event took place on Main Street on
         June 20, 2026, as reported in a PDF source."
```

The administrative `LESO2.pdf` row, **deterministic fallback** output
(`summary_method = disabled`, e.g. when no key is configured):

```text
input:  {event: "Training / Administrative", location: "Benton County",
         time: "May 26, 2015", severity: "Unknown", source: "pdf", ...}
output: "A Training / Administrative incident was reported via pdf at Benton
         County. The reported time was May 26, 2015."
```

### Run it

```python
import os
from dotenv import load_dotenv
from llm_summarizer.summarizer import summarize_incident

load_dotenv()  # reads ENABLE_LLM_SUMMARY / OPENROUTER_API_KEY / LLM_MODEL_NAME
print(summarize_incident({
    "source": "pdf", "source_type": "PDF", "event": "Theft / Robbery",
    "location": "Main Street", "time": "June 20, 2026", "severity": "High",
    "confidence": 0.8,
    "raw_text": "A robbery occurred near Main Street on June 20, 2026.",
}))
```

### Test status

`tests/test_llm_summarizer.py` — **8/8 passing**, covering valid LLM output,
disabled, enabled-but-missing-key, network/exception error, over-length
rejection, and empty-output rejection. Every test injects a fake `llm_call`, so
no test makes a network request or needs an API key.

## Tests

```bash
pytest
```

## Documentation

See [PRD](docs/PRD.md), [specifications](docs/specs.md), [technical design](docs/tech.md), [rules](docs/rules.md), and [tickets](docs/tickets.md).

Per-student design notes: [Student 2 — Document Analyst + LLM Summarizer bonus](docs/student2-document-analyst.md).
