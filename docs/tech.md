# Technical Design: Multimodal Crime / Incident Report Analyzer

## 1. Repository Structure

```text
multimodal-incident-analyzer/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── app.py                     # Streamlit entry point
├── .github/
│   └── workflows/
├── .streamlit/
├── audio/
├── cloud_deployment/
├── diagrams/
├── docs/
│   ├── PRD.md
│   ├── specs.md
│   ├── tech.md
│   ├── rules.md
│   ├── tickets.md
│   └── rodney-document-analyst.md
├── images/
├── integration/
├── llm_summarizer/
├── pdf/
├── text/
├── video/
└── tests/
    ├── test_file_type_detector.py
    ├── test_extractor_schema.py
    ├── test_image_processor.py
    ├── test_modality_output_schemas.py
    ├── test_integration_schema.py
    ├── test_integration_mapping.py
    ├── test_llm_summarizer.py
    ├── test_id_generator.py
    ├── test_supabase_mapping.py
    ├── test_final_export_schema.py
    └── test_dashboard_smoke.py
```

Modality and deployment tests also live beside the relevant packages:
`audio/tests/test_audio_processor.py`, `video/tests/test_video_processor.py`,
and `cloud_deployment/tests/test_cloud_deployment.py`.

## 2. Main Modules

| **Module** | **Responsibility** |
| --- | --- |
| app.py | Streamlit UI, upload flow, synchronous processing, dashboard, and CSV download |
| integration/integration.py | Run the full Integration workflow through `integrate_records(draft_df, source_type)`: standardize rows, call `llm_summarizer`, generate IDs, and return final incident rows |
| cloud_deployment/supabase_client.py | Create Supabase client and upload/query user-confirmed incident rows; final returned rows use the nine-field table schema |
| cloud_deployment/validators.py | Validate Supabase insert payloads |
| cloud_deployment/exporter.py | Query Supabase and export the final approved nine-field CSV |
| audio/ | Transcribe audio and output `Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score` |
| pdf/ | Extract whole-document fields and use whole-document OCR only when direct extraction is near-empty; output `Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome` |
| images/ | Use the Roboflow Inference SDK for supported scene/object signals and session-only bounding-box overlays; OCR enlarged corner crops and keep generic readable text after cleanup; output `Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score` |
| video/ | Sample frames, gate detection by motion, and output `Timestamp, Frame_ID, Event_Detected, Objects, Confidence` |
| text/ | Preserve source text, run NLP analysis, and output `Text_ID, Source, Raw_Text, Sentiment, Entities, Topic` |
| Structured text files | The Integration dispatcher reads incident-like CSVs directly; text-oriented CSVs are parsed by `text/processor.py`; JSON uploads are unsupported; conventional text artifacts live under `text/output/` |
| llm_summarizer/summarizer.py | Two public capabilities: `summarize_incident(row)` for summaries and `update_image_location(row)` for image OCR location updates |
| llm_summarizer/prompts.py | Prompt templates for OpenRouter summary generation and image OCR location extraction |
| llm_summarizer/fallback.py | Rule-based deterministic summary when OpenRouter fails or is disabled |
| llm_summarizer/schemas.py | Input/output schema constants for the summary function |

## 3. LLM Summarizer Technical Contract

The LLM summarizer must be a separate folder and must not be embedded inside the modality extractors. The Integration workflow imports it after row standardization. For images the order is: OCR writes `Text_Extracted`, Integration calls `update_image_location(row)` to fill a missing `Location`, and then Integration calls `summarize_incident(row)` before ID generation.

Public functions:

```text
# llm_summarizer/summarizer.py

def summarize_incident(incident_row: dict) -> dict:
    """
    Input: one standardized integrated incident row.
    Output keys:
      - incident_summary: str
      - summary_method: "llm" | "rule_based" | "disabled" | "error"
      - summary_model: str
    """

def update_image_location(image_row: dict) -> dict:
    """
    Input: one image draft row with Text_Extracted and optional Location.
    Output: a copy of the row with Location filled only when OCR text contains
    an explicit road, highway, county, address, or LLM-confirmed place.
    """
```

Recommended call location:

```text
final_df = integrate_records(draft_df, source_type)

rows_to_insert = []
for row in final_df.to_dict(orient="records"):
    payload = {
        "incident_id": row["Incident_ID"],
        "source": row["Source"],
        "event": row["Event"],
        "location": row["Location"],
        "time": row["Time"],
        "severity": row["Severity"],
        "incident_summary": row["Incident_Summary"],
    }
    rows_to_insert.append(payload)

# Called only after the user confirms the final Integration result.
insert_incidents(rows_to_insert)
```

The LLM summarizer uses OpenRouter when `OPENROUTER_API_KEY` is configured. The fallback in `fallback.py` must always work without model downloads or paid APIs.

## 4. Suggested Dependencies

| **Category** | **Packages** |
| --- | --- |
| Core | python, pandas, numpy, streamlit, python-dotenv |
| Supabase | supabase |
| Audio | openai-whisper, torch, and the FFmpeg system command |
| PDF | pymupdf, pdfplumber, pytesseract, plus the Conda `tesseract` executable for whole-document OCR fallback |
| Image | opencv-python, pillow, pytesseract, inference-sdk, plus the Conda `tesseract` executable for OCR |
| Video | opencv-python, ultralytics |
| NLP/LLM optional | spacy and the OpenRouter HTTP client (`requests`) |
| Testing | pytest |
| Not required in MVP | watchdog, sqlite-specific tooling, AWS SDK, async queue libraries |

## 5. Environment Variables

| **Variable** | **Required** | **Purpose** |
| --- | --- | --- |
| SUPABASE_URL | Yes | Supabase project URL |
| SUPABASE_KEY | Yes | Supabase anon key or service role key depending on local demo setup |
| SUPABASE_TABLE | No | Defaults to incidents |
| OPENROUTER_API_KEY | No | Enables OpenRouter summaries when configured |
| ROBOFLOW_API_KEY | No | Optional/free-tier Roboflow key for image inference; must come from environment variables, never committed |
| ROBOFLOW_MODEL_ID | No | Optional Roboflow fire model id; defaults to `fire-detection-data-pre/4` when used |
| ROBOFLOW_PERSON_MODEL_ID | No | Optional Roboflow person model id; defaults to `yolov8n-640` when used |
| ROBOFLOW_API_URL | No | Optional image inference endpoint; defaults to `https://serverless.roboflow.com` |
| VIDEO_YOLO_MODEL_PATH | No | Optional YOLO model path; defaults to `video/yolov8s.pt` and may point to an exported ONNX model |
| VIDEO_YOLO_IMAGE_SIZE | No | Optional YOLO inference image size; defaults to `640` for faster CPU/GPU processing |
| VIDEO_YOLO_SAMPLE_STRIDE | No | Optional stride over motion-sampled frames eligible for YOLO; defaults to `2` |
| LLM_MODEL_NAME | No | Optional OpenRouter model label for summary module |
| LLM_TIMEOUT_SECONDS | No | Optional timeout for summary generation before fallback |
| TESSERACT_CMD | No | Optional path to the local Tesseract executable used by PDF OCR |
| WHISPER_MODEL | No | Optional Whisper model name; defaults to `small.en` for better English transcripts than `base` |
| WHISPER_DEVICE | No | Whisper execution device; defaults to `cpu` |
| WHISPER_LANGUAGE | No | Transcription language; defaults to `en` |
| WHISPER_MODEL_DIR | No | Optional local directory for Whisper model downloads |
| WHISPER_BEAM_SIZE | No | Optional Whisper beam size; defaults to `5` for more accurate deterministic decoding |

For deployment, store Supabase values in the host's secret manager or environment settings. Do not commit credentials or raw evidence. The hosted app only needs to support the classroom workflow; production availability and emergency-service security certification are out of scope.

## 6. Supabase Table SQL

```sql
create table if not exists incidents (
  id bigint generated by default as identity primary key,
  created_at timestamp with time zone default now(),
  incident_id text not null unique,
  source text not null check (source in ('Audio', 'PDF', 'Image', 'Video', 'Text')),
  event text not null default 'Unknown',
  location text not null default 'Unknown',
  time text not null default 'Unknown',
  severity text not null default 'Low' check (severity in ('Low', 'Medium', 'High', 'Unknown')),
  incident_summary text not null default 'Unknown'
);
```

The Supabase stored row and final CSV export use exactly these nine fields in order:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

After user confirmation, the insert payload sent by the app contains only the seven app-provided fields: `incident_id, source, event, location, time, severity, incident_summary`. Supabase generates `id` and `created_at`.

## 7. Technical Risks

| **Risk** | **Mitigation** |
| --- | --- |
| Heavy models run slowly inside Streamlit | Use short demo files and cached model downloads |
| LLM model unavailable | Use deterministic rule-based summary fallback from `llm_summarizer/fallback.py` |
| LLM hallucinates details | Constrain prompt, validate output, and never allow LLM to override normalized fields |
| Supabase credentials missing or wrong | Show setup guidance and do not crash |
| Integration schema mismatch | Add strict validator tests before Supabase insert |
| ID collision if multiple users insert at the same time | For class demo, query current max per type before insert; document single-user assumption |
| OCR setup is difficult | Use text-based PDF for the main demo; when direct extraction is near-empty, the processor attempts OCR and degrades to Unknown fields if it is unavailable |
| Video processing is slow | Reject long videos, use a documented sample interval, run YOLO only on every configured motion-sampled frame, and keep YOLO image size configurable |
| Roboflow image API unavailable, quota exhausted, or key missing | Treat Roboflow as optional/free-tier external inference; load the API key from environment variables and return safe image artifact placeholders without crashing |
| Object detections are mistaken for activities | Require documented temporal or rule-based evidence for video event labels |
| Extractor returns nulls | Validators convert missing values to Unknown and ensure an Unknown event has Low severity |
| Dashboard reads local stale data | Dashboard must query Supabase directly |
