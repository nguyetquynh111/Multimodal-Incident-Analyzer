"""Audio extraction for the Multimodal Incident Analyzer.

The public ``process_audio`` function accepts a path or an uploaded file,
transcribes it with a local Wav2Vec2 model, and returns the extractor DataFrame
contract shared by all modalities.  Model imports are lazy so schema validation
and rule extraction remain usable when the optional audio stack is unavailable.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, BinaryIO, Callable, Iterator, Mapping
import wave

import pandas as pd


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
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}
DEFAULT_ASR_MODEL = "facebook/wav2vec2-base-960h"
UNKNOWN = "Unknown"


@dataclass(frozen=True)
class TranscriptionResult:
    """Normalized output from any supported transcription callable."""

    text: str
    confidence: float = 0.0


@dataclass(frozen=True)
class EventRule:
    label: str
    severity: str
    patterns: tuple[str, ...]


EVENT_RULES = (
    EventRule("Fire", "High", (r"\bfire\b", r"\bflames?\b", r"\bsmoke\b")),
    EventRule(
        "Weapon-related incident",
        "High",
        (r"\bgun\b", r"\bweapon\b", r"\bshots? fired\b", r"\bshoot(?:ing|er)?\b", r"\bstabb(?:ing|ed)\b"),
    ),
    EventRule("Person trapped", "High", (r"\btrapped\b", r"\bcan(?:not|'t) get out\b")),
    EventRule("Structural collapse", "High", (r"\bcollapse(?:d)?\b", r"\bcave[ -]?in\b")),
    EventRule("Physical fight", "High", (r"\bfight(?:ing)?\b", r"\bphysical altercation\b", r"\bassault\b")),
    EventRule(
        "Severe vehicle crash",
        "High",
        (r"\bsevere (?:car |vehicle )?(?:crash|collision|accident)\b", r"\brollover\b", r"\bvehicle (?:is )?on fire\b"),
    ),
    EventRule(
        "Medical emergency",
        "High",
        (r"\bnot breathing\b", r"\bunconscious\b", r"\boverdose\b", r"\bheart attack\b", r"\bseizure\b"),
    ),
    EventRule("Robbery", "Medium", (r"\brobbery\b", r"\brobbed\b")),
    EventRule("Theft", "Medium", (r"\btheft\b", r"\bstolen\b", r"\bsteal(?:ing)?\b", r"\bburglary\b")),
    EventRule(
        "Public disturbance",
        "Medium",
        (r"\bdisturbance\b", r"\bdisorderly\b", r"\bnoise complaint\b"),
    ),
    EventRule(
        "Property damage",
        "Medium",
        (r"\bproperty damage\b", r"\bvandalis(?:m|ed)\b", r"\bbroken window\b"),
    ),
    EventRule(
        "Vehicle crash",
        "Medium",
        (r"\bcar (?:crash|accident)\b", r"\bvehicle (?:crash|collision)\b", r"\btraffic accident\b"),
    ),
)

CRITICAL_URGENCY_PATTERNS = (
    r"\bnot breathing\b",
    r"\bsomeone (?:has been |was )?shot\b",
    r"\bshots? fired\b",
    r"\b(?:person|people|someone) trapped\b",
    r"\bbuilding (?:is )?on fire\b",
    r"\bgun\b",
)
URGENCY_TERMS = {
    "help": 0.22,
    "emergency": 0.24,
    "hurry": 0.24,
    "quickly": 0.18,
    "immediately": 0.20,
    "please": 0.08,
    "danger": 0.18,
    "dying": 0.28,
    "bleeding": 0.20,
    "scared": 0.14,
    "screaming": 0.14,
}

TIME_PATTERNS = (
    re.compile(r"\b(?:at\s+)?((?:0?[1-9]|1[0-2])(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?))\b", re.IGNORECASE),
    re.compile(r"\b(?:at\s+)?((?:[01]?\d|2[0-3]):[0-5]\d)\b"),
    re.compile(r"\b(midnight|noon)\b", re.IGNORECASE),
)
STREET_ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){0,5}"
    r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|"
    r"Lane|Ln\.?|Court|Ct\.?|Highway|Hwy\.?|Way|Place|Pl\.?)\b",
    re.IGNORECASE,
)
FACILITY_PATTERN = re.compile(
    r"\b(?:at|near|inside|outside|by)\s+(?:the\s+)?"
    r"((?:[A-Za-z0-9.'-]+\s+){0,4}(?:school|hospital|store|bank|park|station|"
    r"parking lot|intersection|apartment|house|mall|restaurant|airport))\b",
    re.IGNORECASE,
)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _clean_text(text: Any) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned if cleaned else UNKNOWN


def _normalize_transcription(value: Any) -> TranscriptionResult:
    if isinstance(value, TranscriptionResult):
        return TranscriptionResult(_clean_text(value.text), _clamp(value.confidence))
    if isinstance(value, str):
        return TranscriptionResult(_clean_text(value), 0.0)
    if isinstance(value, Mapping):
        text = value.get("text", value.get("transcription", UNKNOWN))
        confidence = value.get("confidence", value.get("score", 0.0))
        return TranscriptionResult(_clean_text(text), _clamp(float(confidence or 0.0)))
    if isinstance(value, tuple) and value:
        confidence = value[1] if len(value) > 1 else 0.0
        return TranscriptionResult(_clean_text(value[0]), _clamp(float(confidence or 0.0)))
    return TranscriptionResult(UNKNOWN, 0.0)


def extract_event(transcript: str) -> tuple[str, str]:
    """Return the highest-severity event label found in a transcript."""

    text = transcript.lower()
    for rule in EVENT_RULES:
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in rule.patterns):
            return rule.label, rule.severity
    return UNKNOWN, "Low"


def extract_time(transcript: str) -> str:
    for pattern in TIME_PATTERNS:
        match = pattern.search(transcript)
        if match:
            return re.sub(r"^at\s+", "", match.group(1), flags=re.IGNORECASE).strip()
    return UNKNOWN


def extract_location(transcript: str) -> str:
    address = STREET_ADDRESS_PATTERN.search(transcript)
    if address:
        return address.group(0).strip(" ,.;")

    facility = FACILITY_PATTERN.search(transcript)
    if facility:
        return facility.group(1).strip(" ,.;")
    return UNKNOWN


def _wav_energy_score(path: Path) -> float:
    """Estimate vocal intensity from PCM WAV data without third-party packages."""

    if path.suffix.lower() != ".wav":
        return 0.0
    try:
        with wave.open(str(path), "rb") as audio:
            sample_width = audio.getsampwidth()
            frame_count = min(audio.getnframes(), audio.getframerate() * 30)
            raw = audio.readframes(frame_count)
    except (wave.Error, OSError):
        return 0.0

    if sample_width not in {1, 2, 4} or not raw:
        return 0.0

    max_value = float((1 << (sample_width * 8 - 1)) - 1)
    stride = max(sample_width, (len(raw) // 200_000 // sample_width) * sample_width)
    squares = 0.0
    count = 0
    for offset in range(0, len(raw) - sample_width + 1, stride):
        sample = int.from_bytes(
            raw[offset : offset + sample_width],
            byteorder="little",
            signed=sample_width != 1,
        )
        if sample_width == 1:
            sample -= 128
        normalized = sample / max_value
        squares += normalized * normalized
        count += 1
    if not count:
        return 0.0
    rms = math.sqrt(squares / count)
    return _clamp((rms - 0.02) / 0.23, maximum=0.65)


def calculate_urgency(transcript: str, acoustic_score: float = 0.0) -> float:
    """Calculate a deterministic 0-1 urgency score from words and loudness."""

    if transcript == UNKNOWN:
        return round(_clamp(acoustic_score, maximum=0.65), 3)

    text = transcript.lower()
    if any(re.search(pattern, text) for pattern in CRITICAL_URGENCY_PATTERNS):
        lexical_score = 0.82
    else:
        lexical_score = 0.0

    for term, weight in URGENCY_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", text):
            lexical_score += weight
    lexical_score += min(transcript.count("!"), 3) * 0.05
    combined = max(lexical_score, acoustic_score, lexical_score * 0.9 + acoustic_score * 0.1)
    return round(_clamp(combined), 3)


@lru_cache(maxsize=2)
def _load_wav2vec2(model_name: str, local_files_only: bool) -> tuple[Any, Any]:
    try:
        from transformers import AutoProcessor, Wav2Vec2ForCTC
    except ImportError as exc:  # pragma: no cover - depends on optional packages
        raise RuntimeError(
            "Audio transcription requires transformers, torch, and librosa. "
            "Install the project requirements or inject a transcriber."
        ) from exc

    processor = AutoProcessor.from_pretrained(model_name, local_files_only=local_files_only)
    model = Wav2Vec2ForCTC.from_pretrained(model_name, local_files_only=local_files_only)
    model.eval()
    return processor, model


def transcribe_wav2vec2(audio_path: str | Path, model_name: str | None = None) -> TranscriptionResult:
    """Transcribe an audio file with the local/free Hugging Face Wav2Vec2 model."""

    try:
        import librosa
        import torch
    except ImportError as exc:  # pragma: no cover - depends on optional packages
        raise RuntimeError(
            "Audio transcription requires transformers, torch, and librosa."
        ) from exc

    selected_model = model_name or os.getenv("AUDIO_ASR_MODEL", DEFAULT_ASR_MODEL)
    local_only = os.getenv("AUDIO_LOCAL_FILES_ONLY", "false").lower() in {"1", "true", "yes"}
    processor, model = _load_wav2vec2(selected_model, local_only)
    samples, _ = librosa.load(str(audio_path), sr=16_000, mono=True)
    if samples.size == 0:
        return TranscriptionResult(UNKNOWN, 0.0)

    inputs = processor(samples, sampling_rate=16_000, return_tensors="pt", padding=True)
    with torch.inference_mode():
        logits = model(**inputs).logits
    predicted_ids = torch.argmax(logits, dim=-1)
    text = processor.batch_decode(predicted_ids)[0]
    token_confidence = torch.softmax(logits, dim=-1).amax(dim=-1).mean().item()
    return TranscriptionResult(_clean_text(text), _clamp(token_confidence))


def _source_filename(audio: str | Path | BinaryIO) -> str:
    if isinstance(audio, (str, Path)):
        return Path(audio).name
    name = getattr(audio, "name", "uploaded_audio.wav")
    return Path(str(name)).name


@contextmanager
def _materialized_audio(audio: str | Path | BinaryIO, suffix: str) -> Iterator[Path]:
    if isinstance(audio, (str, Path)):
        path = Path(audio)
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")
        yield path
        return

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            if hasattr(audio, "seek"):
                audio.seek(0)
            shutil.copyfileobj(audio, temporary)
        yield temporary_path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _row_confidence(
    transcription_confidence: float,
    transcript: str,
    event: str,
    location: str,
    incident_time: str,
) -> float:
    if transcript == UNKNOWN:
        return 0.0
    base = transcription_confidence if transcription_confidence > 0 else 0.55
    detected = sum(value != UNKNOWN for value in (event, location, incident_time))
    return round(_clamp(base * 0.75 + detected * 0.08), 3)


def process_audio(
    audio: str | Path | BinaryIO,
    *,
    transcriber: Callable[[Path], Any] | None = None,
    model_name: str | None = None,
) -> pd.DataFrame:
    """Process one audio file and return the required eight-column DataFrame.

    A custom ``transcriber`` may return a string, ``TranscriptionResult``,
    ``(text, confidence)``, or a mapping with ``text`` and ``confidence`` keys.
    Transcription failures intentionally produce an Unknown fallback row.
    """

    filename = _source_filename(audio)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise ValueError(f"Unsupported audio type '{suffix or '<none>'}'. Expected: {supported}")

    with _materialized_audio(audio, suffix) as audio_path:
        acoustic_score = _wav_energy_score(audio_path)
        try:
            transcription_value = (
                transcriber(audio_path)
                if transcriber is not None
                else transcribe_wav2vec2(audio_path, model_name=model_name)
            )
            transcription = _normalize_transcription(transcription_value)
        except Exception:
            transcription = TranscriptionResult(UNKNOWN, 0.0)

    transcript = transcription.text
    event, event_severity = extract_event(transcript)
    location = extract_location(transcript)
    incident_time = extract_time(transcript)
    urgency = calculate_urgency(transcript, acoustic_score)
    severity = "High" if urgency >= 0.75 or event_severity == "High" else event_severity
    confidence = _row_confidence(
        transcription.confidence,
        transcript,
        event,
        location,
        incident_time,
    )

    row = {
        "source_filename": filename,
        "source_type": "AUD",
        "raw_event": event,
        "raw_location": location,
        "raw_time": incident_time,
        "raw_severity": severity,
        "confidence": confidence,
        "raw_text": transcript,
    }
    return pd.DataFrame([row], columns=EXTRACTOR_COLUMNS)


extract_audio = process_audio


__all__ = [
    "EXTRACTOR_COLUMNS",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "TranscriptionResult",
    "calculate_urgency",
    "extract_audio",
    "extract_event",
    "extract_location",
    "extract_time",
    "process_audio",
    "transcribe_wav2vec2",
]
