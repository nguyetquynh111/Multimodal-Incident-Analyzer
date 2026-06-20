"""Draft video-to-CSV pipeline with placeholder event values."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = ["Timestamp", "Frame_ID", "Event_Detected", "Objects", "Confidence"]
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mpg", ".mpeg"}
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "output" / "video_output.csv"


def process_video(
    input_file: str | Path,
    output_csv: str | Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    """Validate one video and write one fake, schema-correct CSV row."""
    _validate_file(input_file)
    row = {
        "Timestamp": "00:00:00",
        "Frame_ID": "FRM_001",
        "Event_Detected": "Unknown",
        "Objects": "Unknown",
        "Confidence": 0.0,
    }
    return _write_csv(row, output_csv)


def _validate_file(input_file: str | Path) -> Path:
    path = Path(input_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported video type '{path.suffix}'. Expected: {supported}")
    return path


def _write_csv(row: dict[str, object], output_csv: str | Path) -> pd.DataFrame:
    output = Path(output_csv).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([row], columns=OUTPUT_COLUMNS)
    frame.to_csv(output, index=False)
    logger.info("Wrote draft video CSV to %s", output)
    return frame


def main(argv: list[str] | None = None) -> int:
    """Run the draft video pipeline from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="Path to an MP4, MOV, MPG, or MPEG video")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(argv)
    process_video(args.input_file, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
