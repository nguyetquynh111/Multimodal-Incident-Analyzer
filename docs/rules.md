# Project Rules: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 26, 2026 |

## 1. Core Project Rules

| **Rule** | **Requirement** |
| --- | --- |
| Class prototype only | Do not present the app as production emergency software |
| Python required | Use Python for all processing and Streamlit dashboard code |
| No paid APIs | Do not require paid LLM, paid OCR, paid speech, or paid cloud inference APIs |
| No committed secrets | Do not commit Supabase keys, API keys, credentials, or private data |
| Single-file upload | The MVP processes exactly one uploaded file per Streamlit processing run |
| Synchronous processing | Processing occurs inside the Streamlit session and inserts automatically when complete |
| Supabase source of truth | After insert, dashboard and export must read from Supabase `incidents` table |
| One main table | Use one Supabase table named `incidents` for structured incident rows and summary columns |
| LLM summary is separate | LLM summary code must live in `src/llm_summarizer/`, not inside extractors or hidden inside Student 6 integration |
| No raw Supabase Storage in MVP | Do not upload raw evidence files to Supabase Storage as a required MVP feature |
| No watch-folder flow | Do not implement local watch-folder monitoring as the main pipeline |
| No SQLite source of truth | Do not use SQLite or local CSV files as the persistent source of truth |

## 2. Incident ID Rules

Synthetic incident IDs must use this format:

```text
INC_TYPE_NUMBER
```

`TYPE` must be an approved abbreviation. `NUMBER` must be zero-padded to three digits within each type. The app generates IDs after Student 6 integration, after summary fields are produced, and before Supabase insertion.

### 2.1 Approved Type Abbreviations

| **Source** | **Abbreviation** | **Example IDs** |
| --- | --- | --- |
| Audio | AUD | INC_AUD_001, INC_AUD_002 |
| PDF | PDF | INC_PDF_001, INC_PDF_002 |
| Image | IMG | INC_IMG_001, INC_IMG_002 |
| Video | VID | INC_VID_001, INC_VID_002 |
| Text | TXT | INC_TXT_001, INC_TXT_002 |
| CSV | CSV | INC_CSV_001, INC_CSV_002 |
| JSON | JSON | INC_JSON_001, INC_JSON_002 |

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

The main Supabase table is named `incidents`. It can contain operational columns, but the final CSV export must contain only these columns:

```text
Incident_ID, Source, Event, Location, Time, Severity
```

| **Field** | **Rule** |
| --- | --- |
| Incident_ID | Must come from `incident_id` and follow `INC_TYPE_NUMBER` |
| Source | Must identify the modality/source such as `audio`, `pdf`, `image`, `video`, `text`, `csv`, or `json` |
| Event | No null values; use `Unknown` when not found |
| Location | No null values; use `Unknown` when not found |
| Time | No null values; use `Unknown` when not found |
| Severity | Must be exactly `Low`, `Medium`, or `High` |
| incident_summary | Stored in Supabase for dashboard display; not included in the final six-column CSV |
| summary_method | Stored in Supabase to show whether `llm`, `rule_based`, `disabled`, or `error` produced the summary |

## 4. Extractor DataFrame Rules

Every modality extractor must return a pandas DataFrame with exactly these required columns before Student 6 integration:

```text
source_filename, source_type, raw_event, raw_location, raw_time, raw_severity, confidence, raw_text
```

Rules:
- A DataFrame can contain zero, one, or many rows.
- One uploaded file can produce many raw candidate incident rows.
- Do not write intermediate CSV files as the primary pipeline contract.
- Extra debug columns are allowed only if Student 6 integration ignores or explicitly handles them.
- Missing values must be converted to `Unknown` or safe defaults before Supabase insertion.

## 5. Student 6 Integration Rules

Student 6 integration must accept a pandas DataFrame, not a CSV path. The required function contract is:

```text
def integrate_records(extractor_df: pandas.DataFrame) -> pandas.DataFrame:
    """Return cleaned incident rows before ID assignment and before Supabase insert."""
```

Student 6 integration output must include:

```text
event, location, time, severity, confidence, raw_text
```

It may include additional columns if they are documented and supported. It must not insert directly into Supabase before ID generation and LLM summary enrichment are complete.

## 6. LLM Summarizer Rules

The LLM summarizer is required as a separate folder:

```text
src/llm_summarizer/
├── __init__.py
├── summarizer.py
├── prompts.py
├── fallback.py
└── schemas.py
```

Student 6 must call this module after `integrate_records(...)` returns cleaned rows and before Supabase insertion. The required public function is:

```text
from src.llm_summarizer.summarizer import summarize_incident

summary_result = summarize_incident(incident_row: dict)

# Required return keys:
# incident_summary: str
# summary_method: "llm" | "rule_based" | "disabled" | "error"
# summary_model: str
```

LLM summary rules:

| **Rule** | **Requirement** |
| --- | --- |
| Separate responsibility | The summarizer only creates a readable summary; it must not compute final severity, rewrite IDs, insert database rows, or override Student 6 normalized fields |
| Use integrated fields | The prompt/function must summarize from `event`, `location`, `time`, `severity`, `source`, and `raw_text` when available |
| No hallucination | If a detail is missing, write `Unknown` or omit that detail; do not invent people, places, weapons, dates, or outcomes |
| Length | Keep `incident_summary` short: one to three sentences, preferably under 80 words |
| Fallback required | If the LLM is disabled, unavailable, slow, or invalid, use deterministic rule-based fallback |
| No paid API requirement | Local/free model or fallback only; no required paid LLM API |
| Safe output | The summary is for dashboard review, not official investigation or legal conclusions |

## 7. Severity Rules

| **Signal** | **Severity** |
| --- | --- |
| Fire, weapon, trapped person, collapse, fighting, severe crash | High |
| Distressed audio sentiment or urgency score >= 0.75 | High |
| Theft, robbery, public disturbance, property damage | Medium |
| Neutral report or low-confidence non-violent event | Low |
| No reliable signal | Low with Event = Unknown |

When multiple signals disagree, choose the highest severity. Severity must always be normalized to exactly `Low`, `Medium`, or `High` before Supabase insertion.

## 8. Source Priority Rules

| **Field** | **Priority** |
| --- | --- |
| Time | PDF/text/CSV/JSON explicit time first, then audio transcript, then video timestamp, then image OCR, then `Unknown` |
| Location | PDF/text/CSV/JSON explicit location first, then audio transcript, then image OCR, then `Unknown` |
| Event | Highest-confidence or highest-severity integrated signal first |
| Severity | Highest severity across available signals |
| Summary | Use integrated final fields first; raw text is supporting context only |

## 9. Fallback Rules

| **Failure** | **Required Fallback** |
| --- | --- |
| Unsupported file type | Show clear Streamlit error and do not insert rows |
| Extractor returns empty DataFrame | Show no incident found message; insert nothing unless demo rules require an Unknown row |
| Failed audio transcription | Use Unknown transcript-derived fields and continue if possible |
| PDF text extraction empty | Try OCR fallback when enabled |
| OCR unavailable or failed | Use Unknown fields and continue |
| Image/video model detects nothing | Use OCR or Unknown fields |
| Student 6 integration schema mismatch | Stop before Supabase insert and show validation error |
| Local/free LLM fails | Use rule-based summary from `src/llm_summarizer/fallback.py` |
| Supabase credentials missing | Show setup guidance and do not crash |

## 10. Logging Rules

Each processing run must log or display:
- Uploaded filename.
- Detected source type.
- Processor selected.
- Number of raw extractor rows.
- Number of integrated incident rows.
- Whether LLM summary or rule-based summary was used.
- Number of Supabase rows inserted.
- Error messages and fallback behavior.

## 11. Testing Rules

Minimum required tests:

| **Test** | **Purpose** |
| --- | --- |
| test_file_type_detector.py | Extensions map to AUD/PDF/IMG/VID/TXT/CSV/JSON |
| test_extractor_schema.py | Each processor returns required extractor DataFrame columns |
| test_student6_integration_schema.py | Student 6 integration returns required cleaned incident columns |
| test_llm_summarizer.py | LLM summarizer returns required keys and fallback works |
| test_id_generator.py | IDs follow `INC_TYPE_NUMBER` and increment by source type |
| test_supabase_mapping.py | Supabase payload maps all required table columns |
| test_final_export_schema.py | Final CSV export has exact six columns and no null values |
| test_dashboard_smoke.py | Streamlit app can load without crashing |

## 12. Demo Rules

Keep sample data small. Use `FAST_DEMO_MODE=True` for presentation safety. The demo should show: one raw uploaded file, extracted DataFrame count, Student 6 integration result, LLM/fallback summary, Supabase insertion, dashboard filtering, and final six-column CSV export.
