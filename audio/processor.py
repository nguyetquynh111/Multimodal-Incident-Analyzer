"""Public audio processing API and command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Callable

import pandas as pd

try:
    from .config import OUTPUT_COLUMNS, SUPPORTED_AUDIO_EXTENSIONS
    from .extract import analyze_transcript
    from .transcribe import transcribe_audio
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from audio.config import OUTPUT_COLUMNS, SUPPORTED_AUDIO_EXTENSIONS
    from audio.extract import analyze_transcript
    from audio.transcribe import transcribe_audio


DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "audio_output.csv"


def _validate_audio_path(audio_path: str | Path) -> Path:
    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise ValueError(
            f"Unsupported audio type '{path.suffix or '<none>'}'. Supported formats: {supported}"
        )
    return path


def process_audio_file(
    audio_path: str,
    call_id: str | None = None,
    *,
    transcriber: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Transcribe and analyze one audio file, returning one exact-schema row."""

    path = _validate_audio_path(audio_path)
    transcript = (transcriber or transcribe_audio)(str(path))
    return analyze_transcript(call_id or path.stem, transcript)


def process_audio_folder(
    folder_path: str,
    output_csv_path: str,
    *,
    transcriber: Callable[[str], str] | None = None,
) -> pd.DataFrame:
    """Process all supported top-level audio files in a folder and save a CSV."""

    folder = Path(folder_path).expanduser()
    if not folder.is_dir():
        raise NotADirectoryError(f"Audio folder not found: {folder}")
    files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    )
    if not files:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise ValueError(f"No supported audio files found in {folder}. Expected: {supported}")

    rows = [
        process_audio_file(
            str(path),
            transcriber=transcriber,
        )
        for path in files
    ]
    return save_rows(rows, output_csv_path)


def save_rows(rows: list[dict[str, Any]], output_csv_path: str | Path) -> pd.DataFrame:
    """Write audio rows with the required column order and return the DataFrame."""

    output = Path(output_csv_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    frame.to_csv(output, index=False)
    return frame


def build_parser() -> argparse.ArgumentParser:
    """Build the audio processor command-line parser."""

    parser = argparse.ArgumentParser(
        description="Transcribe emergency audio and write structured incident CSV rows."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="A supported audio file or a folder of audio files")
    source.add_argument("--demo-transcript", help="Analyze text without running Whisper")
    parser.add_argument("--call-id", default=None, help="Optional ID for one file/demo row")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Destination CSV path; defaults to {DEFAULT_OUTPUT_PATH}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the audio processor command-line interface."""

    args = build_parser().parse_args(argv)
    if args.demo_transcript is not None:
        row = analyze_transcript(args.call_id or "DEMO001", args.demo_transcript)
        frame = save_rows([row], args.output)
    else:
        input_path = Path(args.input).expanduser()
        if input_path.is_dir():
            frame = process_audio_folder(str(input_path), args.output)
        else:
            row = process_audio_file(str(input_path), call_id=args.call_id)
            frame = save_rows([row], args.output)
    print(frame.to_string(index=False))
    print(f"Saved {len(frame)} row(s) to {Path(args.output).expanduser()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["analyze_transcript", "process_audio_file", "process_audio_folder"]
