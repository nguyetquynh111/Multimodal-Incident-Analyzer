# Multimodal Incident Analyzer

A Streamlit prototype that converts evidence files into structured incident
records. It supports audio, PDF, image, video, text, and structured CSV inputs,
then lets users review and save confirmed records.

## Features

- Process one uploaded evidence file at a time on the Add Incident page.
- Extract modality-specific draft rows from audio, PDFs, images, videos, and text.
- Standardize records with Integration, incident IDs, severity, and summaries.
- Review before inserting into Supabase database.
- Combine completed session reviews into a local seven-field preview.
- Browse, filter, edit, bulk update, delete, and export saved incidents from Supabase.

## Supported Files

```text
Audio: .wav, .mp3, .m4a
PDF:   .pdf
Image: .jpg, .jpeg, .png
Video: .mp4, .mov, .mpg, .mpeg (max 5 minutes)
Text:  .txt, .csv
```

## Quick reference output
[Final merged CSV](integration/output/final_incident_dataset.csv)

## Configuration

Create a local `.env` file.

### Required

```bash
ROBOFLOW_API_KEY=...
```

Used for image object detection and GLM-OCR.

### Optional

```bash
OPENROUTER_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
```

- `OPENROUTER_API_KEY`: enables LLM-generated summaries. Otherwise, deterministic summaries are used.
- `SUPABASE_URL` and `SUPABASE_KEY`: enable data persistence. If omitted, persistence is disabled.

## Quick Start

Python 3.10 is recommended. FFmpeg is required for audio transcription, and
Tesseract is required for PDF OCR.

```bash
conda create -n multimodal-incident-analyzer python=3.10 -y
conda activate multimodal-incident-analyzer
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
conda install -c conda-forge ffmpeg -y
conda install -c conda-forge tesseract -y
streamlit run app.py
```

Open the local URL printed by Streamlit.

## Run Processors Directly

```bash
python audio/processor.py --input "path/to/audio_or_folder" --output "output/audio_output.csv"
python pdf/processor.py --input "path/to/report_or_folder" --output "output/pdf_output.csv"
python images/processor.py --input "path/to/photo_or_folder" --output "output/image_output.csv"
python video/processor.py --input "path/to/video_or_folder" --output "output/video_output.csv"
python text/processor.py --input "path/to/csv_or_text_or_folder" --output "output/text_output.csv"
python integration/integration.py --input_audio "audio/output/audio_output.csv" --input_pdf "pdf/output/pdf_output.csv" --input_image "images/output/image_output.csv" --input_video "video/output/video_output.csv" --input_text "text/output/text_output.csv"
```

Each processor writes a modality draft CSV. The integration command accepts any
mix of those processor output CSVs; empty strings are skipped when a modality is
not available. By default, integration writes
`integration/output/final_incident_dataset.csv`. The Streamlit app runs these
processors automatically during upload review.

## Output

Integration preview rows use:

```text
Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary
```

The final Supabase export uses:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

Missing values are represented as `Unknown`. Severity is `Low`, `Medium`,
`High`, or `Unknown`.

## Tests

```bash
python -m pytest -q
python -m ruff check .
```

The live Supabase CRUD test is skipped automatically unless the Supabase package
and valid Supabase credentials are configured.

## More Docs
- [Product Requirements](docs/PRD.md)
- [Specifications](docs/specs.md)
- [Rules](docs/rules.md)
- [Technical Design](docs/tech.md)
- [Tickets](docs/tickets.md)
