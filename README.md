# Multimodal Incident Analyzer

Class prototype for converting incident evidence into structured records. The audio module uses local Whisper transcription plus keyword, regex, and urgency rules. It does not use an LLM or download Hugging Face models.

## Pipeline (Stage 1–5)

```text
one file  ──►  modality processor  ──►  DRAFT csv  ──►  integration  ──►  FINAL 6 cols  ──►  Supabase  ──►  dashboard / CSV export
(.wav/.pdf/   (audio/pdf/image/      (per-modality   (integration/    Incident_ID,Source,   incidents      (app.py:
 .png/.mp4/    video/text)            schema)         integration.py)  Event,Location,        table          filter, chart,
 .txt)                                                                 Time,Severity)                        CRUD, export)
```

The **Integration & Dashboard Lead (Student 6)** owns `integration/integration.py`
(Stage 4 merge) and `app.py` (Stage 5 dashboard + CRUD).

## Streamlit App — run it

The app is the demo surface: upload a file, convert it to the final schema,
insert into Supabase, and explore the dashboard.

```bash
# 1) create an isolated virtual environment (run once)
python3 -m venv .venv

# 2) activate it   (bash/zsh shown; fish shell: source .venv/bin/activate.fish)
source .venv/bin/activate

# 3) install dependencies (covers the app + all five modalities)
python -m pip install -r requirements.txt

# 4) run the app   (needs a project-root .env — see "Supabase setup" below)
streamlit run app.py
```

A single `requirements.txt` covers the app, integration, and every modality
processor. Real Whisper audio also needs FFmpeg (`brew install ffmpeg`); without
it audio processing stops with an installation hint. Uploaded audio is always
transcribed and never replaced with a pasted transcript.

The app has four pages:

- **Ingest & Convert** — upload one file → see the draft output → see the final
  six columns → download the CSV or insert into Supabase. Try it with the
  included `samples/social_post.txt`.
- **Integrate** — UNION every modality's `*/output/*.csv` into the unified master
  dataset (the assignment's Final Integration Task), then save it to
  `integration/output/final_incident_dataset.csv` or push it to Supabase.
- **Dashboard** — KPIs, charts (by source / severity / event), filters, and the
  six-column CSV export, all read live from Supabase.
- **Manage Data** — the "add data" buttons: **Add / Edit / Delete** incident rows
  via the `cloud_deployment` CRUD helpers.

### Test the full integrated pipeline

The repo ships **sample outputs for all five modalities** under each `*/output/`
folder, so you can demo the complete Stage-4 merge without running every model:

Or build it programmatically with the data-engineering CLI:

```bash
python -m integration.integration        # merge all */output/*.csv -> final_incident_dataset.csv
```

In the app: **Integrate** → **Build unified dataset** — all five modalities merge
into one table (`AUD-`/`DOC-`/`IMG-`/`VID-`/`TXT-`). **Save to repo** writes
`integration/output/final_incident_dataset.csv`; **Upload all to Supabase** pushes
the rows live; the **Dashboard** then shows them with charts and filters.

To regenerate a modality's output from raw input, run its processor (each writes
to its own `*/output/` folder), then re-run the merge:

```bash
python -m text.processor  samples/social_post.txt --output text/output/text_output.csv
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

The existing `incidents` table is used as-is — `incident_id` stays `int8`, so
**no schema change is required**. To confirm connectivity, open the
**Dashboard** page, or run the optional live round-trip test:

```bash
RUN_SUPABASE_LIVE_TESTS=1 python -m pytest cloud_deployment/tests -k insert_exists
```

With Supabase credentials configured, the live test runs by default and writes
to the configured database before cleaning up its temporary row. Set
`RUN_SUPABASE_LIVE_TESTS=0` in `.env` to disable it and keep pytest offline.

### ID and severity scheme (assignment §4)

- **`incident_id`** is stored as a unique integer. The dashboard and final CSV
  display the derived **modality-prefixed label** `<PREFIX>-<NNN>` (e.g.
  `AUD-008`), built from `source` + `incident_id`. Prefixes: Audio→`AUD`,
  PDF→`DOC`, Image→`IMG`, Video→`VID`, Text→`TXT`. Numbering is global, so
  labels are unique but not reset per modality (you may see `AUD-001`,
  `DOC-002`). For strictly per-modality numbering (`AUD-001`, `DOC-001`), change
  the `incident_id` column to `text` and store the labels directly.
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

Python 3.10+ works (tested on 3.13). FFmpeg is required for real audio
transcription. This installs the same single `requirements.txt` as the app
above — in fish, activate with `source .venv/bin/activate.fish`.

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

Tickets T-009 / T-010. Converts one PDF document into one six-column output, per
[specs](docs/specs.md) section 5.2:

- A six-column DataFrame and CSV at `pdf/output/pdf_output.csv`
  (`Report_ID, Incident_Type, Date, Location, Officer, Summary`).

Text is extracted directly first (PyMuPDF, then pdfplumber); OCR (pytesseract) runs
only when direct extraction is empty or near-empty.

Run it:

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
