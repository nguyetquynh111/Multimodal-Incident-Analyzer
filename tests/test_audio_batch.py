from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from src.audio.batch import (
    discover_audio_files,
    load_existing_results,
    save_results,
)
from src.audio.processor import AUDIO_OUTPUT_COLUMNS


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
                "Call_ID": "call",
                "Transcript": "Unknown",
                "Extracted_Event": "Unknown",
                "Location": "Unknown",
                "Sentiment": "Calm",
                "Urgency_Score": 0.0,
            }
            save_results(pd.DataFrame([row]), output)
            loaded = load_existing_results(output)

        self.assertEqual(list(loaded.columns), AUDIO_OUTPUT_COLUMNS)
        self.assertEqual(loaded.iloc[0]["Call_ID"], "call")


if __name__ == "__main__":
    unittest.main()
