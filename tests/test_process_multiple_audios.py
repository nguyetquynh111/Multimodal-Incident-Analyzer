from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from audio.process_multiple_audios import (
    discover_audio_files,
    load_existing_results,
    save_results,
)
from src.extractors.audio_processor import EXTRACTOR_COLUMNS


class ProcessMultipleAudiosTests(unittest.TestCase):
    def test_discovers_supported_files_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.WAV").touch()
            (root / "a.mp3").touch()
            (root / "ignore.txt").touch()
            nested = root / "nested"
            nested.mkdir()
            (nested / "c.m4a").touch()

            top_level = discover_audio_files(root)

        self.assertEqual([path.name for path in top_level], ["a.mp3", "b.WAV"])

    def test_atomic_save_and_resume_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audio_output.csv"
            row = {
                "source_filename": "call.wav",
                "source_type": "AUD",
                "raw_event": "Unknown",
                "raw_location": "Unknown",
                "raw_time": "Unknown",
                "raw_severity": "Low",
                "confidence": 0.0,
                "raw_text": "Unknown",
            }
            save_results(pd.DataFrame([row]), output)
            loaded = load_existing_results(output)

        self.assertEqual(list(loaded.columns), EXTRACTOR_COLUMNS)
        self.assertEqual(loaded.iloc[0]["source_filename"], "call.wav")


if __name__ == "__main__":
    unittest.main()
