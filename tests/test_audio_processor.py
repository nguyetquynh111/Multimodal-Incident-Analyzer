from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
import wave

from src.audio.processor import (
    AUDIO_OUTPUT_COLUMNS,
    EXTRACTOR_COLUMNS,
    UNKNOWN,
    _load_whisper,
    analyze_transcript,
    extract_names,
    extract_urgency_phrases,
    process_audio,
    to_audio_output,
    transcribe_whisper,
)


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

    def test_audio_output_uses_required_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "call_001.wav"
            _write_silent_wav(path)
            extractor_result = process_audio(
                path,
                transcriber=lambda _: "Please hurry, there is a fire at 12 Main Street!",
            )
            result = to_audio_output(
                extractor_result,
                audio_paths={path.name: path},
            )

        self.assertEqual(list(result.columns), AUDIO_OUTPUT_COLUMNS)
        row = result.iloc[0]
        self.assertEqual(row["Call_ID"], "call_001")
        self.assertEqual(row["Extracted_Event"], "Fire")
        self.assertEqual(row["Location"], "12 Main Street")
        self.assertEqual(row["Sentiment"], "Distressed")
        self.assertGreater(row["Urgency_Score"], 0.75)

    def test_extracts_explicit_names_and_urgency_phrases(self) -> None:
        transcript = (
            "My name is Sarah Connor. Please hurry and send an ambulance right now. "
            "John is nearby."
        )

        self.assertEqual(extract_names(transcript), "Sarah Connor")
        phrases = extract_urgency_phrases(transcript).lower()
        self.assertIn("please", phrases)
        self.assertIn("hurry", phrases)
        self.assertIn("send an ambulance", phrases)
        self.assertIn("right now", phrases)
        self.assertNotIn("john", extract_names(transcript).lower())

    def test_sentiment_and_urgency_are_independent(self) -> None:
        analysis = analyze_transcript("There is a fire at 12 Main Street.")

        self.assertEqual(analysis["sentiment"], "Calm")
        self.assertGreaterEqual(analysis["urgency_score"], 0.75)

    def test_process_audio_preserves_intermediate_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "named_call.wav"
            _write_silent_wav(path)
            result = process_audio(
                path,
                transcriber=lambda _: "This is Alex Morgan. Please send police right now.",
            )

        annotations = result.attrs["audio_annotations"]["named_call.wav"]
        self.assertEqual(annotations["names"], "Alex Morgan")
        self.assertIn("send police", annotations["urgency_phrases"].lower())
        self.assertIn(annotations["sentiment"], {"Calm", "Distressed"})
        self.assertGreaterEqual(annotations["urgency_score"], 0.0)
        self.assertLessEqual(annotations["urgency_score"], 1.0)

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

    def test_openai_whisper_backend_normalizes_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "whisper.wav"
            _write_silent_wav(path)

            model = Mock()
            model.transcribe.return_value = {
                "text": "  There is a fire at the school.  ",
                "segments": [{"avg_logprob": -0.1, "no_speech_prob": 0.05}],
            }
            whisper_module = ModuleType("whisper")
            whisper_module.load_model = Mock(return_value=model)

            _load_whisper.cache_clear()
            with (
                patch.dict(sys.modules, {"whisper": whisper_module}),
                patch.dict(
                    os.environ,
                    {
                        "WHISPER_DEVICE": "cpu",
                        "WHISPER_LANGUAGE": "en",
                        "WHISPER_MODEL_DIR": "",
                    },
                ),
                patch("src.audio.processor.shutil.which", return_value="/usr/bin/ffmpeg"),
            ):
                result = transcribe_whisper(path, model_name="tiny.en")
            _load_whisper.cache_clear()

        whisper_module.load_model.assert_called_once_with("tiny.en", device="cpu")
        model.transcribe.assert_called_once_with(
            str(path),
            task="transcribe",
            language="en",
            fp16=False,
            verbose=False,
        )
        self.assertEqual(result.text, "There is a fire at the school.")
        self.assertGreater(result.confidence, 0.8)


if __name__ == "__main__":
    unittest.main()
