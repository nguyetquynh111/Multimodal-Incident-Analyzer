"""Offline tests for image drafts using the checked-in sample images."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

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
    monkeypatch.setattr(
        processor,
        "_infer_detection_result",
        lambda _: (
            [
                {"class": "fire", "confidence": 0.88, "x": 50, "y": 40, "width": 20, "height": 10},
                {"class": "person", "confidence": 0.74, "x": 30, "y": 35, "width": 12, "height": 24},
            ],
            True,
        ),
    )
    monkeypatch.setattr(processor, "_ocr_text", lambda _: "Main Street")

    frame = processor.process_image(sample)

    assert list(frame.columns) == processor.ARTIFACT_COLUMNS
    assert frame.iloc[0].to_dict() == {
        "Image_ID": "IMG_001", "Scene_Type": "Fire and Smoke Scene", "Objects_Detected": "fire, person",
        "Text_Extracted": "Main Street", "Confidence_Score": 0.81,
    }
    assert frame.attrs["image_detections"][0]["class"] == "fire"
    assert frame.attrs["image_detections"][0]["width"] == 20
    assert 0.0 <= float(frame.iloc[0]["Confidence_Score"]) <= 1.0


def test_folder_processing_uses_the_samples_in_sorted_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for sample in SAMPLE_IMAGES:
        shutil.copy2(sample, tmp_path / sample.name)
    monkeypatch.setattr(processor, "_infer_detection_result", lambda _: ([], False))
    monkeypatch.setattr(processor, "_ocr_text", lambda _: processor.UNKNOWN)

    output = tmp_path / "image_output.csv"
    frame = processor.process_folder(tmp_path, output)
    saved = pd.read_csv(output, keep_default_na=False)

    assert frame["Image_ID"].tolist() == [f"IMG_{index:03d}" for index in range(1, len(SAMPLE_IMAGES) + 1)]
    assert frame["Confidence_Score"].tolist() == [0.5] * len(SAMPLE_IMAGES)
    assert list(saved.columns) == processor.ARTIFACT_COLUMNS
    assert not saved.isnull().values.any()


def test_no_image_signal_uses_documented_artifact_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processor, "_infer_detection_result", lambda _: ([], True))
    monkeypatch.setattr(processor, "_ocr_text", lambda _: processor.NO_TEXT)

    row = processor.analyze_image(SAMPLE_IMAGES[0])

    assert row["Scene_Type"] == "General Scene"
    assert row["Objects_Detected"] == "None"
    assert row["Text_Extracted"] == "N/A"
    assert row["Confidence_Score"] == 0.5


def test_image_confidence_uses_average_of_valid_detection_scores() -> None:
    detections = [
        {"class": "fire", "confidence": 0.95},
        {"class": "smoke", "confidence": 0.65},
        {"class": "person", "confidence": "not-a-score"},
        {"class": "vehicle"},
    ]

    labels, confidence = processor._labels_and_confidence(detections, fallback_confidence=0.5)

    assert labels == ["fire", "smoke", "person", "vehicle"]
    assert confidence == 0.8


def test_image_confidence_is_bounded_before_averaging() -> None:
    detections = [
        {"class": "fire", "confidence": 1.4},
        {"class": "smoke", "confidence": -0.2},
    ]

    _labels, confidence = processor._labels_and_confidence(detections, fallback_confidence=0.5)

    assert confidence == 0.5


def test_near_one_image_confidence_rounds_naturally() -> None:
    detections = [{"class": "fire", "confidence": 0.999998}]

    _labels, confidence = processor._labels_and_confidence(detections, fallback_confidence=0.5)

    assert confidence == 1.0


def test_roboflow_inference_combines_fire_and_person_models(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    api_urls: list[str] = []

    class FakeInferenceHTTPClient:
        def __init__(self, api_url: str, api_key: str) -> None:
            self.api_url = api_url
            self.api_key = api_key
            api_urls.append(api_url)

        def infer(self, img_path: str, model_id: str) -> dict[str, list[dict[str, float | str]]]:
            calls.append(model_id)
            if model_id == processor.DEFAULT_MODEL_ID:
                return {"predictions": [{"class": "fire", "confidence": 0.8}]}
            return {
                "predictions": [
                    {"class": "person", "confidence": 0.6},
                    {"class": "car", "confidence": 0.9},
                ]
            }

    monkeypatch.setenv("ROBOFLOW_API_KEY", "test-key")
    monkeypatch.delenv("ROBOFLOW_MODEL_ID", raising=False)
    monkeypatch.delenv("ROBOFLOW_PERSON_MODEL_ID", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "inference_sdk",
        SimpleNamespace(InferenceHTTPClient=FakeInferenceHTTPClient),
    )

    detections, inference_available = processor._infer_detection_result("example.jpg")

    assert inference_available is True
    assert api_urls == [processor.DEFAULT_API_URL]
    assert calls == [processor.DEFAULT_MODEL_ID, processor.DEFAULT_PERSON_MODEL_ID]
    assert detections == [
        {"class": "fire", "confidence": 0.8},
        {"class": "person", "confidence": 0.6},
    ]


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (["fire", "person"], "Fire and Smoke Scene"),
        (["fire", "smoke"], "Fire and Smoke Scene"),
        (["fire"], "Fire Scene"),
        (["smoke"], "Smoke Scene"),
        (["person"], "General Scene"),
        ([], "General Scene"),
    ],
)
def test_classify_scene_uses_documents_style_labels(labels: list[str], expected: str) -> None:
    assert processor.classify_scene(labels) == expected


def test_roboflow_bbox_coordinates_convert_to_box_corners() -> None:
    detection = {"class": "fire", "confidence": 0.91, "x": 50, "y": 40, "width": 20, "height": 10}

    assert processor._bbox_from_detection(detection, 100, 80) == (40, 35, 60, 45)


@pytest.mark.parametrize(
    ("readings", "expected"),
    [
        (["readable ExampleNews.com"], "readable ExampleNews.com"),
        (["In Loving Memory"], "In Loving Memory"),
        (["unrelated marks"], "unrelated marks"),
        (["!!!", "  "], processor.NO_TEXT),
    ],
)
def test_ocr_cleanup_preserves_generic_readable_text(readings, expected) -> None:
    """Exercise OCR text cleanup without requiring OpenCV/Tesseract in CI."""

    cleaned = [
        processor._clean_ocr_candidate(reading)
        for reading in readings
        if processor._clean_ocr_candidate(reading)
    ]

    if cleaned:
        actual = max(cleaned, key=lambda value: (len("".join(ch for ch in value if ch.isalnum())), len(value)))
    else:
        actual = processor.NO_TEXT

    assert actual == expected
