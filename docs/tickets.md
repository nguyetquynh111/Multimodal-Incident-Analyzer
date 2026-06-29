# Implementation Tickets: Multimodal Crime / Incident Report Analyzer

| **Owner** | **Project Type** | **Date** | **Submission** |
| --- | --- | --- | --- |
| Group 2 | Class prototype only | June 19, 2026 | June 30, 2026 |


## Milestone 1: Project Setup

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-001 | Create repo structure | Group 2 | High | Folders match [tech.md](tech.md#1-repository-structure) |
| T-002 | Add README setup instructions | Group 2 | High | Fresh user can install, configure Supabase, and run Streamlit |
| T-003 | Add requirements.txt and .env.example | Group 2 | High | Dependencies install and env variables are documented |
| T-004 | Configure Supabase incidents table | Quynh | High | Connection settings point at the required `incidents` table |

## Milestone 2: Upload and Dispatch

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-005 | Build Streamlit single-file upload UI | JN | High | User can upload exactly one supported file |
| T-006 | Build file type detector | JN | High | Extensions map to source abbreviations; CSV routes to TXT; JSON is rejected |

## Milestone 3: Modality Extractors

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-007 | Build audio processor | Quynh | High | Produces the audio draft schema from [specs.md](specs.md#3-modality-output-contract) |
| T-008 | Extract audio signals | Quynh | Medium | Event, location, sentiment, and urgency are populated or safely defaulted |
| T-009 | Build PDF processor | Rodney | High | Produces the PDF draft schema |
| T-010 | Add PDF OCR fallback | Rodney | Medium | Scanned pages attempt OCR; failures use `Unknown` |
| T-011 | Build image processor | Zainab | High | Produces the image draft schema |
| T-012 | Add image OCR/object mapping | Zainab | Medium | Visual evidence and OCR text are available for Integration |
| T-013 | Build video processor | Alex | High | Rejects long clips and produces sampled frame rows |
| T-014 | Extract video event signals | Alex | Medium | Motion-gated logic produces the video draft schema |
| T-015 | Build text processor | Anh | High | Preserves `Raw_Text` and produces the text draft schema |
| T-016 | Extract text signals | Anh | Medium | Entities, sentiment, and topic are populated or safely defaulted |
| T-017 | Handle CSV text input | Group 2 | Medium | Incident-like CSVs go to Integration; text CSVs go to text processor |
| T-018 | Reject JSON input | JN | Medium | `.json` uploads show a clear unsupported-file message and insert nothing |

## Milestone 4: Integration and Summaries

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-019 | Build Integration function | JN | High | `integrate_records(...)` returns final rows using the Integration contract |
| T-020 | Build severity classifier | JN | High | Severity follows [rules.md](rules.md#8-severity-rules) |
| T-021 | Build schema validators | JN | High | Draft, Integration, Supabase payload, and export schemas are validated |
| T-022 | Create separate LLM summarizer package | Rodney | High | `llm_summarizer/` contains summarizer, prompts, fallback, and schemas |
| T-023 | Build summarizer public functions | Rodney | High | Summary and image-location helper return valid outputs |
| T-024 | Build rule-based summary fallback | Rodney | High | Fallback works when LLM is unavailable, disabled, or invalid |
| T-025 | Connect Integration to summarizer | JN | High | Integration fills eligible image locations and summarizes before ID generation |
| T-026 | Build ID generator | JN | High | Preview IDs follow `INC_TYPE_NUMBER`; saved IDs can refresh before insert |

## Milestone 5: Persistence, Dashboard, and Export

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-027 | Build Supabase client wrapper | JN | High | App can insert, query, update, and delete `incidents` rows |
| T-028 | Insert after confirmation | JN | High | Rows insert only after user confirms final Integration output |
| T-029 | Build dashboard and management UI | JN | High | Dashboard filters and Manage Incidents operations work from Supabase |
| T-030 | Show incident summaries | JN | Medium | Dashboard displays `incident_summary` from Supabase |
| T-031 | Build CSV exports | JN | High | Final export uses the nine-field Supabase schema; Combine Reports uses local preview |

## Milestone 6: Quality and Submission

| **ID** | **Task** | **Owner** | **Priority** | **Done When** |
| --- | --- | --- | --- | --- |
| T-032 | Add unit tests | Group 2 | High | Core tests from [rules.md](rules.md#12-testing-rules) pass |
| T-033 | Create architecture and data-flow diagrams | Zainab | Medium | Diagrams distinguish artifact, DataFrame, and export schemas |
| T-034 | Write project report | Alex | High | Report explains models, flow, Supabase table, summary module, results, and limitations |
| T-035 | Deploy and validate class demo | Quynh | High | Hosted app connects to Supabase with protected credentials |
| T-036 | Refactor codebase | Quynh | High | Duplicate logic is removed, the project follows `rules.md`, code is modular and documented, and all tests pass |
| T-037 | Record demo | Anh | High | Demo shows upload, preview, confirmation, Supabase insert, dashboard/export, and summary |
| T-038 | Freeze final submission | Group 2 | High | Repository, documentation, report, diagrams, CSV export, and demo are complete and ready for submission |