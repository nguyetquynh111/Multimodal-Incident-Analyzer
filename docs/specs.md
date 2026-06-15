# specs.md

## 1. Purpose

This file defines the product behavior and data contracts for the Multimodal Crime / Incident Report Analyzer. It focuses on what the system must do, not how the code is structured.

## 2. Input Contract

Each synthetic case is stored under:

```text
data/raw/INC_###/
```

Expected subfolders:

```text
audio/
pdf/
images/
video/
text/
```

Supported MVP limits:

| Modality | Limit |
|---|---:|
| Audio | Up to 3 files |
| PDF | Up to 1 file |
| Images | Up to 20 files |
| Video | Up to 1 file, max 5 minutes |
| Text | Up to 20 entries |

## 3. Final Dataset Schema

The integration module must create:

```text
data/final/final_incidents.csv
```

Required columns, in exact order:

| Column | Type | Required | Rule |
|---|---|---|---|
| Incident_ID | string | Yes | Format `INC_###` |
| Source | string | Yes | `Audio`, `PDF`, `Image`, `Video`, `Text`, or `Merged` |
| Event | string | Yes | Free text or `Unknown` |
| Location | string | Yes | Free text or `Unknown` |
| Time | string | Yes | ISO-like string, timestamp, or `Unknown` |
| Severity | string | Yes | `Low`, `Medium`, or `High` |

Final CSV must contain no null values and no extra columns.

## 4. Intermediate Output Contracts

Each modality writes one intermediate CSV to `data/intermediate/`.

| Modality | File | Minimum Fields |
|---|---|---|
| Audio | `audio_intermediate.csv` | `Incident_ID`, `Call_ID`, `Transcript`, `Extracted_Event`, `Location`, `Sentiment`, `Urgency_Score` |
| PDF | `pdf_intermediate.csv` | `Incident_ID`, `Report_ID`, `Incident_Type`, `Date`, `Location`, `Officer`, `Summary` |
| Image | `image_intermediate.csv` | `Incident_ID`, `Image_ID`, `Scene_Type`, `Objects_Detected`, `Text_Extracted`, `Confidence_Score` |
| Video | `video_intermediate.csv` | `Incident_ID`, `Clip_ID`, `Timestamp`, `Frame_ID`, `Event_Detected`, `Objects`, `Confidence` |
| Text | `text_intermediate.csv` | `Incident_ID`, `Text_ID`, `Source`, `Raw_Text`, `Sentiment`, `Entities`, `Topic` |

Intermediate files may have extra fields for debugging. Extra fields must not appear in the final CSV.

## 5. Functional Specifications

### 5.1 Ingestion

The ingestion module must:

- Create synthetic IDs in the format `INC_###`.
- Place raw evidence into the correct modality subfolder.
- Support missing modality folders without crashing.
- Skip unsupported file types and log the reason.

### 5.2 Audio Processor

The audio processor must:

- Read up to 3 audio files per case.
- Transcribe audio using a local or free speech-to-text option.
- Extract transcript-based event, location, sentiment, and urgency signals.
- Output `audio_intermediate.csv`.

### 5.3 PDF Processor

The PDF processor must:

- Read up to 1 PDF per case.
- Extract text from text-based PDFs.
- Attempt OCR fallback if PDF text extraction is empty or near-empty.
- Extract incident type, date/time, location, officer/person entities when available.
- Output `pdf_intermediate.csv`.

### 5.4 Image Processor

The image processor must:

- Read up to 20 images per case.
- Detect relevant objects when supported by the selected model.
- Attempt OCR for visible signs, labels, or street text.
- Output `image_intermediate.csv`.

### 5.5 Video Processor

The video processor must:

- Read up to 1 surveillance video per case.
- Reject videos longer than 5 minutes.
- Extract frames at configurable intervals.
- Detect objects and simple abnormal event signals when possible.
- Output `video_intermediate.csv`.

### 5.6 Text Processor

The text processor must:

- Read up to 20 text evidence entries per case.
- Clean raw text.
- Extract entities, sentiment, topic, time, and location signals when available.
- Output `text_intermediate.csv`.

### 5.7 Integration

The integration module must:

- Load available intermediate CSVs.
- Normalize fields into the final schema.
- Fill missing final values with `Unknown`.
- Compute severity.
- Save `final_incidents.csv`.
- Validate schema before dashboard launch.

### 5.8 Dashboard

The Streamlit dashboard must:

- Display the final dataset.
- Filter by `Incident_ID`, `Source`, `Event`, `Location`, and `Severity`.
- Show a selected incident summary.
- Provide a final CSV download button.
- Show setup guidance instead of crashing when the final CSV is missing or empty.

## 6. Acceptance Criteria

| ID | Scenario | Expected Result |
|---|---|---|
| AC-001 | Raw files are placed in a case folder | System assigns `INC_###` |
| AC-002 | Audio processor runs | Audio intermediate CSV is generated |
| AC-003 | PDF processor runs | PDF intermediate CSV is generated |
| AC-004 | Image processor runs | Image intermediate CSV is generated |
| AC-005 | Video processor runs | Timestamped video signals are generated |
| AC-006 | Text processor runs | Text intermediate CSV is generated |
| AC-007 | Integration runs | Final CSV has exactly six approved columns |
| AC-008 | A modality is missing | Pipeline still generates final CSV |
| AC-009 | Severity is computed | Value is only `Low`, `Medium`, or `High` |
| AC-010 | Dashboard launches | Dataset table and filters appear |
| AC-011 | LLM fails | Rule-based summary appears |
| AC-012 | Fast demo mode is enabled | Cached outputs can regenerate final CSV |

## 7. Edge Cases

| Edge Case | Expected Behavior |
|---|---|
| PDF has no extractable text | Attempt OCR; if failed, output `Unknown` |
| Audio transcription fails | Store `Unknown` transcript-derived fields and continue |
| Image model detects no objects | Use OCR or other modality signal; otherwise `Unknown` |
| Video exceeds 5 minutes | Reject with clear message |
| Text has no location | Set `Location = Unknown` |
| Multiple modalities disagree | Use priority rules from `rules.md` |
| Local LLM fails | Use rule-based summary |
| Empty final CSV | Dashboard shows setup guidance |
