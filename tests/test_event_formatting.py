"""Tests for canonical event labels across records and exports."""

from __future__ import annotations

import pandas as pd
import pytest

from integration.integration import normalize_event, to_final_csv_frame, with_display_ids


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "Unknown"),
        ("", "Unknown"),
        ("unknown", "Unknown"),
        ("unknown emergency", "Unknown"),
        ("UNKNOWN-INCIDENT", "Unknown"),
        ("shooting", "Shooting"),
        ("Crowd gathering", "Crowd Gathering"),
        ("Person collapsing", "Person Collapsing"),
        ("burglary/robbery", "Burglary / Robbery"),
        ("car accident", "Car Accident"),
        ("building fire", "Building Fire"),
    ],
)
def test_normalize_event(raw: object, expected: str) -> None:
    assert normalize_event(raw) == expected


def test_existing_rows_are_formatted_for_display_and_export() -> None:
    rows = pd.DataFrame(
        [
            {
                "incident_id": "INC_AUD_001",
                "source": "Audio",
                "event": "unknown emergency",
                "location": "Unknown",
                "time": "Unknown",
                "severity": "Medium",
                "summary_by_llm": "Unknown",
            }
        ]
    )

    assert with_display_ids(rows).loc[0, "event"] == "Unknown"
    assert to_final_csv_frame(rows).loc[0, "event"] == "Unknown"
