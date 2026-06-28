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


def test_integration_input_paths_skip_empty_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def integrate_records(
        draft: pd.DataFrame,
        source_type: str,
        existing_ids=(),
        *,
        source_filename: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Incident_ID": f"INC_{ig.source_prefix(source_type)}_001",
                    "Source": ig.source_label(source_type),
                    "Event": "Unknown",
                    "Location": "Unknown",
                    "Time": "Unknown",
                    "Severity": "Low",
                    "Incident_Summary": f"{source_filename} integrated.",
                }
            ]
        )

    monkeypatch.setattr(ig, "integrate_records", integrate_records)
    audio_draft = tmp_path / "audio.csv"
    pd.DataFrame([{"draft": "audio"}]).to_csv(audio_draft, index=False)
    output = tmp_path / "integrated.csv"

    frame = ig.integrate_input_paths(
        {
            "audio": audio_draft,
            "pdf": "",
            "image": None,
            "video": "   ",
            "text": "",
        },
        output,
    )

    assert frame["Incident_ID"].tolist() == ["INC_AUD_001"]
    assert pd.read_csv(output)["Incident_ID"].tolist() == ["INC_AUD_001"]


def test_integration_input_paths_falls_back_to_processor_default_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def integrate_records(
        draft: pd.DataFrame,
        source_type: str,
        existing_ids=(),
        *,
        source_filename: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Incident_ID": f"INC_{ig.source_prefix(source_type)}_001",
                    "Source": ig.source_label(source_type),
                    "Event": "Unknown",
                    "Location": "Unknown",
                    "Time": "Unknown",
                    "Severity": "Low",
                    "Incident_Summary": f"{source_filename} integrated.",
                }
            ]
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ig, "integrate_records", integrate_records)
    default_audio_draft = tmp_path / "audio" / "output" / "audio.csv"
    default_audio_draft.parent.mkdir(parents=True)
    pd.DataFrame([{"draft": "audio"}]).to_csv(default_audio_draft, index=False)
    output = tmp_path / "integrated.csv"

    frame = ig.integrate_input_paths({"audio": "output/audio.csv"}, output)

    assert frame["Incident_ID"].tolist() == ["INC_AUD_001"]
    assert frame["Incident_Summary"].tolist() == ["audio.csv integrated."]
    assert pd.read_csv(output)["Incident_ID"].tolist() == ["INC_AUD_001"]


def test_integration_input_paths_does_not_fallback_for_custom_missing_path(
    tmp_path: Path,
) -> None:
    default_audio_draft = tmp_path / "audio" / "output" / "audio.csv"
    default_audio_draft.parent.mkdir(parents=True)
    pd.DataFrame([{"draft": "audio"}]).to_csv(default_audio_draft, index=False)

    with pytest.raises(FileNotFoundError, match="missing/audio.csv"):
        ig.integrate_input_paths(
            {"audio": tmp_path / "missing" / "audio.csv"}, tmp_path / "out.csv"
        )
