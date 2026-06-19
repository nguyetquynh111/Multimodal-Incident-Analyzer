"""Command-line compatibility wrapper for the Student 01 audio extractor."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# ``python audio/process_audio.py`` puts only ``audio/`` on sys.path. Add the
# repository root so the documented direct command can import the ``src`` package.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.extractors.audio_processor import process_audio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract incident signals from one audio file.")
    parser.add_argument("audio_file", type=Path, help="Path to a WAV, MP3, or M4A file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("audio_output.csv"),
        help="CSV output path (default: audio/audio_output.csv)",
    )
    parser.add_argument("--model", default=None, help="Optional Hugging Face Wav2Vec2 model")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = process_audio(args.audio_file, model_name=args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(result.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
