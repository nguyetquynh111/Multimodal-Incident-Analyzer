"""Image processor for the documented five-column image artifact.

Output columns:
Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv


ARTIFACT_COLUMNS = [
    "Image_ID",
    "Scene_Type",
    "Objects_Detected",
    "Text_Extracted",
    "Confidence_Score",
]

UNKNOWN = "Unknown"
NO_OBJECTS = "None"
NO_TEXT = "N/A"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "image_output.csv"
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_ID = "fire-detection-data-pre/4"
DEFAULT_PERSON_MODEL_ID = "yolov8n-640"
DEFAULT_API_URL = "https://serverless.roboflow.com"
logger = logging.getLogger(__name__)


def _load_image_environment() -> None:
    """Load image settings without replacing already-exported values."""

    load_dotenv(PROJECT_ROOT / ".env", override=False)


def classify_scene(labels: list[str]) -> str:
    labels_lower = [label.lower() for label in labels]
    if "fire" in labels_lower and "person" in labels_lower:
        return "Fire and Smoke Scene"
    if "fire" in labels_lower and "smoke" in labels_lower:
        return "Fire and Smoke Scene"
    if "fire" in labels_lower:
        return "Fire Scene"
    if "smoke" in labels_lower:
        return "Smoke Scene"
    if "person" in labels_lower:
        return "General Scene"
    return "General Scene"


def _normalize_prediction(prediction: Mapping[str, Any]) -> dict[str, Any] | None:
    """Keep Roboflow labels/confidence/bbox data in a UI-friendly shape."""

    label = prediction.get("class")
    if not label:
        return None

    detection: dict[str, Any] = {"class": str(label)}
    for key in ("confidence", "x", "y", "width", "height"):
        value = prediction.get(key)
        if value is not None:
            try:
                detection[key] = float(value)
            except (TypeError, ValueError):
                continue
    return detection


def _infer_detection_result(img_path: str) -> tuple[list[dict[str, Any]], bool]:
    _load_image_environment()
    api_key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    if not api_key:
        logger.warning("ROBOFLOW_API_KEY is not configured; using image detection fallback.")
        return [], False
    try:
        from inference_sdk import InferenceHTTPClient  # type: ignore

        client = InferenceHTTPClient(
            api_url=os.getenv("ROBOFLOW_API_URL", DEFAULT_API_URL),
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Roboflow client setup failed for %s (%s); using fallback.",
            Path(img_path).name,
            type(exc).__name__,
        )
        return [], False

    model_specs = (
        (os.getenv("ROBOFLOW_MODEL_ID", DEFAULT_MODEL_ID), None),
        (os.getenv("ROBOFLOW_PERSON_MODEL_ID", DEFAULT_PERSON_MODEL_ID), "person"),
    )
    detections: list[dict[str, Any]] = []
    inference_available = False
    for model_id, class_filter in model_specs:
        try:
            result = client.infer(img_path, model_id=model_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Roboflow inference failed for %s with %s: %s: %r",
                Path(img_path).name,
                model_id,
                type(exc).__name__,
                exc,
            )
            continue
        inference_available = True
        predictions = result.get("predictions", []) if isinstance(result, dict) else []
        for pred in predictions:
            if not isinstance(pred, Mapping):
                continue
            if class_filter is not None and pred.get("class") != class_filter:
                continue
            detection = _normalize_prediction(pred)
            if detection is not None:
                detections.append(detection)

    return detections, inference_available


def _infer_detections(img_path: str) -> list[dict[str, Any]]:
    detections, _inference_available = _infer_detection_result(img_path)
    return detections


def _bounded_confidence(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return max(0.0, min(1.0, score))


def _confidence_score(detections: list[dict[str, Any]], *, fallback_confidence: float) -> float:
    confidences = [
        score
        for det in detections
        for score in [_bounded_confidence(det.get("confidence"))]
        if score is not None
    ]
    if not confidences:
        return fallback_confidence
    return round(sum(confidences) / len(confidences), 2)


def _labels_and_confidence(detections: list[dict[str, Any]], *, fallback_confidence: float) -> tuple[list[str], float]:
    labels = [str(det.get("class")) for det in detections if det.get("class")]
    return labels, _confidence_score(detections, fallback_confidence=fallback_confidence)


def _infer_labels(img_path: str) -> tuple[list[str], float]:
    """Compatibility wrapper for code/tests that only need label + confidence."""

    detections, _inference_available = _infer_detection_result(img_path)
    fallback_confidence = 0.5
    return _labels_and_confidence(detections, fallback_confidence=fallback_confidence)


def _clean_ocr_candidate(text: str, *, max_length: int = 160) -> str:
    """Normalize one OCR reading without whitelisting sample-specific values."""

    lines = []
    for raw_line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", raw_line).strip()
        cleaned = cleaned.strip(" \t\r\n|:;,.•·-_")
        if len(re.sub(r"[^A-Za-z0-9]", "", cleaned)) >= 3:
            lines.append(cleaned)

    if not lines:
        return ""

    cleaned_text = " ".join(lines)
    return cleaned_text[:max_length].strip()


def _ocr_text(img_path: str) -> str:
    """Run full-image grayscale OCR, matching the original image draft flow."""

    try:
        import cv2  # type: ignore
        import pytesseract  # type: ignore

        img = cv2.imread(img_path)
        if img is None:
            logger.warning("Could not read image %s for OCR; using N/A.", Path(img_path).name)
            return NO_TEXT

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ocr_text = pytesseract.image_to_string(gray).strip().replace("\n", " ")
        return ocr_text if len(ocr_text) > 3 else NO_TEXT
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OCR failed for %s (%s); using N/A.", Path(img_path).name, type(exc).__name__
        )
        return NO_TEXT


def _analyze_image_with_detections(
    img_path: str | Path,
    image_id: str = "IMG_001",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(img_path)
    detections, _inference_available = _infer_detection_result(str(path))
    labels, confidence = _labels_and_confidence(
        detections,
        fallback_confidence=0.5,
    )
    ocr_text = _ocr_text(str(path))
    return {
        "Image_ID": image_id,
        "Scene_Type": classify_scene(labels),
        "Objects_Detected": ", ".join(sorted(set(labels))) if labels else NO_OBJECTS,
        "Text_Extracted": ocr_text,
        "Confidence_Score": confidence,
    }, detections


def analyze_image(img_path: str | Path, image_id: str = "IMG_001") -> dict[str, Any]:
    row, _detections = _analyze_image_with_detections(img_path, image_id)
    return row


def _frame_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=ARTIFACT_COLUMNS)
    for column in ARTIFACT_COLUMNS:
        fallback = {
            "Objects_Detected": NO_OBJECTS,
            "Text_Extracted": NO_TEXT,
        }.get(column, UNKNOWN)
        frame[column] = frame[column].fillna(fallback)
    return frame


def process_image(
    img_path: str | Path,
    output_csv_path: str | Path | None = None,
    *,
    image_id: str = "IMG_001",
) -> pd.DataFrame:
    """Analyze one image and return the five-column image draft."""

    row, detections = _analyze_image_with_detections(img_path, image_id)
    frame = _frame_from_rows([row])
    frame.attrs["image_detections"] = detections
    if output_csv_path is not None:
        output = Path(output_csv_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False)
    return frame


def process_folder(input_path: str | Path, output_csv: str | Path = DEFAULT_OUTPUT_PATH) -> pd.DataFrame:
    path = Path(input_path)
    image_files = sorted(
        file for file in path.iterdir()
        if file.is_file() and file.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )
    rows: list[dict[str, Any]] = []
    detections_by_id: dict[str, list[dict[str, Any]]] = {}
    for index, img_file in enumerate(image_files, start=1):
        image_id = f"IMG_{index:03d}"
        row, detections = _analyze_image_with_detections(img_file, image_id)
        rows.append(row)
        detections_by_id[image_id] = detections
    frame = _frame_from_rows(rows)
    frame.attrs["image_detections_by_id"] = detections_by_id
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    return frame


def _bbox_from_detection(
    detection: Mapping[str, Any],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int] | None:
    """Convert Roboflow center-x/y/width/height coordinates to image box corners."""

    try:
        center_x = float(detection["x"])
        center_y = float(detection["y"])
        width = float(detection["width"])
        height = float(detection["height"])
    except (KeyError, TypeError, ValueError):
        return None

    left = max(0, min(image_width - 1, int(round(center_x - width / 2))))
    top = max(0, min(image_height - 1, int(round(center_y - height / 2))))
    right = max(0, min(image_width - 1, int(round(center_x + width / 2))))
    bottom = max(0, min(image_height - 1, int(round(center_y + height / 2))))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def annotate_image_with_detections(
    img_path: str | Path,
    detections: list[Mapping[str, Any]] | None = None,
) -> Any:
    """Return a PIL image with detection bounding boxes drawn on top.

    This helper is intentionally separate from the five-column CSV artifact:
    bounding boxes are UI evidence, while the required artifact schema remains
    stable for integration/export tests.
    """

    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(img_path).convert("RGB")
    width, height = image.size
    detections = list(detections) if detections is not None else _infer_detections(str(img_path))
    if not detections:
        return image

    draw = ImageDraw.Draw(image)
    line_width = max(3, round(min(width, height) / 180))
    try:
        font = ImageFont.truetype("Arial.ttf", max(14, line_width * 5))
    except OSError:
        font = ImageFont.load_default()

    for detection in detections:
        bbox = _bbox_from_detection(detection, width, height)
        if bbox is None:
            continue
        left, top, right, bottom = bbox
        label = str(detection.get("class", "object"))
        confidence = detection.get("confidence")
        if confidence is not None:
            try:
                label = f"{label} {float(confidence):.0%}"
            except (TypeError, ValueError):
                pass

        draw.rectangle((left, top, right, bottom), outline="#22C55E", width=line_width)
        text_bbox = draw.textbbox((left, top), label, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        label_top = max(0, top - text_height - 2 * line_width)
        draw.rectangle(
            (left, label_top, left + text_width + 2 * line_width, label_top + text_height + 2 * line_width),
            fill="#22C55E",
        )
        draw.text(
            (left + line_width, label_top + line_width),
            label,
            fill="#0F172A",
            font=font,
        )

    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze image evidence.")
    parser.add_argument("--input", required=True, help="An image file or a folder of images")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--image-id", default="IMG_001", help="Image ID when --input is one file")
    args = parser.parse_args(argv)

    input_path = Path(args.input).expanduser()
    if input_path.is_file():
        frame = process_image(input_path, args.output, image_id=args.image_id)
    elif input_path.is_dir():
        frame = process_folder(input_path, args.output)
    else:
        parser.error(f"Input path does not exist: {input_path}")
    print(f"Saved {len(frame)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
