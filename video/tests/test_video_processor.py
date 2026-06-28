"""Tests for the video processor."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pytest

cv2 = pytest.importorskip("cv2", reason="OpenCV is required for video processor tests.")
np = pytest.importorskip("numpy", reason="NumPy is required for video processor tests.")

from video import processor  # noqa: E402
from video.processor import (  # noqa: E402
    DRAFT_COLUMNS,
    classify_event,
    event_to_severity,
    format_objects,
    process_video,
    process_video_file,
    process_video_folder,
)


def _make_synthetic_video(path: Path, duration_seconds: int = 4, fps: int = 15) -> None:
    """Write a tiny synthetic video file for testing."""
    width, height = 320, 180
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    total_frames = duration_seconds * fps
    for i in range(total_frames):
        frame = np.full((height, width, 3), 200, dtype=np.uint8)
        x = (i * 6) % width
        cv2.rectangle(frame, (x, 60), (x + 30, 120), (30, 30, 30), -1)
        writer.write(frame)
    writer.release()


class VideoDraftSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.video_path = Path(self._tmpdir.name) / "test_clip.mp4"
        _make_synthetic_video(self.video_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_returns_dataframe_with_exact_draft_columns(self) -> None:
        df = process_video_file(str(self.video_path))
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(list(df.columns), DRAFT_COLUMNS)

    def test_frame_ids_use_required_format(self) -> None:
        df = process_video_file(str(self.video_path))
        self.assertGreaterEqual(len(df), 1)
        for value in df["Frame_ID"]:
            self.assertRegex(str(value), r"^FRM_\d{3}$")

    def test_confidence_is_bounded_float(self) -> None:
        df = process_video_file(str(self.video_path))
        for value in df["Confidence"]:
            self.assertIsInstance(float(value), float)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_no_null_values(self) -> None:
        df = process_video_file(str(self.video_path))
        self.assertFalse(df.isnull().values.any())

    def test_public_video_output_has_five_draft_columns(self) -> None:
        output = Path(self._tmpdir.name) / "video_output.csv"
        frame = process_video(str(self.video_path), output)
        saved = pd.read_csv(output)

        self.assertEqual(list(frame.columns), DRAFT_COLUMNS)
        self.assertEqual(list(saved.columns), DRAFT_COLUMNS)
        self.assertGreaterEqual(len(frame), 1)
        self.assertRegex(str(frame.iloc[0]["Frame_ID"]), r"^FRM_\d{3}$")

    def test_folder_input_combines_supported_videos(self) -> None:
        second_video = Path(self._tmpdir.name) / "second_clip.mp4"
        _make_synthetic_video(second_video)
        output = Path(self._tmpdir.name) / "folder_output.csv"

        frame = process_video_folder(self._tmpdir.name, output)
        saved = pd.read_csv(output)

        self.assertEqual(list(frame.columns), DRAFT_COLUMNS)
        self.assertEqual(list(saved.columns), DRAFT_COLUMNS)
        self.assertEqual(len(saved), len(frame))
        self.assertGreaterEqual(len(frame), 2)

    def test_unreadable_path_returns_empty_dataframe(self) -> None:
        df = process_video_file("nonexistent_video.mp4")
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(list(df.columns), DRAFT_COLUMNS)
        self.assertEqual(len(df), 0)

    def test_video_over_five_minutes_is_rejected(self) -> None:
        long_video = Path(self._tmpdir.name) / "long_clip.mp4"
        _make_synthetic_video(long_video, duration_seconds=301)
        with self.assertRaisesRegex(ValueError, "five-minute MVP limit"):
            process_video_file(str(long_video))


class YoloPerformanceConfigTests(unittest.TestCase):
    def test_yolo_stride_runs_only_on_configured_candidates(self) -> None:
        decisions = [
            processor._should_run_yolo(True, candidate_index, stride=2)
            for candidate_index in range(5)
        ]

        self.assertEqual(decisions, [True, False, True, False, True])
        self.assertFalse(processor._should_run_yolo(False, 0, stride=2))

    def test_run_yolo_uses_configured_image_size(self) -> None:
        class FakeModel:
            names = {}

            def __call__(self, frame, *, verbose, imgsz, iou, device=None):
                self.imgsz = imgsz
                self.verbose = verbose
                self.iou = iou
                self.device = device
                return []

        model = FakeModel()
        frame = np.zeros((180, 320, 3), dtype=np.uint8)

        objects, confidence, collapsed, collapse_confidence, boxes = processor.run_yolo(
            model, frame, imgsz=320, device="cuda"
        )

        self.assertEqual(model.imgsz, 320)
        self.assertFalse(model.verbose)
        self.assertEqual(model.iou, 0.45)
        self.assertEqual(model.device, "cuda")
        self.assertEqual(objects, [])
        self.assertEqual(confidence, 0.0)
        self.assertFalse(collapsed)
        self.assertEqual(collapse_confidence, 0.0)
        self.assertEqual(boxes, [])

    def test_yolo_auto_device_uses_cuda_when_available(self) -> None:
        original = processor._cuda_available
        env_value = os.environ.get("VIDEO_YOLO_DEVICE")
        processor._cuda_available = lambda: True
        os.environ.pop("VIDEO_YOLO_DEVICE", None)
        try:
            self.assertEqual(processor._yolo_device(), "cuda")
        finally:
            processor._cuda_available = original
            if env_value is None:
                os.environ.pop("VIDEO_YOLO_DEVICE", None)
            else:
                os.environ["VIDEO_YOLO_DEVICE"] = env_value

    def test_yolo_cuda_device_falls_back_to_cpu_when_unavailable(self) -> None:
        original = processor._cuda_available
        env_value = os.environ.get("VIDEO_YOLO_DEVICE")
        processor._cuda_available = lambda: False
        os.environ["VIDEO_YOLO_DEVICE"] = "cuda"
        try:
            self.assertEqual(processor._yolo_device(), "cpu")
        finally:
            processor._cuda_available = original
            if env_value is None:
                os.environ.pop("VIDEO_YOLO_DEVICE", None)
            else:
                os.environ["VIDEO_YOLO_DEVICE"] = env_value

    def test_default_yolo_model_uses_onnx_asset(self) -> None:
        self.assertTrue(processor._DEFAULT_YOLO_MODEL_PATH.endswith(".onnx"))

    def test_onnx_model_uses_static_640_image_size(self) -> None:
        env_value = os.environ.get("VIDEO_YOLO_IMAGE_SIZE")
        os.environ["VIDEO_YOLO_IMAGE_SIZE"] = "320"
        try:
            self.assertEqual(processor._yolo_image_size("video/yolov8s.onnx"), 640)
        finally:
            if env_value is None:
                os.environ.pop("VIDEO_YOLO_IMAGE_SIZE", None)
            else:
                os.environ["VIDEO_YOLO_IMAGE_SIZE"] = env_value


class ClassifyEventTests(unittest.TestCase):
    def test_altercation_with_high_motion(self) -> None:
        event, conf = classify_event(0.15, ["person", "person"], 2)
        self.assertEqual(event, "Possible altercation")
        self.assertGreater(conf, 0.5)

    def test_multiple_persons_low_motion(self) -> None:
        event, conf = classify_event(0.01, [], 2)
        self.assertEqual(event, "Multiple persons present")

    def test_person_running(self) -> None:
        event, conf = classify_event(0.20, ["person"], 1)
        self.assertEqual(event, "Person running")

    def test_person_walking(self) -> None:
        event, conf = classify_event(0.08, ["person"], 1)
        self.assertEqual(event, "Person walking")

    def test_no_activity(self) -> None:
        event, conf = classify_event(0.0, [], 0)
        self.assertEqual(event, "No activity")

    def test_yolo_ran_but_found_nothing(self) -> None:
        event, conf = classify_event(0.05, [], 0, yolo_ran=True)
        self.assertEqual(event, "Unclear motion detected")

    def test_motion_detected_without_yolo(self) -> None:
        event, conf = classify_event(0.05, [], 0, yolo_ran=False)
        self.assertEqual(event, "Motion detected")

    def test_confidence_is_bounded(self) -> None:
        for score in [0.0, 0.05, 0.15, 0.30, 0.50]:
            for moving in [0, 1, 2, 3]:
                _, conf = classify_event(score, [], moving)
                self.assertGreaterEqual(conf, 0.0)
                self.assertLessEqual(conf, 1.0)


class SeverityMappingTests(unittest.TestCase):
    def test_fire_is_high(self) -> None:
        self.assertEqual(event_to_severity("Fire detected"), "High")

    def test_altercation_is_high(self) -> None:
        self.assertEqual(event_to_severity("Possible altercation"), "High")

    def test_collapsing_is_high(self) -> None:
        self.assertEqual(event_to_severity("Person collapsing"), "High")

    def test_running_is_medium(self) -> None:
        self.assertEqual(event_to_severity("Person running"), "Medium")

    def test_multiple_persons_is_medium(self) -> None:
        self.assertEqual(event_to_severity("Multiple persons detected"), "Medium")

    def test_walking_is_low(self) -> None:
        self.assertEqual(event_to_severity("Person walking"), "Low")

    def test_no_activity_is_unknown(self) -> None:
        self.assertEqual(event_to_severity("No activity"), "Unknown")


class FormatObjectsTests(unittest.TestCase):
    def test_single_person(self) -> None:
        self.assertEqual(format_objects(["person"]), "1 person")

    def test_multiple_persons(self) -> None:
        self.assertEqual(format_objects(["person", "person"]), "2 persons")

    def test_motion_regions_fallback(self) -> None:
        self.assertEqual(format_objects([], moving_regions=3), "3 motion regions")

    def test_none_detected(self) -> None:
        self.assertEqual(format_objects([]), "none detected")


if __name__ == "__main__":
    unittest.main()
