"""Smoke test that executes the default Streamlit dashboard page."""

from __future__ import annotations

from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip(
    "streamlit.testing.v1",
    reason="Streamlit is required for the dashboard smoke test.",
)
AppTest = streamlit_testing.AppTest


def test_streamlit_dashboard_loads_without_an_exception() -> None:
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.run(timeout=15)

    assert not app.exception
