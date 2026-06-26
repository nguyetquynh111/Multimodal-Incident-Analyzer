# Rodney — Document Analyst (+ LLM Summarizer)

Design notes for the two parts owned by Rodney:

1. **Document Analyst** — the PDF processor ([`pdf/processor.py`](../pdf/processor.py)).
2. **LLM-based summarization** — the separate
   [`llm_summarizer/`](../llm_summarizer/) package.

These notes complement [rules.md](rules.md) and [specs.md](specs.md); they do not
replace them.

---

## 1. Role and scope

| | |
| --- | --- |
| **Role** | Rodney — Document Analyst |
| **Required deliverable** | Extract structured incident fields from a PDF police/incident report into the eight-column artifact CSV and the shared in-memory extractor DataFrame. |
| **Summary deliverable** | LLM-based human-readable incident summary (`llm_summarizer/`), stored by the app as `incident_summary`. |
| **Not in scope** | The other four modalities (audio/image/video/text), the Integration implementation, ID generation implementation, and Supabase insertion. |

The sample document is [`tests/fixtures/LESO2.pdf`](../tests/fixtures/LESO2.pdf):
the **Benton County, AR Sheriff's Office 1033 / MRAP training proposal**, obtained
via the assignment's MuckRock FOIA link. It is a 75-page bundle in which only
~10 pages carry an embedded text layer; the remaining ~65 are scanned images.

---

## 2. Extracted fields and the functions that produce them

The artifact CSV columns are `Report_ID, Incident_Type, Date, Location, Officer,
Summary, Suspect_Description, Outcome`. Each field is produced by a dedicated,
source-grounded function — nothing is invented; a field with no real match
becomes `Unknown`.

| Artifact field | Producing function | Reference |
| --- | --- | --- |
| `Incident_Type` | `classify_incident` — keyword/category matching, with an administrative-dominance guard so a stray crime word in a training/policy bundle does not flip the label. | [`processor.py:250`](../pdf/processor.py#L250) |
| `Date` | `extract_date` — first explicit date matched by the month-name / numeric date regex. | [`processor.py:179`](../pdf/processor.py#L179) |
| `Location` | `extract_location` — spaCy `GPE/LOC/FAC` entity when available, else an org-anchored or `City, ST` regex. | [`processor.py:193`](../pdf/processor.py#L193) |
| `Officer` | `extract_officer` — first ranked law-enforcement title + proper name. | [`processor.py:186`](../pdf/processor.py#L186) |
| `Summary` | `summarize_document` — source-grounded lead summary that prefers the document's subject/`RE:` line and otherwise the first body sentence, **skipping the letterhead block** (names/address/phone). Distinct from final `incident_summary`. | [`processor.py:381`](../pdf/processor.py#L381) |

For a bundle, the per-agency text is assembled into **one row per detected
document** by `analyze_document`
([`processor.py:404`](../pdf/processor.py#L404)) and mapped onto the shared
extractor contract by `map_to_extractor`
([`processor.py:439`](../pdf/processor.py#L439)). See section 3.1 for the
boundary detection that produces those per-agency segments.

### Design decision: `Officer` on documents with no incident

On a document with no actual incident, `Officer` returns the document's
signer/author name (e.g. `Chief Deputy R.L. Conner`) rather than `Unknown`,
because the name is real and source-grounded, not fabricated. This is intentional
and matches the README's stated design decision.

---

## 3. OCR strategy — page-aware, not whole-document

OCR is handled by `_extract_pages_text`
([`processor.py:730`](../pdf/processor.py#L730)), which drives `_ocr_pages`
([`processor.py:681`](../pdf/processor.py#L681)).

The flow is:

1. Read every page's embedded text layer directly (PyMuPDF, then pdfplumber).
2. Identify **only the pages whose direct text is empty/near-empty** (scanned
   images).
3. OCR (pytesseract, 300 DPI) **only those scanned pages**, keeping each page's
   text separate so the document can be segmented (section 3.1).

Why page-aware rather than OCR'ing the whole document:

- **Accuracy.** Pages that already have a clean text layer should be read
  directly; re-OCR'ing them would only introduce recognition errors.
- **Speed.** OCR is the expensive step. On `LESO2.pdf`, ~65 of 75 pages are
  scanned, so a full run still takes several minutes; OCR'ing the ~10 text pages
  too would waste time for a worse result.
- **Resilience.** If pytesseract or the system `tesseract` binary is missing, the
  scanned pages are skipped with a logged warning and the text-layer pages still
  produce the structured fields — the processor never crashes.

OCR has been exercised end-to-end against the real scanned pages of `LESO2.pdf`
with a real install (Tesseract 5.5.0); the full test suite passes.

### 3.1 Multi-document segmentation — one row per agency

`LESO2.pdf` is a **bundle of ~17 agencies' stapled 1033/MRAP proposals**, not a
single report. `segment_pages`
([`processor.py:581`](../pdf/processor.py#L581)) groups the per-page text into
one segment per stapled document, and `process_pdf_file` runs the full
eight-column pipeline independently on each segment, emitting `RPT_001`,
`RPT_002`, … in document order.

Boundary detection is **content-based, never a fixed page count** (the agencies
vary in length from 1 to ~30 pages):

- A new segment starts only at a page whose **header** (first ~400 chars) both
  carries a new-document cue — a cover letter (`To: Whom it may Concern` /
  `RE: MRAP`), a letterhead with a phone number, a `MEMORANDUM`, or a
  policy/SOP/`Cover Sheet` title — **and** names a *different* agency than the
  running one (`_header_agency` / `_same_agency`).
- Trusting only the header means body prose that merely mentions another
  agency ("…obtained for the police department") cannot split a long document;
  this is what keeps the 30-page Little Rock aviation SOP as a single row.
- Continuation pages (including OCR-only pages with no header cue) stay with the
  current segment.

**Known limitations (OCR-driven, deliberately surfaced rather than hidden):**

1. **Mississippi County Sheriff is merged into the Lonoke County row.** Its
   OCR'd letterhead reads "County of Mississippi / State of Arkansas / SHERIFF'S
   DEPARTMENT", which the `<Place> Sheriff's Department` matcher does not catch,
   so no boundary is detected at that page. Fixing it would need a `County of
   <Place> … Sheriff` pattern; deferred to avoid over-fitting to one OCR form.
2. **RPT_012 (Little Rock) is the weakest-extraction row in the dataset.** Its
   source is the 30-page aviation SOP — an aircraft operating procedure
   structurally unlike the other agencies' MRAP letters — so *both* of its
   free-text fields are degraded: `Officer` reads "Sergeant Responsibilities"
   and `Summary` is the bare fragment "to the following restrictions" rather
   than a usable summary. The Crawford cover page similarly yields a noisier
   `Summary` than the cleaner agencies. The rows are still the correct
   *agencies*; only these free-text fields are degraded by OCR quality.
3. **Three rows leak a leading article into `Location`** from OCR: RPT_011
   ("The Jefferson"), RPT_015 ("The Rogers"), and RPT_016 ("The Union County").
   Cosmetic and harmless — the agency identity is still correct.

Net: **16 rows** are detected for the current fixture (the 17th agency,
Mississippi County, shares the Lonoke row). The count is derived from content,
so a different OCR engine/version could shift it slightly; the deterministic
`segment_pages` unit test pins the splitting *logic* independently of OCR.

---

## 4. Incident ID decision

PDF artifacts keep `Report_ID` only. Final incident IDs are generated centrally
inside the Integration workflow as `INC_PDF_001`, `INC_PDF_002`, … and stored in the Supabase
`incident_id` field.

---

## 5. Open handoff items for the Integration Lead

1. **Low-signal administrative rows.** Every agency in `LESO2.pdf`
   classifies as `Training / Administrative` with `severity` = `Low`, because these are administrative/training documents with source-grounded content but no violent, urgent, or criminal event signal. An `Unknown` event also uses `Low` severity.
   Rodney's PDF processor should return the extracted PDF rows only. Integration decides whether rows are valid final incidents, must not invent crime facts, and must never insert rows for demo-only visibility exceptions.

---

## 6. LLM Summarizer

The required summary module lives in [`llm_summarizer/`](../llm_summarizer/).

- **Input:** the structured integrated fields (`event`, `location`, `time`,
  `severity`, `source`, `raw_text`) — use `Unknown` for `raw_text` if the source provides no supporting text; never pass raw unprocessed full files as the only input.
- **Output:** the summarizer returns `incident_summary`, `summary_method`, and
  `summary_model`; Integration stores the accepted summary text as `Incident_Summary`, and the app maps it to Supabase `incident_summary`.
- **Real LLM call:** OpenRouter chat completion in
  [`summarizer.py`](../llm_summarizer/summarizer.py), with a strict
  anti-hallucination prompt ([`prompts.py`](../llm_summarizer/prompts.py)) and
  output validation (length/prose) before acceptance.
- **Fallback:** deterministic, dependency-free rule-based summary in
  [`fallback.py`](../llm_summarizer/fallback.py) whenever the LLM is disabled,
  unavailable, slow, or invalid — so a valid result is always returned and no
  paid API is required.
- **Config:** `OPENROUTER_API_KEY`, `LLM_MODEL_NAME`
  (see `.env.example`; real keys must never be committed — `.env` is gitignored).
- **Tests:** [`tests/test_llm_summarizer.py`](../tests/test_llm_summarizer.py),
  8/8 passing (valid output, disabled, missing-key, network error, over-length,
  empty). No test makes a network call.

See the README for sample input, output, and run instructions.
