"""Emergency audio-call and witness-statement processing."""

from .extract import analyze_transcript
from .transcribe import transcribe_audio


def process_audio_file(*args, **kwargs):
    """Lazily import the file pipeline so ``python -m`` runs without warnings."""

    from .pipeline import process_audio_file as _process_audio_file

    return _process_audio_file(*args, **kwargs)


def process_audio_folder(*args, **kwargs):
    """Lazily import the folder pipeline so ``python -m`` runs without warnings."""

    from .pipeline import process_audio_folder as _process_audio_folder

    return _process_audio_folder(*args, **kwargs)

__all__ = [
    "analyze_transcript",
    "process_audio_file",
    "process_audio_folder",
    "transcribe_audio",
]
