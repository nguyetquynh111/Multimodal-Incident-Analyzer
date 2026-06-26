# Technical Design: Multimodal Crime / Incident Report Analyzer

## 1. Repository Structure

```text
multimodal-incident-analyzer/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── app.py                     # planned Streamlit entry point
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
│   ├── rodney-document-analyst.md
│   └── diagrams/
├── images/
├── integration/
├── llm_summarizer/
├── pdf/
├── text/
├── video/
└── tests/
    ├── test_file_type_detector.py
    ├── test_extractor_schema.py
    ├── test_modality_output_schemas.py
    ├── test_integration_schema.py
    ├── test_llm_summarizer.py
    ├── test_id_generator.py
    ├── test_supabase_mapping.py
    ├── test_final_export_schema.py
    └── test_dashboard_smoke.py
```

## 2. Main Modules

| **Module** | **Responsibility** |
| --- | --- |
| app.py | Streamlit UI, upload flow, synchronous processing, dashboard, and CSV download |
| integration/integration.py | Run the full Integration workflow through `integrate_records(draft_df, source_type)`: standardize rows, call `llm_summarizer`, generate IDs, and return final incident rows |
| cloud_deployment/supabase_client.py | Create Supabase client and upload/query approved incident rows; final returned rows use the nine-field table schema |
| cloud_deployment/validators.py | Validate Supabase insert payloads |
| cloud_deployment/exporter.py | Query Supabase and export the final approved nine-field CSV |
| audio/ | Transcribe audio and output `Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score` |
| pdf/ | Extract document fields with conditional OCR and output `Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome` |
| images/ | Detect supported scene/object signals, run OCR, and output `Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score` |
| video/ | Sample frames, gate detection by motion, and output `Timestamp, Frame_ID, Event_Detected, Objects, Confidence` |
| text/ | Preserve source text, run NLP analysis, and output `Text_ID, Source, Raw_Text, Sentiment, Entities, Topic` |
| Structured text files | CSV and JSON are parsed as text evidence; conventional outputs live under `text/output/` |
| llm_summarizer/summarizer.py | Public `summarize_incident(row)` function called by Integration after row standardization and before ID generation/Supabase insert |
| llm_summarizer/prompts.py | Prompt template for OpenRouter summary generation |
| llm_summarizer/fallback.py | Rule-based deterministic summary when OpenRouter fails or is disabled |
| llm_summarizer/schemas.py | Input/output schema constants for summary function |

## 3. LLM Summarizer Technical Contract

The LLM summarizer must be a separate folder and must not be embedded inside the modality extractors. The Integration workflow imports it and calls it after row standardization and before ID generation.

Public function:

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

insert_incidents(rows_to_insert)
```

The LLM summarizer uses OpenRouter when `ENABLE_LLM_SUMMARY=True` and `OPENROUTER_API_KEY` is configured. The fallback in `fallback.py` must always work without model downloads or paid APIs.

## 4. Suggested Dependencies

| **Category** | **Packages** |
| --- | --- |
| Core | python, pandas, numpy, streamlit, python-dotenv |
| Supabase | supabase |
| Audio | openai-whisper, torch, and the FFmpeg system command |
| PDF | pymupdf, pdfplumber, pytesseract |
| Image | opencv-python, pillow, pytesseract, ultralytics |
| Video | opencv-python, ultralytics, moviepy, imageio |
| NLP/LLM optional | spacy, nltk, transformers, and an optional local LLM client |
| Testing | pytest |
| Not required in MVP | watchdog, sqlite-specific tooling, AWS SDK, async queue libraries |

## 5. Environment Variables

| **Variable** | **Required** | **Purpose** |
| --- | --- | --- |
| SUPABASE_URL | Yes | Supabase project URL |
| SUPABASE_KEY | Yes | Supabase anon key or service role key depending on local demo setup |
| SUPABASE_TABLE | No | Defaults to incidents |
| ENABLE_LLM_SUMMARY | No | Turn OpenRouter summary generation on or off |
| OPENROUTER_API_KEY | No | Required only when OpenRouter summaries are enabled |
| LLM_MODEL_NAME | No | Optional OpenRouter model label for summary module |
| LLM_TIMEOUT_SECONDS | No | Optional timeout for summary generation before fallback |
| ENABLE_RULE_SUMMARY_FALLBACK | No | Keep summary fallback enabled; should default to true |
| ENABLE_OCR_FALLBACK | No | Allow PDF/image OCR fallback |
| FAST_DEMO_MODE | No | Use reduced processing for demo safety |

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
  severity text not null default 'Unknown' check (severity in ('Low', 'Medium', 'High', 'Unknown')),
  incident_summary text not null default 'Unknown'
);
```

The Supabase stored row and final CSV export use exactly these nine fields in order:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

The insert payload sent by the app contains only the seven app-provided fields: `incident_id, source, event, location, time, severity, incident_summary`. Supabase generates `id` and `created_at`.

## 7. Technical Risks

| **Risk** | **Mitigation** |
| --- | --- |
| Heavy models run slowly inside Streamlit | Use FAST_DEMO_MODE, small models, cached model downloads, and short demo files |
| LLM model unavailable | Use deterministic rule-based summary fallback from `llm_summarizer/fallback.py` |
| LLM hallucinates details | Constrain prompt, validate output, and never allow LLM to override normalized fields |
| Supabase credentials missing or wrong | Show setup guidance and do not crash |
| Integration schema mismatch | Add strict validator tests before Supabase insert |
| ID collision if multiple users insert at the same time | For class demo, query current max per type before insert; document single-user assumption |
| OCR setup is difficult | Use text-based PDF for main demo and keep OCR fallback optional |
| Video processing is slow | Reject long videos, use a documented sample interval, and run detection only on motion frames |
| Object detections are mistaken for activities | Require documented temporal or rule-based evidence for video event labels |
| Extractor returns nulls | Validators convert missing values to Unknown and severity to Low/Medium/High/Unknown |
| Dashboard reads local stale data | Dashboard must query Supabase directly |
