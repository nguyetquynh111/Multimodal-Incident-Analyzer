"""Audio extraction for the Multimodal Incident Analyzer.

The public ``process_audio`` function accepts a path or an uploaded file,
transcribes it with a local OpenAI Whisper model, and returns the extractor DataFrame
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
AUDIO_OUTPUT_COLUMNS = [
    "Call_ID",
    "Transcript",
    "Extracted_Event",
    "Location",
    "Sentiment",
    "Urgency_Score",
]
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}
DEFAULT_WHISPER_MODEL = "base.en"
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
    r"\bfire\b",
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
DISTRESS_PATTERNS = (
    r"\bhelp\b",
    r"\bscared\b",
    r"\bterrified\b",
    r"\bpanic(?:king|ked)?\b",
    r"\bcrying\b",
    r"\bscreaming\b",
    r"\bplease hurry\b",
    r"\boh my god\b",
    r"\bcan(?:not|'t) breathe\b",
)
URGENCY_PHRASE_PATTERNS = CRITICAL_URGENCY_PATTERNS + (
    r"\bneed (?:an? )?(?:ambulance|police|fire department)\b",
    r"\bsend (?:an? )?(?:ambulance|police|help)\b",
    r"\bas soon as possible\b",
    r"\bright now\b",
) + tuple(rf"\b{re.escape(term)}\b" for term in URGENCY_TERMS)
NAME_INTRO_PATTERN = re.compile(
    r"\b(?:(?i:my name is|this is|i am|i'm|caller is|victim is|suspect is|officer))\s+"
    r"([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,2})"
)
NAME_TRAILING_STOPWORDS = {
    "At",
    "Calling",
    "From",
    "In",
    "On",
    "Please",
    "Reporting",
    "The",
    "Unknown",
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


def extract_names(transcript: str) -> str:
    """Extract explicitly introduced person names without guessing unnamed people."""

    if transcript == UNKNOWN:
        return UNKNOWN
    names: list[str] = []
    for match in NAME_INTRO_PATTERN.finditer(transcript):
        tokens = match.group(1).split()
        while tokens and tokens[-1] in NAME_TRAILING_STOPWORDS:
            tokens.pop()
        candidate = " ".join(tokens)
        if candidate and candidate.casefold() not in {name.casefold() for name in names}:
            names.append(candidate)
    return "; ".join(names) if names else UNKNOWN


def extract_urgency_phrases(transcript: str) -> str:
    """Return distinct urgency phrases found in transcript order."""

    if transcript == UNKNOWN:
        return UNKNOWN
    matches: list[tuple[int, str]] = []
    for pattern in URGENCY_PHRASE_PATTERNS:
        for match in re.finditer(pattern, transcript, re.IGNORECASE):
            matches.append((match.start(), match.group(0).strip()))
    matches.sort(key=lambda item: item[0])

    phrases: list[str] = []
    seen: set[str] = set()
    for _, phrase in matches:
        normalized = phrase.casefold()
        if normalized not in seen:
            seen.add(normalized)
            phrases.append(phrase)
    return "; ".join(phrases) if phrases else UNKNOWN


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
    sample_count = len(raw) // sample_width
    target_samples = 20_000
    stride = max(1, sample_count // target_samples) * sample_width
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


def classify_sentiment(transcript: str, acoustic_score: float = 0.0) -> str:
    """Classify the caller's apparent state as Calm or Distressed."""

    if transcript == UNKNOWN:
        return "Calm"
    distressed_language = any(
        re.search(pattern, transcript, re.IGNORECASE) for pattern in DISTRESS_PATTERNS
    )
    repeated_exclamation = transcript.count("!") >= 2
    return "Distressed" if distressed_language or repeated_exclamation or acoustic_score >= 0.45 else "Calm"


def analyze_transcript(transcript: str, acoustic_score: float = 0.0) -> dict[str, Any]:
    """Extract all documented audio signals from one normalized transcript."""

    cleaned = _clean_text(transcript)
    event, event_severity = extract_event(cleaned)
    return {
        "event": event,
        "event_severity": event_severity,
        "location": extract_location(cleaned),
        "time": extract_time(cleaned),
        "names": extract_names(cleaned),
        "urgency_phrases": extract_urgency_phrases(cleaned),
        "sentiment": classify_sentiment(cleaned, acoustic_score),
        "urgency_score": calculate_urgency(cleaned, acoustic_score),
    }


def to_audio_output(
    extractor_df: pd.DataFrame,
    *,
    audio_paths: Mapping[str, str | Path] | None = None,
) -> pd.DataFrame:
    """Convert shared extractor rows to the required six-column audio artifact."""

    missing = [column for column in EXTRACTOR_COLUMNS if column not in extractor_df.columns]
    if missing:
        raise ValueError(f"Audio extractor output is missing columns: {', '.join(missing)}")

    paths = audio_paths or {}
    output_rows: list[dict[str, Any]] = []
    for row in extractor_df.to_dict(orient="records"):
        filename = _clean_text(row.get("source_filename"))
        transcript = _clean_text(row.get("raw_text"))
        source_path = paths.get(filename)
        acoustic_score = _wav_energy_score(Path(source_path)) if source_path else 0.0
        output_rows.append(
            {
                "Call_ID": Path(filename).stem if filename != UNKNOWN else UNKNOWN,
                "Transcript": transcript,
                "Extracted_Event": _clean_text(row.get("raw_event")),
                "Location": _clean_text(row.get("raw_location")),
                "Sentiment": classify_sentiment(transcript, acoustic_score),
                "Urgency_Score": calculate_urgency(transcript, acoustic_score),
            }
        )
    return pd.DataFrame(output_rows, columns=AUDIO_OUTPUT_COLUMNS)


@lru_cache(maxsize=2)
def _load_whisper(model_name: str, device: str, download_root: str | None) -> Any:
    try:
        import whisper
    except ImportError as exc:  # pragma: no cover - depends on optional packages
        raise RuntimeError(
            "Audio transcription requires openai-whisper. "
            "Install the project requirements or inject a transcriber."
        ) from exc

    load_options: dict[str, Any] = {"device": device}
    if download_root:
        load_options["download_root"] = download_root
    return whisper.load_model(model_name, **load_options)


def transcribe_whisper(audio_path: str | Path, model_name: str | None = None) -> TranscriptionResult:
    """Transcribe an audio file locally with OpenAI Whisper."""

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "OpenAI Whisper requires ffmpeg. On macOS, install it with: brew install ffmpeg"
        )

    selected_model = model_name or os.getenv("WHISPER_MODEL", DEFAULT_WHISPER_MODEL)
    device = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
    language = os.getenv("WHISPER_LANGUAGE", "en").strip() or None
    download_root = os.getenv("WHISPER_MODEL_DIR", "").strip() or None
    model = _load_whisper(selected_model, device, download_root)
    result = model.transcribe(
        str(audio_path),
        task="transcribe",
        language=language,
        fp16=device.startswith("cuda"),
        verbose=False,
    )

    text = _clean_text(result.get("text", UNKNOWN))
    segments = result.get("segments") or []
    segment_confidences = []
    for segment in segments:
        avg_logprob = segment.get("avg_logprob")
        if avg_logprob is None:
            continue
        no_speech_probability = _clamp(segment.get("no_speech_prob", 0.0))
        segment_confidences.append(math.exp(float(avg_logprob)) * (1.0 - no_speech_probability))
    confidence = (
        sum(segment_confidences) / len(segment_confidences)
        if segment_confidences
        else 0.0
    )
    return TranscriptionResult(text, _clamp(confidence))


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
    raise_on_transcription_error: bool = False,
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
                else transcribe_whisper(audio_path, model_name=model_name)
            )
            transcription = _normalize_transcription(transcription_value)
        except Exception as exc:
            if raise_on_transcription_error:
                raise RuntimeError(f"Whisper transcription failed for {filename}: {exc}") from exc
            transcription = TranscriptionResult(UNKNOWN, 0.0)

    transcript = transcription.text
    analysis = analyze_transcript(transcript, acoustic_score)
    event = analysis["event"]
    event_severity = analysis["event_severity"]
    location = analysis["location"]
    incident_time = analysis["time"]
    urgency = analysis["urgency_score"]
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
    result = pd.DataFrame([row], columns=EXTRACTOR_COLUMNS)
    result.attrs["audio_annotations"] = {
        filename: {
            "names": analysis["names"],
            "urgency_phrases": analysis["urgency_phrases"],
            "sentiment": analysis["sentiment"],
            "urgency_score": analysis["urgency_score"],
        }
    }
    return result


extract_audio = process_audio


__all__ = [
    "AUDIO_OUTPUT_COLUMNS",
    "EXTRACTOR_COLUMNS",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "TranscriptionResult",
    "analyze_transcript",
    "calculate_urgency",
    "classify_sentiment",
    "extract_audio",
    "extract_event",
    "extract_location",
    "extract_names",
    "extract_time",
    "extract_urgency_phrases",
    "process_audio",
    "to_audio_output",
    "transcribe_whisper",
]
