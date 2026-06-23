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

## PDF Processor

Tickets T-009 / T-010. Converts one PDF document into two distinct outputs, per
[specs](docs/specs.md) section 5.2:

- An 8-column demo artifact CSV at `pdf/output/pdf_output.csv`
  (`Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome`).
- An in-memory extractor DataFrame consumed by Integration
  (`source_filename, source_type, raw_event, raw_location, raw_time, raw_severity, confidence, raw_text`).

Text is extracted directly first (PyMuPDF, then pdfplumber); OCR (pytesseract) runs
only when direct extraction is empty or near-empty.

Run it:

```python
from pdf.processor import process_pdf_file

extractor_df = process_pdf_file("tests/fixtures/LESO2.pdf")  # also writes the artifact CSV
```

### Test status

`tests/test_extractor_schema.py` and `tests/test_modality_output_schemas.py` —
5 tests passing (extractor-contract columns, OCR fallback path, and artifact CSV
schema with no nulls).

### Design decision (intentional, not open for debate)

On documents with no actual incident, the `Officer` field returns the document's
signer/author name (e.g. `Cpl. Monty McMillen`) rather than `Unknown`, because the
name is real and source-grounded, not fabricated. This is intentional behavior.

### Open items needing team sign-off

1. **Multi-agency bundle.** The current test PDF is a bundle of 5 different agencies'
   submissions in one file. The processor returns a single row using only the first
   agency's info; the other 4 agencies remain in `raw_text` but are not broken out
   into the structured fields. Splitting was deferred given the deadline — documented
   as a known limitation.
2. **All-Unknown rows.** This PDF legitimately produces a row with
   `Incident_Type` / `severity` = `Unknown` and `confidence` = 0.7. Integration
   (T-019+) needs to decide whether to insert or drop all-Unknown rows.
3. **OCR not verified on real scans.** The OCR fallback is unit-tested with a mocked
   OCR result only; it has not yet been verified against a real scanned PDF with a
   real pytesseract install.

## Tests

```bash
pytest
```

## Documentation

See [PRD](docs/PRD.md), [specifications](docs/specs.md), [technical design](docs/tech.md), [rules](docs/rules.md), and [tickets](docs/tickets.md).
