"""Local speech-to-text support using OpenAI Whisper (not the OpenAI API)."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
from typing import Any

from .config import WHISPER_MODEL


def _clean_transcript(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


@lru_cache(maxsize=2)
def _load_whisper(model_name: str, device: str, download_root: str | None) -> Any:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Audio transcription requires openai-whisper. "
            "Install dependencies with: python -m pip install -r requirements.txt"
        ) from exc

    options: dict[str, Any] = {"device": device}
    if download_root:
        options["download_root"] = download_root
    return whisper.load_model(model_name, **options)


def transcribe_audio(audio_path: str, model_name: str | None = None) -> str:
    """Transcribe one supported audio file locally and return normalized text."""

    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "Whisper requires FFmpeg. Install it first (for example: brew install ffmpeg)."
        )

    selected_model = model_name or os.getenv("WHISPER_MODEL", WHISPER_MODEL)
    device = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
    language = os.getenv("WHISPER_LANGUAGE", "en").strip() or None
    download_root = os.getenv("WHISPER_MODEL_DIR", "").strip() or None
    model = _load_whisper(selected_model, device, download_root)
    result = model.transcribe(
        str(path),
        task="transcribe",
        language=language,
        fp16=device.startswith("cuda"),
        verbose=False,
    )
    transcript = _clean_transcript(result.get("text") if isinstance(result, dict) else result)
    if not transcript:
        raise RuntimeError(f"Whisper returned an empty transcript for: {path}")
    return transcript


__all__ = ["transcribe_audio"]
