"""Regression tests for app-to-processor modality dispatch."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pandas as pd
import pytest

from audio.config import OUTPUT_COLUMNS
from integration import integration as ig


FIXTURE_DIR = Path("tests") / "fixtures"
PDF_PATH = FIXTURE_DIR / "report.pdf"
VIDEO_PATH = FIXTURE_DIR / "clip.mp4"
AUDIO_PATH = FIXTURE_DIR / "call.wav"


def _processor_module(name: str, function_name: str, function: MagicMock) -> ModuleType:
    module = ModuleType(name)
    setattr(module, function_name, function)
    return module


def test_pdf_dispatch_uses_six_column_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = pd.DataFrame([{"Report_ID": "RPT_001"}])
    process = MagicMock(return_value=expected)
    monkeypatch.setitem(
        sys.modules,
        "pdf.processor",
        _processor_module("pdf.processor", "process_pdf", process),
    )

    assert ig.run_modality("pdf", PDF_PATH).equals(expected)
    process.assert_called_once_with(str(PDF_PATH), output_csv_path=None)


def test_video_dispatch_uses_five_column_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = pd.DataFrame([{"Frame_ID": "FRM_001"}])
    process = MagicMock(return_value=expected)
    monkeypatch.setitem(
        sys.modules,
        "video.processor",
        _processor_module("video.processor", "process_video", process),
    )

    assert ig.run_modality("video", VIDEO_PATH).equals(expected)
    process.assert_called_once_with(str(VIDEO_PATH))


def test_audio_dispatch_always_calls_file_processor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = dict.fromkeys(OUTPUT_COLUMNS, "value")
    process = MagicMock(return_value=row)
    monkeypatch.setitem(
        sys.modules,
        "audio.processor",
        _processor_module("audio.processor", "process_audio_file", process),
    )

    result = ig.run_modality("audio", AUDIO_PATH)

    process.assert_called_once_with(str(AUDIO_PATH))
    assert result.to_dict(orient="records") == [row]


def test_audio_dispatch_rejects_transcript_bypass() -> None:
    with pytest.raises(TypeError, match="transcript"):
        ig.run_modality("audio", AUDIO_PATH, transcript="typed text")  # type: ignore[call-arg]
