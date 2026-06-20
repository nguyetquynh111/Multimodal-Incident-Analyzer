"""Draft text-to-CSV pipeline with placeholder NLP values."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = ["Text_ID", "Source", "Raw_Text", "Sentiment", "Entities", "Topic"]
SUPPORTED_EXTENSIONS = {".txt"}
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "output" / "text_output.csv"


def process_text(
    input_file: str | Path,
    output_csv: str | Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    """Read one text file and write one draft, schema-correct CSV row."""
    path = _validate_file(input_file)
    raw_text = path.read_text(encoding="utf-8").strip() or "Unknown"
    row = {
        "Text_ID": path.stem,
        "Source": path.name,
        "Raw_Text": raw_text,
        "Sentiment": "Unknown",
        "Entities": "Unknown",
        "Topic": "Other",
    }
    return _write_csv(row, output_csv)


def _validate_file(input_file: str | Path) -> Path:
    path = Path(input_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Text file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported text type '{path.suffix}'. Expected: .txt")
    return path


def _write_csv(row: dict[str, object], output_csv: str | Path) -> pd.DataFrame:
    output = Path(output_csv).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
    frame.to_csv(output, index=False)
    logger.info("Wrote draft text CSV to %s", output)
    return frame


def main(argv: list[str] | None = None) -> int:
    """Run the draft text pipeline from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="Path to a TXT file")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(argv)
    process_text(args.input_file, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
