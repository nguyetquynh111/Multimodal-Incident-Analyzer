# Functional Specifications: Multimodal Crime / Incident Report Analyzer

## 1. End-to-End Behavior

1. User starts the app with `streamlit run app.py` or opens the hosted prototype.
2. User uploads exactly one supported file on the Add Incident page.
3. App detects the file type and source abbreviation.
4. App runs the correct extractor synchronously.
5. Extractor returns its modality draft DataFrame.
6. Integration standardizes incident rows from the draft DataFrame.
7. For image rows with no explicit location, Integration may use the image OCR location helper.
8. Integration summarizes each standardized row.
9. Integration generates preview `INC_TYPE_NUMBER` IDs.
10. App displays final rows for confirmation.
11. Confirmed rows are mapped to the Supabase insert payload; saved IDs may be refreshed immediately before insert.
12. Dashboard, Manage Incidents, and final CSV export read from Supabase.
13. Combine Reports can export a session-local seven-field Integration preview from completed reviews.

## 2. Input Contract

| **Input Type** | **Extensions** | **Source Abbreviation** | **Required Behavior** |
| --- | --- | --- | --- |
| Audio | `.wav`, `.mp3`, `.m4a` | AUD | Transcribe locally, then extract event, location, sentiment, and urgency signals |
| PDF | `.pdf` | PDF | Extract embedded text per page; OCR scanned pages when possible |
| Image | `.jpg`, `.jpeg`, `.png` | IMG | Run OCR/object detection when configured, then extract incident signals |
| Video | `.mp4`, `.mov`, `.mpg`, `.mpeg` | VID | Reject clips over 5 minutes; sample frames and analyze motion-qualified frames |
| Text | `.txt`, `.csv` | TXT | Read free text; parse structured CSV rows when incident-like columns are present |
| JSON | `.json` | none | Reject with a clear unsupported-file message and no insert |

Additional input behavior:

- The Add Incident uploader accepts exactly one file per run.
- Raw files are processed in memory or temporary local storage only.
- Raw files are not uploaded to Supabase Storage in the MVP.
- A single uploaded file may produce zero, one, or many incident rows.
- JSON Lines content is allowed only when saved as a supported `.txt` input.

## 3. Modality Output Contract

Every modality processor returns a pandas DataFrame with its exact draft columns. A processor may return an empty DataFrame when no incident candidate is found.

| **Modality** | **Draft Columns** |
| --- | --- |
| Audio | `Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score` |
| PDF | `Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome` |
| Image | `Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score` |
| Video | `Timestamp, Frame_ID, Event_Detected, Objects, Confidence` |
| Text | `Text_ID, Source, Raw_Text, Sentiment, Entities, Topic` |
| Structured CSV text | `Event, Location, Time, Severity, Summary, Confidence` when available |

## 4. Feature Behavior by Modality

### 4.1 Audio

The audio processor transcribes one audio file with local Whisper and extracts event, location, sentiment, and urgency. A transcription failure must be shown as a processing error and must not insert rows.

### 4.2 PDF

The PDF processor extracts text from every page directly and attempts OCR for scanned pages. It emits one PDF draft row per uploaded PDF. Missing fields use `Unknown`.

### 4.3 Image

The image processor analyzes one scene image with Roboflow services when configured. Bounding boxes are session-only Visual Evidence metadata. Empty or failed detection must use safe placeholders instead of crashing.

Integration may use cleaned OCR text to fill a missing image location before summary generation.

### 4.4 Video

The video processor rejects clips longer than five minutes. Accepted clips are sampled every 0.5 seconds, use elapsed `HH:MM:SS` timestamps and `FRM_NNN` frame IDs, apply motion gating, and run object detection only on qualifying frames. Fire-color detection may emit `Fire detected` from sampled-frame evidence even without a qualifying motion frame.

### 4.5 Text and CSV

The text processor preserves `Raw_Text` and analyzes a cleaned copy for entities, sentiment, and topic. CSV files with incident-like columns are read directly into Integration; text-oriented CSVs go through the text processor when a recognized text column exists.

## 5. Integration Output Contract

Integration receives a draft DataFrame directly in memory. Its public output columns are:

```text
Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary
```

Required behavior:

- Normalize event, location, time, and severity.
- Convert missing final fields to `Unknown`.
- Use `Low`, `Medium`, `High`, or `Unknown` for severity.
- Apply severity rules from [rules.md](rules.md#8-severity-rules).
- Summarize rows before preview ID generation.
- Generate preview `INC_TYPE_NUMBER` IDs from current known IDs.
- Return zero, one, or many final incident rows.
- Leave Supabase insertion to the app/cloud layer after user confirmation.

## 6. LLM Summarizer Behavior

The Integration workflow calls the separate `llm_summarizer/` package after row standardization and before preview ID generation. For image rows, location extraction happens before summary generation.

Required summary return fields:

| **Return Field** | **Requirement** |
| --- | --- |
| `incident_summary` | One-to-three sentence summary grounded in cleaned integrated fields |
| `summary_method` | `llm`, `rule_based`, `disabled`, or `error` |
| `summary_model` | Model name when LLM is used; fallback/disabled/error label otherwise |

The accepted summary text becomes `Incident_Summary` in Integration output and `incident_summary` in Supabase.

## 7. Supabase and Export Behavior

The app insert payload contains only these seven app-provided fields:

```text
incident_id, source, event, location, time, severity, incident_summary
```

Supabase generates `id` and `created_at`. The dashboard final CSV export must contain exactly:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

No final exported CSV row may contain null values.

## 8. Dashboard Behavior

The Streamlit app must:

- Show processing status and errors.
- Show extractor-row and integrated-row counts.
- Preview rows before insertion.
- Insert only after user confirmation.
- Display Supabase `incidents` rows.
- Filter by Incident_ID, Source, Event, Location, and Severity display labels.
- Show `incident_summary` for selected rows.
- Export the final nine-field CSV from Supabase.
- Provide Combine Reports as a session-local seven-field preview export.
- Provide Manage Incidents actions for add, edit, bulk update, and delete.
- Keep `incident_id` and `source` immutable during edits.

## 9. Edge Cases

| **Edge Case** | **Expected Behavior** |
| --- | --- |
| Unsupported file type | Show clear error and insert nothing |
| `.json` upload | Reject with unsupported-file message and insert nothing |
| Extractor returns empty DataFrame | Show no incidents found and insert nothing |
| Audio transcription fails | Show processing error and insert nothing |
| PDF page has no extractable text | Attempt OCR; use `Unknown` if OCR is unavailable or fails |
| Image model detects no supported objects | Use safe placeholders and map final fields safely |
| Video exceeds 5 minutes | Reject with clear message and insert nothing |
| Video frame has no qualifying motion | Skip YOLO for that frame; do not invent an activity event |
| Text has no location | Set Location to `Unknown` |
| Text has no supported topic | Set Topic to `Other` |
| CSV contains many rows | Produce multiple final rows when appropriate |
| LLM unavailable | Use rule-based summary fallback |
| Supabase insert fails | Show error and do not pretend rows were saved |

## 10. Acceptance Criteria

| **ID** | **Scenario** | **Expected Result** |
| --- | --- | --- |
| AC-001 | User uploads one supported file | Correct extractor route is selected |
| AC-002 | Audio processor runs | Audio draft DataFrame is returned or a processing error is displayed |
| AC-003 | PDF processor runs | One-row, eight-column PDF draft is produced with OCR fallback when needed |
| AC-004 | Image processor runs | Five-column image draft is produced; available boxes appear as visual evidence |
| AC-005 | Video processor runs | Motion-gated sampled frames produce correctly formatted event rows |
| AC-006 | Text/CSV processor runs | Text and CSV inputs map through the correct text contract; JSON is rejected |
| AC-007 | Integration runs | Final DataFrame has the seven Integration output columns |
| AC-008 | Summary runs | Each final row has `Incident_Summary`, with fallback if needed |
| AC-009 | ID generation runs | Each final row has a valid preview `INC_TYPE_NUMBER` ID |
| AC-010 | Supabase insert runs | Confirmed rows appear in Supabase `incidents` |
| AC-011 | Dashboard launches | Table, filters, management, and summaries appear |
| AC-012 | Final export runs | CSV has exactly nine approved fields and no null values |
| AC-013 | Hosted demo runs | App connects to Supabase without exposing credentials |
