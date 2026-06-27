"""Configuration shared by the emergency-audio processing pipeline."""

from __future__ import annotations

import os


OUTPUT_COLUMNS = [
    "Call_ID",
    "Transcript",
    "Extracted_Event",
    "Location",
    "Sentiment",
    "Urgency_Score",
]

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}
UNKNOWN = "Unknown"

DEFAULT_WHISPER_MODEL = "small.en"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", DEFAULT_WHISPER_MODEL)
LOCATION_LABELS = {"street address", "location", "building", "floor", "city"}
