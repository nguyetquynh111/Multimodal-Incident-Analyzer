"""Draft PDF-to-CSV pipeline with placeholder extraction values."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "Report_ID",
    "Incident_Type",
    "Date",
    "Location",
    "Officer",
    "Summary",
    "Suspect_Description",
    "Outcome",
]
SUPPORTED_EXTENSIONS = {".pdf"}
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "output" / "pdf_output.csv"


def process_pdf(
    input_file: str | Path,
    output_csv: str | Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    """Validate one PDF and write one fake, schema-correct CSV row."""
    path = _validate_file(input_file)
    row = {
        "Report_ID": path.stem,
        "Incident_Type": "Unknown",
        "Date": "Unknown",
        "Location": "Unknown",
        "Officer": "Unknown",
        "Summary": "Unknown",
        "Suspect_Description": "Unknown",
        "Outcome": "Unknown",
    }
    return _write_csv(row, output_csv)


def _validate_file(input_file: str | Path) -> Path:
    path = Path(input_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported PDF type '{path.suffix}'. Expected: .pdf")
    return path


def _write_csv(row: dict[str, object], output_csv: str | Path) -> pd.DataFrame:
    output = Path(output_csv).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
    frame.to_csv(output, index=False)
    logger.info("Wrote draft PDF CSV to %s", output)
    return frame


def main(argv: list[str] | None = None) -> int:
    """Run the draft PDF pipeline from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="Path to a PDF file")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(argv)
    process_pdf(args.input_file, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
