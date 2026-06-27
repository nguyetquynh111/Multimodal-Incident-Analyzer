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
| Input flow | Streamlit Add Incident processes exactly one uploaded file per review run; completed reviews can be queued in the browser session for Combine Reports |
| Processing mode | Synchronous processing inside the Streamlit app |
| Integration strategy | Extractor output is passed as a pandas DataFrame to Integration logic |
| LLM summary strategy | Separate `llm_summarizer/` module with two responsibilities: `summarize_incident(row)` for summaries and `update_image_location(row)` for image OCR location updates before summarization. OpenRouter can be used when configured, and rule-based fallbacks are required. |
| Cloud/data scope | Supabase stores structured incident rows only; raw files are not uploaded to Supabase Storage in the MVP |
| Cloud deployment | Host the class prototype with protected Supabase credentials; production hosting is out of scope |
| Final submission date | June 28, 2026 |

## 2. Product Definition

The app converts one uploaded evidence file into zero, one, or many structured
incident rows. The Add Incident page processes one file per review run.
Completed reviews can be combined later in the session-local Combine Reports
preview.

Supported inputs are audio, PDF, image, video, text, and CSV. Structured
incident CSVs go directly to Integration; text-oriented CSVs go through
`text/processor.py`. JSON uploads are rejected.

Integration standardizes extractor DataFrames, optionally fills image location
from OCR through `llm_summarizer.update_image_location(...)`, creates
`Incident_Summary` through `summarize_incident(...)`, generates `INC_TYPE_NUMBER`
IDs, and returns final rows for user confirmation. Confirmed rows are inserted
into Supabase. Dashboard, Manage Incidents, and final export read from Supabase.

## 3. Problem

Incident evidence can arrive as emergency calls, PDF reports, scene photos, surveillance video, typed reports, or CSV records. Reviewing these sources manually is slow and inconsistent. For a class demo, the project must show that multimodal AI, integration logic, rule-based fallback logic, and an OpenRouter-backed LLM summary module can turn messy unstructured or semi-structured evidence into consistent structured incident records.

## 4. Goals

| **ID** | **Goal** | **Success Target** |
| --- | --- | --- |
| G1 | Process supported evidence modalities | Audio, PDF, image, video, and text upload paths exist; CSV is handled as structured text input |
| G2 | Use a simple Streamlit upload workflow | The app accepts exactly one uploaded file per processing run |
| G3 | Support one file producing multiple incidents | A single uploaded file can produce zero, one, or many incident rows for confirmed insertion |
| G4 | Standardize through Integration | Extractor DataFrame is passed to Integration; Integration standardizes, summarizes, generates IDs, and returns final rows for confirmation before Supabase insert |
| G5 | Generate incident summaries | Integration calls the separate LLM summarizer function to add `Incident_Summary` before ID generation and confirmed insert |
| G6 | Generate stable synthetic IDs | Incident IDs use abbreviated `INC_TYPE_NUMBER`, such as `INC_VID_001` |
| G7 | Persist cleaned rows in Supabase | Rows are inserted into the Supabase `incidents` table after user confirmation |
| G8 | Provide dashboard review, management, and export | Streamlit can filter Supabase rows, show summaries, edit/remove saved incidents, and export the approved nine-field CSV |
| G9 | Provide safe fallbacks | OpenRouter summary or rule-based fallback summary works without required paid APIs |
| G10 | Produce consistent modality results | Audio, PDF, image, video, and text outputs follow their documented artifact schemas |
| G11 | Demonstrate cloud access | The hosted class prototype connects to Supabase using protected credentials |

## 5. Scope

| **Input Type** | **MVP Limit** | **Required Result** |
| --- | --- | --- |
| Audio | Exactly 1 uploaded file per run | Speech transcription and urgency/event extraction |
| PDF | Exactly 1 uploaded file per run | Page-aware direct text extraction, OCR fallback for scanned pages, and structured report fields |
| Image | Exactly 1 uploaded file per run | Scene/object detection, OCR, and bounded confidence |
| Video | Exactly 1 uploaded file per run; max 5 minutes | Regular frame sampling, motion gating, and timestamped event signals |
| Text | Exactly 1 uploaded `.txt` or `.csv` file per run | Preserved source text or structured CSV text evidence, with entities, sentiment/topic, or incident-like fields |

The main application contract remains the shared extractor DataFrame. For team review and demonstration, each unstructured modality also produces a small artifact with the following exact columns:

| **Modality** | **Artifact Columns** |
| --- | --- |
| Audio | `Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score` |
| PDF | `Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome` |
| Image | `Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score` |
| Video | `Timestamp, Frame_ID, Event_Detected, Objects, Confidence` |
| Text | `Text_ID, Source, Raw_Text, Sentiment, Entities, Topic` |

Structured text CSVs may contain `Event, Location, Time, Severity, Summary,
Confidence`. Modality artifacts are review artifacts; Supabase export uses the
final nine-field schema.

## 6. Core Processing Flow

```text
Streamlit Add Incident uploads exactly one file
        ↓
Detect file type and route to one extractor
        ↓
Extractor returns normalized intermediate pandas DataFrame
        ↓
Integration receives DataFrame and standardizes incident rows
        ↓
For image rows, Integration may call llm_summarizer.update_image_location(...)
        ↓
Integration calls llm_summarizer.summarize_incident(...) for each row
        ↓
Integration adds Incident_Summary and generates abbreviated INC_TYPE_NUMBER Incident_ID
        ↓
App maps final Integration rows to the Supabase insert payload
        ↓
App shows final rows for confirmation and inserts confirmed rows into Supabase incidents table
        ↓
Dashboard reads from Supabase
        ↓
Dashboard filtering, management, and final CSV export read from Supabase and output the nine required fields
```

## 7. Final Output and Data Persistence

The application must insert integrated and summarized incident rows into one Supabase table named `incidents` only after user confirmation.

The stored Supabase row and final CSV export must contain exactly these nine fields in this exact order:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

`id` and `created_at` are database-generated. Therefore, the insert payload sent by the app contains the other seven fields only: `incident_id, source, event, location, time, severity, incident_summary`. Missing text fields must be filled with `Unknown`. Severity must always be `Low`, `Medium`, `High`, or `Unknown`; when Event is `Unknown`, Severity must be `Low`. No final exported CSV row may contain null values.

## 8. LLM Summarizer Requirement

The LLM summary feature lives in `llm_summarizer/`, separate from modality
extractors:

```text
llm_summarizer/
├── __init__.py
├── summarizer.py
├── prompts.py
├── fallback.py
└── schemas.py
```

Integration calls the summarizer after standardization and before ID generation.
OpenRouter is optional; fallback summary must work without external LLM access.

## 9. Success Metrics

| **Metric** | **Target** |
| --- | --- |
| Modality coverage | 5/5 modalities have a route or clear processing error: audio, PDF, image, video, text; structured CSV is accepted through Integration and text-oriented CSV through `text/processor.py`; `.json` uploads are rejected |
| Upload behavior | Exactly one file is processed per Streamlit run |
| One-file-many-incidents behavior | A single uploaded file can produce zero, one, or many Supabase incident rows |
| DataFrame contract validity | Extractor output and Integration output match the documented schemas |
| LLM module separation | LLM summary code lives under `llm_summarizer/` and is called by the Integration workflow; it is not mixed into extractor code |
| Incident summary availability | Every inserted row has `incident_summary`; fallback is used if OpenRouter fails |
| ID validity | 100% of inserted rows use `INC_TYPE_NUMBER` with approved type abbreviations |
| Supabase insert success | Confirmed processed rows are inserted into the `incidents` table |
| Final schema validity | Exported CSV has exactly nine required fields and no extra fields |
| Missing value handling | 0 null values in final exported CSV |
| Dashboard usability | User can filter, read summaries, edit/remove saved incidents, and export incidents from Supabase without code |
| Modality artifact validity | Audio, PDF, image, video, and text artifacts use their exact documented columns |
| Hosted demo | Hosted app connects to Supabase without exposing credentials |
