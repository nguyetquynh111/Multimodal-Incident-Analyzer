# Implementation Tickets: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 28, 2026 |

## 1. Goal

Build the current Streamlit workflow: upload one evidence file, process it
synchronously, integrate/summarize/generate IDs, insert confirmed rows into
Supabase, then review, manage, and export saved incidents.

## 2. Ticket Board

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-001 | Create repo structure | Group 2 | High | Folders match `docs/tech.md`, including `llm_summarizer/` |
| T-002 | Add README setup instructions | Group 2 | High | Fresh user can install, configure Supabase, and run Streamlit |
| T-003 | Add requirements.txt and .env.example | Group 2 | High | Dependencies install and env variables are documented |
| T-004 | Configure Supabase incidents table | Quynh | High | Protected connection settings point at the required `incidents` table |
| T-005 | Build Streamlit single-file upload UI | JN | High | User can upload exactly one supported file |
| T-006 | Build file type detector | JN | High | Extensions map to AUD, PDF, IMG, VID, TXT; CSV routes to TXT; JSON uploads are rejected |
| T-007 | Build audio processor | Quynh | High | Produces the six-column audio artifact and extractor mapping |
| T-008 | Extract audio event/location/urgency | Quynh | Medium | Sentiment is Calm, Concerned, or Distressed; urgency is independently bounded 0–1 |
| T-009 | Build PDF processor | Rodney | High | Produces the eight-column PDF draft and integration mapping |
| T-010 | Add PDF OCR fallback | Rodney | Medium | When page direct extraction is near-empty, OCR scanned pages in parallel through `PDF_OCR_WORKERS`; failures use Unknown |
| T-011 | Build image processor | Zainab | High | Produces the five-column image artifact with supported labels and confidence |
| T-012 | Add image OCR/object mapping | Zainab | Medium | Roboflow/OCR evidence maps to the image draft; available boxes appear in Visual Evidence; OCR may populate final Location through `llm_summarizer.update_image_location(...)` |
| T-013 | Build video processor | Alex | High | Rejects long clips and produces formatted timestamps/frame IDs at a regular interval |
| T-014 | Extract video event signals | Alex | Medium | Motion gates detection; documented logic produces the five-column event log |
| T-015 | Build text processor | Anh | High | Preserves Raw_Text and produces the six-column text artifact |
| T-016 | Extract text entities/sentiment/topic | Anh | Medium | Entities and sentiment are present; topic uses the approved labels or Other |
| T-017 | Handle CSV text input | Group 2 | Medium | Incident-like CSVs are dispatched directly to Integration; text-oriented CSVs map through `text/processor.py` to its documented draft or Unknown fallback |
| T-018 | Reject JSON text input | JN | Medium | `.json` uploads show a clear unsupported-file message and do not insert rows |
| T-019 | Build integration function | JN | High | `integrate_records(draft_df, source_type)` returns final rows with `Incident_ID, Source, Event, Location, Time, Severity, Incident_Summary` |
| T-020 | Build severity classifier | JN | High | Severity is always Low, Medium, High, or Unknown |
| T-021 | Build schema validators | JN | High | Modality draft, integration, Supabase payload, and export schemas are validated |
| T-022 | Create separate LLM summarizer folder | Rodney | High | `llm_summarizer/` exists with summarizer, prompts, fallback, and schemas files |
| T-023 | Build LLM summarizer public functions | Rodney | High | `summarize_incident(row: dict)` returns incident_summary, summary_method, summary_model; `update_image_location(row: dict)` fills missing image Location from explicit OCR location text |
| T-024 | Build rule-based summary fallback | Rodney | High | Fallback summary works when LLM is unavailable, disabled, or invalid |
| T-025 | Connect integration to LLM summarizer | JN | High | Integration calls the image location helper when applicable, then calls the summary function after row standardization and before ID generation/Supabase insert |
| T-026 | Build INC_TYPE_NUMBER ID generator | JN | High | Generates INC_AUD_001 style IDs based on Supabase existing rows |
| T-027 | Build Supabase client wrapper | JN | High | App can insert and query `incidents` table |
| T-028 | Insert after confirmation | JN | High | Processed integrated summarized rows insert only after the user confirms the final Integration result |
| T-029 | Build dashboard table, filters, and management UI | JN | High | Dashboard shows Supabase rows and filters; Manage Incidents supports add, edit, bulk update, and delete against Supabase |
| T-030 | Show selected incident summary in dashboard | JN | Medium | Dashboard displays `incident_summary` from Supabase |
| T-031 | Build final CSV export | JN | High | Dashboard download reads Supabase and contains exactly `id, created_at, incident_id, source, event, location, time, severity, incident_summary`; Combine Reports downloads the seven-field local preview |
| T-032 | Add unit tests | Group 2 | High | Core pytest tests pass, including `test_modality_output_schemas.py` |
| T-033 | Create architecture and data-flow diagrams | Zainab | Medium | Both diagrams show the approved pipeline and distinguish artifact/DataFrame/export schemas |
| T-034 | Write project report | Alex | High | Report explains implemented models, flow, Supabase table, summary module, results, and limitations |
| T-035 | Record demo | Anh | High | Demo shows upload, Integration preview, confirmation, Supabase insert, dashboard/export, and summary |
| T-036 | Deploy and validate class demo | Quynh | High | Hosted app connects to Supabase with protected credentials and passes a fresh-account test |
| T-037 | Freeze final submission | Group 2 | High | Repo, docs, report, diagram, CSV export, and demo are ready |
