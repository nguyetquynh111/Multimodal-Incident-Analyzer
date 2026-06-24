"""Tests for validation, payload creation, and optional Supabase round trips.

``incident_id`` is a unique integer (the Supabase column is ``int8``). The live
round-trip test only runs when ``RUN_SUPABASE_LIVE_TESTS=1`` so the default
``pytest`` run stays offline and never mutates the real database.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call

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


def _duplicate_id_frame() -> pd.DataFrame:
    return pd.concat([_incident_frame(101), _incident_frame(101)], ignore_index=True)


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (pd.DataFrame(), "empty"),
        (_incident_frame().drop(columns="event"), "missing required columns"),
        (_incident_frame(None), "null values"),
        (_incident_frame("not-an-integer"), "convertible"),
        (_incident_frame(1.5), "whole integer"),
        (_duplicate_id_frame(), "unique"),
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


def test_query_incidents_applies_filters_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    query = MagicMock()
    response = SimpleNamespace(data=[{"id": 7, "incident_id": 101}])
    client.table.return_value.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    rows = supabase_client.query_incidents(
        {"incident_id": "101", "severity": "Low"},
        limit=10,
    )

    client.table.assert_called_once_with("incidents")
    client.table.return_value.select.assert_called_once_with(
        ",".join(supabase_client.SELECT_COLUMNS)
    )
    assert query.eq.call_args_list == [
        call("incident_id", 101),
        call("severity", "Low"),
    ]
    query.limit.assert_called_once_with(10)
    assert rows == response.data


def test_get_incident_returns_row_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    query = MagicMock(return_value=[{"id": 12, "incident_id": 7}])
    monkeypatch.setattr(supabase_client, "query_incidents", query)

    assert supabase_client.get_incident(7) == {"id": 12, "incident_id": 7}
    query.assert_called_once_with({"incident_id": 7}, limit=1)

    query.return_value = []
    assert supabase_client.get_incident(8) is None


def test_update_incident_uses_incident_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    query = MagicMock()
    response = SimpleNamespace(data=[{"id": 7, "severity": "High"}])
    client.table.return_value.update.return_value = query
    query.eq.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    summary = supabase_client.update_incident(7, {"severity": "High"})

    client.table.return_value.update.assert_called_once_with({"severity": "High"})
    query.eq.assert_called_once_with("incident_id", 7)
    assert summary["updated_count"] == 1
    assert summary["data"] == response.data


def test_delete_incident_uses_incident_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    query = MagicMock()
    response = SimpleNamespace(data=[{"id": 7}])
    client.table.return_value.delete.return_value = query
    query.eq.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    summary = supabase_client.delete_incident(7)

    query.eq.assert_called_once_with("incident_id", 7)
    assert summary["deleted_count"] == 1
    assert summary["data"] == response.data


@pytest.mark.parametrize("column", ["id", "created_at", "unknown"])
def test_update_incident_rejects_protected_columns(column: str) -> None:
    with pytest.raises(ValueError, match="Unsupported update columns"):
        supabase_client.update_incident(7, {column: "value"})


def test_crud_rejects_invalid_identifiers_and_filters() -> None:
    with pytest.raises(ValueError, match="convertible"):
        supabase_client.get_incident("not-an-id")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="whole integer"):
        supabase_client.delete_incident(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unsupported query columns"):
        supabase_client.query_incidents({"not_a_column": "value"})
    with pytest.raises(ValueError, match="between 1 and 1000"):
        supabase_client.query_incidents(limit=0)


@pytest.mark.skipif(
    os.getenv("RUN_SUPABASE_LIVE_TESTS") != "1",
    reason="Set RUN_SUPABASE_LIVE_TESTS=1 to run the live Supabase round trip.",
)
def test_supabase_insert_exists_then_delete() -> None:
    """Create, read, update, and delete one row, then confirm cleanup.

    The configured key must have permission to insert, select, update, and
    delete test rows so cleanup can be verified.
    """
    load_dotenv(supabase_client.PROJECT_ROOT / ".env", override=False)
    if not any(
        os.getenv(name)
        for name in (
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_ANON_KEY",
            "SUPABASE_KEY",
        )
    ):
        pytest.skip("Live CRUD test requires a configured Supabase key.")

    incident_id = time.time_ns()
    source = "pytest-cloud-deployment"
    frame = _incident_frame(incident_id)
    client = supabase_client.get_supabase_client()

    try:
        summary = upload_service.upload_incidents(frame)
        assert summary["success"] is True
        assert summary["inserted_count"] == 1

        selected = supabase_client.query_incidents(
            {"incident_id": incident_id, "source": source},
            limit=2,
        )
        assert len(selected) == 1
        assert selected[0]["event"] == "test event"

        update_summary = supabase_client.update_incident(
            incident_id,
            {"event": "updated test event", "severity": "Medium"},
        )
        assert update_summary["updated_count"] == 1
        updated = supabase_client.get_incident(incident_id)
        assert updated is not None
        assert updated["event"] == "updated test event"
        assert updated["severity"] == "Medium"

        delete_summary = supabase_client.delete_incident(incident_id)
        assert delete_summary["deleted_count"] == 1
        assert supabase_client.get_incident(incident_id) is None
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
