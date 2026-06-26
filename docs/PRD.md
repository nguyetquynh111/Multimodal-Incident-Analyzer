# Product Requirements Document: Multimodal Crime / Incident Report Analyzer

| **Team** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 28, 2026 |

## 1. Project Summary

| **Field** | **Decision** |
| --- | --- |
| Project name | Multimodal Crime / Incident Report Analyzer |
| Team | Group 2 |
| Project type | Class prototype only |
| Primary language | Python |
| Dashboard | Streamlit |
| Persistent data layer | Supabase Postgres, one main table named incidents |
| Input flow | Streamlit single-file upload; exactly one file per processing run |
| Processing mode | Synchronous processing inside the Streamlit app |
| Integration strategy | Extractor output is passed as a pandas DataFrame to Integration logic |
| LLM summary strategy | Separate `llm_summarizer/` module. The Integration workflow calls it after row standardization and before ID generation/Supabase insert. OpenRouter when configured, rule-based fallback always required. |
| Cloud/data scope | Supabase stores structured incident rows only; raw files are not uploaded to Supabase Storage in the MVP |
| Cloud deployment | Host the class prototype with protected Supabase credentials; production hosting is out of scope |
| Final submission date | June 28, 2026 |

## 2. Product Definition

The product is a class prototype that converts one uploaded multimodal evidence file into one or more structured incident rows. The app supports five modalities: audio, PDF, image, video, and text. CSV and JSON are structured text input formats handled by the text path. Streamlit handles the upload and UI. The selected extractor processes the file synchronously and returns a normalized intermediate pandas DataFrame. Integration receives that DataFrame, cleans and standardizes the extracted information, calls the LLM summarizer, generates IDs, and returns zero, one, or many final incident rows.

During the Integration flow, Integration must call the separate LLM summarizer function from `llm_summarizer/` before ID generation. The summarizer adds a short `Incident_Summary` to each integrated row. Integration then generates synthetic `Incident_ID` values using the abbreviated `INC_TYPE_NUMBER` format and returns final rows for automatic Supabase insertion.

After insertion, the application treats Supabase as the source of truth. Dashboard filtering, selected-incident summary display, and final CSV export must read from Supabase, not from local intermediate files.

## 3. Problem

Incident evidence can arrive as emergency calls, PDF reports, scene photos, surveillance video, typed reports, CSV records, or JSON records. Reviewing these sources manually is slow and inconsistent. For a class demo, the project must show that multimodal AI, integration logic, rule-based fallback logic, and an OpenRouter-backed LLM summary module can turn messy unstructured or semi-structured evidence into consistent structured incident records.

## 4. Goals

| **ID** | **Goal** | **Success Target** |
| --- | --- | --- |
| G1 | Process supported evidence modalities | Audio, PDF, image, video, and text upload paths exist; CSV and JSON are handled as structured text inputs |
| G2 | Use a simple Streamlit upload workflow | The app accepts exactly one uploaded file per processing run |
| G3 | Support one file producing multiple incidents | A single uploaded file can insert zero, one, or many incident rows |
| G4 | Standardize through Integration | Extractor DataFrame is passed to Integration; Integration standardizes, summarizes, generates IDs, and returns final rows for Supabase insert |
| G5 | Generate incident summaries | Integration calls the separate LLM summarizer function to add `Incident_Summary` before ID generation and insert |
| G6 | Generate stable synthetic IDs | Incident IDs use abbreviated `INC_TYPE_NUMBER`, such as `INC_VID_001` |
| G7 | Persist cleaned rows in Supabase | Rows are automatically inserted into the Supabase `incidents` table |
| G8 | Provide dashboard review and export | Streamlit can filter Supabase rows, show summaries, and export the approved nine-field CSV |
| G9 | Provide safe fallbacks | OpenRouter summary or rule-based fallback summary works without required paid APIs |
| G10 | Produce consistent modality results | Audio, PDF, image, video, and text outputs follow their documented artifact schemas |
| G11 | Demonstrate cloud access | The hosted class prototype connects to Supabase using protected credentials |

## 5. Non-Goals

| **ID** | **Non-Goal** | **Reason** |
| --- | --- | --- |
| NG1 | Production emergency deployment | This is an educational class prototype only |
| NG2 | Paid APIs or paid LLM services | The project should be runnable without paid API usage |
| NG3 | Local watch-folder as the main pipeline | The chosen MVP uses Streamlit upload, not folder monitoring |
| NG4 | SQLite or local CSV as source of truth | Supabase `incidents` table is the source of truth after insertion |
| NG5 | Supabase Storage for raw files | The MVP stores structured results only, not raw uploaded evidence |
| NG6 | Async queue or external worker | Processing is synchronous inside Streamlit for the MVP |
| NG7 | Multi-file batch or folder upload | The MVP accepts one file at a time |
| NG8 | Legal-grade crime classification | Output is for demonstration and education, not official investigation |
| NG9 | LLM as a factual authority | The LLM summarizer may summarize integrated fields; it must not override final event, location, time, or severity |
| NG10 | Train custom vision models | Pretrained models and documented rules are sufficient for the class prototype |

## 6. Users

| **User** | **Need** |
| --- | --- |
| Student Developer | Clear ownership, input contracts, output contracts, and testable tasks |
| Integration Lead | Stable extractor DataFrame contract, Integration contract, separate LLM summary function contract, ID rules, Supabase schema, and final export contract |
| Modality Developers | A clear DataFrame output contract for audio, PDF, image, video, and text processors; CSV and JSON are structured text inputs |
| LLM Module Developer | A separate folder and function contract for incident summary generation with safe fallback behavior |
| Instructor / Evaluator | A clear end-to-end demo from upload to extractor to integration to LLM summary to Supabase table to final CSV export |
| Demo Analyst User | Simple dashboard for filtering, reading summaries, and exporting incident rows |

## 7. MVP Scope

| **Input Type** | **MVP Limit** | **Required Result** |
| --- | --- | --- |
| Audio | Exactly 1 uploaded file per run | Speech transcription and urgency/event extraction |
| PDF | Exactly 1 uploaded file per run | Direct text extraction, conditional OCR fallback, and structured report fields |
| Image | Exactly 1 uploaded file per run | Scene/object detection, OCR, and bounded confidence |
| Video | Exactly 1 uploaded file per run; max 5 minutes | Regular frame sampling, motion gating, and timestamped event signals |
| Text | Exactly 1 uploaded `.txt`, `.csv`, or `.json` file per run | Preserved source text, or structured CSV/JSON text evidence, with entities, sentiment/topic, or incident-like fields |

The main application contract remains the shared extractor DataFrame. For team review and demonstration, each unstructured modality also produces a small artifact with the following exact columns:

| **Modality** | **Artifact Columns** |
| --- | --- |
| Audio | `Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score` |
| PDF | `Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome` |
| Image | `Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score` |
| Video | `Timestamp, Frame_ID, Event_Detected, Objects, Confidence` |
| Text | `Text_ID, Source, Raw_Text, Sentiment, Entities, Topic` |

Structured text inputs may also arrive as CSV with `Event, Location, Time,
Severity, Summary, Confidence`, or JSON with `event, location, time, severity,
summary, confidence`. These modality artifacts do not replace the shared
extractor DataFrame, Supabase table, or final nine-field project export.

## 8. Core Processing Flow

```text
Streamlit uploads exactly one file
        ↓
Detect file type and route to one extractor
        ↓
Extractor returns normalized intermediate pandas DataFrame
        ↓
Integration receives DataFrame and standardizes incident rows
        ↓
Integration calls llm_summarizer.summarize_incident(...) for each row
        ↓
Integration adds Incident_Summary and generates abbreviated INC_TYPE_NUMBER Incident_ID
        ↓
App maps final Integration rows to the Supabase insert payload
        ↓
App automatically inserts rows into Supabase incidents table
        ↓
Dashboard reads from Supabase
        ↓
Final CSV export reads from Supabase and outputs the nine required fields
```

## 9. Final Output and Data Persistence

The application must automatically insert integrated and summarized incident rows into one Supabase table named `incidents`.

The stored Supabase row and final CSV export must contain exactly these nine fields in this exact order:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

`id` and `created_at` are database-generated. Therefore, the insert payload sent by the app contains the other seven fields only: `incident_id, source, event, location, time, severity, incident_summary`. Missing text fields must be filled with `Unknown`. Severity must always be `Low`, `Medium`, `High`, or `Unknown`. No final exported CSV row may contain null values.

## 10. LLM Summarizer Requirement

The LLM summary feature is a required module, but it is not part of the core extraction logic and must not be duplicated inside modality extractors. Integration imports and calls the separate summarizer module from this folder:

```text
llm_summarizer/
├── __init__.py
├── summarizer.py
├── prompts.py
├── fallback.py
└── schemas.py
```

Integration calls the summarizer after it standardizes rows and before ID generation and Supabase insertion. The summarizer uses OpenRouter when enabled and returns text that Integration stores as `Incident_Summary`, which is later mapped to Supabase `incident_summary`, without changing normalized facts. If OpenRouter is unavailable, slow, disabled, or invalid, the fallback must produce a safe deterministic summary.

## 11. Success Metrics

| **Metric** | **Target** |
| --- | --- |
| Modality coverage | 5/5 modalities have a route or graceful fallback: audio, PDF, image, video, text; CSV and JSON are accepted through text |
| Upload behavior | Exactly one file is processed per Streamlit run |
| One-file-many-incidents behavior | A single uploaded file can produce zero, one, or many Supabase incident rows |
| DataFrame contract validity | Extractor output and Integration output match the documented schemas |
| LLM module separation | LLM summary code lives under `llm_summarizer/` and is called by the Integration workflow; it is not mixed into extractor code |
| Incident summary availability | Every inserted row has `incident_summary`; fallback is used if OpenRouter fails |
| ID validity | 100% of inserted rows use `INC_TYPE_NUMBER` with approved type abbreviations |
| Supabase insert success | Processed rows are inserted into the `incidents` table automatically |
| Final schema validity | Exported CSV has exactly nine required fields and no extra fields |
| Missing value handling | 0 null values in final exported CSV |
| Dashboard usability | User can filter, read summaries, and export incidents from Supabase without code |
| Modality artifact validity | Audio, PDF, image, video, and text artifacts use their exact documented columns |
| Hosted demo | Hosted app connects to Supabase without exposing credentials |
