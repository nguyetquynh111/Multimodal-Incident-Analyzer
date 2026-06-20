"""Tests for validation, payload creation, and optional Supabase round trips."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from dotenv import load_dotenv

from cloud_deployment import supabase_client, upload_service
from cloud_deployment.validators import INCIDENT_COLUMNS, validate_incidents_df


def _incident_frame(incident_id: object = 101) -> pd.DataFrame:
    """Return one valid integration-ready incident row."""
    return pd.DataFrame(
        [
            {
                "incident_id": incident_id,
                "source": "pytest-cloud-deployment",
                "event": "test event",
                "location": None,
                "time": "2026-06-20T00:00:00Z",
                "severity": "Low",
            }
        ]
    )


def test_validate_incidents_df_accepts_valid_input() -> None:
    validate_incidents_df(_incident_frame("101"))


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (pd.DataFrame(), "empty"),
        (_incident_frame().drop(columns="event"), "missing required columns"),
        (_incident_frame(None), "null values"),
        (_incident_frame("not-an-integer"), "convertible"),
        (_incident_frame(1.5), "whole integer"),
    ],
)
def test_validate_incidents_df_rejects_invalid_input(
    frame: pd.DataFrame,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_incidents_df(frame)


def test_insert_incidents_sends_only_allowed_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    response = SimpleNamespace(data=[{"id": 1}])
    client.table.return_value.insert.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    summary = supabase_client.insert_incidents(_incident_frame("101"))

    client.table.assert_called_once_with("incidents")
    records = client.table.return_value.insert.call_args.args[0]
    assert list(records[0]) == list(INCIDENT_COLUMNS)
    assert records[0]["incident_id"] == 101
    assert records[0]["location"] is None
    assert "id" not in records[0]
    assert "created_at" not in records[0]
    assert summary["success"] is True
    assert summary["inserted_count"] == 1


def test_upload_incidents_validates_before_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    insert = MagicMock(return_value={"success": True, "inserted_count": 1, "data": []})
    monkeypatch.setattr(upload_service, "insert_incidents", insert)

    summary = upload_service.upload_incidents(_incident_frame())

    insert.assert_called_once()
    assert summary["inserted_count"] == 1


@pytest.mark.skipif(
    os.getenv("RUN_SUPABASE_INTEGRATION_TEST") != "1",
    reason="Set RUN_SUPABASE_INTEGRATION_TEST=1 to modify the live test table.",
)
def test_supabase_insert_exists_then_delete() -> None:
    """Insert one unique row, verify it, and always remove it afterward.

    A service-role key is required so row-level security cannot prevent the
    cleanup step. The test never falls back to an anon key.
    """
    load_dotenv(supabase_client.PROJECT_ROOT / ".env", override=False)
    if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        pytest.skip(
            "Live insert/delete test requires SUPABASE_SERVICE_ROLE_KEY for safe cleanup."
        )

    incident_id = time.time_ns()
    source = "pytest-cloud-deployment"
    frame = _incident_frame(incident_id)
    client = supabase_client.get_supabase_client()

    try:
        summary = upload_service.upload_incidents(frame)
        assert summary["success"] is True
        assert summary["inserted_count"] == 1

        selected = (
            client.table("incidents")
            .select("incident_id,source,event,location,time,severity")
            .eq("incident_id", incident_id)
            .eq("source", source)
            .execute()
        )
        assert len(selected.data) == 1
        assert selected.data[0]["event"] == "test event"
    finally:
        (
            client.table("incidents")
            .delete()
            .eq("incident_id", incident_id)
            .eq("source", source)
            .execute()
        )

    remaining = (
        client.table("incidents")
        .select("incident_id")
        .eq("incident_id", incident_id)
        .eq("source", source)
        .execute()
    )
    assert remaining.data == []
