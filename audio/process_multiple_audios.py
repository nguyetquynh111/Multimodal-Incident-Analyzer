"""Process every supported audio file in one directory with OpenAI Whisper."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import tempfile

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.extractors.audio_processor import (
    EXTRACTOR_COLUMNS,
    SUPPORTED_AUDIO_EXTENSIONS,
    TranscriptionResult,
    process_audio,
)


OUTPUT_PATH = Path(__file__).with_name("audio_output.csv")
CHECKPOINT_EVERY = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process all WAV, MP3, and M4A files in one directory."
    )
    parser.add_argument("audio_directory", type=Path, help="Directory containing audio files")
    return parser.parse_args()


def discover_audio_files(audio_directory: Path) -> list[Path]:
    if not audio_directory.is_dir():
        raise NotADirectoryError(f"Audio directory not found: {audio_directory}")
    return sorted(
        path
        for path in audio_directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    )


def load_existing_results(output_path: Path) -> pd.DataFrame:
    if not output_path.exists() or output_path.stat().st_size == 0:
        return pd.DataFrame(columns=EXTRACTOR_COLUMNS)
    results = pd.read_csv(output_path)
    if list(results.columns) != EXTRACTOR_COLUMNS:
        raise ValueError(f"Incorrect columns in {output_path}")
    return results


def save_results(results: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".csv",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            results.reindex(columns=EXTRACTOR_COLUMNS).to_csv(temporary, index=False)
        temporary_path.replace(output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def check_runtime() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg is not installed in the active environment")
    try:
        import whisper  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("openai-whisper is not installed in the active environment") from exc


def unknown_result(audio_path: Path) -> pd.DataFrame:
    return process_audio(
        audio_path,
        transcriber=lambda _: TranscriptionResult("Unknown", 0.0),
    )


def main() -> int:
    args = parse_args()
    audio_directory = args.audio_directory.expanduser().resolve()

    try:
        files = discover_audio_files(audio_directory)
        results = load_existing_results(OUTPUT_PATH)
    except (NotADirectoryError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    completed = set(results["source_filename"].dropna().astype(str))
    pending = [path for path in files if path.name not in completed]
    print(f"Found {len(files)} audio files; {len(pending)} remaining")
    if not pending:
        return 0

    try:
        check_runtime()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    failures = 0
    new_results: list[pd.DataFrame] = []
    try:
        for index, audio_path in enumerate(pending, start=1):
            try:
                frame = process_audio(audio_path, raise_on_transcription_error=True)
                row = frame.iloc[0]
                status = f"{row['raw_event']} / {row['raw_severity']}"
            except Exception as exc:
                failures += 1
                print(f"ERROR {audio_path.name}: {exc}", file=sys.stderr)
                frame = unknown_result(audio_path)
                status = "Unknown fallback"

            new_results.append(frame)
            print(f"[{index}/{len(pending)}] {audio_path.name}: {status}", flush=True)

            if index % CHECKPOINT_EVERY == 0:
                results = pd.concat([results, *new_results], ignore_index=True)
                new_results.clear()
                save_results(results, OUTPUT_PATH)
                print(f"Saved {len(results)} rows", flush=True)
    except KeyboardInterrupt:
        print("\nStopped; saving completed rows...", file=sys.stderr)
        failures += 1
    finally:
        if new_results:
            results = pd.concat([results, *new_results], ignore_index=True)
        save_results(results, OUTPUT_PATH)

    print(f"Finished with {len(results)} rows and {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
