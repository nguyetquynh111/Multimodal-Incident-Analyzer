"""Tests for the documented upload-extension routing contract."""

from __future__ import annotations

import pytest

from integration.integration import detect_source_type, supported_extensions


@pytest.mark.parametrize(
    ("filename", "source_type"),
    [
        ("call.wav", "audio"),
        ("call.MP3", "audio"),
        ("call.m4a", "audio"),
        ("report.pdf", "pdf"),
        ("scene.jpg", "image"),
        ("scene.JPEG", "image"),
        ("scene.png", "image"),
        ("clip.mp4", "video"),
        ("clip.mov", "video"),
        ("clip.mpg", "video"),
        ("clip.mpeg", "video"),
        ("note.txt", "text"),
        ("records.csv", "text"),
    ],
)
def test_supported_extensions_route_to_the_expected_modality(
    filename: str, source_type: str
) -> None:
    assert detect_source_type(filename) == source_type


@pytest.mark.parametrize("filename", ["records.json", "archive.zip", "no-extension"])
def test_unsupported_extensions_are_rejected(filename: str) -> None:
    assert detect_source_type(filename) is None


def test_supported_extensions_match_the_uploader_contract() -> None:
    assert supported_extensions() == [
        "csv",
        "jpeg",
        "jpg",
        "m4a",
        "mov",
        "mp3",
        "mp4",
        "mpeg",
        "mpg",
        "pdf",
        "png",
        "txt",
        "wav",
    ]
