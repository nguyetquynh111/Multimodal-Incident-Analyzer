# Multimodal Incident Analyzer

A Streamlit prototype that converts evidence files into structured incident
records. It supports audio, PDF, image, video, text, and structured CSV inputs,
then lets users review and save confirmed records to Supabase.

## Features

- Process one uploaded evidence file at a time.
- Extract modality-specific draft rows from audio, PDFs, images, videos, and text.
- Standardize records with Integration, incident IDs, severity, and summaries.
- Review before inserting into Supabase.
- Browse, filter, edit, and export saved incidents from the dashboard.

## Supported Files

```text
Audio: .wav, .mp3, .m4a
PDF:   .pdf
Image: .jpg, .jpeg, .png
Video: .mp4, .mov, .mpg, .mpeg (max 5 minutes)
Text:  .txt, .csv
```

JSON uploads are intentionally unsupported.

## Quick Start

Python 3.10 is recommended. FFmpeg is required for audio transcription, and
Tesseract is required for OCR.

```bash
conda create -n multimodal-incident-analyzer python=3.10 -y
conda activate multimodal-incident-analyzer
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
conda install -c conda-forge tesseract -y
streamlit run app.py
```

Open the local URL printed by Streamlit.

## Configuration

Create a local `.env` file and set Supabase values when persistence is needed:

```bash
SUPABASE_URL=...
SUPABASE_KEY=...
SUPABASE_TABLE=incidents
```

Useful optional settings:

```bash
OPENROUTER_API_KEY=...          # Enables LLM summaries
ROBOFLOW_API_KEY=...            # Enables image object detection
WHISPER_MODEL=small.en          # Audio transcription model
WHISPER_DEVICE=auto             # auto uses cuda when available, otherwise cpu
VIDEO_YOLO_DEVICE=auto          # auto uses cuda when available, otherwise default
VIDEO_YOLO_SAMPLE_STRIDE=2      # Skip YOLO work on some video frames
VIDEO_YOLO_IMAGE_SIZE=640
VIDEO_YOLO_MODEL_PATH=video/yolov8s.pt
```

Without OpenRouter, summaries use the deterministic fallback.

## Run Processors Directly

```bash
python audio/processor.py --input "path/to/call.wav" --output "output/audio.csv"
python pdf/processor.py --input "path/to/report.pdf" --output "output/pdf.csv"
python images/processor.py --input "path/to/photo.jpg" --output "output/image.csv"
python video/processor.py --input "path/to/footage.mp4" --output "output/video.csv"
python text/processor.py "path/to/report.txt" --output "output/text.csv"
```

Each processor writes a modality draft CSV. The Streamlit app runs these
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
RUN_SUPABASE_LIVE_TESTS=0 python -m pytest -q
```

Set `RUN_SUPABASE_LIVE_TESTS=1` only when valid Supabase credentials are
configured and a live CRUD round trip is intended.

## More Docs

- [Deployment](DEPLOYMENT.md)
- [Product Requirements](docs/PRD.md)
- [Specifications](docs/specs.md)
- [Rules](docs/rules.md)
- [Technical Design](docs/tech.md)
- [Tickets](docs/tickets.md)
