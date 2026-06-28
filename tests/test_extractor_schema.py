"""PDF draft-contract and OCR fallback tests."""

from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from pdf.processor import (
    ARTIFACT_COLUMNS,
    ADMIN_INCIDENT_LABEL,
    UNKNOWN,
    process_pdf_file,
)


FIXTURE_PDF = Path(__file__).resolve().parents[1] / "pdf" / "sample_data" / "LESO2.pdf"


class PdfDraftSchemaTests(unittest.TestCase):
    def test_direct_extraction_returns_pdf_contract(self) -> None:
        frame = process_pdf_file(
            str(FIXTURE_PDF),
            report_id="RPT_001",
            text_extractor=lambda _: (
                "Officer Rivera\n"
                "June 23, 2026\n"
                "RE: Burglary reported near Main Street.\n"
                "A burglary was reported near Main Street."
            ),
            write_artifact=False,
        )

        self.assertIsInstance(frame, pd.DataFrame)
        self.assertEqual(list(frame.columns), ARTIFACT_COLUMNS)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["Report_ID"], "RPT_001")
        self.assertNotEqual(frame.iloc[0]["Summary"], UNKNOWN)

    def test_ocr_fallback_runs_when_direct_extraction_is_empty(self) -> None:
        ocr_calls: list[str] = []

        def empty_direct(_: str) -> str:
            return "   \n  "

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

        self.assertEqual(len(ocr_calls), 1)
        self.assertEqual(list(frame.columns), ARTIFACT_COLUMNS)
        self.assertEqual(frame.iloc[0]["Incident_Type"], "Theft / Robbery")
        self.assertIn("robbery", frame.iloc[0]["Summary"])

    def test_missing_values_are_literal_unknown(self) -> None:
        frame = process_pdf_file(
            str(FIXTURE_PDF),
            text_extractor=lambda _: (
                "Administrative training document with no incident."
            ),
            write_artifact=False,
        )

        self.assertFalse(frame.isnull().values.any())
        self.assertEqual(frame.iloc[0]["Incident_Type"], ADMIN_INCIDENT_LABEL)


if __name__ == "__main__":
    unittest.main()
