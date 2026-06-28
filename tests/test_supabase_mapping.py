"""Tests for the Integration-to-Supabase seven-field payload mapping."""

from __future__ import annotations

import pandas as pd

from integration.integration import SUPABASE_PAYLOAD_COLUMNS, to_supabase_payload_frame


def test_display_columns_map_to_exact_lower_case_insert_payload() -> None:
    display_row = pd.DataFrame(
        [
            {
                "Incident_ID": "INC_IMG_005",
                "Source": "Image",
                "Event": "fire / arson",
                "Location": "",
                "Time": None,
                "Severity": "high",
                "Incident_Summary": "Person and fire detected.",
                "id": 99,
                "created_at": "2026-06-26T10:00:00Z",
            }
        ]
    )

    payload = to_supabase_payload_frame(display_row)

    assert list(payload.columns) == list(SUPABASE_PAYLOAD_COLUMNS)
    assert payload.to_dict(orient="records") == [
        {
            "incident_id": "INC_IMG_005",
            "source": "Image",
            "event": "Fire / Arson",
            "location": "Unknown",
            "time": "Unknown",
            "severity": "High",
            "incident_summary": "Person and fire detected.",
        }
    ]


def test_missing_payload_fields_are_safe_unknown_values() -> None:
    payload = to_supabase_payload_frame(pd.DataFrame([{"Incident_ID": "INC_TXT_001"}]))

    assert list(payload.columns) == list(SUPABASE_PAYLOAD_COLUMNS)
    assert payload.iloc[0].to_dict() == {
        "incident_id": "INC_TXT_001",
        "source": "Unknown",
        "event": "Unknown",
        "location": "Unknown",
        "time": "Unknown",
        "severity": "Low",
        "incident_summary": "Unknown",
    }
