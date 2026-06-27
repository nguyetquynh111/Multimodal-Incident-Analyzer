# Multimodal Incident Analyzer

A Streamlit prototype that converts evidence files into structured incident
records. It supports audio, PDF, image, video, text, and structured CSV inputs,
then lets users review and save confirmed records to Supabase.

## Features

- Process one uploaded evidence file at a time on the Add Incident page.
- Extract modality-specific draft rows from audio, PDFs, images, videos, and text.
- Standardize records with Integration, incident IDs, severity, and summaries.
- Review before inserting into Supabase.
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
SUPABASE_SERVICE_ROLE_KEY=...   # Preferred for trusted hosted demos
SUPABASE_ANON_KEY=...           # Or use this / SUPABASE_KEY for local demos
SUPABASE_KEY=...                # Backward-compatible alternative
SUPABASE_TABLE=incidents
```

Useful optional settings:

```bash
OPENROUTER_API_KEY=...          # Enables LLM summaries
LLM_MODEL_NAME=openai/gpt-oss-20b:free
LLM_TIMEOUT_SECONDS=6.0
ROBOFLOW_API_KEY=...            # Enables image object detection
ROBOFLOW_MODEL_ID=fire-detection-data-pre/4
ROBOFLOW_PERSON_MODEL_ID=yolov8n-640
ROBOFLOW_API_URL=https://detect.roboflow.com
WHISPER_MODEL=small.en          # Audio transcription model
WHISPER_DEVICE=auto             # auto uses cuda when available, otherwise cpu
WHISPER_LANGUAGE=en
WHISPER_MODEL_DIR=              # Optional local model cache
WHISPER_BEAM_SIZE=5
VIDEO_YOLO_DEVICE=auto          # auto uses cuda when available, otherwise default
VIDEO_YOLO_SAMPLE_STRIDE=4      # Skip YOLO work on more video frames for speed
VIDEO_YOLO_IMAGE_SIZE=320
VIDEO_YOLO_MODEL_PATH=video/yolov8s.pt
TESSERACT_CMD=                  # Optional path when tesseract is outside PATH
PDF_OCR_WORKERS=8               # Parallel scanned-page OCR workers
```

Without OpenRouter, summaries use the deterministic fallback.

## Run Processors Directly

Run these commands from the repository root. Use slashes for file paths
(`audio/processor.py`) or module mode (`python -m audio.processor`), not
`audio.processor.py`.

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
