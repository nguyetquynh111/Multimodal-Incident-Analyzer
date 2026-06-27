"""Modality artifact tests for the PDF processor (rules.md section 4.1).

Verifies the demonstration CSV uses its exact eight columns in order and never
contains NaN/None (missing values are the literal string ``Unknown``).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from pdf.processor import (
    ARTIFACT_COLUMNS,
    UNKNOWN,
    process_pdf,
    process_pdf_file,
    save_artifact,
    summarize_document,
)


FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "LESO2.pdf"


class PdfArtifactSchemaTests(unittest.TestCase):
    def test_public_pdf_output_has_eight_draft_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pdf_output.csv"
            frame = process_pdf(str(FIXTURE_PDF), output)

        self.assertEqual(list(frame.columns), ARTIFACT_COLUMNS)
        self.assertEqual(len(frame.columns), 8)

    def test_artifact_csv_has_exact_columns_in_order_and_no_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pdf_output.csv"
            process_pdf_file(
                str(FIXTURE_PDF),
                output_csv_path=str(output),
            )
            saved = pd.read_csv(output, keep_default_na=False)

        self.assertEqual(list(saved.columns), ARTIFACT_COLUMNS)
        self.assertEqual(len(saved.columns), 8)
        self.assertFalse(saved.isnull().values.any())
        for value in saved.to_numpy().ravel():
            self.assertNotIn(value, ("", None))

    def test_summary_uses_subject_and_skips_letterhead(self) -> None:
        # Deterministic (no OCR): the Summary should describe the document's
        # substance (its RE:/subject line), never the letterhead block of
        # names, address, and phone numbers.
        text = (
            "Benton County Sheriff's Office\n"
            "Sheriff Kelley Cradduck\n"
            "4300 SW 14th Street Bentonville, AR 72712\n"
            "Phone: 479-271-1011  Fax: 479-271-1008\n"
            "May 26, 2015\n"
            "RE: Mine Resistant Ambush Protected (MRAP) vehicle acquired "
            "through the 1033 Program\n"
            "The following documentation is intended to document the training."
        )

        summary = summarize_document(text)

        self.assertIn("MRAP", summary)
        self.assertNotIn("Phone", summary)
        self.assertNotIn("4300", summary)
        self.assertNotIn("Kelley Cradduck", summary)

    def test_summary_falls_back_to_first_body_sentence(self) -> None:
        # No descriptive subject line -> first substantive body sentence, not
        # the "To/From/Date" header block.
        text = (
            "To: Whom it may Concern\n"
            "From: Fort Smith Police Department\n"
            "Date: January 19, 2015\n"
            "Ref: MRAP\n"
            "The following documentation is intended to document the intended "
            "use and training of the vehicle allocated to the department."
        )

        summary = summarize_document(text)

        self.assertTrue(summary.startswith("The following documentation"))
        self.assertNotIn("Whom it may Concern", summary)

    def test_missing_fields_become_the_unknown_string(self) -> None:
        # An administrative document has no suspect/outcome; those must be Unknown,
        # never blank or fabricated.
        frame = save_artifact(
            [
                {
                    "Report_ID": "RPT_001",
                    "Incident_Type": UNKNOWN,
                    "Date": "January 19, 2015",
                    "Location": "Fort Smith",
                    "Officer": UNKNOWN,
                    "Summary": "Training proposal document.",
                    "Suspect_Description": UNKNOWN,
                    "Outcome": UNKNOWN,
                }
            ],
            output_csv_path=Path(tempfile.gettempdir()) / "pdf_artifact_schema_test.csv",
        )

        self.assertEqual(list(frame.columns), ARTIFACT_COLUMNS)
        self.assertEqual(frame.iloc[0]["Officer"], UNKNOWN)
        self.assertFalse(frame.isnull().values.any())


if __name__ == "__main__":
    unittest.main()
