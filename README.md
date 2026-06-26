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
transcription. Tesseract provides OCR for scanned PDFs and image text/credits.

```bash
conda create -n multimodal-incident-analyzer python=3.10 -y
conda activate multimodal-incident-analyzer
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
conda install -c conda-forge tesseract -y
streamlit run app.py
```

Open the local URL shown by Streamlit. A small text example is available at
`text/samples/social_post.txt`.

## Run Processors Directly

Run these commands from the repository root when you want to create a draft
CSV from one evidence file without opening Streamlit. Replace each example
path with your own file path. On Windows, use `py` in place of `python` if
that is how Python is installed.

```bash
# Audio (.wav, .mp3, .m4a)
python audio/processor.py --input "path/to/call.wav" --output "output/audio.csv"

# PDF (.pdf)
python pdf/processor.py --input "path/to/report.pdf" --output "output/pdf.csv"

# Image (.jpg, .jpeg, .png)
python images/processor.py --input "path/to/photo.jpg" --output "output/image.csv"

# Video (.mp4, .mov, .mpg, .mpeg; maximum five minutes)
python video/processor.py --input "path/to/footage.mp4" --output "output/video.csv"

# Text (.txt or .csv)
python text/processor.py "path/to/report.txt" --output "output/text.csv"
```

Each command prints a preview and writes its modality-specific draft CSV to
the `--output` path. Audio requires FFmpeg; image OCR and scanned-PDF OCR
require the `tesseract` executable installed in the active Conda environment.
Image inference uses `ROBOFLOW_API_KEY` when it is set. The image processor
first reads enlarged corner crops and keeps generic readable OCR text after
cleanup. Roboflow bounding boxes are kept as session metadata for the
Streamlit Visual Evidence overlay, while the saved image artifact remains the
required five columns. The processor uses `None` for no detected objects and
`N/A` when no readable image text is found. Image location handling happens in
Integration: OCR writes `Text_Extracted`, Integration calls
`llm_summarizer.update_image_location(...)` to fill a missing `Location`, and only
then Integration calls `summarize_incident(...)`.

## Environment

Copy `.env.example` to `.env`, set `SUPABASE_URL` and `SUPABASE_KEY` for
persistence, and leave `SUPABASE_TABLE=incidents` unless your table is named
differently. Set `OPENROUTER_API_KEY` to use OpenRouter summaries automatically;
without it, the deterministic fallback is used. Set `ROBOFLOW_API_KEY` only when
image inference is needed. `ROBOFLOW_API_URL` is optional and defaults to
`https://detect.roboflow.com`, the hosted object-detection endpoint.
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
