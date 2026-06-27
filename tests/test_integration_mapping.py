"""Regression tests for modality draft-to-incident mappings."""

from __future__ import annotations

import pandas as pd
import pytest

from integration.integration import (
    FINAL_CSV_COLUMNS,
    INCIDENT_COLUMNS,
    detect_source_type,
    generate_incident_id,
    integrate_records,
    to_supabase_payload_frame,
    to_final_csv_frame,
)


@pytest.fixture(autouse=True)
def _disable_openrouter_for_mapping_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep exact mapping assertions independent of a developer's .env file."""

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


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

    result = integrate_records(draft, "pdf")

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert result.to_dict(orient="records") == [
        {
            "Incident_ID": "INC_PDF_001",
            "Source": "PDF",
            "Event": "Burglary / Robbery",
            "Location": "Main Street",
            "Time": "June 23, 2026",
            "Severity": "Medium",
            "Incident_Summary": "A Medium-severity Burglary / Robbery incident was reported via PDF at Main Street. The reported time was June 23, 2026.",
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

    result = integrate_records(draft, "video")

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert result.to_dict(orient="records") == [
        {
            "Incident_ID": "INC_VID_001",
            "Source": "Video",
            "Event": "Person Collapsing",
            "Location": "Unknown",
            "Time": "00:00:12",
            "Severity": "High",
            "Incident_Summary": "A High-severity Person Collapsing incident was reported via Video. The reported time was 00:00:12.",
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

    result = integrate_records(draft, "text")

    assert list(result.columns) == list(INCIDENT_COLUMNS)
    assert result.to_dict(orient="records") == [
        {
            "Incident_ID": "INC_TXT_001",
            "Source": "Text",
            "Event": "Theft / Robbery",
            "Location": "Oak Street, Chicago",
            "Time": "9pm tonight",
            "Severity": "Medium",
            "Incident_Summary": "A Medium-severity Theft / Robbery incident was reported via Text at Oak Street, Chicago. The reported time was 9pm tonight.",
        }
    ]
    assert list(to_final_csv_frame(result).columns) == list(FINAL_CSV_COLUMNS)


def test_csv_inputs_belong_to_text_modality_and_json_is_rejected() -> None:
    assert detect_source_type("records.csv") == "text"
    assert detect_source_type("records.json") is None
    assert generate_incident_id("csv", 1) == "INC_TXT_001"


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

    result = integrate_records(draft, "text")

    assert result.to_dict(orient="records") == [
        {
            "Incident_ID": "INC_TXT_001",
            "Source": "Text",
            "Event": "Fire",
            "Location": "Main Street",
            "Time": "June 25, 2026",
            "Severity": "High",
            "Incident_Summary": "A High-severity Fire incident was reported via Text at Main Street. The reported time was June 25, 2026.",
        }
    ]


def test_image_artifact_placeholders_map_to_safe_final_values() -> None:
    draft = pd.DataFrame(
        [
            {
                "Image_ID": "IMG_001",
                "Scene_Type": "Unknown",
                "Objects_Detected": "None",
                "Text_Extracted": "N/A",
                "Confidence_Score": 0.0,
            }
        ]
    )

    result = integrate_records(draft, "image")

    assert result.loc[0, "Event"] == "Unknown"
    assert result.loc[0, "Severity"] == "Low"
    assert "N/A" not in result.loc[0, "Incident_Summary"]


def test_image_ocr_text_can_populate_location_with_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    import integration.integration as ig

    draft = pd.DataFrame(
        [
            {
                "Image_ID": "IMG_001",
                "Scene_Type": "Fire / Arson",
                "Objects_Detected": "fire",
                "Text_Extracted": "SAN BERNARDINO COUNTY CALL BOX 1226",
                "Confidence_Score": 0.91,
            }
        ]
    )
    monkeypatch.setattr(
        ig,
        "update_image_location_with_llm",
        lambda row: {**dict(row), "Location": "San Bernardino County"},
    )

    result = ig.integrate_records(draft, "image")

    assert result.loc[0, "Location"] == "San Bernardino County"
    assert "San Bernardino County" in result.loc[0, "Incident_Summary"]


def test_image_ocr_road_location_is_extracted_without_raw_text_summary() -> None:
    draft = pd.DataFrame(
        [
            {
                "Image_ID": "IMG_001",
                "Scene_Type": "Fire / Arson",
                "Objects_Detected": "fire",
                "Text_Extracted": 'ALABAMA BANKHEAD HIGHWAY re P e — No ~ A, we ome + me Beer"" aes Bee no Pad',
                "Confidence_Score": 0.91,
            }
        ]
    )

    result = integrate_records(draft, "image")

    assert result.loc[0, "Location"] == "Alabama Bankhead Highway"
    assert "Alabama Bankhead Highway" in result.loc[0, "Incident_Summary"]
    assert "Raw text" not in result.loc[0, "Incident_Summary"]
    assert "Beer" not in result.loc[0, "Incident_Summary"]


def test_unknown_event_is_always_low_severity() -> None:
    draft = pd.DataFrame(
        [
            {
                "Event": "unknown emergency",
                "Location": "Unknown",
                "Time": "Unknown",
                "Severity": "High",
                "Summary": "No reliable event was identified.",
            }
        ]
    )

    result = integrate_records(draft, "text")

    assert result.loc[0, "Event"] == "Unknown"
    assert result.loc[0, "Severity"] == "Low"


@pytest.mark.parametrize(
    ("event", "confidence", "expected"),
    [
        ("Other", 0.30, "Low"),
        ("Fire / Arson", 0.30, "High"),
        ("Assault / Violence", 0.30, "High"),
        ("Public Disturbance", 0.10, "Medium"),
        ("Theft / Robbery", 0.10, "Medium"),
    ],
)
def test_event_category_overrides_generic_confidence_severity(
    event: str,
    confidence: float,
    expected: str,
) -> None:
    draft = pd.DataFrame(
        [
            {
                "Event": event,
                "Location": "Unknown",
                "Time": "Unknown",
                "Confidence": confidence,
                "Summary": "Structured incident row.",
            }
        ]
    )

    result = integrate_records(draft, "text")

    assert result.loc[0, "Event"] == event
    assert result.loc[0, "Severity"] == expected
