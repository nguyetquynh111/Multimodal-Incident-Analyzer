# Multimodal Incident Analyzer

Class prototype for converting incident evidence into structured records. The audio module uses local Whisper transcription plus keyword, regex, and urgency rules. It does not use an LLM or download Hugging Face models.

## Pipeline (Stage 1–5)

```text
one file  ──►  modality processor  ──►  draft DataFrame  ──►  integration  ──►  Supabase payload  ──►  Supabase  ──►  dashboard / CSV export
(.wav/.pdf/   (audio/pdf/images/      (per-modality       (integration/    id, created_at,       incidents      (app.py:
 .png/.mp4/    video/text; CSV/JSON    schema)             integration.py)  incident_id, source,  table          filter, chart,
 .txt/.csv/                                                               event, location,                      CRUD, export)
 .json)                                                                   time, severity,
                                                                           summary_by_llm
```

The **Integration & Dashboard Lead (Student 6)** owns `integration/integration.py`
(Stage 4 merge) and `app.py` (Stage 5 dashboard + CRUD).

## Streamlit App — run it

The app is the demo surface: upload a file, convert it to the final schema,
insert into Supabase, and explore the dashboard.

```bash
# 1) create the named conda environment (run once)
conda create -n multimodal-incident-analyzer python=3.10 -y

# 2) activate it
conda activate multimodal-incident-analyzer

# 3) install dependencies
python -m pip install -r requirements.txt

# 4) run the app   (needs a project-root .env — see "Supabase setup" below)
streamlit run app.py
```

A single `requirements.txt` covers the app, integration, and every modality
processor. Real Whisper audio also needs FFmpeg (`brew install ffmpeg`); without
it audio processing stops with an installation hint. Uploaded audio is always
transcribed and never replaced with a pasted transcript.

The app has four pages:

- **Ingest & Convert** — upload one file → see the draft output → see the
  seven-field Integration row → download the nine-field CSV or insert into
  Supabase. Try it with the included `text/samples/social_post.txt`.
- **Integrate** — UNION every modality's `*/output/*.csv` into the unified master
  dataset (the assignment's Final Integration Task), then save it to
  `integration/output/final_incident_dataset.csv` or push it to Supabase.
- **Dashboard** — KPIs, charts (by source / severity / event), filters, and the
  nine-field CSV export, all read live from Supabase.
- **Manage Data** — the "add data" buttons: **Add / Edit / Delete** incident rows
  via the `cloud_deployment` CRUD helpers.

### Test the full integrated pipeline

The repo ships **sample outputs for the model-backed modalities** under each
`*/output/` folder. CSV and JSON uploads are supported as structured text
sources under `text/`, so you can demo the complete Stage-4 merge without
running every model:

Or build it programmatically with the data-engineering CLI:

```bash
python -m integration.integration        # merge all */output/*.csv -> final_incident_dataset.csv
```

In the app: **Integrate** → **Build unified dataset** — modalities merge
into one table (`INC_AUD_001`, `INC_PDF_001`, `INC_IMG_001`, `INC_VID_001`,
`INC_TXT_001`; CSV/JSON inputs also use the `TXT` prefix). **Save to repo** writes
`integration/output/final_incident_dataset.csv`; **Upload all to Supabase** pushes
the rows live; the **Dashboard** then shows them with charts and filters.

To regenerate a modality's output from raw input, run its processor (each writes
to its own `*/output/` folder), then re-run the merge:

```bash
python -m text.processor text/samples/social_post.txt --output text/output/text_output.csv
python -m audio.processor --demo-transcript "There is a fire on Main St" --output audio/output/audio_output.csv
```

## Supabase setup

Credentials are read from a project-root `.env` (locally) or `st.secrets` (on
Streamlit Cloud):

```text
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_KEY=<publishable-or-anon-key>
# Live tests are enabled by default; set this to 0 to keep pytest offline
RUN_SUPABASE_LIVE_TESTS=1
```

The app expects the Supabase `incidents` table to expose these nine fields:

```text
id, created_at, incident_id, source, event, location, time, severity, summary_by_llm
```

`id` and `created_at` are database-generated. The app inserts the other seven
fields. To confirm connectivity, open the **Dashboard** page, or run the
optional live round-trip test:

```bash
RUN_SUPABASE_LIVE_TESTS=1 python -m pytest cloud_deployment/tests -k insert_exists
```

With Supabase credentials configured, the live test runs by default and writes
to the configured database before cleaning up its temporary row. Set
`RUN_SUPABASE_LIVE_TESTS=0` in `.env` to disable it and keep pytest offline.

### ID, summary, and severity scheme

- **`incident_id`** is stored directly as `INC_TYPE_NUMBER`, for example
  `INC_AUD_001`, `INC_PDF_001`, `INC_IMG_001`, `INC_VID_001`, `INC_TXT_001`,
  with CSV/JSON inputs using the `TXT` type. Numbering increments independently
  per type.
- **`summary_by_llm`** is the dashboard/export summary generated through
  OpenRouter when enabled, with deterministic fallback when disabled or failed.
- **Severity** = `score = confidence × 10`, with `0–3 → Low`, `3–7 → Medium`,
  `7–10 → High`. Modalities without a numeric confidence default to `Medium`.

## Deploy the dashboard (Streamlit Community Cloud)

Push the repo, create an app pointing at `app.py`, add `SUPABASE_URL` and
`SUPABASE_KEY` in the app's **Secrets** (see
[`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example)). Note that
`requirements.txt` includes the heavy AI deps (torch, opencv), so the cloud
build is large — for a lighter hosted dashboard, trim it to `streamlit`,
`pandas`, `supabase`, and `python-dotenv`.

## Setup

Python 3.10 is the tested local runtime. Use the named conda environment so
native dependencies such as OpenCV (`cv2`) are installed into the same
environment used by tests and the app. Python 3.13 currently lacks compatible
wheels for several pinned AI dependencies on Intel macOS. FFmpeg is required for
real audio transcription.

```bash
conda create -n multimodal-incident-analyzer python=3.10 -y
conda activate multimodal-incident-analyzer
python -m pip install --upgrade pip setuptools wheel
python -m pip install --only-binary=opencv-python,opencv-python-headless -r requirements.txt
python -m pip uninstall --yes opencv-python opencv-contrib-python
python -m pip install --force-reinstall --no-deps opencv-python-headless==4.10.0.84
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
Tickets T-009 / T-010. Converts one PDF document into one eight-column output, per
[specs](docs/specs.md) section 5.2:

- An eight-column DataFrame and CSV at `pdf/output/pdf_output.csv`
  (`Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome`).

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
(`segment_pages()`), and the eight-column PDF artifact pipeline runs independently on each
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
report).

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

pdf_df = process_pdf_file("tests/fixtures/LESO2.pdf")
```

### Test status

`tests/test_extractor_schema.py` and `tests/test_modality_output_schemas.py` —
5 tests passing (PDF draft columns, OCR fallback path, and CSV schema with no
nulls).

### Design decision (intentional, not open for debate)

On documents with no actual incident, the `Officer` field returns the document's
signer/author name (e.g. `Cpl. Monty McMillen`) rather than `Unknown`, because the
name is real and source-grounded, not fabricated. This is intentional behavior.

### Open items needing team sign-off

1. **Multi-agency bundle.** The current test PDF is a bundle of 5 different agencies'
   submissions in one file. The processor returns a single row using only the first
   agency's info; the other 4 agencies remain in the source document but are not broken out
   into the structured fields. Splitting was deferred given the deadline — documented
   as a known limitation.
2. **All-Unknown rows.** This PDF legitimately produces a row with
   low-signal administrative rows. Integration may insert them if they are useful
   for the class demo, but should not invent crime facts.
3. **OCR not verified on real scans.** The OCR fallback is unit-tested with a mocked
   OCR result only; it has not yet been verified against a real scanned PDF with a
   real pytesseract install.

## Text Processor

Student 5 converts CrimeReport social/news posts into:

```text
Text_ID, Source, Raw_Text, Sentiment, Entities, Topic
```

The processor preserves `Raw_Text`, cleans a separate analysis copy, extracts
`PERSON`, `LOCATION`, `ORGANIZATION`, and `DATE` groups, then classifies one of
`Theft / Robbery`, `Assault / Violence`, `Fire / Arson`, `Traffic Accident`,
`Public Disturbance`, or `Other`. It uses spaCy NER when `en_core_web_sm` is
available and rule-based fallbacks otherwise, so the demo works offline.

The Kaggle CrimeReport download is stored at `text/data/crimereport.txt`. The
download is a JSON Lines `.txt` file: each line is one tweet/news-like record
with fields such as `text`, `created_at`, `source`, `place`, and `user`. The
processor detects that format and emits one structured row per JSON line. The
current dataset produces 115 text rows.

Run the Kaggle dataset:

```bash
python -m text.processor text/data/crimereport.txt --output text/output/text_output.csv --source CrimeReport
python -m integration.integration
```

This writes `text/output/text_output.csv` and rebuilds
`integration/output/final_incident_dataset.csv`. The sample
`text/samples/social_post.txt` is still useful for a one-row smoke test, but it is
not the main Student 5 dataset.

For CSV variants, pass the file path and optionally `--text-column` if the
narrative column is not named `Raw_Text`, `text`, `details`, `report`,
`narrative`, `content`, `post`, `tweet`, `article`, or `summary`.

## Tests

```bash
conda activate multimodal-incident-analyzer
pytest
```

## Documentation

See [PRD](docs/PRD.md), [specifications](docs/specs.md), [technical design](docs/tech.md), [rules](docs/rules.md), and [tickets](docs/tickets.md).

Per-student design notes: [Student 2 — Document Analyst + LLM Summarizer bonus](docs/student2-document-analyst.md).
