# PRD: Multimodal Crime / Incident Report Analyzer

## 1. Project Summary

**Project name:** Multimodal Crime / Incident Report Analyzer  
**Owner:** Group 2  
**Project type:** Class prototype only  
**Primary language:** Python  
**Dashboard:** Streamlit  
**LLM strategy:** Local HuggingFace model with rule-based fallback  
**Cloud scope:** AWS deployment plan only, with no paid billing  
**Final submission date:** June 26, 2026

The product is a class prototype that converts multimodal incident evidence into a single structured incident dataset. The system processes audio, PDF, image, video, and text evidence, assigns synthetic incident IDs, extracts key signals, computes severity, and displays results in a Streamlit dashboard.

## 2. Problem

Incident evidence can arrive in many formats: emergency calls, PDF reports, scene photos, surveillance videos, and written text reports. Reviewing each source manually is slow and inconsistent. For a class demo, the project must show that multimodal AI can turn messy unstructured evidence into a consistent structured report.

## 3. Goals

| ID | Goal | Success Target |
|---|---|---|
| G1 | Process five evidence modalities | Audio, PDF, image, video, and text processors exist |
| G2 | Generate synthetic incident cases | Each case receives an `Incident_ID` like `INC_001` |
| G3 | Produce a final incident dataset | Final CSV has exactly six required columns |
| G4 | Classify severity | Severity is always `Low`, `Medium`, or `High` |
| G5 | Provide dashboard review | Streamlit can filter and display incidents |
| G6 | Generate incident summaries | Local HuggingFace summary or fallback summary works |
| G7 | Support demo safety | Fast demo mode and cached outputs reduce risk |
| G8 | Provide cloud plan | AWS no-billing deployment plan is documented |

## 4. Non-Goals

| ID | Non-Goal | Reason |
|---|---|---|
| NG1 | Production emergency deployment | This is only a class prototype |
| NG2 | Paid APIs | Project must avoid paid API usage |
| NG3 | Paid AWS resources | AWS is only documented as a no-billing plan |
| NG4 | Legal-grade crime classification | Output is educational, not investigative evidence |
| NG5 | Perfect cross-dataset matching | Source datasets are unrelated |
| NG6 | Large-scale batch processing | MVP is small, local, and demo-focused |

## 5. MVP Scope

| Input Type | MVP Limit |
|---|---:|
| PDF incident report | Up to 1 PDF per case |
| Crime scene images | Up to 20 images per case |
| Witness audio recordings | Up to 3 audio files per case |
| Surveillance video | Up to 1 video, max 5 minutes |
| Text evidence entries | Up to 20 text entries per case |

## 6. Final Output

The final dataset must contain only these columns:

```text
Incident_ID, Source, Event, Location, Time, Severity
```

Missing final values must be filled with `Unknown`, except `Severity`, which must be `Low`, `Medium`, or `High`.

## 7. Success Metrics

| Metric | Target |
|---|---|
| Modality coverage | 5/5 modalities implemented |
| Final schema validity | 100% rows match required schema |
| Missing value handling | 0 null values in final CSV |
| Extraction success | At least 80% curated demo samples produce non-Unknown event or location |
| Runtime | One MVP case runs in 5 minutes or less, excluding first-time model downloads |
| Dashboard usability | User can filter and view incident rows without code |
| Summary availability | Every selected incident gets local LLM or fallback summary |
| Submission readiness | Repo, report, diagram, dataset, and demo ready by June 26 |

## 8. Timeline

| Date | Milestone |
|---|---|
| Jun 15 | Finalize PRD, roles, repo structure, dataset choices |
| Jun 16 | Create repo, folders, requirements, and sample data layout |
| Jun 17 | Build ingestion and synthetic ID generator |
| Jun 18 | Build first-pass audio, PDF, image, and text processors |
| Jun 19 | Build video processor and frame extraction |
| Jun 20 | Standardize intermediate outputs |
| Jun 21 | Build integration and severity classifier |
| Jun 22 | Build Streamlit dashboard and summary module |
| Jun 23 | Add upload or watch-folder ingestion |
| Jun 24 | Write report and create architecture diagram |
| Jun 25 | Record demo and test fresh setup |
| Jun 26 | Final submission package ready |
