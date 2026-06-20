"""Draft image-to-CSV pipeline with placeholder analysis values."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "Image_ID",
    "Scene_Type",
    "Objects_Detected",
    "Text_Extracted",
    "Confidence_Score",
]
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "output" / "image_output.csv"


def process_image(
    input_file: str | Path,
    output_csv: str | Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    """Validate one image and write one fake, schema-correct CSV row."""
    path = _validate_file(input_file)
    row = {
        "Image_ID": path.stem,
        "Scene_Type": "Unknown",
        "Objects_Detected": "Unknown",
        "Text_Extracted": "Unknown",
        "Confidence_Score": 0.0,
    }
    return _write_csv(row, output_csv)


def _validate_file(input_file: str | Path) -> Path:
    path = Path(input_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Image file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported image type '{path.suffix}'. Expected: {supported}")
    return path


def _write_csv(row: dict[str, object], output_csv: str | Path) -> pd.DataFrame:
    output = Path(output_csv).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
    frame.to_csv(output, index=False)
    logger.info("Wrote draft image CSV to %s", output)
    return frame


def main(argv: list[str] | None = None) -> int:
    """Run the draft image pipeline from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="Path to a JPG, JPEG, or PNG image")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(argv)
    process_image(args.input_file, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
