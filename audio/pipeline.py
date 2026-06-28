"""Backward-compatible alias for :mod:`audio.processor`."""

from .processor import (
    analyze_transcript,
    build_parser as build_parser,
    main,
    process_audio_file,
    process_audio_folder,
    save_rows as save_rows,
)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["analyze_transcript", "process_audio_file", "process_audio_folder"]
