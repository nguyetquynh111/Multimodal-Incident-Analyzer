# images/processor.py
import pytesseract
import pandas as pd
import argparse
import cv2
from pathlib import Path
from inference_sdk import InferenceHTTPClient

CLIENT = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="MeVt1zw9wmCsXsAspmAt"
)

MODEL_ID  = "fire-detection-data-pre/4"
MODEL_ID2 = "yolov8n-640"

def classify_scene(labels: list) -> str:
    labels_lower = [l.lower() for l in labels]
    if "fire" in labels_lower and "person" in labels_lower:
        return "Fire and Smoke Scene"
    elif "fire" in labels_lower and "smoke" in labels_lower:
        return "Fire and Smoke Scene"
    elif "fire" in labels_lower:
        return "Fire Scene"
    elif "smoke" in labels_lower:
        return "Smoke Scene"
    elif "person" in labels_lower:
        return "General Scene"
    return "General Scene"

def _run_detection(img_path: str) -> dict:
    """Run fire + person detection and OCR on one image file."""
    try:
        result1 = CLIENT.infer(img_path, model_id=MODEL_ID)
        preds1 = result1.get("predictions", [])
    except Exception:
        preds1 = []

    try:
        result2 = CLIENT.infer(img_path, model_id=MODEL_ID2)
        preds2 = [p for p in result2.get("predictions", []) if p["class"] == "person"]
    except Exception:
        preds2 = []

    all_preds = preds1 + preds2
    labels = [p["class"] for p in all_preds]
    confs  = [round(p["confidence"], 2) for p in all_preds]
    avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.50

    try:
        img = cv2.imread(str(img_path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ocr_text = pytesseract.image_to_string(gray).strip().replace("\n", " ")
        ocr_clean = ocr_text if len(ocr_text) > 3 else "N/A"
    except Exception:
        ocr_clean = "N/A"

    return {
        "Scene_Type":       classify_scene(labels),
        "Objects_Detected": ", ".join(sorted(set(labels))) if labels else "None",
        "Text_Extracted":   ocr_clean,
        "Confidence_Score": avg_conf,
    }

def process_image(input_path, output_csv=None) -> pd.DataFrame:
    """Entry point called by integration.py for a single image file."""
    img_path = str(input_path)
    detection = _run_detection(img_path)
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
