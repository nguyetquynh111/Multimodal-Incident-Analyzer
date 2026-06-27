# Implementation Tickets: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 28, 2026 |

## 1. Sprint Goal

Build a working class prototype that uploads one evidence file at a time through Streamlit, processes it synchronously, sends extractor output through Integration, lets Integration standardize rows, call the separate LLM summarizer, generate IDs, return final rows, insert one or more confirmed incident rows into a Supabase `incidents` table, and display/filter/export the approved nine-field incident CSV by June 28, 2026.

## 2. Ticket Board

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-001 | Create updated repo structure | Group 2 | High | Folders match updated tech.md, including `llm_summarizer/` |
| T-002 | Add README setup instructions | Group 2 | High | Fresh user can install, configure Supabase, and run Streamlit |
| T-003 | Add requirements.txt and .env.example | Group 2 | High | Dependencies install and env variables are documented |
| T-004 | Configure Supabase incidents table | Quynh | High | Protected connection settings point at the required `incidents` table |
| T-005 | Build Streamlit single-file upload UI | JN | High | User can upload exactly one supported file |
| T-006 | Build file type detector | JN | High | Extensions map to AUD, PDF, IMG, VID, TXT; CSV routes to TXT; JSON uploads are rejected |
| T-007 | Build audio processor | Quynh | High | Produces the six-column audio artifact and extractor mapping |
| T-008 | Extract audio event/location/urgency | Quynh | Medium | Sentiment is Calm, Concerned, or Distressed; urgency is independently bounded 0–1 |
| T-009 | Build PDF processor | Rodney | High | Produces the eight-column PDF draft and integration mapping |
| T-010 | Add PDF OCR fallback | Rodney | Medium | When whole-document direct extraction is near-empty, OCR the full PDF; failures use Unknown |
| T-011 | Build image processor | Zainab | High | Produces the five-column image artifact with supported labels and confidence |
| T-012 | Add image OCR/object mapping | Zainab | Medium | Supported evidence maps to the image draft; available Roboflow bounding boxes appear in Visual Evidence; full-image grayscale OCR writes readable text or `N/A`; image OCR text may populate final Location through `llm_summarizer.update_image_location(...)`; no detected objects may use `None`, empty OCR may use `N/A`, and Roboflow failure writes safe empty artifacts without crashing |
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
| T-029 | Build dashboard table and filters | JN | High | Dashboard shows Supabase rows and filters |
| T-030 | Show selected incident summary in dashboard | JN | Medium | Dashboard displays `incident_summary` from Supabase |
| T-031 | Build final CSV export | JN | High | The dashboard download reads Supabase and contains exactly `id, created_at, incident_id, source, event, location, time, severity, incident_summary`; the Combine Reports download is a separate seven-field local preview |
| T-032 | Add unit tests | Group 2 | High | Core pytest tests pass, including `test_modality_output_schemas.py` |
| T-033 | Create architecture and data-flow diagrams | Zainab | Medium | Both diagrams show the approved pipeline and distinguish artifact/DataFrame/export schemas |
| T-034 | Write project report | Alex | High | Report explains implemented models, flow, Supabase table, summary module, results, and limitations |
| T-035 | Record demo | Anh | High | Demo shows upload, Integration preview, confirmation, Supabase insert, dashboard/export, and summary |
| T-036 | Deploy and validate class demo | Quynh | High | Hosted app connects to Supabase with protected credentials and passes a fresh-account test |
| T-037 | Freeze final submission | Group 2 | High | Repo, docs, report, diagram, CSV export, and demo are ready |

## 3. Recommended Work Order

| **Order** | **Work** |
| --- | --- |
| 1 | Create repo skeleton, requirements, and .env.example |
| 2 | Build Streamlit upload UI and file type detector |
| 3 | Build each modality processor independently with the extractor DataFrame schema |
| 4 | Build integration standardization and severity normalization |
| 5 | Build separate `llm_summarizer/` folder with fallback summary first |
| 6 | Connect Integration workflow to the LLM image-location and summary functions |
| 7 | Build schema validators and ID generator used by Integration |
| 8 | Build Supabase insert/query wrapper |
| 9 | Connect full upload -> process -> integrate -> summarize -> ID -> confirm -> insert flow |
| 10 | Build dashboard filters, selected incident summary display, and final CSV export |
| 11 | Add tests for modality artifacts, schemas, LLM fallback, IDs, Supabase mapping, and dashboard smoke run |
| 12 | Create both diagrams, write report, deploy/test setup, and record final demo |

## 4. LLM Summarizer Implementation Checklist

| **Item** | **Required Detail** |
| --- | --- |
| Folder | `llm_summarizer/` |
| Public functions | `summarize_incident(incident_row: dict) -> dict`; `update_image_location(image_row: dict) -> dict` |
| Required output | `incident_summary`, `summary_method`, `summary_model` |
| Caller | `integrate_records(...)` calls it during the Integration workflow |
| Timing | Before ID generation and confirmed Supabase insert is required |
| Fallback | Rule-based fallback must work without any LLM model |
| Database update | `incident_summary` is included in the confirmed payload inserted into the `incidents` table |
| Final CSV | Export contains `id, created_at, incident_id, source, event, location, time, severity, incident_summary` |

## 5. Removed / Not Required Tickets

| **Old Item** | **Status in Updated Architecture** |
| --- | --- |
| Build `data/raw/INC_001` folder layout | Removed; input is Streamlit single-file upload |
| Build local ingestion script that organizes files into modality folders | Removed; file type detector routes uploaded file directly |
| Create intermediate CSV files per modality as main contract | Replaced by pandas DataFrame contract |
| Build merge script that writes local `data/final/final_incidents.csv` as source of truth | Replaced by Supabase table and export from Supabase |
| Add upload or watch-folder flow | Replaced by required Streamlit upload only |
| Prepare an AWS-specific plan | Removed; only a simple hosted class demo with Supabase is required |
| Handle `.json` structured text input | Removed; `.json` uploads are unsupported in the MVP and should be rejected clearly |
| Duplicate summary code inside integration | Removed; LLM summary code must stay in the separate `llm_summarizer/` folder, and Integration calls that function instead of reimplementing it |
