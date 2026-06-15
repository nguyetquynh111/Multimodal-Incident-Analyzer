# rules.md

## 1. Project Rules

1. This is a class prototype only.
2. Use Python for all processing and dashboard code.
3. Do not use paid APIs.
4. Do not commit API keys, secrets, credentials, or private data.
5. AWS is a deployment plan only unless free-tier safety is confirmed.
6. The final CSV must contain only the six approved columns.
7. Rich debugging fields belong only in intermediate CSVs.

## 2. Incident ID Rules

- Synthetic IDs must use this format: `INC_###`.
- Examples: `INC_001`, `INC_002`, `INC_003`.
- Datasets are unrelated, so synthetic grouping is accepted for the MVP.

## 3. Final Schema Rules

Final file:

```text
data/final/final_incidents.csv
```

Required exact columns:

```text
Incident_ID, Source, Event, Location, Time, Severity
```

Rules:

- No extra columns.
- No null values.
- Missing text fields become `Unknown`.
- `Severity` must be `Low`, `Medium`, or `High`.

## 4. Severity Rules

| Signal | Severity |
|---|---|
| Fire, weapon, trapped person, collapse, fighting, severe crash | High |
| Distressed audio sentiment or urgency score >= 0.75 | High |
| Theft, robbery, public disturbance, property damage | Medium |
| Neutral report or low-confidence non-violent event | Low |
| No reliable signal | Low with `Event = Unknown` |

When multiple sources disagree, choose the highest severity.

## 5. Source Priority Rules

| Field | Priority |
|---|---|
| Time | PDF/text first, then audio, then video timestamp, then `Unknown` |
| Location | PDF/text first, then audio, then image OCR, then `Unknown` |
| Event | Highest-confidence or highest-severity signal first |
| Severity | Highest severity across all available modality signals |

## 6. Fallback Rules

| Failure | Required Fallback |
|---|---|
| Missing modality | Continue pipeline |
| Failed audio transcription | Use `Unknown` transcript-derived fields |
| PDF text extraction empty | Try OCR fallback |
| OCR unavailable or failed | Use `Unknown` |
| Image/video model detects nothing | Use `Unknown` or other modality signal |
| Local LLM fails | Use rule-based summary |
| Final CSV missing | Dashboard shows setup guidance |
| Unsupported file type | Skip file and log reason |

## 7. Logging Rules

Each processor must log:

- Processed files.
- Skipped files.
- Error messages.
- Output file path.
- Whether fallback logic was used.

## 8. Testing Rules

Minimum required tests:

| Test | Purpose |
|---|---|
| `test_ingestion.py` | Synthetic ID and folder handling |
| `test_schema.py` | Final CSV has exact schema and no null values |
| `test_severity.py` | Severity outputs are valid and rule-based |
| `test_dashboard_smoke.py` | Streamlit app can load without crashing |

## 9. Demo Rules

- Keep sample data small.
- Use `FAST_DEMO_MODE=True` for presentation safety.
- Cache intermediate outputs before final demo.
- Show raw input, intermediate output, final CSV, dashboard, and summary.
