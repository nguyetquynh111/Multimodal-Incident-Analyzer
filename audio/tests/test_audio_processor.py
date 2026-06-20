from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from audio.config import OUTPUT_COLUMNS
from audio.extract import analyze_transcript
from audio.pipeline import main, process_audio_file, process_audio_folder


class AudioProcessorTests(unittest.TestCase):
    def test_rule_based_analysis(self) -> None:
        row = analyze_transcript(
            "DEMO001",
            "There is fire and smoke at 123 Main Street. Help me!",
        )

        self.assertEqual(row["Extracted_Event"], "building fire")
        self.assertEqual(row["Urgency_Score"], 0.9)
        self.assertEqual(row["Sentiment"], "Distressed")

    def test_incident_keyword_rules(self) -> None:
        examples = {
            "Several fires were reported.": "building fire",
            "A shed burned while another building was burning.": "building fire",
            "A person is stuck and cannot get out.": "trapped person",
            "They had guns and fired shots.": "shooting",
            "Several shootings were reported nearby.": "shooting",
            "Multiple crashes and collisions were reported.": "car accident",
            "Two heart attacks were reported.": "medical emergency",
            "The patient bleeds and is unconscious.": "medical emergency",
            "Several overdoses involved drugs and pills.": "overdose",
            "Several burglaries and break-ins occurred.": "burglary/robbery",
            "Multiple robberies involved stolen property.": "burglary/robbery",
            "Multiple fights and assaults occurred.": "assault",
            "We cannot find the missing child.": "missing person",
            "This is a routine report.": "unknown emergency",
        }
        for transcript, expected in examples.items():
            with self.subTest(transcript=transcript):
                self.assertEqual(
                    analyze_transcript("C001", transcript)["Extracted_Event"],
                    expected,
                )

    def test_urgency_uses_word_boundaries(self) -> None:
        row = analyze_transcript(
            "C001", "The firefighter has begun a routine training report."
        )
        self.assertEqual(row["Extracted_Event"], "unknown emergency")
        self.assertEqual(row["Urgency_Score"], 0.3)
        self.assertEqual(row["Sentiment"], "Calm")

    def test_location_extraction_ignores_generic_floor(self) -> None:
        generic = analyze_transcript(
            "C001", "They had guns and told everyone to get on the floor."
        )
        specific = analyze_transcript(
            "C002",
            "Fire at 123 Main Street on the second floor near Central Park.",
        )
        self.assertEqual(generic["Location"], "Unknown")
        self.assertEqual(
            specific["Location"],
            "123 Main Street; second floor; Central Park",
        )

    def test_output_dictionary_has_exact_required_columns(self) -> None:
        row = analyze_transcript("C001", "There is a fire at 123 Main Street.")
        self.assertEqual(list(row), OUTPUT_COLUMNS)

    def test_urgency_is_bounded_and_maps_to_sentiment(self) -> None:
        distressed = analyze_transcript(
            "C001", "There is a fire and smoke. Help me, this is an emergency."
        )
        calm = analyze_transcript("C002", "This is a routine report.")
        self.assertEqual(distressed["Urgency_Score"], 0.9)
        self.assertEqual(distressed["Sentiment"], "Distressed")
        self.assertEqual(calm["Urgency_Score"], 0.3)
        self.assertEqual(calm["Sentiment"], "Calm")
        for row in (distressed, calm):
            self.assertGreaterEqual(row["Urgency_Score"], 0.0)
            self.assertLessEqual(row["Urgency_Score"], 1.0)

    def test_process_audio_file_accepts_flac_with_custom_transcriber(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "C009.flac"
            audio_path.touch()
            row = process_audio_file(
                str(audio_path),
                transcriber=lambda _: "There are guns at 123 Main Street.",
            )
        self.assertEqual(row["Call_ID"], "C009")
        self.assertEqual(row["Extracted_Event"], "shooting")
        self.assertEqual(list(row), OUTPUT_COLUMNS)

    def test_folder_processing_is_sorted_top_level_only_and_writes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "C002.MP3").touch()
            (root / "C001.wav").touch()
            (root / "ignored.txt").touch()
            nested = root / "nested"
            nested.mkdir()
            (nested / "C003.m4a").touch()
            output = root / "results" / "audio.csv"

            frame = process_audio_folder(
                str(root),
                str(output),
                transcriber=lambda _: "This is a routine report.",
            )
            saved = pd.read_csv(output)

        self.assertEqual(frame["Call_ID"].tolist(), ["C001", "C002"])
        self.assertEqual(list(frame.columns), OUTPUT_COLUMNS)
        self.assertEqual(list(saved.columns), OUTPUT_COLUMNS)

    def test_path_and_empty_folder_errors_are_helpful(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "Audio file not found"):
            process_audio_file("missing.wav")
        with self.assertRaisesRegex(NotADirectoryError, "Audio folder not found"):
            process_audio_folder("missing-folder", "unused.csv")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsupported = root / "call.txt"
            unsupported.touch()
            with self.assertRaisesRegex(ValueError, "Unsupported audio type"):
                process_audio_file(str(unsupported))
            with self.assertRaisesRegex(ValueError, "No supported audio files"):
                process_audio_folder(str(root), str(root / "output.csv"))

    def test_demo_cli_writes_exact_schema_without_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo.csv"
            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "--demo-transcript",
                        "There are guns near Central Station.",
                        "--output",
                        str(output),
                    ]
                )
            frame = pd.read_csv(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(list(frame.columns), OUTPUT_COLUMNS)
        self.assertEqual(frame.iloc[0]["Extracted_Event"], "shooting")


if __name__ == "__main__":
    unittest.main()
