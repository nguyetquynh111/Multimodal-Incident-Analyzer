"""Supabase-backed final CSV export helpers."""

from __future__ import annotations

import pandas as pd

from integration.integration import to_final_csv_frame

from .supabase_client import query_incidents


def export_incidents_csv(*, limit: int = 1000) -> bytes:
    """Read incident rows from Supabase and return the approved CSV bytes."""

    rows = query_incidents(limit=limit)
    frame = to_final_csv_frame(pd.DataFrame(rows))
    return frame.to_csv(index=False).encode("utf-8")


__all__ = ["export_incidents_csv"]
