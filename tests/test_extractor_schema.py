"""Extractor-contract tests for the PDF processor (rules.md section 4).

Covers ticket T-009/T-010: the in-memory extractor DataFrame schema and the
OCR fallback path.
"""

from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from pdf.processor import (
    EXTRACTOR_COLUMNS,
    SOURCE_TYPE,
    process_pdf_file,
    segment_pages,
)


FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "LESO2.pdf"


class PdfExtractorSchemaTests(unittest.TestCase):
    def test_direct_extraction_returns_extractor_contract(self) -> None:
        frame = process_pdf_file(str(FIXTURE_PDF), write_artifact=False)

        self.assertIsInstance(frame, pd.DataFrame)
        self.assertEqual(list(frame.columns), EXTRACTOR_COLUMNS)
        # The fixture bundles several agencies' stapled proposals, so the
        # processor splits it into one row per detected document (> 1 row).
        self.assertGreater(len(frame), 1)

        # Every row carries the PDF source contract and a bounded confidence.
        for _, row in frame.iterrows():
            self.assertEqual(row["source_type"], SOURCE_TYPE)
            self.assertEqual(row["source_filename"], FIXTURE_PDF.name)
            self.assertIsInstance(float(row["confidence"]), float)
            self.assertGreaterEqual(row["confidence"], 0.0)
            self.assertLessEqual(row["confidence"], 1.0)
            self.assertNotEqual(row["raw_text"], "Unknown")

        # raw_text is scoped per agency segment, not the whole document, so the
        # rows do not all share one identical blob.
        self.assertGreater(frame["raw_text"].nunique(), 1)

    def test_ocr_fallback_runs_when_direct_extraction_is_empty(self) -> None:
        ocr_calls: list[str] = []

        def empty_direct(_: str) -> str:
            return "   \n  "  # near-empty: simulates a scanned PDF

        def fake_ocr(path: str) -> str:
            ocr_calls.append(path)
            return "Incident report: a robbery occurred near Main Street."

        frame = process_pdf_file(
            str(FIXTURE_PDF),
            report_id="RPT_OCR",
            text_extractor=empty_direct,
            ocr_extractor=fake_ocr,
            write_artifact=False,
        )

        self.assertEqual(len(ocr_calls), 1)  # OCR fallback was used
        self.assertEqual(list(frame.columns), EXTRACTOR_COLUMNS)
        row = frame.iloc[0]
        self.assertEqual(row["source_type"], SOURCE_TYPE)
        self.assertIn("robbery", row["raw_text"])
        self.assertGreaterEqual(row["confidence"], 0.0)
        self.assertLessEqual(row["confidence"], 1.0)
        # OCR applies a penalty, so confidence stays below the direct-extraction band.
        self.assertLess(row["confidence"], 0.6)

    def test_segment_pages_splits_a_bundle_by_agency(self) -> None:
        # Deterministic (no OCR): a new letterhead/cover page that names a
        # different agency starts a new segment; continuation pages do not.
        pages = [
            "Fort Smith Police Department\nTo: Whom it may Concern\n"
            "From: Fort Smith Police Department\nRef: MRAP\n"
            "The following documentation is intended to document the training.",
            "Course outline continued: vehicle familiarization and maintenance "
            "for the assigned vehicle, as presented by the instructor.",
            "Hot Springs Police Department S.W.A.T. Training\nCover Sheet\n"
            "Subject: MRAP Operations\nDuration of Class: 8 hours",
            "Lonoke County Sheriff's Office\nJohn Staley - Sheriff\n"
            "Tel: (501) 676-3001\nTo: Whom it may Concern\nRef: MRAP",
        ]

        self.assertEqual(segment_pages(pages), [[0, 1], [2], [3]])

    def test_segment_pages_handles_single_and_empty_input(self) -> None:
        self.assertEqual(segment_pages([]), [])
        self.assertEqual(segment_pages(["one page only"]), [[0]])

    def test_confidence_is_always_a_bounded_float(self) -> None:
        frame = process_pdf_file(str(FIXTURE_PDF), write_artifact=False)
        for value in frame["confidence"]:
            self.assertIsInstance(float(value), float)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
