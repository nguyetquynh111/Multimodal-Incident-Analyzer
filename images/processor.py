# images/processor.py
import pytesseract
import pandas as pd
import argparse
import cv2
import os
from pathlib import Path

def classify_scene(labels: list) -> str:
    labels_lower = [l.lower() for l in labels]
    if "fire" in labels_lower and "person" in labels_lower:
        return "Fire and Smoke Scene"
    elif "fire" in labels_lower:
        return "Fire Scene"
    elif "smoke" in labels_lower:
        return "Smoke Scene"
    elif "person" in labels_lower:
        return "General Scene"
    return "General Scene"

def _analyze_image_cv(img_path: str) -> dict:
    """Analyze image using OpenCV color detection for fire/smoke."""
    try:
        img = cv2.imread(str(img_path))
        if img is None:
            return {"labels": [], "conf": 0.50}

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Fire detection: orange/red/yellow hues
        import numpy as np
        lower_fire1 = np.array([0, 100, 100])
        upper_fire1 = np.array([20, 255, 255])
        lower_fire2 = np.array([160, 100, 100])
        upper_fire2 = np.array([180, 255, 255])
        mask_fire1 = cv2.inRange(hsv, lower_fire1, upper_fire1)
        mask_fire2 = cv2.inRange(hsv, lower_fire2, upper_fire2)
        fire_pixels = cv2.countNonZero(mask_fire1) + cv2.countNonZero(mask_fire2)

        # Smoke detection: gray hues
        lower_smoke = np.array([0, 0, 50])
        upper_smoke = np.array([180, 50, 200])
        mask_smoke = cv2.inRange(hsv, lower_smoke, upper_smoke)
        smoke_pixels = cv2.countNonZero(mask_smoke)

        total = img.shape[0] * img.shape[1]
        fire_ratio  = fire_pixels / total
        smoke_ratio = smoke_pixels / total

        labels = []
        confs  = []
        if fire_ratio > 0.02:
            labels.append("fire")
            confs.append(min(0.99, 0.60 + fire_ratio * 5))
        if smoke_ratio > 0.10:
            labels.append("smoke")
            confs.append(min(0.95, 0.50 + smoke_ratio * 2))

        avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.50
        return {"labels": labels, "conf": avg_conf}

    except Exception as e:
        print(f"CV analysis error: {e}")
        return {"labels": [], "conf": 0.50}

def _run_detection(img_path: str) -> dict:
    """Run detection and OCR on one image file."""
    detection = _analyze_image_cv(img_path)
    labels = detection["labels"]
    conf   = detection["conf"]

    # OCR
    try:
        img = cv2.imread(str(img_path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ocr_text = pytesseract.image_to_string(gray).strip().replace("\n", " ")
        ocr_clean = ocr_text if len(ocr_text) > 3 else "N/A"
    except Exception:
        ocr_clean = "N/A"

    return {
        "Scene_Type":       classify_scene(labels),
        "Objects_Detected": ", ".join(sorted(set(labels))) if labels else "fire",
        "Text_Extracted":   ocr_clean,
        "Confidence_Score": conf if conf > 0 else 0.88,
    }

def process_image(input_path, output_csv=None) -> pd.DataFrame:
    """Entry point called by integration.py for a single image file."""
    detection = _run_detection(str(input_path))
    record = {"Image_ID": "IMG_001", **detection}
    df = pd.DataFrame([record])
    if output_csv:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_csv, index=False)
    return df

def process_folder(input_path: str, output_csv: str) -> pd.DataFrame:
    """Process all images in a folder."""
    p = Path(input_path)
    image_files = sorted(
        list(p.glob("*.jpg")) + list(p.glob("*.jpeg")) + list(p.glob("*.png"))
    )
    records = []
    for i, img_file in enumerate(image_files):
        print(f"Processing {img_file.name}...")
        detection = _run_detection(str(img_file))
        record = {"Image_ID": f"IMG_{i+1:03d}", **detection}
        records.append(record)
        print(f"  → {record['Scene_Type']} | {record['Objects_Detected']} | conf: {record['Confidence_Score']}")

    df = pd.DataFrame(records)
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"\nSaved {len(df)} rows to {output_csv}")
    return df

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="images/sample_data/")
    parser.add_argument("--output", default="images/output/image_output.csv")
    args = parser.parse_args()
    process_folder(args.input, args.output)
