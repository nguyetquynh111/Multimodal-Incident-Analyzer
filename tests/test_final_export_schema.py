"""Tests for the approved nine-field CSV export contract."""

from __future__ import annotations

from io import StringIO

import pandas as pd

from cloud_deployment import exporter
from integration.integration import FINAL_CSV_COLUMNS, to_final_csv_frame


def test_final_export_has_exact_columns_and_no_null_values() -> None:
    records = pd.DataFrame(
        [
            {
                "id": 7,
                "created_at": "2026-06-26T10:00:00Z",
                "incident_id": "INC_VID_001",
                "source": "Video",
                "event": "person running",
                "location": None,
                "time": "",
                "severity": "medium",
                "incident_summary": None,
                "extra": "not exported",
            }
        ]
    )

    exported = to_final_csv_frame(records)

    assert list(exported.columns) == list(FINAL_CSV_COLUMNS)
    assert len(exported.columns) == 9
    assert not exported.isnull().values.any()
    assert exported.iloc[0].to_dict() == {
        "id": "7",
        "created_at": "2026-06-26T10:00:00Z",
        "incident_id": "INC_VID_001",
        "source": "Video",
        "event": "Person Running",
        "location": "Unknown",
        "time": "Unknown",
        "severity": "Medium",
        "incident_summary": "Unknown",
    }


def test_csv_exporter_serializes_only_the_final_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        exporter,
        "query_incidents",
        lambda **_: [
            {
                "id": 1,
                "created_at": "2026-06-26",
                "incident_id": "INC_PDF_001",
                "source": "PDF",
                "event": "burglary",
                "location": "Unknown",
                "time": "Unknown",
                "severity": "Medium",
                "incident_summary": "Burglary reported.",
                "extra": "ignore",
            }
        ],
    )

    csv = pd.read_csv(
        StringIO(exporter.export_incidents_csv().decode("utf-8")), keep_default_na=False
    )

    assert list(csv.columns) == list(FINAL_CSV_COLUMNS)
    assert not csv.isnull().values.any()
