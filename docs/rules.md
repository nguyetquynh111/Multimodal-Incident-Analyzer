# Development Rules: Multimodal Crime / Incident Report Analyzer

## 1. General Coding Standards

- Keep functions small and single-purpose.
- Prefer explicit schemas, validators, and clear error messages over silent failures.
- Keep extractor code separate from Integration, Supabase, dashboard, and summarizer logic.
- Do not hard-code local absolute paths.
- Do not commit generated outputs, raw evidence, credentials, virtual environments, or model cache files.
- Use deterministic fallbacks when optional external APIs or models are unavailable.
- Never claim rows were saved unless Supabase insert succeeds.

## 2. Security and Privacy Rules

- Store Supabase, OpenRouter, and Roboflow credentials only in environment variables, Streamlit secrets, GitHub secrets, or the deployment host secret manager.
- Do not log secrets.
- Do not upload raw files to Supabase Storage in the MVP.
- Treat uploaded evidence as temporary runtime data.
- Summaries are for classroom review, not legal findings or official investigations.

## 3. File Handling Rules

- Add Incident processes exactly one uploaded file per review run.
- Reject unsupported extensions before extractor execution.
- Reject standalone `.json` uploads.
- Use temporary local storage only when a library requires a file path.
- Clean up temporary files when processing finishes.
- Completed review drafts may be kept only in the browser session for Combine Reports preview.

## 4. Modality DataFrame Rules

Each modality must return the exact draft columns defined in [specs.md](specs.md#3-modality-output-contract). A draft DataFrame may contain zero, one, or many rows.

Required value rules:

- Missing final evidence maps to `Unknown` unless a modality-specific placeholder is explicitly allowed.
- Image no-object placeholder is `Objects_Detected = None`.
- Image empty OCR placeholder is `Text_Extracted = N/A`.
- Text unsupported topic is `Other`.
- Bounded numeric confidence/urgency scores must stay within `0.0` to `1.0`.
- Never infer facts absent from the source file or model output.

## 5. Integration Rules

- Integration accepts a pandas DataFrame and `source_type`; it must not depend on a local CSV path as the primary contract.
- Integration standardizes each input row independently and must not merge facts across modalities.
- Integration output uses the seven-column contract defined in [specs.md](specs.md#5-integration-output-contract).
- The Supabase insert payload is created only at the cloud/app boundary.
- Insert payloads must omit database-generated `id` and `created_at`.
- Supabase insertion occurs only after Integration output is previewed and the user confirms.
- If ID refresh is enabled, the upload service updates `incident_id` immediately before validation and insert.
- Manage Incidents may edit `event`, `location`, `time`, `severity`, and `incident_summary`; it must not edit `incident_id`, `source`, `id`, or `created_at`.

## 6. LLM Summarizer Rules

- The summarizer must remain in the separate `llm_summarizer/` package.
- `summarize_incident(row)` creates only a readable summary; it must not change normalized fields, IDs, or database rows.
- `update_image_location(row)` may fill only a missing image `Location`, and only from explicit OCR/place evidence.
- Summary prompts/functions use cleaned integrated fields: `event`, `location`, `time`, `severity`, and `source`.
- Raw OCR/source text must not be sent to the summary prompt.
- If a detail is missing, write `Unknown` or omit it; do not invent people, places, weapons, dates, or outcomes.
- Keep `incident_summary` one to three sentences, preferably under 80 words.
- Use deterministic fallback when OpenRouter is disabled, unavailable, slow, or invalid.
- Validate required keys, types, and length before accepting model output.

## 7. Severity Rules

| **Signal** | **Severity** |
| --- | --- |
| Fire, arson, assault/violence, weapon, trapped person, collapse, fighting, severe crash | High |
| Audio urgency score `>= 0.70` | High |
| Audio urgency score `0.30` to `0.69` | Medium |
| Theft, robbery, burglary, public disturbance, property damage | Medium |
| Other, neutral report, no activity, or low-confidence non-violent event | Low |
| No reliable signal | Low with Event = `Unknown` |

Apply event-category rules before generic confidence scoring. If no category applies, preserve valid explicit severity or map confidence/urgency as `< 0.30 = Low`, `< 0.70 = Medium`, and `>= 0.70 = High`. `Unknown` events are always `Low`.

## 8. Per-Modality Mapping Rules

| **Final Field** | **Mapping Rule** |
| --- | --- |
| Time | PDF uses `Date`; video uses `Timestamp`; structured text uses explicit time/date fields; unstructured text uses date/time entities; audio/image use optional draft time fields or `Unknown` |
| Location | Audio/PDF use `Location`; text uses location fields/entities; image uses draft `Location` then optional summarizer location helper; video uses optional draft `Location` only |
| Event | Audio uses `Extracted_Event`; PDF uses `Incident_Type`; image uses `Scene_Type` then objects; video uses `Event_Detected`; text uses `Topic` or structured incident fields |
| Severity | Apply section 8 to each mapped row |
| Summary | Summarize final integrated fields only; image OCR may fill missing location before summary |

## 9. Fallback Rules

| **Failure** | **Required Fallback** |
| --- | --- |
| Unsupported file type | Show clear Streamlit error and do not insert rows |
| Extractor returns empty DataFrame | Show no incident found and insert nothing |
| Failed audio transcription | Show processing error and insert nothing |
| PDF direct extraction near-empty | Try page OCR fallback |
| OCR unavailable or failed | Use `Unknown` fields and continue |
| Image model unavailable or detects nothing | Use safe image placeholders and continue |
| Video model detects nothing | Use `Unknown` fields |
| Video frame has no qualifying motion | Skip YOLO for that frame and do not invent an activity event |
| Text has no supported topic | Use `Other` |
| Integration schema mismatch | Stop before Supabase insert and show validation error |
| OpenRouter fails | Use rule-based summary fallback |
| Supabase credentials missing | Show setup guidance and do not crash |

## 10. Logging Rules

Each processing run should log or display:

- Uploaded filename.
- Detected source type.
- Selected processor.
- Raw extractor row count.
- Integrated incident row count.
- Summary method used.
- Number of Supabase rows inserted after confirmation.
- Error and fallback messages.

## 11. Testing Rules

Minimum required tests:

| **Test** | **Purpose** |
| --- | --- |
| `test_file_type_detector.py` | Extensions map to source abbreviations; CSV routes to text; JSON is rejected |
| `test_extractor_schema.py` plus modality-specific tests | Processors return required draft columns |
| `test_modality_output_schemas.py` | Modality artifacts use exact columns and bounded scores |
| `test_integration_schema.py` | Integration returns the seven final columns |
| `test_integration_mapping.py` | Modality drafts map to final fields correctly |
| `test_llm_summarizer.py` | Summary return keys and fallback behavior work |
| `test_id_generator.py` | IDs follow `INC_TYPE_NUMBER` and increment by source type |
| `test_supabase_mapping.py` | Insert payload has seven app-owned fields and omits generated fields |
| `test_final_export_schema.py` | Final CSV has exact nine fields and no null values |
| `test_dashboard_smoke.py` | Streamlit app loads without crashing |
