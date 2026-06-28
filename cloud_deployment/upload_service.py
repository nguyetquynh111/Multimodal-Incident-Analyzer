"""High-level service for uploading incident DataFrames."""

import logging
from typing import Any

import pandas as pd

from .supabase_client import insert_incidents, query_incidents
from .validators import validate_incidents_df
from integration.integration import (
    generate_incident_id,
    next_incident_number,
    normalize_source_type,
    to_supabase_payload_frame,
)

logger = logging.getLogger(__name__)


def _existing_incident_ids() -> list[str]:
    """Read saved incident IDs so inserts get a fresh key at upload time."""

    return [
        str(row["incident_id"])
        for row in query_incidents(limit=1000)
        if row.get("incident_id") is not None
    ]


def _assign_fresh_incident_ids(
    payload: pd.DataFrame, existing_ids: list[str]
) -> pd.DataFrame:
    """Return a payload copy with IDs that follow the current Supabase state."""

    refreshed = payload.copy()
    counters = {
        source_type: next_incident_number(existing_ids, source_type) - 1
        for source_type in ("audio", "pdf", "image", "video", "text")
    }
    assigned_ids: list[str] = []
    for source in refreshed["source"]:
        source_type = normalize_source_type(str(source))
        counters[source_type] += 1
        assigned_ids.append(generate_incident_id(source_type, counters[source_type]))
    refreshed["incident_id"] = assigned_ids
    return refreshed


def upload_incidents(df: pd.DataFrame, *, refresh_ids: bool = False) -> dict[str, Any]:
    """Validate and upload an integration-ready incident DataFrame.

    Args:
        df: DataFrame with the integration incident schema.
        refresh_ids: When true, re-read saved IDs and assign fresh
            ``INC_TYPE_NUMBER`` values immediately before insert.

    Returns:
        The upload summary returned by :func:`insert_incidents`.

    Raises:
        TypeError: If the input is not a pandas DataFrame.
        ValueError: If the DataFrame fails validation.
        RuntimeError: If the Supabase upload fails.
    """
    logger.info("Starting incident upload.")
    payload = to_supabase_payload_frame(df)
    if refresh_ids:
        payload = _assign_fresh_incident_ids(payload, _existing_incident_ids())
    validate_incidents_df(payload)
    summary = insert_incidents(payload)
    summary["incident_ids"] = payload["incident_id"].tolist()
    logger.info("Incident upload completed.")
    return summary
