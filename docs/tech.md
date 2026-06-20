# Technical Design: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 26, 2026 |

## 1. Architecture

```text
Streamlit App
  ├── Single-file uploader
  ├── File type detector
  ├── Synchronous extractor router
  │     ├── audio processor
  │     ├── pdf processor
  │     ├── image processor
  │     ├── video processor
  │     ├── text processor
  │     ├── csv processor
  │     └── json processor
  ├── Integration
  ├── Separate LLM summarizer folder/function
  ├── INC_TYPE_NUMBER ID generator
  ├── Supabase insert/query wrapper
  └── Dashboard + final CSV export

Supabase Postgres
  └── incidents table = source of truth after insert

Hosted class demo
  └── protected environment secrets + Supabase connection
```

Old local-folder ingestion, watch-folder monitoring, SQLite, an AWS-specific plan, and local final CSV as source of truth are removed. A simple hosted class demo remains required.

## 2. Repository Structure

```text
multimodal-incident-analyzer/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── app.py                     # planned Streamlit entry point
├── docs/
│   ├── PRD.md
│   ├── specs.md
│   ├── tech.md
│   ├── rules.md
│   ├── tickets.md
│   └── diagrams/
├── sql/
│   └── create_incidents_table.sql
├── src/
│   ├── __init__.py
│   ├── file_type.py
│   ├── id_generator.py
│   ├── supabase_client.py
│   ├── audio/                 # processor, CLI/batch, local output
│   ├── pdf/                   # processor and local output
│   ├── image/                 # processor and local output
│   ├── video/                 # processor and local output
│   ├── text/                  # processor and local output
│   ├── csv/                   # processor and local output
│   ├── json/                  # planned processor and local output
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── integration.py
│   │   ├── severity.py
│   │   └── validators.py
│   ├── llm_summarizer/
│   │   ├── __init__.py
│   │   ├── summarizer.py
│   │   ├── prompts.py
│   │   ├── fallback.py
│   │   └── schemas.py
│   └── export/
│       ├── __init__.py
│       └── csv_export.py
└── tests/
    ├── test_file_type_detector.py
    ├── test_extractor_schema.py
    ├── test_integration_schema.py
    ├── test_llm_summarizer.py
    ├── test_id_generator.py
    ├── test_supabase_mapping.py
    ├── test_final_export_schema.py
    └── test_dashboard_smoke.py
```

## 3. Main Modules

| **Module** | **Responsibility** |
| --- | --- |
| app.py (planned) | Streamlit UI, upload flow, synchronous processing, dashboard, and final CSV download |
| src/file_type.py | Detect extension and map to source abbreviation and processor |
| src/id_generator.py | Generate `INC_TYPE_NUMBER` IDs by checking existing Supabase rows |
| src/supabase_client.py | Create Supabase client and wrap insert/query/export calls |
| src/audio/ | Transcribe audio and produce the audio artifact plus extractor mapping |
| src/pdf/ | Extract document fields with conditional OCR and produce the PDF artifact |
| src/image/ | Detect supported scene/object signals, run OCR, and produce the image artifact |
| src/video/ | Sample frames, gate detection by motion, and produce the video event log |
| src/text/ | Preserve source text, run NLP analysis, and produce the text artifact |
| src/csv/ and src/json/ | Parse structured records and map them to the extractor schema |
| src/integration/integration.py | Accept extractor DataFrame and return cleaned incident rows |
| src/integration/severity.py | Apply severity rules and normalize severity values |
| src/integration/validators.py | Validate extractor, integration, LLM summary, Supabase payload, and final export schemas |
| src/llm_summarizer/summarizer.py | Public `summarize_incident(row)` function called by the platform before Supabase insert |
| src/llm_summarizer/prompts.py | Prompt template for local/free LLM summary generation |
| src/llm_summarizer/fallback.py | Rule-based deterministic summary when LLM fails or is disabled |
| src/llm_summarizer/schemas.py | Input/output schema constants for summary function |
| src/export/csv_export.py | Generate final six-column CSV from Supabase rows |

## 4. LLM Summarizer Technical Contract

The LLM summarizer must be a separate folder and must not be embedded inside the Integration module. The platform imports it and calls it after integration has produced cleaned rows.

Public function:

```text
# src/llm_summarizer/summarizer.py

def summarize_incident(incident_row: dict) -> dict:
    """
    Input: one cleaned integrated incident row.
    Output keys:
      - incident_summary: str
      - summary_method: "llm" | "rule_based" | "disabled" | "error"
      - summary_model: str
    """
```

Recommended call location:

```text
integrated_df = integrate_records(extractor_df)

rows_to_insert = []
for row in integrated_df.to_dict(orient="records"):
    summary = summarize_incident(row)
    row.update(summary)
    row["incident_id"] = generate_next_incident_id(row["source_type"])
    rows_to_insert.append(row)

insert_incidents(rows_to_insert)
```

The LLM summarizer can use a local/free text-generation model such as Ollama if available, but the fallback in `fallback.py` must always work without model downloads or paid APIs.

## 5. Suggested Dependencies

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

## 6. Environment Variables

| **Variable** | **Required** | **Purpose** |
| --- | --- | --- |
| SUPABASE_URL | Yes | Supabase project URL |
| SUPABASE_KEY | Yes | Supabase anon key or service role key depending on local demo setup |
| SUPABASE_TABLE | No | Defaults to incidents |
| ENABLE_LLM_SUMMARY | No | Turn local/free summary generation on or off |
| LLM_MODEL_NAME | No | Optional local/free model label for summary module |
| LLM_TIMEOUT_SECONDS | No | Optional timeout for summary generation before fallback |
| ENABLE_RULE_SUMMARY_FALLBACK | No | Keep summary fallback enabled; should default to true |
| ENABLE_OCR_FALLBACK | No | Allow PDF/image OCR fallback |
| FAST_DEMO_MODE | No | Use lightweight processing for demo safety |

For deployment, store Supabase values in the host's secret manager or environment settings. Do not commit credentials or raw evidence. The hosted app only needs to support the classroom workflow; production availability and emergency-service security certification are out of scope.

## 7. Supabase Table SQL

```text
create table if not exists incidents (
  incident_id text primary key,
  source text not null,
  event text not null default 'Unknown',
  location text not null default 'Unknown',
  time text not null default 'Unknown',
  severity text not null check (severity in ('Low', 'Medium', 'High')),
  source_filename text not null,
  source_type text not null check (source_type in ('AUD', 'PDF', 'IMG', 'VID', 'TXT', 'CSV', 'JSON')),
  confidence double precision default 0.0,
  raw_text text default 'Unknown',
  incident_summary text not null default 'Unknown',
  summary_method text not null default 'rule_based'
    check (summary_method in ('llm', 'rule_based', 'disabled', 'error')),
  summary_model text not null default 'Unknown',
  created_at timestamptz not null default now()
);
```

## 8. Local Run Flow

```text
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env from .env.example and add Supabase values
SUPABASE_URL=...
SUPABASE_KEY=...
SUPABASE_TABLE=incidents
ENABLE_LLM_SUMMARY=True
ENABLE_RULE_SUMMARY_FALLBACK=True
FAST_DEMO_MODE=True

# 3. Create Supabase table using sql/create_incidents_table.sql

# 4. Launch Streamlit
streamlit run app.py

# 5. Upload one supported file

# 6. App processes synchronously:
#    extractor -> Integration -> LLM summarizer -> ID generation -> Supabase insert

# 7. Use dashboard filters, selected incident summaries, and final CSV export from Supabase

# 8. Run tests
pytest
```

## 9. Technical Risks

| **Risk** | **Mitigation** |
| --- | --- |
| Heavy models run slowly inside Streamlit | Use FAST_DEMO_MODE, small models, cached model downloads, and short demo files |
| LLM model unavailable | Use deterministic rule-based summary fallback from `src/llm_summarizer/fallback.py` |
| LLM hallucinates details | Constrain prompt, validate output, and never allow LLM to override normalized fields |
| Supabase credentials missing or wrong | Show setup guidance and do not crash |
| Integration schema mismatch | Add strict validator tests before summary and Supabase insert |
| ID collision if multiple users insert at the same time | For class demo, query current max per type before insert; document single-user assumption |
| OCR setup is difficult | Use text-based PDF for main demo and keep OCR fallback optional |
| Video processing is slow | Reject long videos, use a documented sample interval, and run detection only on motion frames |
| Object detections are mistaken for activities | Require documented temporal or rule-based evidence for video event labels |
| Extractor returns nulls | Validators convert missing values to Unknown and severity to Low/Medium/High |
| Dashboard reads local stale data | Dashboard must query Supabase directly |
