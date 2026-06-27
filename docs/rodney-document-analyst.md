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
| `Incident_Type` | `classify_incident` — keyword/category matching, with an administrative-dominance guard so a stray crime word in a training/policy bundle does not flip the label. | [`processor.py`](../pdf/processor.py#L222) |
| `Date` | `extract_date` — first explicit date matched by the month-name / numeric date regex. | [`processor.py`](../pdf/processor.py#L149) |
| `Location` | `extract_location` — spaCy `GPE/LOC/FAC` entity when available, else an org-anchored or `City, ST` regex. | [`processor.py`](../pdf/processor.py#L165) |
| `Officer` | `extract_officer` — first ranked law-enforcement title + proper name. | [`processor.py`](../pdf/processor.py#L158) |
| `Summary` | `summarize_document` — source-grounded lead summary that prefers the document's subject/`RE:` line and otherwise the first body sentence, **skipping the letterhead block** (names/address/phone). Distinct from final `incident_summary`. | [`processor.py`](../pdf/processor.py#L332) |

`analyze_document` ([`processor.py`](../pdf/processor.py#L404)) builds the
artifact row directly. The current public PDF path processes the uploaded PDF
as one document and returns one eight-column row; there is no
`map_to_extractor` function or multi-document segmentation in the active path.

### Design decision: `Officer` on documents with no incident

On a document with no actual incident, `Officer` returns the document's
signer/author name (e.g. `Chief Deputy R.L. Conner`) rather than `Unknown`,
because the name is real and source-grounded, not fabricated. This is intentional
and matches the README's stated design decision.

---

## 3. OCR strategy — whole-document fallback

The public `process_pdf_file` path
([`processor.py`](../pdf/processor.py#L631)) first uses whole-document direct
text extraction through PyMuPDF, falling back to pdfplumber. If the resulting
text is fewer than 20 characters, it OCRs every page at 300 DPI through
`_extract_text_ocr` and `_ocr_pages`
([`processor.py`](../pdf/processor.py#L595)).

If `pytesseract` or the local `tesseract` executable is unavailable, OCR returns
an empty result and field extractors emit `Unknown` rather than crashing. Set
`TESSERACT_CMD` when the executable is installed outside `PATH`.

The module contains an internal `_extract_pages_text` helper, but the active
public processing path does not call it. Consequently, page-aware conditional
OCR and splitting bundled PDFs into one row per agency are not current
behavior. A bundle such as `LESO2.pdf` is represented by a single `RPT_001`
artifact row.

---

## 4. Incident ID decision

PDF artifacts keep `Report_ID` only. Final incident IDs are generated centrally
inside the Integration workflow as `INC_PDF_001`, `INC_PDF_002`, … and stored in the Supabase
`incident_id` field.

---

## 5. Open handoff items for the Integration Lead

1. **Low-signal administrative documents.** `LESO2.pdf` is processed as one
   PDF artifact row. If its extracted event is `Training / Administrative`,
   Integration assigns `Low` severity because it contains no configured
   high- or medium-severity event signal. An `Unknown` event also uses `Low`
   severity. The PDF processor returns extracted fields only; Integration must
   not invent crime facts.

---

## 6. LLM Summarizer

The required summary module lives in [`llm_summarizer/`](../llm_summarizer/).

- **Input:** the structured integrated fields (`event`, `location`, `time`,
  `severity`, `source`). Raw source/OCR text is not sent to the summary prompt; image OCR text can only affect summary indirectly when `update_image_location(row)` fills the cleaned `location` field first.
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
- **Tests:** [`tests/test_llm_summarizer.py`](../tests/test_llm_summarizer.py)
  covers summary output, disabled/error fallbacks, invalid model output, and
  image OCR location extraction. No test makes a network call.

See the README for sample input, output, and run instructions.
