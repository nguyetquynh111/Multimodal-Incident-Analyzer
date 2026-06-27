"""Date parsing helpers for dashboard incident timelines."""

from __future__ import annotations

import re

import pandas as pd

DATE_SIGNAL_RE = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}(?!\d)|"
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b",
    re.IGNORECASE,
)
TWITTER_TIMESTAMP_RE = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+"
    r"\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\s+\d{4}\b",
    re.IGNORECASE,
)


def parse_incident_date(value: object):
    """Return a calendar date from an incident time value, or ``pd.NA``."""
    raw = "" if pd.isna(value) else str(value).strip()
    if raw.lower() in ("", "unknown", "n/a", "nan", "none", "null"):
        return pd.NA
    if not DATE_SIGNAL_RE.search(raw):
        return pd.NA

    match = TWITTER_TIMESTAMP_RE.search(raw)
    candidate = match.group(0) if match else raw
    parsed = pd.to_datetime(candidate, errors="coerce", utc=True)
    if pd.isna(parsed):
        return pd.NA
    return parsed.date()


def incident_dates(view: pd.DataFrame) -> pd.Series:
    """Parse dashboard timeline dates from the incident ``time`` column."""
    if "time" not in view.columns:
        return pd.Series(dtype="object")
    return view["time"].map(parse_incident_date)
