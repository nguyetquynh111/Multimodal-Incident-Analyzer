"""Tests for validation, payload creation, and Supabase round trips."""

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

# Load project-root env before live-test credential checks.
load_dotenv(supabase_client.PROJECT_ROOT / ".env", override=False)


def _incident_frame(incident_id: object = "INC_TXT_101") -> pd.DataFrame:
    """Return one valid integration-ready incident row."""
    return pd.DataFrame(
        [
            {
                "incident_id": incident_id,
                "source": "Text",
                "event": "test event",
                "location": "Unknown",
                "time": "2026-06-20T00:00:00Z",
                "severity": "Low",
                "incident_summary": "A Low-severity test event incident was reported via pytest-cloud-deployment.",
            }
        ]
    )


def test_validate_incidents_df_accepts_valid_input() -> None:
    validate_incidents_df(_incident_frame("INC_TXT_101"))


def test_validate_incidents_df_rejects_non_low_unknown_event() -> None:
    frame = _incident_frame("INC_TXT_102")
    frame.loc[0, "event"] = "unknown emergency"
    frame.loc[0, "severity"] = "High"

    with pytest.raises(ValueError, match="Severity must be Low when event is Unknown"):
        validate_incidents_df(frame)


def _duplicate_id_frame() -> pd.DataFrame:
    return pd.concat(
        [_incident_frame("INC_TXT_101"), _incident_frame("INC_TXT_101")],
        ignore_index=True,
    )


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (pd.DataFrame(), "empty"),
        (_incident_frame().drop(columns="event"), "missing required columns"),
        (_incident_frame(None), "null values"),
        (_incident_frame("not-an-id"), "INC_TYPE_NUMBER"),
        (_incident_frame("INC_DOC_001"), "INC_TYPE_NUMBER"),
        (_duplicate_id_frame(), "unique"),
    ],
)
def test_validate_incidents_df_rejects_invalid_input(
    frame: pd.DataFrame,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_incidents_df(frame)


def test_insert_incidents_sends_only_allowed_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    response = SimpleNamespace(data=[{"id": 1}])
    client.table.return_value.insert.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    summary = supabase_client.insert_incidents(_incident_frame("INC_TXT_101"))

    client.table.assert_called_once_with("incidents")
    records = client.table.return_value.insert.call_args.args[0]
    assert list(records[0]) == list(INCIDENT_COLUMNS)
    assert records[0]["incident_id"] == "INC_TXT_101"
    assert records[0]["location"] == "Unknown"
    assert "id" not in records[0]
    assert "created_at" not in records[0]
    assert summary["success"] is True
    assert summary["inserted_count"] == 1


def test_insert_incidents_explains_legacy_bigint_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.side_effect = RuntimeError(
        'invalid input syntax for type bigint: "INC_TXT_101"'
    )
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    with pytest.raises(RuntimeError, match="incident_id as bigint"):
        supabase_client.insert_incidents(_incident_frame("INC_TXT_101"))


def test_get_supabase_client_uses_shared_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_client = object()
    options = object()
    client = object()
    create_client = MagicMock(return_value=client)

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")
    monkeypatch.setattr(supabase_client, "HttpxClient", lambda: http_client)
    monkeypatch.setattr(
        supabase_client,
        "ClientOptions",
        lambda **kwargs: options if kwargs == {"httpx_client": http_client} else None,
    )
    monkeypatch.setattr(supabase_client, "create_client", create_client)

    assert supabase_client.get_supabase_client() is client
    create_client.assert_called_once_with(
        "https://example.supabase.co",
        "test-key",
        options=options,
    )


def test_upload_incidents_validates_before_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert = MagicMock(return_value={"success": True, "inserted_count": 1, "data": []})
    monkeypatch.setattr(upload_service, "insert_incidents", insert)

    summary = upload_service.upload_incidents(_incident_frame())

    insert.assert_called_once()
    assert summary["inserted_count"] == 1


def test_upload_incidents_accepts_integration_output_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert = MagicMock(return_value={"success": True, "inserted_count": 1, "data": []})
    monkeypatch.setattr(upload_service, "insert_incidents", insert)
    frame = pd.DataFrame(
        [
            {
                "Incident_ID": "INC_TXT_101",
                "Source": "Text",
                "Event": "test event",
                "Location": "Unknown",
                "Time": "2026-06-20T00:00:00Z",
                "Severity": "Low",
                "Incident_Summary": "A Low-severity test event incident was reported via Text.",
            }
        ]
    )

    upload_service.upload_incidents(frame)

    payload = insert.call_args.args[0]
    assert list(payload.columns) == list(INCIDENT_COLUMNS)
    assert payload.loc[0, "incident_id"] == "INC_TXT_101"
    assert payload.loc[0, "incident_summary"].startswith("A Low-severity")


def test_upload_incidents_can_refresh_ids_before_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert = MagicMock(return_value={"success": True, "inserted_count": 1, "data": []})
    monkeypatch.setattr(upload_service, "insert_incidents", insert)
    monkeypatch.setattr(
        upload_service,
        "query_incidents",
        lambda **_: [{"incident_id": "INC_AUD_001"}],
    )
    frame = pd.DataFrame(
        [
            {
                "Incident_ID": "INC_AUD_001",
                "Source": "Audio",
                "Event": "Shooting",
                "Location": "Unknown",
                "Time": "Unknown",
                "Severity": "High",
                "Incident_Summary": "A High-severity Shooting incident was reported via Audio.",
            }
        ]
    )

    summary = upload_service.upload_incidents(frame, refresh_ids=True)

    payload = insert.call_args.args[0]
    assert payload.loc[0, "incident_id"] == "INC_AUD_002"
    assert summary["incident_ids"] == ["INC_AUD_002"]


def test_query_incidents_applies_filters_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    query = MagicMock()
    response = SimpleNamespace(data=[{"id": 7, "incident_id": "INC_TXT_101"}])
    client.table.return_value.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    rows = supabase_client.query_incidents(
        {"incident_id": "INC_TXT_101", "severity": "Low"},
        limit=10,
    )

    client.table.assert_called_once_with("incidents")
    client.table.return_value.select.assert_called_once_with(
        ",".join(supabase_client.SELECT_COLUMNS)
    )
    assert query.eq.call_args_list == [
        call("incident_id", "INC_TXT_101"),
        call("severity", "Low"),
    ]
    query.limit.assert_called_once_with(10)
    assert rows == response.data


def test_get_incident_returns_row_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    query = MagicMock(return_value=[{"id": 12, "incident_id": "INC_TXT_007"}])
    monkeypatch.setattr(supabase_client, "query_incidents", query)

    assert supabase_client.get_incident("INC_TXT_007") == {
        "id": 12,
        "incident_id": "INC_TXT_007",
    }
    query.assert_called_once_with({"incident_id": "INC_TXT_007"}, limit=1)

    query.return_value = []
    assert supabase_client.get_incident("INC_TXT_008") is None


def test_update_incident_uses_incident_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    query = MagicMock()
    response = SimpleNamespace(data=[{"id": 7, "severity": "High"}])
    client.table.return_value.update.return_value = query
    query.eq.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    summary = supabase_client.update_incident("INC_TXT_007", {"severity": "High"})

    client.table.return_value.update.assert_called_once_with({"severity": "High"})
    query.eq.assert_called_once_with("incident_id", "INC_TXT_007")
    assert summary["updated_count"] == 1
    assert summary["data"] == response.data


def test_update_incident_normalizes_event_and_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    query = MagicMock()
    response = SimpleNamespace(data=[{"id": 7, "event": "Updated Test Event"}])
    client.table.return_value.update.return_value = query
    query.eq.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    supabase_client.update_incident(
        "INC_TXT_007",
        {"event": "updated test event", "severity": "medium"},
    )

    client.table.return_value.update.assert_called_once_with(
        {"event": "Updated Test Event", "severity": "Medium"}
    )


def test_delete_incident_uses_incident_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    query = MagicMock()
    response = SimpleNamespace(data=[{"id": 7}])
    client.table.return_value.delete.return_value = query
    query.eq.return_value.execute.return_value = response
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)

    summary = supabase_client.delete_incident("INC_TXT_007")

    query.eq.assert_called_once_with("incident_id", "INC_TXT_007")
    assert summary["deleted_count"] == 1
    assert summary["data"] == response.data


def test_validate_incident_key_accepts_documented_ids() -> None:
    assert supabase_client.validate_incident_key(" INC_TXT_007 ") == "INC_TXT_007"


@pytest.mark.parametrize(
    "column", ["id", "created_at", "incident_id", "source", "unknown"]
)
def test_update_incident_rejects_protected_columns(column: str) -> None:
    with pytest.raises(ValueError, match="Unsupported update columns"):
        supabase_client.update_incident("INC_TXT_007", {column: "value"})


def test_crud_rejects_invalid_identifiers_and_filters() -> None:
    with pytest.raises(ValueError, match="INC_TYPE_NUMBER"):
        supabase_client.get_incident("not-an-id")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="INC_TYPE_NUMBER"):
        supabase_client.delete_incident(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unsupported query columns"):
        supabase_client.query_incidents({"not_a_column": "value"})
    with pytest.raises(ValueError, match="between 1 and 1000"):
        supabase_client.query_incidents(limit=0)


def test_supabase_insert_exists_then_delete() -> None:
    """Create, read, update, and delete one row, then confirm cleanup.

    The configured key must have permission to insert, select, update, and
    delete test rows so cleanup can be verified.
    """
    if supabase_client.create_client is None:
        pytest.skip("Live CRUD test requires the supabase package.")
    if not os.getenv("SUPABASE_URL") or not any(
        os.getenv(name)
        for name in (
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_ANON_KEY",
            "SUPABASE_KEY",
        )
    ):
        pytest.skip("Live CRUD test requires a configured Supabase key.")

    incident_id = f"INC_TXT_{time.time_ns()}"
    source = "Text"
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
        assert selected[0]["event"] == "Test Event"

        update_summary = supabase_client.update_incident(
            incident_id,
            {"event": "updated test event", "severity": "Medium"},
        )
        assert update_summary["updated_count"] == 1
        updated = supabase_client.get_incident(incident_id)
        assert updated is not None
        assert updated["event"] == "Updated Test Event"
        assert updated["severity"] == "Medium"

        delete_summary = supabase_client.delete_incident(incident_id)
        assert delete_summary["deleted_count"] == 1
        assert supabase_client.get_incident(incident_id) is None
    finally:
        (
            client.table(supabase_client.get_table_name())
            .delete()
            .eq("incident_id", incident_id)
            .eq("source", source)
            .execute()
        )

    remaining = (
        client.table(supabase_client.get_table_name())
        .select("incident_id")
        .eq("incident_id", incident_id)
        .eq("source", source)
        .execute()
    )
    assert remaining.data == []
