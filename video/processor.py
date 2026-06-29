"""Video processor for the Multimodal Incident Analyzer group pipeline.

Public output columns
---------------------
Timestamp, Frame_ID, Event_Detected, Objects, Confidence
"""

from __future__ import annotations

import argparse
import logging
import math
import os
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import cv2
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


DRAFT_COLUMNS = [
    "Timestamp",
    "Frame_ID",
    "Event_Detected",
    "Objects",
    "Confidence",
]
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "video_output.csv"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mpg", ".mpeg"}
_SAMPLE_SECONDS = 0.5
_MAX_DURATION_SECONDS = 300  # reject clips longer than 5 minutes
_DEFAULT_YOLO_IMAGE_SIZE = 640
_DEFAULT_YOLO_SAMPLE_STRIDE = 4
_DEFAULT_YOLO_MODEL_PATH = "video/yolov8s.onnx"
_ONNX_YOLO_IMAGE_SIZE = 640

PERSON_CONF_THRESHOLD = 0.15
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle"}
VEHICLE_CONF_THRESHOLD = 0.40


class VideoProcessingSettings(NamedTuple):
    fps: float
    sample_every_frames: int
    yolo_sample_stride: int
    yolo_imgsz: int
    yolo_device: str | None


class YoloFrameResult(NamedTuple):
    objects: List[str]
    confidence: float
    collapsed: bool
    collapse_confidence: float
    boxes: List[Tuple]


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return max(minimum, value)


def _yolo_model_path() -> str:
    return (
        os.getenv("VIDEO_YOLO_MODEL_PATH", _DEFAULT_YOLO_MODEL_PATH).strip()
        or _DEFAULT_YOLO_MODEL_PATH
    )


def _yolo_image_size(model_path: str | Path | None = None) -> int:
    size = _env_int("VIDEO_YOLO_IMAGE_SIZE", _DEFAULT_YOLO_IMAGE_SIZE, minimum=320)
    path = Path(model_path or _yolo_model_path())
    if path.suffix.lower() == ".onnx":
        return _ONNX_YOLO_IMAGE_SIZE
    return size


def _yolo_sample_stride() -> int:
    return _env_int("VIDEO_YOLO_SAMPLE_STRIDE", _DEFAULT_YOLO_SAMPLE_STRIDE, minimum=1)


def _cuda_available() -> bool:
    try:
        import torch
    except (ImportError, OSError) as exc:
        logger.info("PyTorch unavailable for CUDA detection: %s", exc)
        return False
    return bool(torch.cuda.is_available())


def _yolo_device() -> str | None:
    requested = os.getenv("VIDEO_YOLO_DEVICE", "auto").strip() or "auto"
    normalized = requested.lower()
    if normalized == "auto":
        return "cuda" if _cuda_available() else None
    if normalized.startswith("cuda") and not _cuda_available():
        return "cpu"
    return requested


def _should_run_yolo(eligible: bool, candidate_index: int, stride: int) -> bool:
    return eligible and candidate_index % max(1, stride) == 0


def load_yolo_model(model_path: str | Path | None = None):
    try:
        from ultralytics import YOLO

        return YOLO(str(model_path or _yolo_model_path()), task="detect")
    except Exception as exc:  # noqa: BLE001
        logger.warning("YOLO model could not be loaded; using video fallbacks: %s", exc)
        return None


def enhance_frame(frame):
    denoised = cv2.GaussianBlur(frame, (3, 3), 0)
    lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = cv2.merge([clahe.apply(lightness), a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


def run_yolo(model, frame, *, imgsz: int | None = None, device: str | None = None):
    """Run YOLO once and return detection metadata."""
    if model is None:
        return [], 0.0, False, 0.0, []

    options = {"verbose": False, "imgsz": imgsz or _yolo_image_size(), "iou": 0.45}
    if device:
        options["device"] = device
    results = model(frame, **options)
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

    lower1 = np.array([0, 120, 120])
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
    has_vehicle = any(obj in objects for obj in VEHICLE_CLASSES)
    effective_persons = person_count if person_count > 0 else moving_regions
    rules = (
        (effective_persons >= 2 and score >= 0.12, "Possible altercation", 0.95, 0.72),
        (
            effective_persons >= 2 and score >= 0.03,
            "Multiple persons detected",
            0.88,
            0.60,
        ),
        (effective_persons >= 2, "Multiple persons present", 0.82, 0.55),
        (effective_persons == 1 and score >= 0.15, "Person running", 0.92, 0.68),
        (effective_persons == 1 and score >= 0.05, "Person walking", 0.88, 0.58),
        (effective_persons == 1, "Person standing", 0.80, 0.50),
        (has_vehicle and score >= 0.05, "Vehicle movement", 0.90, 0.60),
        (score >= 0.18, "High motion anomaly", 0.85, 0.60),
    )
    for matched, event, cap, base in rules:
        if matched:
            return event, min(cap, base + score)
    if has_vehicle:
        return "Vehicle present", 0.55
    if score >= 0.02:
        if yolo_ran:
            return "Unclear motion detected", min(0.65, 0.40 + score)
        return "Motion detected", min(0.70, 0.45 + score)
    return "No activity", 0.30


def event_to_severity(event: str) -> str:
    event_lower = event.lower()
    if any(
        k in event_lower for k in ["fire", "collapsing", "altercation", "high motion"]
    ):
        return "High"
    if any(
        k in event_lower
        for k in ["running", "multiple persons", "unclear motion", "vehicle movement"]
    ):
        return "Medium"
    return "Unknown" if event_lower == "no activity" else "Low"


def save_annotated_frame(
    filtered_boxes: List[Tuple],
    motion_boxes: List[Tuple],
    frame,
    event: str,
    confidence: float,
    output_dir: Optional[Path],
    clip_id: str,
    frame_id: str,
) -> Optional[str]:
    """Save an annotated frame and return its path."""
    if output_dir is None:
        return None

    annotated = frame.copy()

    if filtered_boxes:
        for x1, y1, x2, y2, label, conf in filtered_boxes:
            color = (0, 140, 255) if label == "person" else (255, 200, 0)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            box_label = f"{label} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(box_label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(
                annotated,
                box_label,
                (x1 + 2, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
            )
    else:
        for x1, y1, x2, y2 in motion_boxes:
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 220, 220), 2)
            cv2.putText(
                annotated,
                "motion region",
                (x1 + 2, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 220, 220),
                1,
            )

    banner = f"{event}  ({confidence:.2f})"
    (tw, th), _ = cv2.getTextSize(banner, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
    cv2.rectangle(annotated, (8, 8), (14 + tw, 22 + th), (0, 0, 0), -1)
    cv2.putText(
        annotated, banner, (10, 10 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2
    )

    out_dir = output_dir / clip_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{frame_id}.jpg"
    cv2.imwrite(str(out_path), annotated)
    return str(out_path)


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _video_processing_settings(cap) -> VideoProcessingSettings:
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or math.isnan(fps) or fps <= 0:
        fps = 25.0

    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if total_frames / fps > _MAX_DURATION_SECONDS:
        raise ValueError("Video exceeds the five-minute MVP limit.")

    return VideoProcessingSettings(
        fps=fps,
        sample_every_frames=max(1, int(round(fps * _SAMPLE_SECONDS))),
        yolo_sample_stride=_yolo_sample_stride(),
        yolo_imgsz=_yolo_image_size(),
        yolo_device=_yolo_device(),
    )


def _empty_yolo_result() -> YoloFrameResult:
    return YoloFrameResult([], 0.0, False, 0.0, [])


def _run_yolo_for_sample(
    model,
    enhanced,
    *,
    run_now: bool,
    settings: VideoProcessingSettings,
) -> YoloFrameResult:
    if not run_now:
        return _empty_yolo_result()
    return YoloFrameResult(
        *run_yolo(
            model,
            enhanced,
            imgsz=settings.yolo_imgsz,
            device=settings.yolo_device,
        )
    )


def _motion_collapse_fallback(motion_boxes: List[Tuple]) -> tuple[bool, float]:
    for mx1, my1, mx2, my2 in motion_boxes:
        mw, mh = mx2 - mx1, my2 - my1
        if mh > 0 and (mw / mh) > 2.0 and mw > 60:
            return True, round(min(0.72, 0.40 + (mw / mh) * 0.06), 2)
    return False, 0.0


def _collapse_with_motion_fallback(
    yolo_result: YoloFrameResult,
    motion_boxes: List[Tuple],
) -> tuple[bool, float]:
    if yolo_result.collapsed or "person" in yolo_result.objects:
        return yolo_result.collapsed, yolo_result.collapse_confidence
    return _motion_collapse_fallback(motion_boxes)


def _frame_event(
    *,
    fire_detected: bool,
    fire_confidence: float,
    collapsed: bool,
    collapse_confidence: float,
    yolo_result: YoloFrameResult,
    score: float,
    moving_regions: int,
    yolo_ran: bool,
) -> tuple[str, float]:
    if fire_detected:
        return "Fire detected", fire_confidence
    if collapsed:
        return "Person collapsing", max(collapse_confidence, yolo_result.confidence)
    event, event_confidence = classify_event(
        score, yolo_result.objects, moving_regions, yolo_ran
    )
    return event, max(event_confidence, yolo_result.confidence)


def _video_row(
    *,
    frame_index: int,
    fps: float,
    event: str,
    objects: List[str],
    moving_regions: int,
    confidence: float,
) -> dict[str, object]:
    return {
        "Timestamp": format_timestamp(frame_index / fps),
        "Frame_ID": f"FRM_{frame_index:03d}",
        "Event_Detected": event,
        "Objects": format_objects(objects, moving_regions),
        "Confidence": round(float(confidence), 2),
    }


def _process_sampled_video_frame(
    *,
    frame,
    frame_index: int,
    path: Path,
    model,
    mog2,
    settings: VideoProcessingSettings,
    yolo_candidate_index: int,
    annotated_frames_dir: Optional[Path],
) -> tuple[tuple[dict[str, object], Optional[str]] | None, int]:
    resized = cv2.resize(frame, (640, 360))
    fgmask = mog2.apply(resized)
    score, moving_regions, motion_boxes = apply_mog2(fgmask)
    fire_detected, fire_confidence = detect_fire(resized)
    qualifies_for_detection = moving_regions > 0 and score >= 0.02
    if not qualifies_for_detection and not fire_detected:
        return None, yolo_candidate_index

    enhanced = enhance_frame(resized)
    yolo_eligible = qualifies_for_detection and not fire_detected
    run_yolo_now = _should_run_yolo(
        yolo_eligible, yolo_candidate_index, settings.yolo_sample_stride
    )
    yolo_candidate_index += int(yolo_eligible)
    yolo_result = _run_yolo_for_sample(
        model, enhanced, run_now=run_yolo_now, settings=settings
    )
    collapsed, collapse_confidence = _collapse_with_motion_fallback(
        yolo_result, motion_boxes
    )
    event, confidence = _frame_event(
        fire_detected=fire_detected,
        fire_confidence=fire_confidence,
        collapsed=collapsed,
        collapse_confidence=collapse_confidence,
        yolo_result=yolo_result,
        score=score,
        moving_regions=moving_regions,
        yolo_ran=run_yolo_now and model is not None,
    )
    frame_id = f"FRM_{frame_index:03d}"
    frame_path = save_annotated_frame(
        yolo_result.boxes,
        motion_boxes,
        enhanced,
        event,
        round(float(confidence), 2),
        annotated_frames_dir,
        path.stem,
        frame_id,
    )
    return (
        _video_row(
            frame_index=frame_index,
            fps=settings.fps,
            event=event,
            objects=yolo_result.objects,
            moving_regions=moving_regions,
            confidence=confidence,
        ),
        frame_path,
    ), yolo_candidate_index


def _iter_processed_video_frames(
    video_path: str,
    annotated_frames_dir: Optional[Path] = None,
):
    """Yield processed video draft rows and optional annotated frame paths."""

    path = Path(video_path)
    model = load_yolo_model()

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return

    settings = _video_processing_settings(cap)
    mog2 = cv2.createBackgroundSubtractorMOG2(
        history=100, varThreshold=25, detectShadows=False
    )
    frame_index = 0
    yolo_candidate_index = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % settings.sample_every_frames == 0:
                processed, yolo_candidate_index = _process_sampled_video_frame(
                    frame=frame,
                    frame_index=frame_index,
                    path=path,
                    model=model,
                    mog2=mog2,
                    settings=settings,
                    yolo_candidate_index=yolo_candidate_index,
                    annotated_frames_dir=annotated_frames_dir,
                )
                if processed is not None:
                    yield processed

            frame_index += 1
    finally:
        cap.release()


def process_video_file(
    video_path: str,
    annotated_frames_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Analyze one video file and return the five-column video draft.

    Rejects clips longer than 5 minutes with a clear ``ValueError``. Returns an
    empty DataFrame with ``DRAFT_COLUMNS`` only when the file cannot be read.

    Args:
        video_path: Path to the video file.
        annotated_frames_dir: If provided, save annotated JPEG frames to this
            directory (one sub-folder per clip). Default None (no frames saved).
    """

    extractor_rows = [
        row
        for row, _frame_path in _iter_processed_video_frames(
            video_path, annotated_frames_dir
        )
    ]
    return pd.DataFrame(extractor_rows, columns=DRAFT_COLUMNS)


def process_video_stream(
    video_path: str,
    annotated_frames_dir: Optional[Path] = None,
):
    """Generator version of process_video_file.

    Yields (row_dict, frame_path_or_None) for each sampled frame as it is
    processed, so callers can update the UI progressively without waiting for
    the full video to finish.
    """
    yield from _iter_processed_video_frames(video_path, annotated_frames_dir)


def process_video(
    video_path: str | Path,
    output_csv_path: str | Path = DEFAULT_OUTPUT_PATH,
    annotated_frames_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Analyze one video and return the five-column video draft contract."""

    frame = process_video_file(
        str(video_path), annotated_frames_dir=annotated_frames_dir
    )
    output = Path(output_csv_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    return frame


def process_video_folder(
    folder_path: str | Path,
    output_csv_path: str | Path = DEFAULT_OUTPUT_PATH,
    annotated_frames_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Analyze all supported top-level videos in a folder and save one CSV."""

    folder = Path(folder_path).expanduser()
    if not folder.is_dir():
        raise NotADirectoryError(f"Video folder not found: {folder}")

    video_files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not video_files:
        supported = ", ".join(sorted(VIDEO_EXTENSIONS))
        raise ValueError(
            f"No supported video files found in {folder}. Expected: {supported}"
        )

    frames = [
        process_video_file(str(path), annotated_frames_dir=annotated_frames_dir)
        for path in video_files
    ]
    frame = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=DRAFT_COLUMNS)
    )
    output = Path(output_csv_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    return frame


def main(argv: list[str] | None = None) -> int:
    """Run the video processor for one evidence file or folder from the command line."""

    parser = argparse.ArgumentParser(description="Analyze video evidence.")
    parser.add_argument(
        "--input", required=True, help="A supported video file or folder of videos"
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT_PATH), help="Destination CSV path"
    )
    parser.add_argument(
        "--annotated-frames-dir",
        default=None,
        help="Optional directory for annotated sampled frames",
    )
    args = parser.parse_args(argv)
    input_path = Path(args.input).expanduser()

    annotated_frames_dir = (
        Path(args.annotated_frames_dir).expanduser()
        if args.annotated_frames_dir
        else None
    )
    try:
        if input_path.is_file():
            frame = process_video(input_path, args.output, annotated_frames_dir)
        elif input_path.is_dir():
            frame = process_video_folder(input_path, args.output, annotated_frames_dir)
        else:
            parser.error(f"Input path does not exist: {input_path}")
    except (NotADirectoryError, ValueError) as exc:
        parser.error(str(exc))

    print(frame.to_string(index=False))
    print(f"Saved {len(frame)} row(s) to {Path(args.output).expanduser()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DRAFT_COLUMNS",
    "process_video",
    "process_video_file",
    "process_video_folder",
    "process_video_stream",
]
