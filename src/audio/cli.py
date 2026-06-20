"""Run the audio extractor for one file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Direct script execution puts only ``src/audio/`` on sys.path.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.audio.processor import process_audio, to_audio_output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract incident signals from one audio file.")
    parser.add_argument("audio_file", type=Path, help="Path to a WAV, MP3, or M4A file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "audio_output.csv",
        help="CSV output path (default: src/audio/output/audio_output.csv)",
    )
    parser.add_argument("--model", default=None, help="Optional OpenAI Whisper model name")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    extractor_result = process_audio(args.audio_file, model_name=args.model)
    filename = extractor_result.iloc[0]["source_filename"]
    result = to_audio_output(
        extractor_result,
        audio_paths={filename: args.audio_file},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(result.to_string(index=False))
    annotations = extractor_result.attrs.get("audio_annotations", {}).get(filename, {})
    print(f"Names: {annotations.get('names', 'Unknown')}")
    print(f"Urgency phrases: {annotations.get('urgency_phrases', 'Unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
