# Multimodal Crime / Incident Report Analyzer

An educational class prototype that converts one uploaded incident-evidence file into zero, one, or many structured incident records. The approved MVP uses a Streamlit single-file upload flow, synchronous local processing, pandas DataFrames between modules, and Supabase Postgres as the source of truth after insertion.

> This project is a classroom prototype. It is not production emergency-response software, investigative evidence, or a legal decision system.

## Approved Processing Flow

```text
Streamlit single-file upload
        ↓
File-type detection and extractor routing
        ↓
Extractor DataFrame
        ↓
Integration and severity normalization
        ↓
Local/free LLM summary or deterministic fallback
        ↓
INC_TYPE_NUMBER ID generation
        ↓
Supabase incidents table
        ↓
Dashboard review and six-column CSV export
```

The dashboard and final export must read from Supabase. Local modality CSV files are compatibility templates only and are not the persistent source of truth.

## Supported Inputs

| Type | Extensions | Abbreviation | MVP behavior |
| --- | --- | --- | --- |
| Audio | `.wav`, `.mp3`, `.m4a` | `AUD` | Transcribe or fall back safely, then extract incident signals |
| PDF | `.pdf` | `PDF` | Extract text with optional OCR fallback |
| Image | `.jpg`, `.jpeg`, `.png` | `IMG` | Extract OCR and object signals |
| Video | `.mp4`, `.mov` | `VID` | Reject clips over five minutes and sample short videos |
| Text | `.txt` | `TXT` | Extract incident fields from text |
| CSV | `.csv` | `CSV` | Map incident-like rows into the extractor schema |
| JSON | `.json` | `JSON` | Map incident-like objects into the extractor schema |

Exactly one file is uploaded per processing run. One file may produce multiple incident rows.

## Data Contracts

Every extractor returns a pandas DataFrame with these columns:

```text
source_filename, source_type, raw_event, raw_location, raw_time, raw_severity, confidence, raw_text
```

Integration receives that DataFrame in memory. Missing values use `Unknown`, and final severity is normalized to `Low`, `Medium`, or `High`.

The final submission CSV is generated from Supabase with exactly:

```text
Incident_ID, Source, Event, Location, Time, Severity
```

Incident IDs use a source-specific format such as `INC_AUD_001`, `INC_PDF_001`, or `INC_VID_001`.

## Repository Structure

```text
multimodal-incident-analyzer/
├── README.md
├── requirements.txt
├── .env.example
├── app.py
├── docs/
│   ├── PRD.md
│   ├── specs.md
│   ├── tech.md
│   ├── rules.md
│   └── tickets.md
├── sql/
│   └── create_incidents_table.sql
├── src/
│   ├── file_type.py
│   ├── id_generator.py
│   ├── supabase_client.py
│   ├── extractors/
│   ├── integration/
│   │   ├── integration.py
│   │   ├── severity.py
│   │   └── validators.py
│   ├── llm_summarizer/
│   └── export/
├── diagrams/
│   └── architecture.png
├── reports/
│   └── project_report.md
└── tests/
```

The older modality folders and `dashboard/` scripts remain as compatibility artifacts while the approved implementation moves under `src/` and root `app.py`.

## Setup

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `SUPABASE_URL` and `SUPABASE_KEY` in `.env`. Do not commit `.env`, API keys, credentials, raw evidence, or private data.

## Run the Audio Extractor

```bash
python audio/process_audio.py path/to/call.wav
```

The default local speech model is `facebook/wav2vec2-base-960h`. Its files may download on first use. If transcription dependencies or model files are unavailable, the extractor returns a safe `Unknown` row instead of crashing.

## Run the Completed Application

After the root Streamlit and Supabase tickets are implemented:

```bash
streamlit run app.py
```

The completed app must process one file synchronously, summarize integrated rows, assign IDs, insert them into Supabase, and render dashboard/export data from Supabase.

## Tests

```bash
pytest
```

To run only the completed audio tests:

```bash
python -m unittest discover -s tests -p 'test_audio_processor.py' -v
```

## Project Documentation

- [Product requirements](docs/PRD.md)
- [Functional specifications](docs/specs.md)
- [Technical design](docs/tech.md)
- [Project rules](docs/rules.md)
- [Implementation tickets](docs/tickets.md)

## Safety and Scope

- Use local/free models and deterministic fallbacks; paid APIs are not required.
- Do not upload raw evidence to Supabase Storage for the MVP.
- Do not treat generated summaries or severity labels as official conclusions.
- Keep demonstration samples small and use `FAST_DEMO_MODE=True` when appropriate.
