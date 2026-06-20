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
| PDF | .pdf | PDF | Extract text directly; use OCR only when scanned or text is unavailable |
| Image | .jpg, .jpeg, .png | IMG | Run OCR/object detection if available, then extract incident signals |
| Video | .mp4, .mov, .mpg, .mpeg | VID | Reject videos longer than 5 minutes; sample frames and analyze motion frames |
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

The audio processor transcribes one audio file and extracts event and location signals. It assigns `Calm` or `Distressed` sentiment and an independent urgency score from `0.0` to `1.0`. If transcription fails, it returns safe `Unknown` values instead of crashing.

```text
Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score
```

For Integration, transcript, event, and location map to `raw_text`, `raw_event`, and `raw_location`. Urgency is not transcription confidence.

### 5.2 PDF Processor

The PDF processor extracts text directly from one official document and uses OCR only when the document is scanned or direct extraction is unavailable. Missing fields use `Unknown`.

```text
Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome
```

For Integration, incident type, date, location, and extracted text map to `raw_event`, `raw_time`, `raw_location`, and `raw_text`. Document `Summary` is source-grounded and is separate from the later LLM `incident_summary`.

### 5.3 Image Processor

The image processor analyzes one scene image with pretrained detection/classification and OCR. It reports only supported labels, uses a confidence from `0.0` to `1.0`, and uses `Unknown` when no supported evidence is found.

```text
Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score
```

For Integration, scene/object labels map to `raw_event`, OCR maps to `raw_text`, and the artifact score maps to `confidence`. OCR maps to location only when it clearly identifies one.

### 5.4 Video Processor

The video processor rejects clips longer than five minutes and samples frames at one documented interval. It records elapsed `HH:MM:SS` timestamps and sequential `FRM_NNN` IDs, applies frame-difference motion detection, and runs object detection only on qualifying motion frames. Activity labels require documented temporal or rule-based evidence; an object detection alone is insufficient.

```text
Timestamp, Frame_ID, Event_Detected, Objects, Confidence
```

For Integration, event, timestamp, and confidence map to `raw_event`, `raw_time`, and `confidence`; frame and detection context map to `raw_text`. One video may produce zero, one, or many rows.

### 5.5 Text Processor

The text processor preserves the original input while cleaning a separate analysis copy. It extracts people, locations, organizations, and dates, then assigns sentiment and one topic: `Theft / Robbery`, `Assault / Violence`, `Fire / Arson`, `Traffic Accident`, `Public Disturbance`, or `Other`.

```text
Text_ID, Source, Raw_Text, Sentiment, Entities, Topic
```

For Integration, topic, location entities, date entities, and original text map to `raw_event`, `raw_location`, `raw_time`, and `raw_text`.

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
- Validate required keys, types, and length before accepting model output.

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
| AC-003 | PDF processor runs | Direct extraction or conditional OCR produces the eight-field artifact and extractor mapping |
| AC-004 | Image processor runs | Supported scene/object/OCR results use the five-field artifact and extractor mapping |
| AC-005 | Video processor runs | Motion-gated sampled frames produce correctly formatted event rows |
| AC-006 | Text/CSV/JSON processor runs | Text artifact and structured content map to the extractor schema |
| AC-007 | Integration runs | Cleaned DataFrame has required integration columns |
| AC-008 | LLM summary module runs | Each row receives `incident_summary`, with fallback if needed |
| AC-009 | ID generation runs | Each row receives valid `INC_TYPE_NUMBER` ID |
| AC-010 | Supabase insert runs | Rows appear in Supabase `incidents` table automatically |
| AC-011 | Dashboard launches | Dataset table, filters, and summaries appear |
| AC-012 | Final export runs | CSV has exactly six approved columns and no null values |
| AC-013 | Hosted demo runs | App connects to Supabase without exposing credentials |

## 12. Edge Cases

| **Edge Case** | **Expected Behavior** |
| --- | --- |
| PDF has no extractable text | Attempt OCR if enabled; otherwise Unknown |
| Audio transcription fails | Use Unknown transcript-derived fields and continue |
| Image model detects no objects | Use OCR or Unknown fields |
| Video exceeds 5 minutes | Reject with clear message and no insert |
| Sampled video frame has no qualifying motion | Skip detection and do not create an unsupported event |
| Text has no location | Set Location = Unknown |
| Text has no supported topic | Set Topic = Other |
| CSV/JSON contains many rows | One file may produce multiple incident rows |
| Integration returns empty DataFrame | Insert nothing and show no incidents found |
| LLM unavailable | Use rule-based summary and mark `summary_method = rule_based` |
| Supabase insert fails | Show error and do not pretend rows were saved |
