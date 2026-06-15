# tech.md

## 1. Architecture

```text
Raw Evidence Folder / Streamlit Upload
        |
        v
Ingestion + Synthetic Incident_ID Generator
        |
        +--> audio processor  --> audio_intermediate.csv
        +--> pdf processor    --> pdf_intermediate.csv
        +--> image processor  --> image_intermediate.csv
        +--> video processor  --> video_intermediate.csv
        +--> text processor   --> text_intermediate.csv
        |
        v
Integration Layer
        |
        v
final_incidents.csv
        |
        v
Streamlit Dashboard
        |
        v
AWS No-Billing Deployment Plan
```

## 2. Repository Structure

```text
multimodal-incident-analyzer/
├── README.md
├── requirements.txt
├── .gitignore
├── docs/
│   ├── PRD.md
│   ├── specs.md
│   ├── tech.md
│   ├── rules.md
│   └── tickets.md
├── data/
│   ├── raw/
│   │   └── INC_001/
│   │       ├── audio/
│   │       ├── pdf/
│   │       ├── images/
│   │       ├── video/
│   │       └── text/
│   ├── intermediate/
│   └── final/
│       └── final_incidents.csv
├── audio/
│   └── audio_processor.py
├── pdf/
│   └── pdf_processor.py
├── images/
│   └── image_processor.py
├── video/
│   └── video_processor.py
├── text/
│   └── text_processor.py
├── integration/
│   ├── ingest.py
│   ├── normalize.py
│   ├── severity.py
│   ├── merge_outputs.py
│   ├── summarize.py
│   └── app.py
├── diagrams/
│   └── architecture.png
├── reports/
│   └── project_report.md
└── tests/
    ├── test_ingestion.py
    ├── test_schema.py
    ├── test_severity.py
    └── test_dashboard_smoke.py
```

## 3. Main Modules

| Module | Responsibility |
|---|---|
| `integration/ingest.py` | Create synthetic IDs and organize files |
| `audio/audio_processor.py` | Transcribe and extract audio signals |
| `pdf/pdf_processor.py` | Extract PDF text and incident fields |
| `images/image_processor.py` | Detect objects and image OCR text |
| `video/video_processor.py` | Extract frames and video signals |
| `text/text_processor.py` | Clean text and extract NLP signals |
| `integration/normalize.py` | Map intermediate outputs to final schema |
| `integration/severity.py` | Compute severity from extracted signals |
| `integration/merge_outputs.py` | Create final CSV |
| `integration/summarize.py` | Generate local LLM or fallback summary |
| `integration/app.py` | Streamlit dashboard |

## 4. Suggested Dependencies

```text
pandas
numpy
streamlit
opencv-python
moviepy
imageio
pymupdf
pdfplumber
pytesseract
spacy
nltk
transformers
torch
torchvision
ultralytics
watchdog
pytest
python-dotenv
```

## 5. Feature Flags

| Flag | Default | Purpose |
|---|---:|---|
| `ENABLE_LLM_SUMMARY` | `True` | Turn local HuggingFace summary on/off |
| `ENABLE_RULE_SUMMARY_FALLBACK` | `True` | Always provide summary fallback |
| `ENABLE_WATCH_FOLDER` | `False` | Enable watch-folder demo only when stable |
| `ENABLE_OCR_FALLBACK` | `True` | Allow OCR fallback for PDFs/images |
| `FAST_DEMO_MODE` | `True` | Use cached outputs or reduced frames |

## 6. Local Run Flow

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add sample evidence under data/raw/INC_001/

# 3. Run modality processors
python audio/audio_processor.py
python pdf/pdf_processor.py
python images/image_processor.py
python video/video_processor.py
python text/text_processor.py

# 4. Merge outputs
python integration/merge_outputs.py

# 5. Launch dashboard
streamlit run integration/app.py

# 6. Run tests
pytest
```

## 7. AWS No-Billing Plan

The implementation runs locally. AWS is documented as an optional plan only.

No-billing architecture:

```text
Local Laptop
├── Streamlit app
├── Local HuggingFace model
└── Local final_incidents.csv

Optional AWS Plan
├── S3 bucket for raw evidence/final CSV only if free-tier safe
├── EC2 free-tier only if free-tier safe
├── IAM least-privilege role
├── No paid API Gateway
├── No managed ML endpoint
└── No paid LLM API
```

## 8. Technical Risks

| Risk | Mitigation |
|---|---|
| Heavy models run slowly | Use small models, cached outputs, and fast demo mode |
| HuggingFace model fails | Use rule-based summary fallback |
| OCR setup is difficult | Use text-based PDF for main demo |
| Video processing is slow | Reduce frame sampling and keep clips short |
| CSV contracts mismatch | Add schema tests for intermediate and final outputs |
| Dependency conflicts | Pin versions after first successful integration test |
