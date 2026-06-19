# Functional Specifications: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 26, 2026 |

## 1. Purpose

This document defines product behavior and data contracts for the Multimodal Crime / Incident Report Analyzer. It focuses on what the system must do and how modules must communicate. It replaces older local-folder, watch-folder, SQLite, and CSV-combine contracts with the approved Streamlit + Supabase flow.

## 2. Approved End-to-End Behavior

```text
1. User opens the Streamlit app.
2. User uploads exactly one supported file.
3. App detects the file type and source abbreviation.
4. App runs the correct extractor synchronously.
5. Extractor returns a pandas DataFrame using the extractor schema.
6. Integration receives that DataFrame and returns cleaned incident rows.
7. The platform calls the separate LLM summarizer function for each cleaned row.
8. App adds summary columns to each row.
9. App generates INC_TYPE_NUMBER IDs.
10. App automatically inserts rows into the Supabase incidents table.
11. Dashboard and final CSV export read from Supabase only.
```

## 3. Input Contract

| **Input Type** | **Extensions** | **Source Abbreviation** | **MVP Behavior** |
| --- | --- | --- | --- |
| Audio | .wav, .mp3, .m4a | AUD | Transcribe or fallback, then extract event/location/time/severity signals |
| PDF | .pdf | PDF | Extract text, use OCR fallback when enabled, then extract incident fields |
| Image | .jpg, .jpeg, .png | IMG | Run OCR/object detection if available, then extract incident signals |
| Video | .mp4, .mov | VID | Reject videos longer than 5 minutes; sample frames from short videos |
| Text | .txt | TXT | Read text and extract incident fields |
| CSV | .csv | CSV | Parse rows/columns and map incident-like records into the extractor schema |
| JSON | .json | JSON | Parse JSON objects/arrays and map incident-like records into the extractor schema |

Rules:
- The Streamlit uploader accepts exactly one file per processing run.
- A single uploaded file can produce zero, one, or many incident rows.
- Raw files are processed in memory or temporary local storage only.
- Raw files are not uploaded to Supabase Storage in the MVP.
- Unsupported file types must be rejected with a clear message and no Supabase insert.

## 4. Extractor Output Contract

Every modality processor must return a pandas DataFrame. Required columns:

```text
source_filename, source_type, raw_event, raw_location, raw_time, raw_severity, confidence, raw_text
```

| **Column** | **Type** | **Requirement** |
| --- | --- | --- |
| source_filename | string | Original uploaded filename |
| source_type | string | One of AUD, PDF, IMG, VID, TXT, CSV, JSON |
| raw_event | string | Extractor-level event label or Unknown |
| raw_location | string | Extractor-level location or Unknown |
| raw_time | string | Extractor-level time or Unknown |
| raw_severity | string | Extractor-level severity signal or Unknown |
| confidence | float | 0.0 to 1.0 if available; otherwise 0.0 |
| raw_text | string | Extracted transcript/text/OCR/structured context or Unknown |

A processor may return an empty DataFrame if no incident candidate is found. Empty output should not crash the app.

## 5. Modality Functional Specifications

### 5.1 Audio Processor

The audio processor must read one uploaded audio file, transcribe when a local/free speech-to-text option is available, and extract transcript-based event, location, time, sentiment, and urgency signals. If transcription fails, it must return Unknown transcript-derived fields instead of crashing.

### 5.2 PDF Processor

The PDF processor must read one uploaded PDF, extract text from text-based PDFs, and attempt OCR fallback if text extraction is empty or near-empty and OCR is enabled. It should extract incident type, date/time, location, officer/person entities, and report summary signals when available.

### 5.3 Image Processor

The image processor must read one uploaded image, detect relevant objects when supported by the selected local/free model, and attempt OCR for signs, labels, street text, or visible reports. If no objects or text are found, use Unknown fields.

### 5.4 Video Processor

The video processor must read one uploaded surveillance video, reject files longer than 5 minutes, sample frames at configurable intervals, and detect objects or abnormal event signals when possible. It can produce multiple incident candidate rows from one video.

### 5.5 Text Processor

The text processor must read one uploaded text file, clean raw text, and extract event, entities, sentiment, topic, time, and location signals when available.

### 5.6 CSV Processor

The CSV processor must parse one uploaded CSV file. If the file already has incident-like columns, map them into the extractor schema. If the CSV has multiple incident rows, the processor may produce multiple extractor rows. Unknown values must be handled explicitly.

### 5.7 JSON Processor

The JSON processor must parse one uploaded JSON file. If the JSON contains a list of incident-like objects, each object may become one extractor row. Nested values should be flattened only as needed for the extractor schema.

## 6. Integration Contract

Integration receives the extractor DataFrame directly in memory. It does not receive a local CSV file path as the primary contract.

Required function:

```text
def integrate_records(extractor_df: pandas.DataFrame) -> pandas.DataFrame:
    """Normalize extractor output into cleaned incident rows."""
```

Required output columns before ID and summary:

```text
event, location, time, severity, confidence, raw_text
```

Integration responsibilities:
- Normalize event names.
- Normalize location and time fields.
- Convert missing fields to Unknown.
- Compute or normalize severity to Low, Medium, or High.
- Preserve enough raw text/context for the LLM summarizer.
- Return zero, one, or many cleaned incident rows.

Integration must not call Supabase insert until ID generation and LLM summary enrichment are complete.

## 7. LLM Summarizer Contract

The LLM summary module is a separate folder and is required:

```text
src/llm_summarizer/
├── __init__.py
├── summarizer.py
├── prompts.py
├── fallback.py
└── schemas.py
```

The platform calls the public function from this folder after Integration and before Supabase insertion:

```text
from src.llm_summarizer.summarizer import summarize_incident

result = summarize_incident(incident_row: dict)
```

Required input fields in `incident_row`:

```text
source, source_type, event, location, time, severity, confidence, raw_text
```

Required return fields:

| **Return Field** | **Type** | **Requirement** |
| --- | --- | --- |
| incident_summary | string | Short one-to-three sentence summary of the integrated incident row |
| summary_method | string | One of llm, rule_based, disabled, error |
| summary_model | string | Model name when LLM is used; otherwise fallback/disabled/error label |

Summary behavior:
- Use a local/free LLM if enabled and available.
- Use deterministic fallback if the LLM fails, is disabled, is too slow, or produces invalid output.
- Do not invent details that are not present in integrated fields or raw text.
- Do not overwrite `event`, `location`, `time`, or `severity`.
- Store the summary fields in the same Supabase `incidents` table.

## 8. Supabase Main Table Contract

The MVP uses one table named `incidents`. Required columns:

| **Column** | **Purpose** |
| --- | --- |
| incident_id | Primary key, generated as INC_TYPE_NUMBER |
| source | Human-readable source name for final CSV export |
| event | Final normalized event or Unknown |
| location | Final normalized location or Unknown |
| time | Final normalized time or Unknown |
| severity | Low, Medium, or High |
| source_filename | Original uploaded filename |
| source_type | AUD, PDF, IMG, VID, TXT, CSV, or JSON |
| confidence | Normalized confidence score |
| raw_text | Raw or cleaned extracted context for debugging and summary |
| incident_summary | LLM/fallback summary for dashboard display |
| summary_method | llm, rule_based, disabled, or error |
| summary_model | Name/label of model or fallback method |
| created_at | Supabase insert timestamp |

## 9. Final CSV Export Contract

The final CSV export is generated from Supabase and must contain exactly:

```text
Incident_ID, Source, Event, Location, Time, Severity
```

Mapping:

| **CSV Column** | **Supabase Column** |
| --- | --- |
| Incident_ID | incident_id |
| Source | source |
| Event | event |
| Location | location |
| Time | time |
| Severity | severity |

`incident_summary` is shown in the dashboard but is not part of the required final CSV export.

## 10. Dashboard Specifications

The Streamlit dashboard must:
- Upload exactly one supported file.
- Show processing status and errors.
- Show number of extractor rows and integrated rows.
- Auto insert successful rows into Supabase.
- Display Supabase `incidents` table rows.
- Filter by Incident_ID, Source, Event, Location, Severity, and Source Type.
- Show `incident_summary` for selected rows.
- Export the final six-column CSV from Supabase.

## 11. Acceptance Criteria

| **ID** | **Scenario** | **Expected Result** |
| --- | --- | --- |
| AC-001 | User uploads one supported file | Correct extractor route is selected |
| AC-002 | Audio processor runs | Extractor DataFrame is returned or safe Unknown fallback appears |
| AC-003 | PDF processor runs | PDF text/OCR signals map to extractor schema |
| AC-004 | Image processor runs | Image OCR/object signals map to extractor schema |
| AC-005 | Video processor runs | Short video is sampled and can produce multiple incident rows |
| AC-006 | Text/CSV/JSON processor runs | Structured or text content maps to extractor schema |
| AC-007 | Integration runs | Cleaned DataFrame has required integration columns |
| AC-008 | LLM summary module runs | Each row receives `incident_summary`, with fallback if needed |
| AC-009 | ID generation runs | Each row receives valid `INC_TYPE_NUMBER` ID |
| AC-010 | Supabase insert runs | Rows appear in Supabase `incidents` table automatically |
| AC-011 | Dashboard launches | Dataset table, filters, and summaries appear |
| AC-012 | Final export runs | CSV has exactly six approved columns and no null values |

## 12. Edge Cases

| **Edge Case** | **Expected Behavior** |
| --- | --- |
| PDF has no extractable text | Attempt OCR if enabled; otherwise Unknown |
| Audio transcription fails | Use Unknown transcript-derived fields and continue |
| Image model detects no objects | Use OCR or Unknown fields |
| Video exceeds 5 minutes | Reject with clear message and no insert |
| Text has no location | Set Location = Unknown |
| CSV/JSON contains many rows | One file may produce multiple incident rows |
| Integration returns empty DataFrame | Insert nothing and show no incidents found |
| LLM unavailable | Use rule-based summary and mark `summary_method = rule_based` |
| Supabase insert fails | Show error and do not pretend rows were saved |
