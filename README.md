# Multimodal Incident Analyzer

A classroom prototype that converts audio, PDF, image, video, text, CSV, or JSON evidence into structured incident records.

> This project is for education only. It is not an emergency-response, investigative, or legal decision system.

## Processing Flow

```text
Single-file upload
    -> modality processor
    -> shared pandas DataFrame
    -> integration and severity normalization
    -> LLM summary or rule-based fallback
    -> incident ID
    -> Supabase
    -> dashboard and CSV export
```

One file may produce zero, one, or many incidents. Supabase is the source of truth after insertion.


## Data Contracts

The final CSV contains exactly:

```text
Incident_ID, Source, Event, Location, Time, Severity
```

Missing text values use `Unknown`. Severity is `Low`, `Medium`, or `High`.

## Setup

Python 3.10 is recommended. FFmpeg is required for audio transcription.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Install FFmpeg with your system package manager, then add Supabase values to `.env` when working on the application flow. Never commit credentials or private evidence.

## Audio Processor

Process one audio file:

```bash
python -m src.audio.cli path/to/call.wav
```

Process every supported audio file in a directory:

```bash
python -m src.audio.batch src/audio/test_data
```

Results are written to `src/audio/output/audio_output.csv` with these columns:

```text
Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score
```

## Tests

```bash
python -m pytest
```

## Documentation

- [Product requirements](docs/PRD.md)
- [Functional specifications](docs/specs.md)
- [Technical design](docs/tech.md)
- [Project rules](docs/rules.md)
- [Implementation tickets](docs/tickets.md)
