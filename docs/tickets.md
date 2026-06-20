# Implementation Tickets: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 26, 2026 |

## 1. Sprint Goal

Build a working class prototype that uploads one evidence file at a time through Streamlit, processes it synchronously, standardizes extractor output through integration, enriches each incident row with a summary from the separate LLM summarizer folder/function, inserts one or more incident rows into a Supabase `incidents` table, and displays/filters/exports the approved six-column incident CSV by June 26, 2026.

## 2. Ticket Board

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-001 | Create updated repo structure | Group 2 | High | Folders match updated tech.md, including `src/llm_summarizer/` |
| T-002 | Add README setup instructions | Group 2 | High | Fresh user can install, configure Supabase, and run Streamlit |
| T-003 | Add requirements.txt and .env.example | Group 2 | High | Dependencies install and env variables are documented |
| T-004 | Configure Supabase incidents table | Quynh | High | Protected connection settings and SQL create the required table |
| T-005 | Build Streamlit single-file upload UI | JN | High | User can upload exactly one supported file |
| T-006 | Build file type detector | JN | High | Extensions map to AUD, PDF, IMG, VID, TXT, CSV, JSON |
| T-007 | Build audio processor | Quynh | High | Produces the six-column audio artifact and extractor mapping |
| T-008 | Extract audio event/location/urgency | Quynh | Medium | Sentiment is Calm/Distressed; urgency is independently bounded 0–1 |
| T-009 | Build PDF processor | Rodney | High | Produces the eight-column document artifact and extractor mapping |
| T-010 | Add PDF OCR fallback | Rodney | Medium | OCR runs only when scanned/direct text is unavailable; failures use Unknown |
| T-011 | Build image processor | Zainab | High | Produces the five-column image artifact with supported labels and confidence |
| T-012 | Add image OCR/object mapping | Zainab | Medium | Supported evidence maps to the extractor schema; missing evidence uses Unknown |
| T-013 | Build video processor | Alex | High | Rejects long clips and produces formatted timestamps/frame IDs at a regular interval |
| T-014 | Extract video event signals | Alex | Medium | Motion gates detection; documented logic produces the five-column event log |
| T-015 | Build text processor | Anh | High | Preserves Raw_Text and produces the six-column text artifact |
| T-016 | Extract text entities/sentiment/topic | Anh | Medium | Entities and sentiment are present; topic uses the approved labels or Other |
| T-017 | Build CSV processor | Group 2 | Medium | CSV content maps to extractor schema or Unknown fallback |
| T-018 | Build JSON processor | JN | Medium | JSON content maps to extractor schema or Unknown fallback |
| T-019 | Build integration function | JN | High | `integrate_records(DataFrame)` returns cleaned incident DataFrame |
| T-020 | Build severity classifier | JN | High | Severity is always Low, Medium, or High |
| T-021 | Build schema validators | JN | High | Extractor, integration, LLM summary, Supabase payload, and export schemas are validated |
| T-022 | Create separate LLM summarizer folder | Rodney | High | `src/llm_summarizer/` exists with summarizer, prompts, fallback, and schemas files |
| T-023 | Build LLM summarizer public function | Rodney | High | `summarize_incident(row: dict)` returns incident_summary, summary_method, summary_model |
| T-024 | Build rule-based summary fallback | Rodney | High | Fallback summary works when LLM is unavailable, disabled, or invalid |
| T-025 | Connect integration to LLM summarizer | JN | High | calls summary function after integration and before Supabase insert |
| T-026 | Build INC_TYPE_NUMBER ID generator | JN | High | Generates INC_AUD_001 style IDs based on Supabase existing rows |
| T-027 | Build Supabase client wrapper | JN | High | App can insert and query `incidents` table |
| T-028 | Auto insert after processing | JN | High | Processed integrated summarized rows insert without manual preview/save step |
| T-029 | Build dashboard table and filters | JN | High | Dashboard shows Supabase rows and filters |
| T-030 | Show selected incident summary in dashboard | JN | Medium | Dashboard displays `incident_summary` from Supabase |
| T-031 | Build final CSV export | JN | High | Download contains exactly Incident_ID, Source, Event, Location, Time, Severity |
| T-032 | Add unit tests | Group 2 | High | Core pytest tests pass |
| T-033 | Create architecture and data-flow diagrams | Zainab | Medium | Both diagrams show the approved pipeline and distinguish artifact/DataFrame/export schemas |
| T-034 | Write project report | Alex | High | Report explains implemented models, flow, Supabase table, summary module, results, and limitations |
| T-035 | Record demo | Anh | High | Demo shows upload to Supabase insert to dashboard/export with summary |
| T-036 | Deploy and validate class demo | Quynh | High | Hosted app connects to Supabase with protected credentials and passes a fresh-account test |
| T-037 | Freeze final submission | Group 2 | High | Repo, docs, report, diagram, Supabase SQL, CSV export, and demo are ready |

## 3. Recommended Work Order

| **Order** | **Work** |
| --- | --- |
| 1 | Create repo skeleton, requirements, .env.example, and Supabase SQL |
| 2 | Build Streamlit upload UI and file type detector |
| 3 | Build each modality processor independently with the extractor DataFrame schema |
| 4 | Build integration and severity normalization |
| 5 | Build separate `src/llm_summarizer/` folder with fallback summary first |
| 6 | Connect integration output to the LLM summary function |
| 7 | Build schema validators and ID generator |
| 8 | Build Supabase insert/query wrapper |
| 9 | Connect full upload -> process -> integrate -> summarize -> ID -> insert flow |
| 10 | Build dashboard filters, selected incident summary display, and final CSV export |
| 11 | Add tests for schemas, LLM fallback, IDs, Supabase mapping, and dashboard smoke run |
| 12 | Create both diagrams, write report, deploy/test setup, and record final demo |

## 4. LLM Summarizer Implementation Checklist

| **Item** | **Required Detail** |
| --- | --- |
| Folder | `src/llm_summarizer/` |
| Public function | `summarize_incident(incident_row: dict) -> dict` |
| Required output | `incident_summary`, `summary_method`, `summary_model` |
| Caller | Integration flow calls it after `integrate_records(...)` |
| Timing | Before ID generation/Supabase insert is acceptable; before Supabase insert is required |
| Fallback | Rule-based fallback must work without any LLM model |
| Database update | Summary fields are included in the payload inserted into the `incidents` table |
| Final CSV | Summary fields stay out of the required six-column final export |

## 5. Removed / Not Required Tickets

| **Old Item** | **Status in Updated Architecture** |
| --- | --- |
| Build `data/raw/INC_001` folder layout | Removed; input is Streamlit single-file upload |
| Build local ingestion script that organizes files into modality folders | Removed; file type detector routes uploaded file directly |
| Create intermediate CSV files per modality as main contract | Replaced by pandas DataFrame contract |
| Build merge script that writes local `data/final/final_incidents.csv` as source of truth | Replaced by Supabase table and export from Supabase |
| Add upload or watch-folder flow | Replaced by required Streamlit upload only |
| Prepare an AWS-specific plan | Removed; only a simple hosted class demo with Supabase is required |
| Put summary code inside integration only | Removed; LLM summary must be a separate folder/function called after Integration |
