from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import wave

from src.extractors.audio_processor import EXTRACTOR_COLUMNS, UNKNOWN, process_audio


def _write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 1_600)


class NamedBytesIO(BytesIO):
    name = "uploaded_call.wav"


class AudioProcessorTests(unittest.TestCase):
    def test_high_severity_call_extracts_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fire_call.wav"
            _write_silent_wav(path)

            result = process_audio(
                path,
                transcriber=lambda _: {
                    "text": (
                        "Please hurry, the building is on fire at 123 Main Street. "
                        "Someone is trapped. It started at 9:30 PM."
                    ),
                    "confidence": 0.92,
                },
            )

        self.assertEqual(list(result.columns), EXTRACTOR_COLUMNS)
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["source_filename"], "fire_call.wav")
        self.assertEqual(row["source_type"], "AUD")
        self.assertEqual(row["raw_event"], "Fire")
        self.assertEqual(row["raw_location"], "123 Main Street")
        self.assertEqual(row["raw_time"].lower(), "9:30 pm")
        self.assertEqual(row["raw_severity"], "High")
        self.assertGreater(row["confidence"], 0.8)

    def test_medium_event_uses_unknown_for_missing_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theft.wav"
            _write_silent_wav(path)
            result = process_audio(
                path,
                transcriber=lambda _: "My bicycle was stolen near the school.",
            )

        row = result.iloc[0]
        self.assertEqual(row["raw_event"], "Theft")
        self.assertEqual(row["raw_location"].lower(), "school")
        self.assertEqual(row["raw_time"], UNKNOWN)
        self.assertEqual(row["raw_severity"], "Medium")

    def test_transcription_failure_returns_safe_fallback(self) -> None:
        def failing_transcriber(_: Path) -> str:
            raise RuntimeError("model unavailable")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed.wav"
            _write_silent_wav(path)
            result = process_audio(path, transcriber=failing_transcriber)

        row = result.iloc[0]
        self.assertEqual(row["raw_text"], UNKNOWN)
        self.assertEqual(row["raw_event"], UNKNOWN)
        self.assertEqual(row["raw_location"], UNKNOWN)
        self.assertEqual(row["raw_time"], UNKNOWN)
        self.assertEqual(row["raw_severity"], "Low")
        self.assertEqual(row["confidence"], 0.0)

    def test_uploaded_file_object_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.wav"
            _write_silent_wav(path)
            uploaded = NamedBytesIO(path.read_bytes())
            result = process_audio(uploaded, transcriber=lambda _: "There is a disturbance at the park.")

        self.assertEqual(result.iloc[0]["source_filename"], "uploaded_call.wav")
        self.assertEqual(result.iloc[0]["raw_event"], "Public disturbance")
        self.assertEqual(result.iloc[0]["raw_location"].lower(), "park")

    def test_unsupported_extension_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported audio type"):
            process_audio("call.txt", transcriber=lambda _: "test")


if __name__ == "__main__":
    unittest.main()
