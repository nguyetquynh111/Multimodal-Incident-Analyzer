"""Backward-compatible alias for :mod:`audio.processor`.

New code should import from ``audio.processor`` or run ``python -m audio.processor``.
"""

from .processor import (
    analyze_transcript,
    build_parser,
    main,
    process_audio_file,
    process_audio_folder,
    save_rows,
)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["analyze_transcript", "process_audio_file", "process_audio_folder"]
