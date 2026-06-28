"""Local speech-to-text support using OpenAI Whisper (not the OpenAI API)."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from functools import lru_cache
from io import StringIO
import os
from pathlib import Path
import re
import shutil
from typing import Any

from .config import WHISPER_MODEL


def _clean_transcript(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return max(minimum, value)


def _transcribe_options(device: str, language: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "task": "transcribe",
        "language": language,
        "fp16": device.startswith("cuda"),
        "verbose": False,
        "temperature": 0,
        "beam_size": _env_int("WHISPER_BEAM_SIZE", 5, minimum=1),
        "condition_on_previous_text": False,
    }
    return options


def _cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    return bool(torch.cuda.is_available())


def _resolve_device(configured_device: str | None) -> str:
    requested = (configured_device or "auto").strip() or "auto"
    normalized = requested.lower()
    if normalized == "auto":
        return "cuda" if _cuda_available() else "cpu"
    if normalized.startswith("cuda") and not _cuda_available():
        return "cpu"
    return requested


def _selected_whisper_settings(
    model_name: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    selected_model = model_name or os.getenv("WHISPER_MODEL", WHISPER_MODEL)
    device = _resolve_device(os.getenv("WHISPER_DEVICE", "auto"))
    language = os.getenv("WHISPER_LANGUAGE", "en").strip() or None
    download_root = os.getenv("WHISPER_MODEL_DIR", "").strip() or None
    return selected_model, device, language, download_root


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


def preload_whisper_model(model_name: str | None = None, *, quiet: bool = True) -> None:
    """Download/load the configured Whisper model ahead of the first audio file."""

    selected_model, device, _language, download_root = _selected_whisper_settings(
        model_name
    )
    if quiet:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            _load_whisper(selected_model, device, download_root)
        return
    _load_whisper(selected_model, device, download_root)


def transcribe_audio(audio_path: str, model_name: str | None = None) -> str:
    """Transcribe one supported audio file locally and return normalized text."""

    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "Whisper requires FFmpeg. Install it first (for example: brew install ffmpeg)."
        )

    selected_model, device, language, download_root = _selected_whisper_settings(
        model_name
    )
    model = _load_whisper(selected_model, device, download_root)
    result = model.transcribe(str(path), **_transcribe_options(device, language))
    transcript = _clean_transcript(
        result.get("text") if isinstance(result, dict) else result
    )
    if not transcript:
        raise RuntimeError(f"Whisper returned an empty transcript for: {path}")
    return transcript


__all__ = ["preload_whisper_model", "transcribe_audio"]
