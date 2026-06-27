"""High-level service for uploading incident DataFrames."""

import logging
from typing import Any

import pandas as pd

from .supabase_client import insert_incidents
from .validators import validate_incidents_df
from integration.integration import to_supabase_payload_frame

logger = logging.getLogger(__name__)


def upload_incidents(df: pd.DataFrame) -> dict[str, Any]:
    """Validate and upload an integration-ready incident DataFrame.

    Args:
        df: DataFrame with the integration incident schema.

    Returns:
        The upload summary returned by :func:`insert_incidents`.

    Raises:
        TypeError: If the input is not a pandas DataFrame.
        ValueError: If the DataFrame fails validation.
        RuntimeError: If the Supabase upload fails.
    """
    logger.info("Starting incident upload.")
    payload = to_supabase_payload_frame(df)
    validate_incidents_df(payload)
    summary = insert_incidents(payload)
    logger.info("Incident upload completed.")
    return summary
