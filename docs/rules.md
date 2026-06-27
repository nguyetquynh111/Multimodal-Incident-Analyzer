# Project Rules: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 28, 2026 |

## 1. Core Project Rules

| **Rule** | **Requirement** |
| --- | --- |
| Class prototype only | Do not present the app as production emergency software |
| Python required | Use Python for all processing and Streamlit dashboard code |
| No paid APIs | Do not require paid LLM, paid OCR, paid speech, or paid cloud inference APIs |
| No committed secrets | Do not commit Supabase keys, API keys, credentials, or private data |
| Single-file upload | The MVP processes exactly one uploaded file per Streamlit processing run |
| Synchronous processing | Processing occurs inside the Streamlit session; rows are inserted only after the user confirms the final Integration result |
| Supabase source of truth | After insert, dashboard and export must read from Supabase `incidents` table |
| One main table | Use one Supabase table named `incidents` for structured incident rows and the `incident_summary` column |
| LLM summary is separate | LLM summary code must live in `llm_summarizer/`, not inside extractors or hidden inside Integration |
| No raw Supabase Storage in MVP | Do not upload raw evidence files to Supabase Storage as a required MVP feature |
| No watch-folder flow | Do not implement local watch-folder monitoring as the main pipeline |
| No SQLite source of truth | Do not use SQLite or local CSV files as the persistent source of truth |

## 2. Incident ID Rules

Synthetic incident IDs must use this format:

```text
INC_TYPE_NUMBER
```

`TYPE` must be an approved abbreviation. `NUMBER` must be zero-padded to three digits within each type. Integration generates IDs after row standardization and after `Incident_Summary` is produced, but before Supabase insertion.

### 2.1 Approved Type Abbreviations

| **Source** | **Abbreviation** | **Example IDs** |
| --- | --- | --- |
| Audio | AUD | INC_AUD_001, INC_AUD_002 |
| PDF | PDF | INC_PDF_001, INC_PDF_002 |
| Image | IMG | INC_IMG_001, INC_IMG_002 |
| Video | VID | INC_VID_001, INC_VID_002 |
| Text | TXT | INC_TXT_001, INC_TXT_002 |

### 2.2 ID Generation Behavior

| **Rule** | **Requirement** |
| --- | --- |
| Number scope | Numbers increment independently per type abbreviation |
| Example | If the highest existing video ID is `INC_VID_009`, the next video incident is `INC_VID_010` |
| One file can create many IDs | If one uploaded video produces three incidents, assign `INC_VID_001`, `INC_VID_002`, and `INC_VID_003` as needed |
| Supabase-aware generation | Before insert, query existing Supabase rows to avoid reusing IDs |
| Single-user assumption | For the class demo, simple max-number lookup is acceptable. Production concurrency is out of scope |
| No old ID format | Do not use the old `INC_001` format in new code or docs |

## 3. Schema Rules

The main Supabase table is named `incidents`. The stored Supabase row and final CSV export must contain these fields:

```text
id, created_at, incident_id, source, event, location, time, severity, incident_summary
```

| **Field** | **Rule** |
| --- | --- |
| id | Database-generated row id |
| created_at | Database-generated insert timestamp |
| incident_id | Must follow `INC_TYPE_NUMBER` |
| source | Must identify the modality/source: `Audio`, `PDF`, `Image`, `Video`, or `Text` |
| event | No null values; use `Unknown` when not found |
| location | No null values; use `Unknown` when not found |
| time | No null values; use `Unknown` when not found |
| severity | Must be exactly `Low`, `Medium`, `High`, or `Unknown`; an `Unknown` event must be `Low` |
| incident_summary | OpenRouter/fallback incident summary for dashboard display and export |

Dashboard labels may be user-friendly and title-cased for readability, such as Incident_ID, Source, Event, Location, and Severity. These labels map to the lower-case Supabase columns in code.

## 4. Modality DataFrame Rules

Each modality returns its exact documented draft columns. A DataFrame can
contain zero, one, or many rows. Missing values must use `Unknown` or a safe
default before Integration.

| **Modality** | **Exact Columns** | **Key Rule** |
| --- | --- | --- |
| Audio | `Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score` | Sentiment is `Calm`, `Concerned`, or `Distressed`; urgency is independently scored from 0.0 to 1.0 |
| PDF | `Report_ID, Incident_Type, Date, Location, Officer, Summary, Suspect_Description, Outcome` | Extract whole-document text first; OCR the whole PDF only when its direct text is near-empty; emit one artifact row per uploaded PDF |
| Image | `Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score` | Use the fire Roboflow model plus the person model, average valid detection confidences from the model response, bound the result from 0.0 to 1.0, and use labels such as `Fire Scene`, `Smoke Scene`, and `Fire and Smoke Scene`. Confidence is the rounded model-derived average; neutral confidence `0.5` is used only when no detection confidence is available. For an empty detection response, use `General Scene`, the string `None`, and neutral confidence `0.5`; empty OCR text uses `N/A`. OCR runs on the full grayscale image. During Integration, `llm_summarizer.update_image_location(...)` may populate final `Location` only when OCR text contains an explicit place. |
| Video | `Timestamp, Frame_ID, Event_Detected, Objects, Confidence` | Use `HH:MM:SS`, source-frame-index `FRM_NNN` IDs, motion gating, and documented event logic |
| Text | `Text_ID, Source, Raw_Text, Sentiment, Entities, Topic` | Preserve `Raw_Text`; unsupported topics use `Other` |

Use `Unknown` for unsupported or missing final evidence. For the image artifact only, no detected objects may be represented as the string `None` and empty OCR text may be represented as `N/A`; Integration must still map final missing fields safely. Never infer facts that are not present in the source or model output.

Structured text inputs may also arrive as CSV
(`Event, Location, Time, Severity, Summary, Confidence`). The Integration
dispatcher reads structured CSVs directly; CSVs that instead contain a
recognized text field are processed by `text/processor.py`. They may produce
many rows and use `Unknown` for missing values.
JSON file uploads are not supported in the MVP and must be rejected with a clear message.

## 5. Integration Rules

Integration must accept a pandas DataFrame and `source_type`, not a CSV path. The public function is `integrate_records(draft_df, source_type)`. The public Integration workflow output contract is:

```text
Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary
```

The lower-case Supabase insert payload is produced only at the cloud upload boundary. It contains seven app-provided fields because `id` and `created_at` are generated by Supabase:

```text
incident_id, source, event, location, time, severity, incident_summary
```

It must not include extra fields at insert time. After insertion, Supabase stored rows and final CSV export contain the full nine-field schema including database-generated `id` and `created_at`. Supabase insert happens only after Integration produces `Incident_Summary` and `Incident_ID`, the user confirms the final rows, and the app maps them to `incident_summary` and `incident_id`.

## 6. LLM Summarizer Rules

The LLM summarizer is required as a separate folder:

```text
llm_summarizer/
├── __init__.py
├── summarizer.py
├── prompts.py
├── fallback.py
└── schemas.py
```

Integration must call this module during `integrate_records(...)` after row standardization and before ID generation and Supabase insertion. The required public functions are:

```text
from llm_summarizer.summarizer import summarize_incident, update_image_location

image_row = update_image_location(image_row)
summary_result = summarize_incident(incident_row: dict)

# Integration stores result["incident_summary"] as Incident_Summary, then the app maps it to Supabase incident_summary.
```

LLM summary rules:

| **Rule** | **Requirement** |
| --- | --- |
| Separate responsibility | `summarize_incident(row)` only creates a readable summary; it must not compute final severity, rewrite IDs, insert database rows, or override Integration's normalized fields. `update_image_location(row)` may fill an image row's missing `Location` from explicit OCR location text, but must not change event, time, severity, IDs, or summaries. |
| Use integrated fields | The summary prompt/function must summarize only from cleaned fields `event`, `location`, `time`, `severity`, and `source`. Raw OCR/source text must not be sent to the summary prompt. |
| No hallucination | If a detail is missing, write `Unknown` or omit that detail; do not invent people, places, weapons, dates, or outcomes |
| Length | Keep `incident_summary` short: one to three sentences, preferably under 80 words |
| Fallback required | If OpenRouter is disabled, unavailable, slow, or invalid, use deterministic rule-based fallback |
| OpenRouter provider | Use OpenRouter when `OPENROUTER_API_KEY` is configured |
| Safe output | The summary is for dashboard review, not official investigation or legal conclusions |
| Validation | Validate required keys, types, and length before accepting model output |

## 7. Severity Rules

| **Signal** | **Severity** |
| --- | --- |
| Fire, weapon, trapped person, collapse, fighting, severe crash | High |
| Audio urgency score >= 0.70 | High |
| Audio urgency score from 0.30 up to 0.69 | Medium |
| Theft, robbery, public disturbance, property damage | Medium |
| Neutral report or low-confidence non-violent event | Low |
| No reliable signal | Low with Event = Unknown |

Integration first forces configured high-risk event terms to `High`, preserves a valid explicit severity when provided, and otherwise maps a confidence or urgency score on a 0–1 scale as `< 0.30 = Low`, `< 0.70 = Medium`, and `>= 0.70 = High`. Severity must always be normalized to exactly `Low`, `Medium`, `High`, or `Unknown` before Supabase insertion. When Event is `Unknown`, Severity must be `Low`, even if an upstream value says otherwise.

## 8. Per-Modality Mapping Rules

Integration standardizes each input row independently; it does not merge facts
from different modalities. The current mappings are:

| **Field** | **Mapping** |
| --- | --- |
| Time | PDF uses `Date`; video uses `Timestamp`; structured text uses its explicit time/date fields; unstructured text uses DATE/TIME entities; audio and image use optional draft `Time`/`Timestamp` fields when present, otherwise `Unknown` |
| Location | Audio and PDF use their `Location`; text uses `Location` or location entities; image uses an optional draft `Location` first and may then use `llm_summarizer.update_image_location(...)`; video uses an optional draft `Location` only |
| Event | Audio uses `Extracted_Event`; PDF uses `Incident_Type`; image uses `Scene_Type` then objects; video uses `Event_Detected`; text uses `Topic` or structured incident fields |
| Severity | Apply the normalized event/explicit-severity/confidence rules in section 7 to each mapped row |
| Summary | Use integrated final fields only; image OCR text may fill a missing `Location` before summary, but summaries must not quote or narrate raw OCR/source text |

## 9. Fallback Rules

| **Failure** | **Required Fallback** |
| --- | --- |
| Unsupported file type | Show clear Streamlit error and do not insert rows |
| Extractor returns empty DataFrame | Show no incident found message; insert nothing |
| Failed audio transcription | Show a processing error and do not insert rows |
| PDF direct extraction near-empty | Try whole-document OCR fallback |
| OCR unavailable or failed | Use Unknown fields and continue |
| Image model detects no supported objects | Keep image artifact values such as `Objects_Detected = None` and `Text_Extracted = N/A` when appropriate; Integration must still map final missing fields safely |
| Roboflow unavailable, quota exhausted, or API key missing | Write safe image artifact placeholders (`None`, `N/A`, confidence `0.5`) and do not crash |
| Video model detects nothing | Use Unknown fields |
| Video frame has no qualifying motion | Skip model inference for that frame and do not invent an event |
| Text has no supported topic | Use `Other` |
| Integration schema mismatch | Stop before Supabase insert and show validation error |
| OpenRouter fails | Use rule-based summary from `llm_summarizer/fallback.py` |
| Supabase credentials missing | Show setup guidance and do not crash |

## 10. Logging Rules

Each processing run must log or display:
- Uploaded filename.
- Detected source type.
- Processor selected.
- Number of raw extractor rows.
- Number of integrated incident rows.
- Whether LLM summary or rule-based summary was used.
- Number of Supabase rows inserted after confirmation.
- Error messages and fallback behavior.

## 11. Testing Rules

Minimum required tests:

| **Test** | **Purpose** |
| --- | --- |
| test_file_type_detector.py | Extensions map to AUD/PDF/IMG/VID/TXT; CSV routes to TXT; JSON uploads are rejected |
| test_extractor_schema.py plus modality-specific tests | Each processor returns its required extractor DataFrame columns |
| test_modality_output_schemas.py plus audio/image/video/text tests | Modality artifacts use their exact columns and bounded numeric scores |
| test_integration_schema.py | Integration returns final `Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary` columns |
| test_llm_summarizer.py | LLM summarizer returns required keys and fallback works |
| test_id_generator.py | IDs follow `INC_TYPE_NUMBER` and increment by source type |
| test_supabase_mapping.py | Supabase payload maps all required table columns |
| test_final_export_schema.py | Final CSV export has exact nine fields and no null values |
| test_dashboard_smoke.py | Streamlit app can load without crashing |
