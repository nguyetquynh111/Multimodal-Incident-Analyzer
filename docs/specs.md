# Functional Specifications: Multimodal Crime / Incident Report Analyzer

## 1. Approved End-to-End Behavior

```text
1. User starts the app with `streamlit run app.py` and opens the Streamlit app.
2. User uploads exactly one supported file on the Add Incident page.
3. App detects the file type and source abbreviation.
4. App runs the correct extractor synchronously.
5. Processor returns its documented modality draft DataFrame.
6. Integration receives that DataFrame and standardizes incident rows.
7. For image rows with no explicit `Location`, Integration calls the separate image OCR location helper.
8. Integration calls the separate LLM summarizer function for each standardized row.
9. Integration adds `Incident_Summary` to each row.
10. Integration generates INC_TYPE_NUMBER `Incident_ID` values and returns final rows.
11. App shows final Integration rows for confirmation, then maps confirmed rows to the Supabase insert payload and inserts them.
12. The dashboard, Manage Incidents page, and final nine-field CSV export read from Supabase. The separate Combine Reports view can download a session-local seven-field Integration preview from completed reviews.
```

## 2. Input Contract

| **Input Type** | **Extensions** | **Source Abbreviation** | **MVP Behavior** |
| --- | --- | --- | --- |
| Audio | .wav, .mp3, .m4a | AUD | Transcribe locally, then extract event, location, sentiment, and urgency signals; transcription errors are shown to the user |
| PDF | .pdf | PDF | Extract embedded text per page; OCR scanned pages when possible |
| Image | .jpg, .jpeg, .png | IMG | Run OCR/object detection if available, then extract incident signals |
| Video | .mp4, .mov, .mpg, .mpeg | VID | Reject videos longer than 5 minutes; sample frames and analyze motion frames |
| Text | .txt, .csv | TXT | Read free text; parse CSV rows as structured text evidence; `.json` uploads are unsupported |

Rules:
- The Add Incident uploader accepts exactly one file per processing run.
- Completed review drafts may be kept in a browser-session queue for the Combine Reports preview.
- A single uploaded file can produce zero, one, or many incident rows.
- Raw files are processed in memory or temporary local storage only.
- Raw files are not uploaded to Supabase Storage in the MVP.
- Unsupported file types must be rejected with a clear message and no Supabase insert.

## 3. Modality Output Contract

Every modality processor returns its documented draft DataFrame below.
Integration maps each draft into final incident rows. A
processor may return an empty DataFrame when no incident candidate is found.

## 4. Modality Functional Specifications

### 4.1 Audio Processor

The audio processor transcribes one audio file with local Whisper and extracts
event, location, sentiment, and urgency. It defaults to `small.en`; deployments
may override `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_LANGUAGE`,
`WHISPER_MODEL_DIR`, and `WHISPER_BEAM_SIZE`. A transcription failure raises an
error for the Streamlit app.

```text
Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score
```

Integration maps event and location directly; urgency contributes to severity
after event-category rules are applied.

### 4.2 PDF Processor

The PDF processor extracts text from every page directly and OCRs scanned pages at 300 DPI when possible. It produces one artifact row per uploaded PDF; missing fields use `Unknown`.

```text
Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome
```

Integration maps incident type, location, and date directly to Event, Location,
and Time. Document `Summary` remains source-grounded supporting context.

### 4.3 Image Processor

The image processor analyzes one scene image with the Roboflow Inference SDK and
OCR. OCR runs on the full grayscale image, keeps cleaned OCR lines with at least
three alphanumeric characters, joins them into `Text_Extracted`, and otherwise
uses `N/A`. Roboflow
bounding-box coordinates are kept as session metadata for the Streamlit Visual
Evidence overlay, while the required CSV artifact remains five columns. Image
location handling happens in Integration: OCR writes `Text_Extracted`,
Integration calls
`llm_summarizer.update_image_location(...)` to fill a missing `Location`, and only
then Integration calls `summarize_incident(...)`. It runs the fire Roboflow model
plus the person model through the default
`https://detect.roboflow.com` endpoint, uses labels such as `Fire Scene`,
`Smoke Scene`, `Fire and Smoke Scene`, and `Fire and Person Scene`, and averages valid detection
confidences from the model response bounded from `0.0` to `1.0`. The score is
the rounded model-derived average, and the neutral `0.5` confidence is used
only when no valid detection confidence is available. When no object is
returned, the artifact uses `General Scene`, `Objects_Detected = None`, and a
neutral `Confidence_Score` of `0.5`. If Roboflow is unavailable, quota is
exhausted, or the API key is missing, the processor writes the same safe
scene/object placeholders with neutral `0.5` confidence instead of crashing;
OCR still runs independently and may still populate `Text_Extracted`.

```text
Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score
```

Integration maps scene/object labels to Event. Event-category rules are applied
before the score is used for Severity.

### 4.4 Video Processor

The Streamlit path rejects clips longer than five minutes and samples frames
every 0.5 seconds. It records elapsed `HH:MM:SS` timestamps and `FRM_NNN` IDs
based on the original frame index, applies MOG2 background subtraction motion
detection, and runs object detection only on qualifying motion frames. YOLO uses
`VIDEO_YOLO_SAMPLE_STRIDE=4` and `VIDEO_YOLO_IMAGE_SIZE=320` unless overridden,
and can load an alternate path such as an exported ONNX model through
`VIDEO_YOLO_MODEL_PATH`. Activity labels require documented temporal or
rule-based evidence; an object detection alone is insufficient.

```text
Timestamp, Frame_ID, Event_Detected, Objects, Confidence
```

Integration maps event and timestamp directly. Event-category rules are applied
before Confidence is used for Severity. One video may produce zero, one, or many
rows.

### 4.5 Text Processor

The text processor preserves the original input while cleaning a separate analysis copy. It extracts people, locations, organizations, and dates, then assigns sentiment and one topic: `Theft / Robbery`, `Assault / Violence`, `Fire / Arson`, `Traffic Accident`, `Public Disturbance`, or `Other`.

```text
Text_ID, Source, Raw_Text, Sentiment, Entities, Topic
```

Integration maps topic and location entities directly to Event and Location.

### 4.6 Structured CSV Text Input

The modality dispatcher reads structured incident CSVs directly into a pandas
DataFrame when they contain incident-like columns such as `Event`, `Location`,
`Time`, or `Severity`; Integration then standardizes those rows. Other CSVs are
sent to `text/processor.py`, which requires a recognized text column and emits
the six-column text artifact. Multiple incident rows may produce multiple final
rows. Unknown values must be handled explicitly.

```text
Event, Location, Time, Severity, Summary, Confidence
```

### 4.7 Unsupported JSON Input

JSON file uploads are not supported in the MVP. If a user uploads a `.json` file, the app must show a clear unsupported-file message and must not insert rows into Supabase.

## 5. Integration Contract

Integration receives the extractor DataFrame directly in memory. It does not receive a local CSV file path as the primary contract.

Required function:

```text
def integrate_records(draft_df: pandas.DataFrame, source_type: str) -> pandas.DataFrame:
    """Run the full Integration workflow and return final incident rows."""
```

Required public Integration workflow output columns after summarization and ID generation:

```text
Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary
```

Integration responsibilities:
- Normalize event names.
- Normalize location and time fields.
- Convert missing fields to Unknown.
- Compute or normalize severity to Low, Medium, High, or Unknown. Event-category
  rules run before generic confidence scoring: Unknown, Other, and No Activity
  are Low; fire/arson/assault/violence and other configured safety-critical
  terms are High; theft/robbery/burglary/disturbance/property damage are at
  least Medium.
- For image rows with no explicit `Location`, call
  `llm_summarizer.update_image_location(...)` before final summarization.
- Call `llm_summarizer.summarize_incident(...)` for each standardized row.
- Add `Incident_Summary`.
- Generate `Incident_ID` using the approved `INC_TYPE_NUMBER` rule.
- Return zero, one, or many final incident rows.

Integration must complete `Incident_Summary` and `Incident_ID` before any Supabase insert happens. Summary generation happens before ID generation. Supabase insertion itself is handled by the cloud/app layer after Integration returns final rows and the user confirms them.

## 6. LLM Summarizer Contract

The LLM summary module is a separate folder and is required:

```text
llm_summarizer/
├── __init__.py
├── summarizer.py
├── prompts.py
├── fallback.py
└── schemas.py
```

The Integration workflow calls the public functions from this folder after row standardization and before ID generation/Supabase insertion. For image rows, location extraction happens before summary generation:

```text
from llm_summarizer.summarizer import summarize_incident, update_image_location

image_row = update_image_location(image_row)
result = summarize_incident(incident_row: dict)
```

Required input fields in `incident_row`:

```text
source, event, location, time, severity
```

Optional supporting fields may include `source_type`, `confidence`, and
`raw_text` when available, but `raw_text` is not sent to the summary prompt.
Image OCR text is used earlier by `update_image_location(row)` to fill a
missing `Location`; summary generation then uses the cleaned location field.

Required return fields:

| **Return Field** | **Type** | **Requirement** |
| --- | --- | --- |
| incident_summary | string | Short one-to-three sentence summary of the integrated incident row |
| summary_method | string | One of llm, rule_based, disabled, error |
| summary_model | string | Model name when LLM is used; otherwise fallback/disabled/error label |

Summary behavior:
- Use OpenRouter if enabled and available.
- Use deterministic fallback if the LLM fails, is disabled, is too slow, or produces invalid output.
- Do not invent details that are not present in cleaned integrated fields.
- Do not overwrite `event`, `location`, `time`, or `severity`.
- Store the accepted summary text as `Incident_Summary` in the Integration output, then map it to `incident_summary` in the Supabase `incidents` table.
- Validate required keys, types, and length before accepting model output.

## 7. Supabase Main Table Contract

The MVP uses one table named `incidents`. Required columns:

| **Column** | **Purpose** |
| --- | --- |
| id | Database-generated row id |
| created_at | Supabase insert timestamp |
| incident_id | Unique synthetic project ID, generated as INC_TYPE_NUMBER |
| source | Modality/source value: Audio, PDF, Image, Video, or Text |
| event | Final normalized event or Unknown |
| location | Final normalized location or Unknown |
| time | Final normalized time or Unknown |
| severity | Low, Medium, High, or Unknown; Low when event is Unknown |
| incident_summary | OpenRouter/fallback incident summary for dashboard display and export |

## 8. Final CSV Export Contract

The app insert payload contains seven app-provided fields: `incident_id, source, event, location, time, severity, incident_summary`. Supabase generates `id` and `created_at`.

The dashboard's final CSV export is generated from Supabase and must contain exactly:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

## 9. Dashboard Specifications

The Streamlit app must:
- Upload exactly one supported file per Add Incident review run.
- Show processing status and errors.
- Show number of extractor rows and integrated rows.
- Preview successful rows and insert them into Supabase after user confirmation.
- Display Supabase `incidents` table rows.
- Filter by user-friendly dashboard labels: Incident_ID, Source, Event, Location, and Severity. These are display labels and may map to lower-case Supabase columns in code.
- Show `incident_summary` for selected rows.
- Export the final nine-field CSV from Supabase.
- Provide a Combine Reports view that rebuilds and downloads a session-local seven-field Integration preview from completed reviews.
- Provide a Manage Incidents view for manual add, edit, bulk update, and delete operations against Supabase rows; `incident_id` and `source` remain immutable in edits.

## 10. Acceptance Criteria

| **ID** | **Scenario** | **Expected Result** |
| --- | --- | --- |
| AC-001 | User uploads one supported file | Correct extractor route is selected |
| AC-002 | Audio processor runs | Extractor DataFrame is returned, or the app displays a transcription/processing error |
| AC-003 | PDF processor runs | Page-aware direct extraction plus OCR fallback produces the one-row, eight-column PDF artifact |
| AC-004 | Image processor runs | Supported scene/object/OCR results use the five-field artifact, and available Roboflow boxes appear in the image visual evidence overlay |
| AC-005 | Video processor runs | Motion-gated sampled frames produce correctly formatted event rows |
| AC-006 | Text processor runs | Text and CSV inputs map through the text modality contract; `.json` uploads are rejected |
| AC-007 | Integration runs | Final DataFrame has `Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary` |
| AC-008 | LLM summary module runs | Integration gives each row `Incident_Summary`, with fallback if needed |
| AC-009 | ID generation runs | Integration gives each row valid `INC_TYPE_NUMBER` `Incident_ID` |
| AC-010 | Supabase insert runs | Confirmed rows appear in Supabase `incidents` table |
| AC-011 | Dashboard launches | Charts, dataset table, filters, and summaries appear |
| AC-012 | Final export runs | CSV has exactly nine approved fields and no null values |
| AC-013 | Hosted demo runs | App connects to Supabase without exposing credentials |
| AC-014 | Manage Incidents runs | User can add, edit, bulk update, or remove Supabase-backed incidents without changing immutable incident IDs or sources |

## 11. Edge Cases

| **Edge Case** | **Expected Behavior** |
| --- | --- |
| PDF page has no extractable text | Attempt scanned-page OCR; use Unknown fields if OCR is unavailable or fails |
| Audio transcription fails | Show a processing error and do not insert rows |
| Image model detects no supported objects | Keep image artifact values such as `Objects_Detected = None` and `Text_Extracted = N/A` when appropriate; final Integration fields still map safely |
| Video exceeds 5 minutes | Reject with clear message and no insert |
| Sampled video frame has no qualifying motion | Skip detection and do not create an unsupported event |
| Text has no location | Set Location = Unknown |
| Text has no supported topic | Set Topic = Other |
| CSV contains many rows | One file may produce multiple incident rows |
| User uploads `.json` | Reject with a clear unsupported-file message and no insert |
| Integration returns empty DataFrame | Insert nothing and show no incidents found |
| LLM unavailable | Use rule-based summary in `incident_summary` |
| Supabase insert fails | Show error and do not pretend rows were saved |
