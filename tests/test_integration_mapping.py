"""Regression tests for modality draft-to-incident mappings."""

from __future__ import annotations

import pandas as pd

from integration.integration import (
    FINAL_CSV_COLUMNS,
    INCIDENT_COLUMNS,
    build_incidents,
    detect_source_type,
    generate_incident_id,
    to_supabase_payload_frame,
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
                "Suspect_Description": "Unknown",
                "Outcome": "Unknown",
            }
        ]
    )

    result = build_incidents(draft, "pdf", existing_ids=[7])

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert result.to_dict(orient="records") == [
        {
            "Incident_ID": "INC_PDF_001",
            "Source": "PDF",
            "Event": "Burglary / Robbery",
            "Location": "Main Street",
            "Time": "June 23, 2026",
            "Severity": "Medium",
            "LLM_Summary": "A Medium-severity Burglary / Robbery incident was reported via PDF at Main Street. The reported time was June 23, 2026.",
        }
    ]
    assert to_supabase_payload_frame(result).to_dict(orient="records")[0]["incident_id"] == "INC_PDF_001"
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
            "Incident_ID": "INC_VID_001",
            "Source": "Video",
            "Event": "Person Collapsing",
            "Location": "Unknown",
            "Time": "00:00:12",
            "Severity": "High",
            "LLM_Summary": "A High-severity Person Collapsing incident was reported via Video. The reported time was 00:00:12.",
        }
    ]
    assert list(to_final_csv_frame(result).columns) == list(FINAL_CSV_COLUMNS)


def test_text_six_column_draft_maps_labeled_entities_to_location_and_time() -> None:
    draft = pd.DataFrame(
        [
            {
                "Text_ID": "TXT_112",
                "Source": "Twitter",
                "Raw_Text": "Robbery reported on Oak Street near Chicago around 9pm tonight.",
                "Sentiment": "Negative",
                "Entities": "LOCATION: Oak Street, Chicago; ORGANIZATION: Police; DATE: 9pm tonight",
                "Topic": "Theft / Robbery",
            }
        ]
    )

    result = build_incidents(draft, "text", existing_ids=[9])

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert result.to_dict(orient="records") == [
        {
            "Incident_ID": "INC_TXT_001",
            "Source": "Text",
            "Event": "Theft / Robbery",
            "Location": "Oak Street, Chicago",
            "Time": "9pm tonight",
            "Severity": "Medium",
            "LLM_Summary": "A Medium-severity Theft / Robbery incident was reported via Text at Oak Street, Chicago. The reported time was 9pm tonight.",
        }
    ]
    assert list(to_final_csv_frame(result).columns) == list(FINAL_CSV_COLUMNS)


def test_csv_and_json_inputs_belong_to_text_modality() -> None:
    assert detect_source_type("records.csv") == "text"
    assert detect_source_type("records.json") == "text"
    assert generate_incident_id("csv", 1) == "INC_TXT_001"
    assert generate_incident_id("json", 2) == "INC_TXT_002"


def test_structured_csv_draft_maps_through_text_modality() -> None:
    draft = pd.DataFrame(
        [
            {
                "Event": "fire",
                "Location": "Main Street",
                "Time": "June 25, 2026",
                "Severity": "High",
                "Summary": "Fire reported on Main Street.",
                "Confidence": 0.9,
            }
        ]
    )

    result = build_incidents(draft, "text")

    assert result.to_dict(orient="records") == [
        {
            "Incident_ID": "INC_TXT_001",
            "Source": "Text",
            "Event": "Fire",
            "Location": "Main Street",
            "Time": "June 25, 2026",
            "Severity": "High",
            "LLM_Summary": "A High-severity Fire incident was reported via Text at Main Street. The reported time was June 25, 2026.",
        }
    ]
