"""Smoke test that executes the default Streamlit dashboard page."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def test_streamlit_dashboard_loads_without_an_exception() -> None:
    streamlit_testing = pytest.importorskip(
        "streamlit.testing.v1",
        reason="Streamlit is required for the dashboard smoke test.",
    )
    AppTest = streamlit_testing.AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.run(timeout=15)

    assert not app.exception


def test_incident_dates_use_time_column_not_created_at() -> None:
    from integration.dashboard_time import incident_dates

    dates = incident_dates(pd.DataFrame([
        {"created_at": "2026-06-27T12:00:00Z", "time": "June 20, 2026"},
        {"created_at": "2026-06-27T12:00:00Z", "time": "2026-06-21T08:30:00Z"},
        {"created_at": "2026-06-27T12:00:00Z", "time": "Sat Feb 01 05:11:45 +0000 2014"},
        {"created_at": "2026-06-27T12:00:00Z", "time": "Today, Fri Jan 31 07:22:18 +0000 2014"},
        {"created_at": "2026-06-27T12:00:00Z", "time": "00:00:12"},
        {"created_at": "2026-06-27T12:00:00Z", "time": "Unknown"},
    ]))

    assert dates.astype(str).tolist() == [
        "2026-06-20",
        "2026-06-21",
        "2014-02-01",
        "2014-01-31",
        "<NA>",
        "<NA>",
    ]
