# Product Requirements Document: Multimodal Crime / Incident Report Analyzer

| **Team** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 30, 2026 |

## 1. Product Summary

The Multimodal Crime / Incident Report Analyzer is a Streamlit class prototype that turns one uploaded evidence file into structured incident rows for review, confirmation, Supabase storage, dashboard review, management, and CSV export.

## 2. Goals

| **ID** | **Goal** | **Success Target** |
| --- | --- | --- |
| G1 | Demonstrate multimodal incident extraction | Audio, PDF, image, video, text, and supported CSV paths can be routed and processed |
| G2 | Keep the user workflow simple | Add Incident processes exactly one uploaded file per review run |
| G3 | Support multiple incidents from one source | One uploaded file may produce zero, one, or many reviewable incident rows |
| G4 | Standardize outputs before storage | Extractor outputs are integrated into one final incident-row format before confirmation |
| G5 | Provide readable summaries | Every saved row has an incident summary from the LLM module or deterministic fallback |
| G6 | Persist approved rows | User-confirmed rows are inserted into the Supabase `incidents` table only after confirmation |
| G7 | Support review and submission | Dashboard filtering, management, and final nine-field CSV export work from Supabase data |
| G8 | Demonstrate hosted access safely | Hosted prototype connects to Supabase with protected credentials and no committed secrets |

## 3. Product Scope

### In Scope

- Single-file upload on the Add Incident page.
- Supported inputs: audio, PDF, image, video, text, and structured CSV text.
- JSON uploads are rejected.
- Synchronous processing inside the Streamlit app.
- Browser-session queue for Combine Reports preview after completed reviews.
- Integration of extractor DataFrames into final incident rows.
- Separate `llm_summarizer/` package for summaries and image OCR location assistance.
- Supabase persistence for structured incident rows only.
- Dashboard review, filters, saved-row management, and final CSV export.
- Hosted class prototype deployment.

### Out of Scope

- Production incident-response use.
- Emergency-service certification.
- Multi-user concurrency guarantees beyond a classroom demo.
- Uploading raw evidence files to Supabase Storage.
- Long-term raw-file archival.
- Legal conclusions or official investigative findings.

## 4. Success Metrics

| **Metric** | **Target** |
| --- | --- |
| Modality coverage | Supported audio, PDF, image, video, text, and CSV inputs route correctly |
| Upload behavior | Exactly one file is processed per Add Incident run |
| One-file-many-incidents behavior | One upload can produce zero, one, or many confirmed rows |
| Summary availability | Every inserted row has `incident_summary`; fallback works when OpenRouter fails |
| ID validity | Inserted rows use approved synthetic `INC_TYPE_NUMBER` incident IDs |
| Supabase insert success | Confirmed rows appear in the `incidents` table |
| Export validity | Final CSV has the approved nine-field schema and no null values |
| Dashboard usability | User can filter, read summaries, manage saved incidents, and export without code |
| Hosted demo | Hosted app connects to Supabase without exposing credentials |