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
DEFAULT_API_URL = "https://detect.roboflow.com"
logger = logging.getLogger(__name__)


def _load_image_environment() -> None:
    """Load image settings without replacing already-exported values."""

    load_dotenv(PROJECT_ROOT / ".env", override=False)


def classify_scene(labels: list[str]) -> str:
    labels_lower = [label.lower() for label in labels]
    if "fire" in labels_lower:
        return "Fire / Arson"
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
        result = client.infer(
            img_path,
            model_id=os.getenv("ROBOFLOW_MODEL_ID", DEFAULT_MODEL_ID),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Roboflow inference failed for %s (%s); using fallback.",
            Path(img_path).name,
            type(exc).__name__,
        )
        return [], False

    predictions = result.get("predictions", []) if isinstance(result, dict) else []
    return [
        detection
        for pred in predictions
        if isinstance(pred, Mapping)
        for detection in [_normalize_prediction(pred)]
        if detection is not None
    ], True


def _infer_detections(img_path: str) -> list[dict[str, Any]]:
    detections, _inference_available = _infer_detection_result(img_path)
    return detections


def _labels_and_confidence(detections: list[dict[str, Any]], *, fallback_confidence: float) -> tuple[list[str], float]:
    labels = [str(det.get("class")) for det in detections if det.get("class")]
    confidences = [
        float(det.get("confidence"))
        for det in detections
        if det.get("confidence") is not None
    ]
    top_confidence = round(max(confidences), 2) if confidences else fallback_confidence
    return labels, top_confidence


def _infer_labels(img_path: str) -> tuple[list[str], float]:
    """Compatibility wrapper for code/tests that only need label + confidence."""

    detections, inference_available = _infer_detection_result(img_path)
    fallback_confidence = 0.5 if inference_available else 0.0
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
    """Read sparse text/watermarks from the image corners before full-scene OCR.

    Evidence photos often contain a small agency or publisher credit in a
    corner. Running OCR across the entire fire/smoke scene produces noise that
    obscures that text, so the corner crops are enlarged and tried in both
    normal and inverted contrast first.
    """

    try:
        import cv2  # type: ignore
        import pytesseract  # type: ignore

        img = cv2.imread(img_path)
        if img is None:
            logger.warning("Could not read image %s for OCR; using N/A.", Path(img_path).name)
            return NO_TEXT

        height, width = img.shape[:2]
        # These regions cover the conventional locations for source credits,
        # without sending the visually busy centre of an evidence photo to OCR.
        corners = (
            img[: int(height * 0.50), : int(width * 0.70)],  # top-left
            img[int(height * 0.75):, int(width * 0.68):],  # bottom-right
        )
        readings: list[str] = []
        for crop in corners:
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            enlarged = cv2.resize(gray, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.threshold(
                enlarged, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )[1]
            for candidate in (enlarged, inverted):
                text = pytesseract.image_to_string(candidate, config="--psm 11")
                cleaned = _clean_ocr_candidate(text)
                if cleaned:
                    readings.append(cleaned)

        if readings:
            # Prefer the longest readable crop result. This keeps OCR data
            # source-driven instead of accepting only known sample phrases.
            return max(readings, key=lambda value: (len(re.sub(r"[^A-Za-z0-9]", "", value)), len(value)))

        return NO_TEXT
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
    detections, inference_available = _infer_detection_result(str(path))
    labels, confidence = _labels_and_confidence(
        detections,
        fallback_confidence=0.5 if inference_available else 0.0,
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
