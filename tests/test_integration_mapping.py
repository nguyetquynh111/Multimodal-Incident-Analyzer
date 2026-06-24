"""Regression tests for modality draft-to-incident mappings."""

from __future__ import annotations

import pandas as pd

from integration.integration import (
    FINAL_CSV_COLUMNS,
    INCIDENT_COLUMNS,
    build_incidents,
    to_final_csv_frame,
)


def test_pdf_six_column_draft_maps_to_incident_schema() -> None:
    draft = pd.DataFrame(
        [
            {
                "Report_ID": "RPT_007",
                "Incident_Type": "burglary/robbery",
                "Date": "June 23, 2026",
                "Location": "Main Street",
                "Officer": "Officer Rivera",
                "Summary": "A burglary was reported on Main Street.",
            }
        ]
    )

    result = build_incidents(draft, "pdf", existing_ids=[7])

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert result.to_dict(orient="records") == [
        {
            "incident_id": 8,
            "source": "PDF",
            "event": "Burglary / Robbery",
            "location": "Main Street",
            "time": "June 23, 2026",
            "severity": "Medium",
        }
    ]
    assert list(to_final_csv_frame(result).columns) == list(FINAL_CSV_COLUMNS)


def test_video_five_column_draft_maps_to_incident_schema() -> None:
    draft = pd.DataFrame(
        [
            {
                "Timestamp": "00:00:12",
                "Frame_ID": "FRM_036",
                "Event_Detected": "Person collapsing",
                "Objects": "1 person",
                "Confidence": 0.88,
            }
        ]
    )

    result = build_incidents(draft, "video", existing_ids=[8])

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert result.to_dict(orient="records") == [
        {
            "incident_id": 9,
            "source": "Video",
            "event": "Person Collapsing",
            "location": "Unknown",
            "time": "00:00:12",
            "severity": "High",
        }
    ]
    assert list(to_final_csv_frame(result).columns) == list(FINAL_CSV_COLUMNS)
