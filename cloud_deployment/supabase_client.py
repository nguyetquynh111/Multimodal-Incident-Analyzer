"""Supabase client setup and incident insertion helpers."""

import logging
import os
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


def get_supabase_client() -> Client:
    """Create a Supabase client using credentials from the project root.

    ``SUPABASE_SERVICE_ROLE_KEY`` is preferred when both supported key
    variables are present. Existing process environment variables are not
    overwritten by values from the root ``.env`` file.

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
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

    missing = []
    if not url:
        missing.append("SUPABASE_URL")
    if not key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")
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
