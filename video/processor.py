"""Video processor for the Multimodal Incident Analyzer group pipeline.

Public interface
----------------
process_video_file(video_path: str) -> pd.DataFrame   # returns EXTRACTOR_COLUMNS schema
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pandas as pd


SOURCE_TYPE = "VID"
EXTRACTOR_COLUMNS = [
    "source_filename",
    "source_type",
    "raw_event",
    "raw_location",
    "raw_time",
    "raw_severity",
    "confidence",
    "raw_text",
]

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg", ".wmv"}
_SAMPLE_SECONDS = 0.5
_MAX_DURATION_SECONDS = 300  # reject clips longer than 5 minutes

PERSON_CONF_THRESHOLD = 0.15
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle"}
VEHICLE_CONF_THRESHOLD = 0.40


def load_yolo_model():
    try:
        from ultralytics import YOLO
        return YOLO("yolov8s.pt")
    except Exception:
        return None


def enhance_frame(frame):
    denoised = cv2.GaussianBlur(frame, (3, 3), 0)
    lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = cv2.merge([clahe.apply(l), a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


def run_yolo(model, frame):
    """Run YOLO once and return objects, max confidence, collapse flag, and filtered boxes for annotation."""
    if model is None:
        return [], 0.0, False, 0.0, []

    results = model(frame, verbose=False, imgsz=1280, iou=0.45)
    objects: List[str] = []
    max_confidence = 0.0
    collapsed = False
    collapse_confidence = 0.0
    filtered_boxes: List[Tuple] = []  # (x1, y1, x2, y2, label, confidence)

    for result in results:
        for box in result.boxes:
            class_id = int(box.cls[0])
            label = model.names[class_id]
            confidence = float(box.conf[0])
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]

            if label == "person" and confidence >= PERSON_CONF_THRESHOLD:
                objects.append(label)
                max_confidence = max(max_confidence, confidence)
                filtered_boxes.append((x1, y1, x2, y2, label, confidence))
                w, h = x2 - x1, y2 - y1
                if h > 0 and (w / h) > 2.0:
                    collapsed = True
                    collapse_confidence = round(min(0.95, 0.55 + (w / h) * 0.08), 2)
            elif label in VEHICLE_CLASSES and confidence >= VEHICLE_CONF_THRESHOLD:
                objects.append(label)
                max_confidence = max(max_confidence, confidence)
                filtered_boxes.append((x1, y1, x2, y2, label, confidence))

    return objects, max_confidence, collapsed, collapse_confidence, filtered_boxes


def format_objects(objects: List[str], moving_regions: int = 0) -> str:
    if objects:
        counts: Dict[str, int] = {}
        for obj in objects:
            counts[obj] = counts.get(obj, 0) + 1
        parts = []
        for label, count in sorted(counts.items()):
            noun = label + "s" if count > 1 else label
            parts.append(f"{count} {noun}")
        return ", ".join(parts)
    if moving_regions > 0:
        noun = "motion regions" if moving_regions > 1 else "motion region"
        return f"{moving_regions} {noun}"
    return "none detected"


def apply_mog2(fgmask) -> Tuple[float, int, List[Tuple]]:
    total = fgmask.shape[0] * fgmask.shape[1]
    score = cv2.countNonZero(fgmask) / total

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    motion_boxes: List[Tuple] = []
    for c in contours:
        if cv2.contourArea(c) > 500:
            x, y, w, h = cv2.boundingRect(c)
            motion_boxes.append((x, y, x + w, y + h))

    return score, len(motion_boxes), motion_boxes


def detect_fire(frame) -> Tuple[bool, float]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    lower1 = np.array([0,  120, 120])
    upper1 = np.array([20, 255, 255])
    lower2 = np.array([160, 120, 120])
    upper2 = np.array([180, 255, 255])

    mask1 = cv2.inRange(hsv, lower1, upper1)
    mask2 = cv2.inRange(hsv, lower2, upper2)
    fire_mask = cv2.bitwise_or(mask1, mask2)

    total = frame.shape[0] * frame.shape[1]
    fire_ratio = cv2.countNonZero(fire_mask) / total

    if fire_ratio > 0.05:
        return True, round(min(0.95, 0.50 + fire_ratio * 4), 2)
    return False, 0.0


def classify_event(
    score: float, objects: List[str], moving_regions: int, yolo_ran: bool = False
) -> Tuple[str, float]:
    person_count = objects.count("person")
    has_vehicle = any(obj in objects for obj in ["car", "truck", "bus", "motorcycle", "bicycle"])

    effective_persons = person_count if person_count > 0 else moving_regions

    if effective_persons >= 2 and score >= 0.12:
        return "Possible altercation", min(0.95, 0.72 + score)
    if effective_persons >= 2 and score >= 0.03:
        return "Multiple persons detected", min(0.88, 0.60 + score)
    if effective_persons >= 2:
        return "Multiple persons present", min(0.82, 0.55 + score)
    if effective_persons == 1 and score >= 0.15:
        return "Person running", min(0.92, 0.68 + score)
    if effective_persons == 1 and score >= 0.05:
        return "Person walking", min(0.88, 0.58 + score)
    if effective_persons == 1:
        return "Person standing", min(0.80, 0.50 + score)
    if has_vehicle and score >= 0.05:
        return "Vehicle movement", min(0.90, 0.60 + score)
    if has_vehicle:
        return "Vehicle present", 0.55
    if score >= 0.18:
        return "High motion anomaly", min(0.85, 0.60 + score)
    if score >= 0.02:
        if yolo_ran:
            return "Unclear motion detected", min(0.65, 0.40 + score)
        return "Motion detected", min(0.70, 0.45 + score)
    return "No activity", 0.30


def event_to_severity(event: str) -> str:
    event_lower = event.lower()
    if any(k in event_lower for k in ["fire", "collapsing", "altercation", "high motion"]):
        return "High"
    if any(k in event_lower for k in ["running", "multiple persons", "unclear motion", "vehicle movement"]):
        return "Medium"
    return "Low"


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def process_video_file(video_path: str) -> pd.DataFrame:
    """Analyze one video file and return an extractor DataFrame.

    Rejects clips longer than 5 minutes. Returns an empty DataFrame with
    EXTRACTOR_COLUMNS if the file cannot be read or exceeds the time limit.
    """
    path = Path(video_path)
    model = load_yolo_model()

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return pd.DataFrame(columns=EXTRACTOR_COLUMNS)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or math.isnan(fps) or fps <= 0:
        fps = 25.0

    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if total_frames / fps > _MAX_DURATION_SECONDS:
        cap.release()
        return pd.DataFrame(columns=EXTRACTOR_COLUMNS)

    sample_every_frames = max(1, int(round(fps * _SAMPLE_SECONDS)))
    mog2 = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=25, detectShadows=False)
    frame_index = 0
    extractor_rows = []

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        resized = cv2.resize(frame, (640, 360))
        fgmask = mog2.apply(resized)

        if frame_index % sample_every_frames == 0:
            score, moving_regions, motion_boxes = apply_mog2(fgmask)
            enhanced = enhance_frame(resized)
            objects, yolo_confidence, collapsed, collapse_confidence, _ = run_yolo(model, enhanced)

            # MOG2 collapse fallback: overhead cameras make lying people invisible to YOLO
            if not collapsed and "person" not in objects:
                for (mx1, my1, mx2, my2) in motion_boxes:
                    mw, mh = mx2 - mx1, my2 - my1
                    if mh > 0 and (mw / mh) > 2.0 and mw > 60:
                        collapsed = True
                        collapse_confidence = round(min(0.72, 0.40 + (mw / mh) * 0.06), 2)
                        break

            yolo_ran = model is not None
            fire_detected, fire_confidence = detect_fire(resized)

            if fire_detected:
                event, confidence = "Fire detected", fire_confidence
            elif collapsed:
                event, confidence = "Person collapsing", max(collapse_confidence, yolo_confidence)
            else:
                event, event_confidence = classify_event(score, objects, moving_regions, yolo_ran)
                confidence = max(event_confidence, yolo_confidence)

            timestamp = format_timestamp(frame_index / fps)
            objects_str = format_objects(objects, moving_regions)
            raw_text = f"Event: {event}. Objects detected: {objects_str}. Timestamp: {timestamp}."

            extractor_rows.append({
                "source_filename": path.name,
                "source_type":     SOURCE_TYPE,
                "raw_event":       event,
                "raw_location":    "Unknown",
                "raw_time":        timestamp,
                "raw_severity":    event_to_severity(event),
                "confidence":      round(float(confidence), 2),
                "raw_text":        raw_text,
            })

        frame_index += 1

    cap.release()
    return pd.DataFrame(extractor_rows, columns=EXTRACTOR_COLUMNS)


__all__ = ["process_video_file", "EXTRACTOR_COLUMNS", "SOURCE_TYPE"]
