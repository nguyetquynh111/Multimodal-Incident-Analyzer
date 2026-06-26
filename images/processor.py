"""Image processor for the documented five-column image artifact.

Output columns:
Image_ID, Scene_Type, Objects_Detected, Text_Extracted, Confidence_Score
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import pandas as pd


ARTIFACT_COLUMNS = [
    "Image_ID",
    "Scene_Type",
    "Objects_Detected",
    "Text_Extracted",
    "Confidence_Score",
]

UNKNOWN = "Unknown"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "image_output.csv"
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID", "fire-detection-data-pre/4")


def classify_scene(labels: list[str]) -> str:
    labels_lower = [label.lower() for label in labels]
    if "fire" in labels_lower:
        return "Fire / Arson"
    if "smoke" in labels_lower:
        return "Smoke Scene"
    if "person" in labels_lower:
        return "General Scene"
    return UNKNOWN


def _infer_labels(img_path: str) -> tuple[list[str], float]:
    api_key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    if not api_key:
        return [], 0.0
    try:
        from inference_sdk import InferenceHTTPClient  # type: ignore

        client = InferenceHTTPClient(
            api_url=os.getenv("ROBOFLOW_API_URL", "https://serverless.roboflow.com"),
            api_key=api_key,
        )
        result = client.infer(img_path, model_id=MODEL_ID)
    except Exception:
        return [], 0.0

    predictions = result.get("predictions", []) if isinstance(result, dict) else []
    labels = [str(pred.get("class")) for pred in predictions if pred.get("class")]
    confidences = [
        float(pred.get("confidence"))
        for pred in predictions
        if isinstance(pred, dict) and pred.get("confidence") is not None
    ]
    top_confidence = round(max(confidences), 2) if confidences else 0.0
    return labels, top_confidence


def _ocr_text(img_path: str) -> str:
    try:
        import cv2  # type: ignore
        import pytesseract  # type: ignore

        img = cv2.imread(img_path)
        if img is None:
            return UNKNOWN
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray).strip().replace("\n", " ")
        return text or UNKNOWN
    except Exception:
        return UNKNOWN


def analyze_image(img_path: str | Path, image_id: str = "IMG_001") -> dict[str, Any]:
    path = Path(img_path)
    labels, confidence = _infer_labels(str(path))
    ocr_text = _ocr_text(str(path))
    return {
        "Image_ID": image_id,
        "Scene_Type": classify_scene(labels),
        "Objects_Detected": ", ".join(sorted(set(labels))) if labels else UNKNOWN,
        "Text_Extracted": ocr_text,
        "Confidence_Score": confidence,
    }


def _frame_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=ARTIFACT_COLUMNS)
    for column in ARTIFACT_COLUMNS:
        frame[column] = frame[column].fillna(UNKNOWN)
    return frame


def process_image(
    img_path: str | Path,
    output_csv_path: str | Path | None = None,
    *,
    image_id: str = "IMG_001",
) -> pd.DataFrame:
    """Analyze one image and return the five-column image draft."""

    frame = _frame_from_rows([analyze_image(img_path, image_id)])
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
    rows = [
        analyze_image(img_file, f"IMG_{index:03d}")
        for index, img_file in enumerate(image_files, start=1)
    ]
    frame = _frame_from_rows(rows)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze image evidence.")
    parser.add_argument("--input", default="images/sample_data/")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args(argv)
    frame = process_folder(args.input, args.output)
    print(f"Saved {len(frame)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
