"""Validation for integration-ready incident DataFrames."""

import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

INCIDENT_COLUMNS = (
    "incident_id",
    "source",
    "event",
    "location",
    "time",
    "severity",
    "incident_summary",
)

ID_PATTERN = re.compile(r"^INC_(AUD|PDF|IMG|VID|TXT)_\d{3,}$")
SEVERITY_LEVELS = {"Low", "Medium", "High", "Unknown"}


def validate_incidents_df(df: pd.DataFrame) -> None:
    """Validate that a DataFrame is ready for the incidents table.

    The function only validates the integration output. It does not modify the
    DataFrame, create identifiers, or repair missing columns.

    Args:
        df: DataFrame formatted by the integration module.

    Raises:
        TypeError: If ``df`` is not a pandas DataFrame.
        ValueError: If the DataFrame is empty, has missing required columns, or
            contains invalid incident identifiers or enum values.
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

    id_text = incident_ids.astype(str)
    if not id_text.map(lambda value: bool(ID_PATTERN.match(value))).all():
        raise ValueError("Every incident_id must follow INC_TYPE_NUMBER, such as INC_PDF_001.")

    if id_text.duplicated().any():
        raise ValueError("Every incident_id must be unique within an upload.")

    for column in ("source", "event", "location", "time", "incident_summary"):
        if df[column].isna().any():
            raise ValueError(f"The {column} column contains null values.")
        if df[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"The {column} column contains blank values.")

    if not df["severity"].isin(SEVERITY_LEVELS).all():
        raise ValueError("Severity must be Low, Medium, High, or Unknown.")

    unknown_event = df["event"].astype(str).str.strip().str.match(
        r"^unknown(?:\b|[_/-])", case=False, na=False
    )
    if (df.loc[unknown_event, "severity"] != "Low").any():
        raise ValueError("Severity must be Low when event is Unknown.")

    logger.debug("Validated incidents DataFrame with %d rows.", len(df))
