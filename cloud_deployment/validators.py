"""Validation for integration-ready incident DataFrames."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

INCIDENT_COLUMNS = (
    "incident_id",
    "source",
    "event",
    "location",
    "time",
    "severity",
)


def validate_incidents_df(df: pd.DataFrame) -> None:
    """Validate that a DataFrame is ready for the incidents table.

    The function only validates the integration output. It does not modify the
    DataFrame, create identifiers, or repair missing columns.

    Args:
        df: DataFrame formatted by the integration module.

    Raises:
        TypeError: If ``df`` is not a pandas DataFrame.
        ValueError: If the DataFrame is empty, has missing required columns, or
            contains invalid incident identifiers.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame for incident upload.")

    if df.empty:
        raise ValueError("The incidents DataFrame is empty.")

    missing_columns = [column for column in INCIDENT_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError(
            "The incidents DataFrame is missing required columns: "
            + ", ".join(missing_columns)
        )

    incident_ids = df["incident_id"]
    if incident_ids.isna().any():
        raise ValueError("The incident_id column contains null values.")

    try:
        numeric_ids = pd.to_numeric(incident_ids, errors="raise")
        integer_ids = numeric_ids.astype("int64")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "Every incident_id must be convertible to a 64-bit integer."
        ) from exc

    if not (numeric_ids == integer_ids).all():
        raise ValueError("Every incident_id must be a whole integer value.")

    logger.debug("Validated incidents DataFrame with %d rows.", len(df))
