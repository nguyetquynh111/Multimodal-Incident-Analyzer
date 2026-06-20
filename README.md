# Multimodal Incident Analyzer

Class prototype for converting incident evidence into structured records. The audio module uses local Whisper transcription plus keyword, regex, and urgency rules. It does not use an LLM or download Hugging Face models.

## Setup

Python 3.10 and FFmpeg are required for audio files.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Audio Processor

Run commands from the repository root. If your terminal is inside `audio/`, run `cd ..` first.

Process one file:

```bash
python -m audio.processor \
  --input audio/sample_data/call_75_0.wav \
  --output audio/output/audio_results.csv
```

Process the sample folder:

```bash
python -m audio.processor \
  --input audio/sample_data/ \
  --output audio/output/audio_results.csv
```

Test extraction without Whisper:

```bash
python -m audio.processor \
  --demo-transcript "There are guns near Central Station." \
  --output audio/output/audio_results.csv
```

Audio CSV columns are exactly:

```text
Call_ID, Transcript, Extracted_Event, Location, Sentiment, Urgency_Score
```

The implementation lives in `audio/processor.py`, matching the `processor.py`
layout used by the image, PDF, text, and video modules. `audio/pipeline.py` is
retained as a backward-compatible import alias.

## Draft Modality Processors

The image, PDF, text, and video draft processors validate one input file and
write a schema-correct demonstration CSV. Their default output paths are inside
each module's `output/` folder.

```bash
python -m images.processor path/to/scene.png
python -m pdf.processor path/to/report.pdf
python -m text.processor path/to/report.txt
python -m video.processor path/to/clip.mp4
```

Pass `--output path/to/result.csv` to override a default output path.

## Tests

```bash
pytest
```

## Documentation

See [PRD](docs/PRD.md), [specifications](docs/specs.md), [technical design](docs/tech.md), [rules](docs/rules.md), and [tickets](docs/tickets.md).
