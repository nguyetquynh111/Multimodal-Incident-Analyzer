"""Support helpers for the Streamlit incident app.

This module keeps styling, charting, temporary-upload state, and lightweight
data helpers.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from cloud_deployment.supabase_client import query_incidents
from integration import integration as ig
from integration.dashboard_time import incident_dates


logger = logging.getLogger(__name__)

SEVERITY_ORDER = list(ig.SEVERITY_LEVELS)
SEV_COLORS = {
    "Low": "#16A34A",
    "Medium": "#D97706",
    "High": "#DC2626",
    "Unknown": "#64748B",
}
SOURCE_ICON = {
    "Audio": "mic",
    "PDF": "description",
    "Image": "image",
    "Video": "movie",
    "Text": "forum",
    "CSV": "table",
}
ACCENT = "#4F46E5"

_TEMP_UPLOAD_DIRS: set[Path] = getattr(sys, "_mia_temp_upload_dirs", set())
setattr(sys, "_mia_temp_upload_dirs", _TEMP_UPLOAD_DIRS)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0&display=block');

html, body, [class*="css"], [data-testid="stMarkdownContainer"] { font-family:'Inter',sans-serif; }
.ms { font-family:'Material Symbols Rounded'; font-size:20px; line-height:1; vertical-align:middle; }

/* Hide only the menu, footer, and Deploy button — never the header or the
   sidebar collapse/expand controls (those live in the header region). */
#MainMenu, footer, [data-testid="stAppDeployButton"] { display:none !important; }
.stApp { background:#F6F7FB; }
.block-container { padding-top:4.5rem; padding-bottom:3rem; max-width:1180px; }

/* page header */
.page-head { display:flex; align-items:center; gap:.9rem; margin-bottom:1.4rem; }
.chip { width:46px; height:46px; border-radius:13px; display:flex; align-items:center; justify-content:center;
        background:linear-gradient(135deg,#4F46E5,#7C3AED); color:#fff; box-shadow:0 8px 18px -8px rgba(79,70,229,.6); }
.chip .ms { font-size:26px; color:#fff; }
.ph-title { font-size:1.4rem; font-weight:800; letter-spacing:-.02em; color:#0F172A; line-height:1.15; }
.ph-sub { font-size:.9rem; color:#64748B; margin-top:1px; }

/* cards */
.statcard, .mcard { background:#fff; border:1px solid #ECEEF5; border-radius:16px;
    box-shadow:0 1px 3px rgba(16,24,40,.05); }
.statcard { padding:.85rem 1.1rem; }
.statrow { display:flex; align-items:center; gap:.4rem; }
.statlabel { font-size:.8rem; color:#64748B; font-weight:600; }
.statval { font-size:1.7rem; font-weight:800; margin-top:.15rem; line-height:1.1; }
.mcard { padding:1rem .6rem; text-align:center; }
.mcard .ms { font-size:26px; color:#6366F1; }
.mname { font-weight:700; font-size:.9rem; color:#0F172A; margin-top:.3rem; }
.mcount { color:#64748B; font-size:.8rem; }

[data-testid="stMetric"] { background:#fff; border:1px solid #ECEEF5; border-radius:16px;
    padding:1rem 1.15rem; box-shadow:0 1px 3px rgba(16,24,40,.05); }

/* sidebar */
[data-testid="stSidebar"] { background:#0F172A; }
[data-testid="stSidebar"] * { color:#E2E8F0; }
.sb-brand { display:flex; align-items:center; gap:.5rem; font-size:1.12rem; font-weight:800; color:#fff; }
.sb-brand .ms { font-size:22px; color:#A5B4FC; }
.sb-sub { font-size:.78rem; color:#94A3B8; margin:.1rem 0 .6rem; }
[data-testid="stSidebar"] .stButton>button { justify-content:flex-start; background:transparent;
    border:none; color:#CBD5E1; font-weight:600; padding:.45rem .7rem; }
[data-testid="stSidebar"] .stButton>button:hover { background:#1E293B; color:#fff; }
[data-testid="stSidebar"] .stButton>button[kind="primary"] { background:#4F46E5; color:#fff; }

/* badges */
.badge { display:inline-flex; align-items:center; gap:.35rem; padding:.25rem .7rem; border-radius:999px;
    font-size:.76rem; font-weight:700; }
.badge .ms { font-size:15px; }
.b-ok { background:#DCFCE7; color:#166534; } .b-bad { background:#FEE2E2; color:#991B1B; }
.b-info { background:#EEF2FF; color:#4338CA; }

.stButton>button, .stDownloadButton>button { border-radius:10px; font-weight:600; }
.section { font-size:.74rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase;
    color:#64748B; margin:.4rem 0 .4rem; }
</style>
"""


def _render_icon(name: str, **style) -> str:
    css = ";".join(f"{k.replace('_', '-')}:{v}" for k, v in style.items())
    return f'<span class="ms" style="{css}">{name}</span>'


def icon(name: str, **style) -> str:
    return _render_icon(name, **style)


def page_head(icon_name: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="page-head"><div class="chip">{icon(icon_name)}</div>'
        f'<div><div class="ph-title">{title}</div><div class="ph-sub">{subtitle}</div></div></div>',
        unsafe_allow_html=True,
    )


def section(label: str) -> None:
    st.markdown(f'<div class="section">{label}</div>', unsafe_allow_html=True)


def stat(
    col, label: str, value, color: str = "#0F172A", icon: str | None = None
) -> None:
    head = _render_icon(icon, color=color, font_size="18px") if icon else ""
    col.markdown(
        f'<div class="statcard"><div class="statrow">{head}<span class="statlabel">{label}</span></div>'
        f'<div class="statval" style="color:{color}">{value}</div></div>',
        unsafe_allow_html=True,
    )


def friendly_error(error: Exception, action: str) -> str:
    """Return useful guidance without exposing implementation details."""

    message = str(error).lower()
    if any(term in message for term in ("ffmpeg", "whisper", "transcrib", "audio")):
        return "We couldn't transcribe this audio. Please confirm the file plays correctly and try again."
    if any(term in message for term in ("unsupported", "file type", "extension")):
        return "This file type isn't supported yet. Please choose one of the listed evidence formats."
    if any(term in message for term in ("five-minute", "duration", "longer than 5")):
        return "This video is longer than five minutes, so it can't be processed in this prototype."
    if any(
        term in message
        for term in ("supabase", "postgrest", "connection", "network", "timeout")
    ):
        return "Incident records are temporarily unavailable. Please try again in a moment."
    return f"We couldn't {action}. Please check your file or entries and try again."


def load_incidents() -> pd.DataFrame:
    rows = query_incidents(limit=1000)
    df = pd.DataFrame(rows)
    if not df.empty and "id" in df.columns:
        df = df.sort_values("id", ascending=False, ignore_index=True)
    return df


def existing_incident_ids() -> list:
    try:
        return [
            r.get("incident_id")
            for r in query_incidents(limit=1000)
            if r.get("incident_id") is not None
        ]
    except Exception as exc:
        logger.warning(
            "Could not load existing incident IDs; using local counters. %s",
            type(exc).__name__,
        )
        return []


def safe_upload_filename(uploaded) -> str:
    """Return a basename-only filename safe to place inside a temp directory."""

    filename = Path(str(getattr(uploaded, "name", ""))).name.strip()
    return filename or "uploaded_evidence"


def save_upload_to_tempdir(uploaded) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="incident_"))
    _TEMP_UPLOAD_DIRS.add(tmpdir.resolve())
    path = tmpdir / safe_upload_filename(uploaded)
    path.write_bytes(uploaded.getbuffer())
    return path


def cleanup_temp_path(path_value: str | os.PathLike[str] | None) -> None:
    """Remove app-created temp upload directories without touching user files."""

    if not path_value:
        return
    try:
        path = Path(path_value).resolve()
        parent = path.parent
        if (
            parent.name.startswith("incident_")
            and parent.parent == Path(tempfile.gettempdir()).resolve()
        ):
            shutil.rmtree(parent, ignore_errors=True)
            _TEMP_UPLOAD_DIRS.discard(parent)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Temp upload cleanup skipped for %s: %s", path_value, type(exc).__name__
        )


def clear_ingest_state() -> None:
    result = st.session_state.pop("ingest", None)
    if isinstance(result, dict):
        cleanup_temp_path(result.get("path"))


def cleanup_registered_temp_uploads() -> None:
    for tmpdir in list(_TEMP_UPLOAD_DIRS):
        shutil.rmtree(tmpdir, ignore_errors=True)
        _TEMP_UPLOAD_DIRS.discard(tmpdir)


if not getattr(sys, "_mia_temp_cleanup_registered", False):
    atexit.register(cleanup_registered_temp_uploads)
    setattr(sys, "_mia_temp_cleanup_registered", True)


def style_table(display_df: pd.DataFrame):
    def sev(value):
        color = SEV_COLORS.get(value)
        return (
            f"background-color: {color}1A; color: {color}; font-weight: 700;"
            if color
            else ""
        )

    styler = display_df.style
    if "Severity" in display_df.columns:
        styler = styler.map(sev, subset=["Severity"])
    if "severity" in display_df.columns:
        styler = styler.map(sev, subset=["severity"])
    return styler


def review_queue() -> dict[str, dict]:
    """Return reviews collected in this browser session, keyed by filename."""

    return st.session_state.setdefault("review_queue", {})


def queue_review(filename: str, source_type: str, draft: pd.DataFrame) -> None:
    """Save a completed review so it can be included in the master UNION."""

    queue = review_queue()
    previous = queue.get(filename)
    has_changed = (
        previous is None
        or previous["source_type"] != source_type
        or not previous["draft"].equals(draft)
    )
    queue[filename] = {"source_type": source_type, "draft": draft.copy()}
    if has_changed:
        st.session_state.pop("master", None)


def sync_current_review() -> None:
    """Include the currently displayed review in the session's master queue."""

    result = st.session_state.get("ingest")
    if not result or "draft" not in result or "filename" not in result:
        return
    source_type = result.get("source_type") or ig.detect_source_type(result["filename"])
    if source_type:
        queue_review(result["filename"], source_type, result["draft"])


def queued_review_status() -> dict[str, int]:
    status = {source_type: 0 for source_type in ig.MODALITIES}
    for item in review_queue().values():
        status[item["source_type"]] += 1
    return status


def build_queued_incidents(existing_ids: list) -> pd.DataFrame:
    """Integrate and UNION each queued modality review into one master frame."""

    frames: list[pd.DataFrame] = []
    used_ids = list(existing_ids)
    for filename, item in review_queue().items():
        frame = ig.integrate_records(
            item["draft"], item["source_type"], used_ids, source_filename=filename
        )
        frames.append(frame)
        used_ids.extend(frame["Incident_ID"].tolist())

    if not frames:
        return pd.DataFrame(columns=list(ig.INTEGRATION_OUTPUT_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def severity_donut(view: pd.DataFrame) -> alt.Chart:
    counts = (
        view["severity"]
        .value_counts()
        .reindex(SEVERITY_ORDER)
        .fillna(0)
        .rename_axis("Severity")
        .reset_index(name="Count")
    )
    return (
        alt.Chart(counts)
        .mark_arc(innerRadius=58, cornerRadius=4)
        .encode(
            theta="Count:Q",
            color=alt.Color(
                "Severity:N",
                scale=alt.Scale(
                    domain=SEVERITY_ORDER, range=[SEV_COLORS[s] for s in SEVERITY_ORDER]
                ),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=["Severity", "Count"],
        )
        .properties(height=250)
    )


def hbar(series: pd.Series, label: str, color: str = "#6366F1") -> alt.Chart:
    df = series.rename_axis(label).reset_index(name="Count")
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=5, color=color)
        .encode(
            x=alt.X("Count:Q", title=None),
            y=alt.Y(f"{label}:N", sort="-x", title=None),
            tooltip=[label, "Count"],
        )
        .properties(height=250)
    )


def severity_scale() -> alt.Scale:
    return alt.Scale(
        domain=SEVERITY_ORDER, range=[SEV_COLORS[s] for s in SEVERITY_ORDER]
    )


def severity_by_source(view: pd.DataFrame) -> alt.Chart:
    """Stacked bar: severity composition within each modality."""

    grouped = (
        view.groupby(["source", "severity"], as_index=False)
        .size()
        .rename(columns={"size": "Count"})
    )
    return (
        alt.Chart(grouped)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("source:N", title=None, sort="-y"),
            y=alt.Y("Count:Q", title=None),
            color=alt.Color(
                "severity:N",
                scale=severity_scale(),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=["source", "severity", "Count"],
        )
        .properties(height=290)
    )


def heatmap_source_severity(view: pd.DataFrame) -> alt.Chart:
    """Source x severity matrix with counts."""

    grouped = (
        view.groupby(["source", "severity"], as_index=False)
        .size()
        .rename(columns={"size": "Count"})
    )
    base = alt.Chart(grouped).encode(
        x=alt.X("severity:N", sort=SEVERITY_ORDER, title=None),
        y=alt.Y("source:N", title=None),
    )
    heat = base.mark_rect().encode(
        color=alt.Color("Count:Q", scale=alt.Scale(scheme="purpleblue"), legend=None),
        tooltip=["source", "severity", "Count"],
    )
    text = base.mark_text(fontWeight="bold").encode(
        text="Count:Q",
        color=alt.condition(
            "datum.Count > 1", alt.value("white"), alt.value("#334155")
        ),
    )
    return (heat + text).properties(height=250)


def known_locations(view: pd.DataFrame) -> pd.DataFrame:
    return view[
        ~view["location"].astype(str).str.lower().isin(["unknown", "n/a", "nan", ""])
    ]


def top_locations(view: pd.DataFrame):
    counts = known_locations(view)["location"].value_counts().head(8)
    return hbar(counts, "Location", color="#0EA5E9") if not counts.empty else None


def timeline(view: pd.DataFrame):
    timed = view.copy()
    timed["Date"] = incident_dates(timed)
    timed = timed.dropna(subset=["Date"])
    if timed.empty:
        return None
    grouped = (
        timed.groupby("Date", as_index=False).size().rename(columns={"size": "Count"})
    )
    return (
        alt.Chart(grouped)
        .mark_area(line={"color": "#6366F1"}, opacity=0.25, color="#A5B4FC")
        .encode(
            x=alt.X("Date:T", title="Incident date"),
            y=alt.Y("Count:Q", title=None),
            tooltip=["Date", "Count"],
        )
        .properties(height=240)
    )


def manual_summary_override(value: object) -> str | None:
    """Return a real manual summary, ignoring blank/default placeholder values."""

    text = str(value or "").strip()
    if not text or text.casefold() == "unknown":
        return None
    return text


def bridge_streamlit_secrets() -> None:
    try:
        secrets = dict(st.secrets)
    except Exception:
        return
    for key in (
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        if key in secrets and not os.environ.get(key):
            os.environ[key] = str(secrets[key])


@st.cache_resource(show_spinner=False)
def start_whisper_preload() -> bool:
    def load() -> None:
        try:
            from audio.transcribe import preload_whisper_model

            preload_whisper_model(quiet=True)
        except Exception as exc:  # noqa: BLE001
            logger.info("Whisper preload skipped: %s", type(exc).__name__)

    threading.Thread(target=load, name="whisper-preload", daemon=True).start()
    return True
