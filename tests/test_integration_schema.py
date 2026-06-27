"""End-to-end schema checks for every documented modality draft."""

from __future__ import annotations

import pandas as pd
import pytest

from integration.integration import INCIDENT_COLUMNS, integrate_records, source_prefix


@pytest.mark.parametrize(
    ("source_type", "draft"),
    [
        ("audio", pd.DataFrame([{
            "Call_ID": "C001", "Transcript": "Fire at Main Street.",
            "Extracted_Event": "building fire", "Location": "Main Street",
            "Sentiment": "Distressed", "Urgency_Score": 0.9,
        }])),
        ("pdf", pd.DataFrame([{
            "Report_ID": "R001", "Incident_Type": "burglary/robbery",
            "Date": "June 20, 2026", "Location": "Oak Street", "Officer": "Unknown",
            "Summary": "A burglary was reported.", "Suspect_Description": "Unknown",
            "Outcome": "Unknown",
        }])),
        ("image", pd.DataFrame([{
            "Image_ID": "IMG_001", "Scene_Type": "Fire / Arson", "Objects_Detected": "fire",
            "Text_Extracted": "Unknown", "Confidence_Score": 0.91,
        }])),
        ("video", pd.DataFrame([{
            "Timestamp": "00:00:02", "Frame_ID": "FRM_001", "Event_Detected": "Person running",
            "Objects": "1 person", "Confidence": 0.66,
        }])),
        ("text", pd.DataFrame([{
            "Text_ID": "TXT_001", "Source": "News", "Raw_Text": "Robbery on Oak Street.",
            "Sentiment": "Negative", "Entities": "LOCATION: Oak Street; DATE: today",
            "Topic": "Theft / Robbery",
        }])),
    ],
)
def test_each_modality_integrates_to_the_exact_final_contract(
    monkeypatch: pytest.MonkeyPatch, source_type: str, draft: pd.DataFrame
) -> None:
    # Keep this contract test deterministic even on a developer machine with a key.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = integrate_records(draft, source_type)

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert len(result) == 1
    assert result.iloc[0]["Incident_ID"] == f"INC_{source_prefix(source_type)}_001"
    assert not result.isnull().values.any()
    assert all(str(value).strip() for value in result.iloc[0])
