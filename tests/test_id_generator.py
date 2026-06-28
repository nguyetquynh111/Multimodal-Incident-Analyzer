"""Tests for documented INC_TYPE_NUMBER identifiers."""

from __future__ import annotations

import pandas as pd
import pytest

from integration.integration import (
    assign_incident_ids,
    generate_incident_id,
    generate_next_incident_id,
    next_incident_number,
)


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        ("audio", "INC_AUD_001"),
        ("pdf", "INC_PDF_001"),
        ("image", "INC_IMG_001"),
        ("video", "INC_VID_001"),
        ("text", "INC_TXT_001"),
        ("csv", "INC_TXT_001"),
    ],
)
def test_ids_use_the_documented_source_prefix(source_type: str, expected: str) -> None:
    assert generate_incident_id(source_type, 1) == expected


def test_next_id_increments_only_within_its_source_type() -> None:
    existing = ["INC_AUD_099", "INC_TXT_004", "INC_TXT_010", "not-an-id"]

    assert next_incident_number(existing, "audio") == 100
    assert next_incident_number(existing, "text") == 11
    assert generate_next_incident_id("video", existing) == "INC_VID_001"


def test_assignment_increments_each_source_independently() -> None:
    rows = pd.DataFrame(
        [
            {"source": "Audio"},
            {"source": "Text"},
            {"source": "Audio"},
        ]
    )

    result = assign_incident_ids(rows, existing_ids=["INC_AUD_007", "INC_TXT_003"])

    assert result["incident_id"].tolist() == [
        "INC_AUD_008",
        "INC_TXT_004",
        "INC_AUD_009",
    ]
