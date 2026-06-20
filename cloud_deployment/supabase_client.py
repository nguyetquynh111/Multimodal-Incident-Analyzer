"""Supabase client setup and CRUD helpers for incidents."""

import logging
import os
from collections.abc import Mapping
from numbers import Integral
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except ImportError:  # Allows validation-only use before dependencies are installed.
    Client = Any
    create_client = None

from .validators import INCIDENT_COLUMNS

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TABLE_NAME = "incidents"
SELECT_COLUMNS = ("id", "created_at", *INCIDENT_COLUMNS)
QUERY_COLUMNS = frozenset(SELECT_COLUMNS)
UPDATABLE_COLUMNS = frozenset(INCIDENT_COLUMNS)


def get_supabase_client() -> Client:
    """Create a Supabase client using credentials from the project root.

    ``SUPABASE_SERVICE_ROLE_KEY`` is preferred, followed by
    ``SUPABASE_ANON_KEY`` and the compatibility name ``SUPABASE_KEY``.
    Existing process environment variables are not overwritten by values from
    the root ``.env`` file.

    Returns:
        An authenticated Supabase client.

    Raises:
        RuntimeError: If the URL or a supported API key is missing, or if the
            client cannot be created.
    """
    if create_client is None:
        raise RuntimeError(
            "The 'supabase' package is not installed. Install the root requirements first."
        )

    load_dotenv(PROJECT_ROOT / ".env", override=False)

    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_KEY")
    )

    missing = []
    if not url:
        missing.append("SUPABASE_URL")
    if not key:
        missing.append(
            "SUPABASE_SERVICE_ROLE_KEY, SUPABASE_ANON_KEY, or SUPABASE_KEY"
        )
    if missing:
        raise RuntimeError(
            "Missing required Supabase environment variable(s): " + ", ".join(missing)
        )

    try:
        return create_client(url, key)
    except Exception as exc:
        logger.exception("Could not create the Supabase client.")
        raise RuntimeError("Could not create the Supabase client.") from exc


def insert_incidents(df: pd.DataFrame) -> dict[str, Any]:
    """Insert integration-ready incidents into the Supabase incidents table.

    Only the six integration schema columns are sent. Database-generated
    ``id`` and ``created_at`` fields are intentionally omitted.

    Args:
        df: A validated incident DataFrame.

    Returns:
        A dictionary containing success status, inserted row count, and any
        row data returned by Supabase.

    Raises:
        RuntimeError: If Supabase rejects or cannot complete the insert.
    """
    upload_df = df.loc[:, list(INCIDENT_COLUMNS)].copy()
    upload_df["incident_id"] = pd.to_numeric(upload_df["incident_id"]).astype("int64")

    # Object dtype allows pandas null values to become JSON-compatible None.
    upload_df = upload_df.astype(object).where(pd.notna(upload_df), None)
    records = upload_df.to_dict(orient="records")
    for record in records:
        record["incident_id"] = int(record["incident_id"])

    logger.info("Uploading %d incident rows to Supabase.", len(records))
    client = get_supabase_client()

    try:
        response = client.table(TABLE_NAME).insert(records).execute()
    except Exception as exc:
        logger.exception("Supabase incident upload failed.")
        raise RuntimeError("Failed to insert incidents into Supabase.") from exc

    response_data = getattr(response, "data", None)
    logger.info("Successfully uploaded %d incident rows.", len(records))
    return {
        "success": True,
        "inserted_count": len(records),
        "data": response_data,
    }


def query_incidents(
    filters: Mapping[str, Any] | None = None,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return incidents matching optional equality filters.

    Args:
        filters: Optional column/value pairs. Supported columns are ``id``,
            ``created_at``, and the six incident data columns.
        limit: Maximum number of rows to return, from 1 through 1000.

    Raises:
        TypeError: If filters is not a mapping.
        ValueError: If a filter column or the limit is invalid.
        RuntimeError: If Supabase cannot complete the query.
    """
    query_filters = _validate_filters(filters)
    query_limit = _validate_limit(limit)
    client = get_supabase_client()

    try:
        query = client.table(TABLE_NAME).select(",".join(SELECT_COLUMNS))
        for column, value in query_filters.items():
            query = query.eq(column, value)
        response = query.limit(query_limit).execute()
    except Exception as exc:
        logger.exception("Supabase incident query failed.")
        raise RuntimeError("Failed to query incidents from Supabase.") from exc

    data = getattr(response, "data", None) or []
    logger.info("Queried %d incident rows from Supabase.", len(data))
    return data


def get_incident(incident_id: int) -> dict[str, Any] | None:
    """Return one incident by ``incident_id``, or ``None`` if absent."""
    validated_id = _validate_incident_id(incident_id)
    rows = query_incidents({"incident_id": validated_id}, limit=1)
    return rows[0] if rows else None


def update_incident(
    incident_id: int,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    """Update incident rows selected by their ``incident_id`` business key.

    Database-generated ``id`` and ``created_at`` fields cannot be updated.
    """
    validated_id = _validate_incident_id(incident_id)
    payload = _validate_updates(updates)
    client = get_supabase_client()

    try:
        response = (
            client.table(TABLE_NAME)
            .update(payload)
            .eq("incident_id", validated_id)
            .execute()
        )
    except Exception as exc:
        logger.exception("Supabase incident update failed.")
        raise RuntimeError("Failed to update incident in Supabase.") from exc

    data = getattr(response, "data", None) or []
    logger.info("Updated incident key %d.", validated_id)
    return {
        "success": True,
        "updated_count": len(data),
        "data": data,
    }


def delete_incident(incident_id: int) -> dict[str, Any]:
    """Delete incident rows selected by their ``incident_id`` business key."""
    validated_id = _validate_incident_id(incident_id)
    client = get_supabase_client()

    try:
        response = (
            client.table(TABLE_NAME)
            .delete()
            .eq("incident_id", validated_id)
            .execute()
        )
    except Exception as exc:
        logger.exception("Supabase incident deletion failed.")
        raise RuntimeError("Failed to delete incident from Supabase.") from exc

    data = getattr(response, "data", None) or []
    logger.info("Deleted incident key %d.", validated_id)
    return {
        "success": True,
        "deleted_count": len(data),
        "data": data,
    }


def _validate_row_id(row_id: int) -> int:
    if isinstance(row_id, bool) or not isinstance(row_id, Integral):
        raise TypeError("The database row id must be an integer.")
    if row_id <= 0:
        raise ValueError("The database row id must be greater than zero.")
    return int(row_id)


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, Integral):
        raise TypeError("Query limit must be an integer.")
    if not 1 <= limit <= 1000:
        raise ValueError("Query limit must be between 1 and 1000.")
    return int(limit)


def _validate_filters(
    filters: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise TypeError("Query filters must be a mapping of columns to values.")

    invalid_columns = sorted(set(filters) - QUERY_COLUMNS)
    if invalid_columns:
        raise ValueError("Unsupported query columns: " + ", ".join(invalid_columns))
    if any(value is None for value in filters.values()):
        raise ValueError("Query filter values cannot be None.")

    validated = dict(filters)
    if "id" in validated:
        validated["id"] = _validate_row_id(validated["id"])
    if "incident_id" in validated:
        validated["incident_id"] = _validate_incident_id(validated["incident_id"])
    return validated


def _validate_updates(updates: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(updates, Mapping):
        raise TypeError("Incident updates must be a mapping of columns to values.")
    if not updates:
        raise ValueError("At least one incident field is required for an update.")

    invalid_columns = sorted(set(updates) - UPDATABLE_COLUMNS)
    if invalid_columns:
        raise ValueError("Unsupported update columns: " + ", ".join(invalid_columns))

    payload = dict(updates)
    if "incident_id" in payload:
        payload["incident_id"] = _validate_incident_id(payload["incident_id"])
    return payload


def _validate_incident_id(incident_id: Any) -> int:
    if incident_id is None:
        raise ValueError("incident_id cannot be null.")
    try:
        numeric_id = pd.to_numeric(incident_id, errors="raise")
        integer_id = int(numeric_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("incident_id must be convertible to an integer.") from exc
    if numeric_id != integer_id:
        raise ValueError("incident_id must be a whole integer value.")
    return integer_id
