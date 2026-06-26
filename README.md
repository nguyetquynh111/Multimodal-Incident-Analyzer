# Multimodal Incident Analyzer

A Streamlit class prototype that converts one uploaded evidence file into one
or more structured incident records. It supports audio, PDF, image, video, and
text evidence, then stores confirmed records in Supabase.

## What It Does

1. Upload one supported file.
2. Run the matching modality processor.
3. Standardize the draft rows, generate summaries and incident IDs.
4. Review the final rows and confirm insertion.
5. Filter, inspect, and export Supabase records from the dashboard.

Supported uploads:

```text
Audio: .wav, .mp3, .m4a
PDF:   .pdf
Image: .jpg, .jpeg, .png
Video: .mp4, .mov, .mpg, .mpeg (maximum five minutes)
Text:  .txt, .csv
```

JSON uploads are intentionally unsupported.

## Quick Start

Python 3.10 is the supported local runtime. FFmpeg is required for audio
transcription; Tesseract is required only for scanned-PDF OCR.

```bash
conda create -n multimodal-incident-analyzer python=3.10 -y
conda activate multimodal-incident-analyzer
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit. A small text example is available at
`text/samples/social_post.txt`.

## Environment

Copy `.env.example` to `.env`, set `SUPABASE_URL` and `SUPABASE_KEY` for
persistence, and leave `SUPABASE_TABLE=incidents` unless your table is named
differently. Set `OPENROUTER_API_KEY` to use OpenRouter summaries automatically;
without it, the deterministic fallback is used. Set `ROBOFLOW_API_KEY` only when
image inference is needed.
The `incidents` table must contain these fields in this order for export:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

Supabase generates `id` and `created_at`. The app inserts the other seven
fields only after the user confirms the Integration result.

## Output Contracts

Each modality returns its documented draft DataFrame. Integration returns:

```text
Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary
```

The final Supabase export is always read from Supabase and contains the
nine-field table schema above. Missing values are represented as `Unknown`;
severity is one of `Low`, `Medium`, `High`, or `Unknown`, and an `Unknown`
event always has `Low` severity.

## Tests

Run the offline suite:

```bash
RUN_SUPABASE_LIVE_TESTS=0 python -m pytest -q
```

Set `RUN_SUPABASE_LIVE_TESTS=1` only when valid Supabase credentials are
configured and a live CRUD round trip is intended.

The offline suite covers upload routing, all five modality contracts,
Integration, ID generation, Supabase payload mapping, the nine-field export,
and a Streamlit smoke test. Image contract tests use the checked-in samples in
`images/sample_data/` and stub external Roboflow/OCR calls.

## Deployment And Documentation

See [DEPLOYMENT.md](DEPLOYMENT.md) for Cloud Run deployment instructions.
Project requirements and detailed contracts live in:

- [PRD](docs/PRD.md)
- [Specifications](docs/specs.md)
- [Rules](docs/rules.md)
- [Technical design](docs/tech.md)
- [Tickets](docs/tickets.md)
