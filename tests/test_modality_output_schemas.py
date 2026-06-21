"""Modality artifact tests for the PDF processor (rules.md section 4.1).

Verifies the demonstration CSV uses its exact eight columns in order and never
contains NaN/None (missing values are the literal string ``Unknown``).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from pdf.processor import ARTIFACT_COLUMNS, UNKNOWN, process_pdf_file, save_artifact


FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "LESO2.pdf"


class PdfArtifactSchemaTests(unittest.TestCase):
    def test_artifact_csv_has_exact_columns_in_order_and_no_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pdf_output.csv"
            process_pdf_file(
                str(FIXTURE_PDF),
                report_id="RPT_001",
                output_csv_path=str(output),
            )
            saved = pd.read_csv(output, keep_default_na=False)

        self.assertEqual(list(saved.columns), ARTIFACT_COLUMNS)
        self.assertEqual(len(saved.columns), 8)
        self.assertFalse(saved.isnull().values.any())
        for value in saved.iloc[0]:
            self.assertNotIn(value, ("", None))

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
        self.assertEqual(frame.iloc[0]["Suspect_Description"], UNKNOWN)
        self.assertFalse(frame.isnull().values.any())


if __name__ == "__main__":
    unittest.main()
