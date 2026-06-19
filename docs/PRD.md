# Product Requirements Document: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 26, 2026 |

## 1. Project Summary

| **Field** | **Decision** |
| --- | --- |
| Project name | Multimodal Crime / Incident Report Analyzer |
| Owner | Group 2 |
| Project type | Class prototype only |
| Primary language | Python |
| Dashboard | Streamlit |
| Persistent data layer | Supabase Postgres, one main table named incidents |
| Input flow | Streamlit single-file upload; exactly one file per processing run |
| Processing mode | Synchronous processing inside the Streamlit app |
| Integration strategy | Extractor output is passed as a pandas DataFrame to Integration logic |
| LLM summary strategy | Separate `src/llm_summarizer/` module. The platform calls it after Integration and before Supabase insert. Local/free LLM when available, rule-based fallback always required. |
| Cloud/data scope | Supabase stores structured incident rows only; raw files are not uploaded to Supabase Storage in the MVP |
| Final submission date | June 26, 2026 |

## 2. Product Definition

The product is a class prototype that converts one uploaded multimodal evidence file into one or more structured incident rows. The app supports audio, PDF, image, video, text, CSV, and JSON inputs. Streamlit handles the upload and UI. The selected extractor processes the file synchronously and returns a normalized intermediate pandas DataFrame. Integration receives that DataFrame, cleans and standardizes the extracted information, and returns zero, one, or many incident rows.

After Integration, the platform must call the separate LLM summarizer function from `src/llm_summarizer/`. The summarizer adds a short `incident_summary` and summary metadata to each integrated row. The app then generates synthetic incident IDs using the abbreviated `INC_TYPE_NUMBER` format and automatically inserts the rows into the Supabase `incidents` table.

After insertion, the application treats Supabase as the source of truth. Dashboard filtering, selected-incident summary display, and final CSV export must read from Supabase, not from local intermediate files.

## 3. Problem

Incident evidence can arrive as emergency calls, PDF reports, scene photos, surveillance video, typed reports, CSV records, or JSON records. Reviewing these sources manually is slow and inconsistent. For a class demo, the project must show that multimodal AI, integration logic, rule-based fallback logic, and a local/free LLM summary module can turn messy unstructured or semi-structured evidence into consistent structured incident records.

## 4. Goals

| **ID** | **Goal** | **Success Target** |
| --- | --- | --- |
| G1 | Process supported evidence modalities | Audio, PDF, image, video, text, CSV, and JSON upload paths exist |
| G2 | Use a simple Streamlit upload workflow | The app accepts exactly one uploaded file per processing run |
| G3 | Support one file producing multiple incidents | A single uploaded file can insert zero, one, or many incident rows |
| G4 | Standardize through Integration | Extractor DataFrame is passed to Integration before summary and Supabase insert |
| G5 | Generate incident summaries | The platform calls the separate LLM summarizer function to add `incident_summary` before insert |
| G6 | Generate stable synthetic IDs | Incident IDs use abbreviated `INC_TYPE_NUMBER`, such as `INC_VID_001` |
| G7 | Persist cleaned rows in Supabase | Rows are automatically inserted into the Supabase `incidents` table |
| G8 | Provide dashboard review and export | Streamlit can filter Supabase rows, show summaries, and export the approved six-column CSV |
| G9 | Provide safe fallbacks | Local/free LLM summary or rule-based fallback summary works without paid APIs |

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

## 6. Users

| **User** | **Need** |
| --- | --- |
| Student Developer | Clear ownership, input contracts, output contracts, and testable tasks |
| Integration Lead | Stable extractor DataFrame contract, Integration contract, separate LLM summary function contract, ID rules, Supabase schema, and final export contract |
| Modality Developers | A clear DataFrame output contract for audio, PDF, image, video, text, CSV, and JSON processors |
| LLM Module Developer | A separate folder and function contract for incident summary generation with safe fallback behavior |
| Instructor / Evaluator | A clear end-to-end demo from upload to extractor to integration to LLM summary to Supabase table to final CSV export |
| Demo Analyst User | Simple dashboard for filtering, reading summaries, and exporting incident rows |

## 7. MVP Scope

| **Input Type** | **MVP Limit** | **Required Result** |
| --- | --- | --- |
| Audio | Exactly 1 uploaded file per run | Speech transcription and urgency/event extraction |
| PDF | Exactly 1 uploaded file per run | Report text extraction with OCR fallback when needed |
| Image | Exactly 1 uploaded file per run | Object/OCR extraction from scene images |
| Video | Exactly 1 uploaded file per run; max 5 minutes | Short surveillance clip frame sampling and event signals |
| Text | Exactly 1 uploaded file per run | Plain text incident evidence extraction |
| CSV | Exactly 1 uploaded file per run | Structured/semi-structured tabular incident evidence extraction |
| JSON | Exactly 1 uploaded file per run | Structured/semi-structured JSON incident evidence extraction |

## 8. Core Processing Flow

```text
Streamlit uploads exactly one file
        ↓
Detect file type and route to one extractor
        ↓
Extractor returns normalized intermediate pandas DataFrame
        ↓
Integration receives DataFrame and returns cleaned incident rows
        ↓
The platform calls src/llm_summarizer.summarize_incident(...) for each row
        ↓
App adds incident_summary, summary_method, and summary_model to rows
        ↓
App generates abbreviated INC_TYPE_NUMBER incident IDs
        ↓
App automatically inserts rows into Supabase incidents table
        ↓
Dashboard reads from Supabase
        ↓
Final CSV export reads from Supabase and outputs only six required columns
```

## 9. Final Output and Data Persistence

The application must automatically insert integrated and summarized incident rows into one Supabase table named `incidents`. The table may contain extra operational columns such as `source_filename`, `source_type`, `confidence`, `raw_text`, `incident_summary`, `summary_method`, `summary_model`, and `created_at`.

The final exported CSV for submission must contain exactly these six columns in this exact order:

```text
Incident_ID, Source, Event, Location, Time, Severity
```

Missing text fields must be filled with `Unknown`. Severity must always be `Low`, `Medium`, or `High`. No final exported CSV row may contain null values. Summary columns must remain in Supabase for dashboard display and must not be included in the final six-column CSV unless the instructor later explicitly changes the required CSV schema.

## 10. LLM Summarizer Requirement

The LLM summary feature is a required module, but it is not part of the core extraction logic and must not be hidden inside Integration code. It must live in a separate folder:

```text
src/llm_summarizer/
├── __init__.py
├── summarizer.py
├── prompts.py
├── fallback.py
└── schemas.py
```

Integration calls the summarizer after rows are standardized and before rows are inserted into Supabase. The summarizer should add a short human-readable incident summary to the main table. If the local/free LLM is unavailable, slow, or returns invalid output, the fallback summary must still produce a safe deterministic summary from the integrated row.

## 11. Success Metrics

| **Metric** | **Target** |
| --- | --- |
| Modality coverage | 7/7 supported input types have a route or graceful fallback: audio, PDF, image, video, text, CSV, JSON |
| Upload behavior | Exactly one file is processed per Streamlit run |
| One-file-many-incidents behavior | A single uploaded file can produce zero, one, or many Supabase incident rows |
| DataFrame contract validity | Extractor output and Integration output match the documented schemas |
| LLM module separation | LLM summary code lives under `src/llm_summarizer/` and is called by the platform; it is not mixed into extractor code |
| Summary availability | Every inserted row has `incident_summary`; fallback is used if LLM fails |
| ID validity | 100% of inserted rows use `INC_TYPE_NUMBER` with approved type abbreviations |
| Supabase insert success | Processed rows are inserted into the `incidents` table automatically |
| Final schema validity | Exported CSV has exactly six required columns and no extra columns |
| Missing value handling | 0 null values in final exported CSV |
| Dashboard usability | User can filter, read summaries, and export incidents from Supabase without code |
