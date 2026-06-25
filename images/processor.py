# images/processor.py
import pytesseract
import pandas as pd
import argparse
import cv2
import requests
from pathlib import Path
from inference_sdk import InferenceHTTPClient

CLIENT = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="MeVt1zw9wmCsXsAspmAt"
)

MODEL_ID = "fire-detection-data-pre/4"

def classify_scene(labels: list[str]) -> str:
    labels_lower = [l.lower() for l in labels]
    if "fire" in labels_lower and "smoke" in labels_lower:
        return "Fire Scene"
    elif "fire" in labels_lower:
        return "Fire Scene"
    elif "smoke" in labels_lower:
        return "Smoke Scene"
    elif "person" in labels_lower:
        return "General Scene"
    return "General Scene"

def process_image(img_path: str, image_id: str) -> dict:
    # Run Roboflow inference
    result = CLIENT.infer(img_path, model_id=MODEL_ID)

    predictions = result.get("predictions", [])
    labels = [p["class"] for p in predictions]
    confs  = [p["confidence"] for p in predictions]

    avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.5
    top_conf = round(max(confs), 2)              if confs else 0.5

    # OCR
    img = cv2.imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ocr_text = pytesseract.image_to_string(gray).strip().replace("\n", " ")

    return {
        "Image_ID":          image_id,
        "Scene_Type":        classify_scene(labels),
        "Objects_Detected":  ", ".join(sorted(set(labels))) if labels else "None",
        "Text_Extracted":    ocr_text if ocr_text else "N/A",
        "Confidence_Score":  top_conf,
    }

def process_folder(input_path: str, output_csv: str):
    p = Path(input_path)
    image_files = sorted(
        list(p.glob("*.jpg")) + list(p.glob("*.jpeg")) + list(p.glob("*.png"))
    )
    records = []
    for i, img_file in enumerate(image_files):
        print(f"Processing {img_file.name}...")
        record = process_image(str(img_file), f"IMG_{i+1:03d}")
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
