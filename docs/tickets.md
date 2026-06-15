# tickets.md

## Sprint Goal

Build a working class prototype that processes five evidence modalities, creates a final six-column incident CSV, and displays it in a Streamlit dashboard by June 26, 2026.

## Ticket Board

| ID | Task | Owner | Priority | Done When |
|---|---|---|---|---|
| T-001 | Create repo structure | Student 06 | High | Folders match `tech.md` |
| T-002 | Add README setup instructions | Student 06 | High | Fresh user can install and run demo |
| T-003 | Add `requirements.txt` | Student 06 | High | Dependencies install successfully |
| T-004 | Build sample `data/raw/INC_001/` layout | Student 06 | High | All modality folders exist |
| T-005 | Build ingestion script | Student 06 | High | Generates `INC_###` and organizes files |
| T-006 | Build audio processor | Student 01 | High | Creates `audio_intermediate.csv` |
| T-007 | Extract audio event/location/urgency | Student 01 | Medium | Audio fields are populated or `Unknown` |
| T-008 | Build PDF processor | Student 02 | High | Creates `pdf_intermediate.csv` |
| T-009 | Add PDF OCR fallback | Student 02 | Medium | Empty PDFs attempt OCR or return `Unknown` |
| T-010 | Build image processor | Student 03 | High | Creates `image_intermediate.csv` |
| T-011 | Add image OCR/object detection mapping | Student 03 | Medium | Objects/text map to event signals |
| T-012 | Build video frame extraction | Student 04 | High | Frames are sampled from short video |
| T-013 | Build video signal extraction | Student 04 | Medium | Creates `video_intermediate.csv` |
| T-014 | Build text processor | Student 05 | High | Creates `text_intermediate.csv` |
| T-015 | Extract text entities/sentiment/topic | Student 05 | Medium | Text fields are populated or `Unknown` |
| T-016 | Build normalization module | Student 06 | High | All modality outputs map to final schema |
| T-017 | Build severity classifier | Student 06 | High | Severity is `Low`, `Medium`, or `High` |
| T-018 | Build merge script | Student 06 | High | Creates `data/final/final_incidents.csv` |
| T-019 | Add schema validation | Student 06 | High | Final CSV has exact six columns and no nulls |
| T-020 | Build Streamlit table and filters | Student 06 | High | Dashboard shows table and filters |
| T-021 | Add summary module | Student 06 | Medium | Local LLM or fallback summary appears |
| T-022 | Add fast demo mode | Student 06 | High | Cached outputs can be used for demo |
| T-023 | Add upload or watch-folder flow | Student 06 | Medium | New files can enter pipeline demo flow |
| T-024 | Add unit tests | All | High | Core tests pass with `pytest` |
| T-025 | Create architecture diagram | Student 06 | Medium | Diagram saved under `diagrams/` |
| T-026 | Write project report | All | High | Report explains datasets, models, flow, results |
| T-027 | Prepare AWS no-billing plan | Student 06 | Medium | Plan appears in report or README |
| T-028 | Record demo | Group 2 | High | Demo shows raw input to final dashboard |
| T-029 | Fresh setup test | Group 2 | High | Another laptop/account can run documented demo |
| T-030 | Freeze final submission | Group 2 | High | Repo, report, diagram, CSV, and demo are ready |

## Recommended Work Order

1. Finish repo skeleton and data layout.
2. Build each modality processor independently.
3. Standardize intermediate CSVs.
4. Build integration, severity, and schema validation.
5. Build dashboard and summary.
6. Add fast demo mode and cached outputs.
7. Write report, diagram, and AWS plan.
8. Test fresh setup and record final demo.
