"""Offline tests for image drafts using the checked-in sample images."""

from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd
import pytest

from images import processor


SAMPLE_IMAGES = sorted(
    path for path in (Path(__file__).resolve().parents[1] / "images" / "sample_data").iterdir()
    if path.suffix.lower() in processor.SUPPORTED_IMAGE_EXTENSIONS
)


def test_repository_includes_image_samples_for_offline_contract_tests() -> None:
    assert SAMPLE_IMAGES, "Add at least one .jpg, .jpeg, or .png image under images/sample_data/."


@pytest.mark.parametrize("sample", SAMPLE_IMAGES, ids=lambda path: path.name)
def test_sample_image_returns_exact_draft_schema_without_network_calls(
    monkeypatch: pytest.MonkeyPatch, sample: Path
) -> None:
    monkeypatch.setattr(processor, "_infer_labels", lambda _: (["fire", "person"], 0.88))
    monkeypatch.setattr(processor, "_ocr_text", lambda _: "Main Street")

    frame = processor.process_image(sample)

    assert list(frame.columns) == processor.ARTIFACT_COLUMNS
    assert frame.iloc[0].to_dict() == {
        "Image_ID": "IMG_001", "Scene_Type": "Fire / Arson", "Objects_Detected": "fire, person",
        "Text_Extracted": "Main Street", "Confidence_Score": 0.88,
    }
    assert 0.0 <= float(frame.iloc[0]["Confidence_Score"]) <= 1.0


def test_folder_processing_uses_the_samples_in_sorted_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for sample in SAMPLE_IMAGES:
        shutil.copy2(sample, tmp_path / sample.name)
    monkeypatch.setattr(processor, "_infer_labels", lambda _: ([], 0.0))
    monkeypatch.setattr(processor, "_ocr_text", lambda _: processor.UNKNOWN)

    output = tmp_path / "image_output.csv"
    frame = processor.process_folder(tmp_path, output)
    saved = pd.read_csv(output, keep_default_na=False)

    assert frame["Image_ID"].tolist() == [f"IMG_{index:03d}" for index in range(1, len(SAMPLE_IMAGES) + 1)]
    assert list(saved.columns) == processor.ARTIFACT_COLUMNS
    assert not saved.isnull().values.any()
