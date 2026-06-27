"""Streamlit UI for the documented single-file incident workflow."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from integration import integration as ig
from cloud_deployment.supabase_client import (
    delete_incident,
    query_incidents,
    update_incident,
    validate_incident_key,
)
from cloud_deployment.exporter import export_incidents_csv
from cloud_deployment.upload_service import upload_incidents

st.set_page_config(
    page_title="Incident Analyzer", page_icon=":material/emergency:",
    layout="wide", initial_sidebar_state="expanded",
)

SEVERITY_ORDER = list(ig.SEVERITY_LEVELS)  # Low, Medium, High
SEV_COLORS = {"Low": "#16A34A", "Medium": "#D97706", "High": "#DC2626", "Unknown": "#64748B"}
# Material Symbol names per modality.
SOURCE_ICON = {
    "Audio": "mic",
    "PDF": "description",
    "Image": "image",
    "Video": "movie",
    "Text": "forum",
    "CSV": "table",
}
FINAL_COLS = list(ig.FINAL_CSV_COLUMNS)

ACCENT = "#4F46E5"
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
_CSS = """
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


def _icon(name: str, **style) -> str:
    css = ";".join(f"{k.replace('_','-')}:{v}" for k, v in style.items())
    return f'<span class="ms" style="{css}">{name}</span>'


def _page_head(icon: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="page-head"><div class="chip">{_icon(icon)}</div>'
        f'<div><div class="ph-title">{title}</div><div class="ph-sub">{subtitle}</div></div></div>',
        unsafe_allow_html=True,
    )


def _section(label: str) -> None:
    st.markdown(f'<div class="section">{label}</div>', unsafe_allow_html=True)


def _stat(col, label: str, value, color: str = "#0F172A", icon: str | None = None) -> None:
    head = _icon(icon, color=color, font_size="18px") if icon else ""
    col.markdown(
        f'<div class="statcard"><div class="statrow">{head}<span class="statlabel">{label}</span></div>'
        f'<div class="statval" style="color:{color}">{value}</div></div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Supabase helpers
# --------------------------------------------------------------------------- #
def _friendly_error(error: Exception, action: str) -> str:
    """Return useful guidance without exposing implementation details."""

    message = str(error).lower()
    if any(term in message for term in ("ffmpeg", "whisper", "transcrib", "audio")):
        return "We couldn't transcribe this audio. Please confirm the file plays correctly and try again."
    if any(term in message for term in ("unsupported", "file type", "extension")):
        return "This file type isn't supported yet. Please choose one of the listed evidence formats."
    if any(term in message for term in ("five-minute", "duration", "longer than 5")):
        return "This video is longer than five minutes, so it can't be processed in this prototype."
    if any(term in message for term in ("supabase", "postgrest", "connection", "network", "timeout")):
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
        return [r.get("incident_id") for r in query_incidents(limit=1000) if r.get("incident_id") is not None]
    except Exception as exc:
        logger.warning("Could not load existing incident IDs; using local counters. %s", type(exc).__name__)
        return []


def _safe_upload_filename(uploaded) -> str:
    """Return a basename-only filename safe to place inside a temp directory."""

    filename = Path(str(getattr(uploaded, "name", ""))).name.strip()
    return filename or "uploaded_evidence"


def _save_upload_to_tempdir(uploaded) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="incident_"))
    path = tmpdir / _safe_upload_filename(uploaded)
    path.write_bytes(uploaded.getbuffer())
    return path


def _cleanup_temp_path(path_value: str | os.PathLike[str] | None) -> None:
    """Remove app-created temp upload directories without touching user files."""

    if not path_value:
        return
    try:
        path = Path(path_value).resolve()
        parent = path.parent
        if parent.name.startswith("incident_") and parent.parent == Path(tempfile.gettempdir()).resolve():
            shutil.rmtree(parent, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Temp upload cleanup skipped for %s: %s", path_value, type(exc).__name__)


def _clear_ingest_state() -> None:
    result = st.session_state.pop("ingest", None)
    if isinstance(result, dict):
        _cleanup_temp_path(result.get("path"))


# --------------------------------------------------------------------------- #
# Presentation helpers
# --------------------------------------------------------------------------- #
def _style_table(display_df: pd.DataFrame):
    def sev(value):
        color = SEV_COLORS.get(value)
        return f"background-color: {color}1A; color: {color}; font-weight: 700;" if color else ""

    styler = display_df.style
    if "Severity" in display_df.columns:
        styler = styler.map(sev, subset=["Severity"])
    if "severity" in display_df.columns:
        styler = styler.map(sev, subset=["severity"])
    return styler


def _review_queue() -> dict[str, dict]:
    """Return reviews collected in this browser session, keyed by filename."""

    return st.session_state.setdefault("review_queue", {})


def _queue_review(filename: str, source_type: str, draft: pd.DataFrame) -> None:
    """Save a completed review so it can be included in the master UNION."""

    queue = _review_queue()
    previous = queue.get(filename)
    has_changed = (
        previous is None
        or previous["source_type"] != source_type
        or not previous["draft"].equals(draft)
    )
    queue[filename] = {"source_type": source_type, "draft": draft.copy()}
    if has_changed:
        # A previously combined result is stale after a new or updated review.
        st.session_state.pop("master", None)


def _sync_current_review() -> None:
    """Include the currently displayed review in the session's master queue."""

    result = st.session_state.get("ingest")
    if not result or "draft" not in result or "filename" not in result:
        return
    source_type = result.get("source_type") or ig.detect_source_type(result["filename"])
    if source_type:
        _queue_review(result["filename"], source_type, result["draft"])


def _queued_review_status() -> dict[str, int]:
    status = {source_type: 0 for source_type in ig.MODALITIES}
    for item in _review_queue().values():
        status[item["source_type"]] += 1
    return status


def _build_queued_incidents(existing_ids: list) -> pd.DataFrame:
    """Integrate and UNION each queued modality review into one master frame."""

    frames: list[pd.DataFrame] = []
    used_ids = list(existing_ids)
    for filename, item in _review_queue().items():
        frame = ig.integrate_records(
            item["draft"], item["source_type"], used_ids, source_filename=filename
        )
        frames.append(frame)
        used_ids.extend(frame["Incident_ID"].tolist())

    if not frames:
        return pd.DataFrame(columns=list(ig.INTEGRATION_OUTPUT_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def _severity_donut(view: pd.DataFrame) -> alt.Chart:
    counts = (
        view["severity"].value_counts().reindex(SEVERITY_ORDER).fillna(0)
        .rename_axis("Severity").reset_index(name="Count")
    )
    return (
        alt.Chart(counts).mark_arc(innerRadius=58, cornerRadius=4).encode(
            theta="Count:Q",
            color=alt.Color(
                "Severity:N",
                scale=alt.Scale(domain=SEVERITY_ORDER, range=[SEV_COLORS[s] for s in SEVERITY_ORDER]),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=["Severity", "Count"],
        ).properties(height=250)
    )


def _hbar(series: pd.Series, label: str, color: str = "#6366F1") -> alt.Chart:
    df = series.rename_axis(label).reset_index(name="Count")
    return (
        alt.Chart(df).mark_bar(cornerRadiusEnd=5, color=color).encode(
            x=alt.X("Count:Q", title=None),
            y=alt.Y(f"{label}:N", sort="-x", title=None),
            tooltip=[label, "Count"],
        ).properties(height=250)
    )


def _severity_scale() -> alt.Scale:
    return alt.Scale(domain=SEVERITY_ORDER, range=[SEV_COLORS[s] for s in SEVERITY_ORDER])


def _severity_by_source(view: pd.DataFrame) -> alt.Chart:
    """Stacked bar: severity composition within each modality."""
    g = view.groupby(["source", "severity"], as_index=False).size().rename(columns={"size": "Count"})
    return (
        alt.Chart(g).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("source:N", title=None, sort="-y"),
            y=alt.Y("Count:Q", title=None),
            color=alt.Color("severity:N", scale=_severity_scale(), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["source", "severity", "Count"],
        ).properties(height=290)
    )


def _heatmap_source_severity(view: pd.DataFrame) -> alt.Chart:
    """Source × severity matrix with counts."""
    g = view.groupby(["source", "severity"], as_index=False).size().rename(columns={"size": "Count"})
    base = alt.Chart(g).encode(
        x=alt.X("severity:N", sort=SEVERITY_ORDER, title=None),
        y=alt.Y("source:N", title=None),
    )
    heat = base.mark_rect().encode(
        color=alt.Color("Count:Q", scale=alt.Scale(scheme="purpleblue"), legend=None),
        tooltip=["source", "severity", "Count"],
    )
    text = base.mark_text(fontWeight="bold").encode(
        text="Count:Q",
        color=alt.condition("datum.Count > 1", alt.value("white"), alt.value("#334155")),
    )
    return (heat + text).properties(height=250)


def _known_locations(view: pd.DataFrame) -> pd.DataFrame:
    return view[~view["location"].astype(str).str.lower().isin(["unknown", "n/a", "nan", ""])]


def _top_locations(view: pd.DataFrame):
    counts = _known_locations(view)["location"].value_counts().head(8)
    return _hbar(counts, "Location", color="#0EA5E9") if not counts.empty else None


def _timeline(view: pd.DataFrame):
    if "created_at" not in view.columns:
        return None
    t = view.copy()
    t["Date"] = pd.to_datetime(t["created_at"], errors="coerce").dt.date
    t = t.dropna(subset=["Date"])
    if t.empty:
        return None
    g = t.groupby("Date", as_index=False).size().rename(columns={"size": "Count"})
    return (
        alt.Chart(g).mark_area(line={"color": "#6366F1"}, opacity=0.25, color="#A5B4FC").encode(
            x=alt.X("Date:T", title=None), y=alt.Y("Count:Q", title=None), tooltip=["Date", "Count"]
        ).properties(height=240)
    )


# --------------------------------------------------------------------------- #
# Visual evidence helpers
# --------------------------------------------------------------------------- #
def _sentiment_badge(sentiment: str) -> str:
    colors = {
        "Negative": ("#FEE2E2", "#991B1B"),
        "Positive": ("#DCFCE7", "#166534"),
        "Distressed": ("#FEE2E2", "#991B1B"),
        "Concerned": ("#FEF3C7", "#92400E"),
        "Calm": ("#DCFCE7", "#166534"),
        "Neutral": ("#EEF2FF", "#4338CA"),
    }
    bg, fg = colors.get(sentiment, ("#F1F5F9", "#334155"))
    return (
        f'<span style="background:{bg};color:{fg};padding:3px 10px;'
        f'border-radius:999px;font-size:.8rem;font-weight:700">{sentiment}</span>'
    )


def _show_audio_evidence(draft_df: pd.DataFrame, file_path: str | None = None) -> None:
    import re as _re
    if file_path:
        st.audio(file_path)
    if draft_df.empty:
        return
    row = draft_df.iloc[0]

    score = float(row.get("Urgency_Score", 0) or 0)
    label = "Distressed" if score >= 0.65 else "Concerned" if score >= 0.40 else "Calm"
    color = SEV_COLORS["High"] if score >= 0.65 else SEV_COLORS["Medium"] if score >= 0.40 else SEV_COLORS["Low"]
    sentiment = str(row.get("Sentiment", ""))

    col_u, col_s = st.columns(2)
    with col_u:
        st.markdown(f'**Urgency — <span style="color:{color}">{label}</span>** `{score:.2f}`', unsafe_allow_html=True)
        st.progress(min(1.0, score))
    with col_s:
        st.markdown("**Sentiment**")
        st.markdown(_sentiment_badge(sentiment), unsafe_allow_html=True)

    transcript = str(row.get("Transcript", ""))
    if transcript and transcript.lower() not in ("unknown", "nan", ""):
        incident_words = [
            "fire", "shot", "shots", "fight", "accident", "robbery", "assault",
            "emergency", "help", "police", "ambulance", "knife", "gun", "dead",
            "injured", "hurt", "bleeding", "attack", "stolen", "crash",
        ]
        highlighted = transcript
        for word in incident_words:
            highlighted = _re.sub(
                rf"\b({_re.escape(word)})\b",
                r'<mark style="background:#FEF08A;border-radius:3px;padding:0 2px">\1</mark>',
                highlighted,
                flags=_re.IGNORECASE,
            )
        st.markdown("**Transcript**")
        st.markdown(
            f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;'
            f'padding:12px;font-size:.9rem;line-height:1.7">{highlighted}</div>',
            unsafe_allow_html=True,
        )


def _show_image_evidence(draft_df: pd.DataFrame, file_path: str | None = None) -> None:
    """Show the uploaded image with the processor's scene, object, and OCR evidence."""

    import html as _html

    if file_path and Path(file_path).exists():
        detections = draft_df.attrs.get("image_detections", []) if isinstance(draft_df, pd.DataFrame) else []
        try:
            from images.processor import annotate_image_with_detections

            annotated_image = annotate_image_with_detections(file_path, detections=detections)
            has_boxes = bool(detections)
            st.image(
                annotated_image,
                caption="Uploaded image with detection boxes" if has_boxes else "Uploaded image",
                width="stretch",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not annotate image evidence: %s", exc)
            st.image(file_path, caption="Uploaded image", width="stretch")
    elif file_path:
        st.caption("Source image is no longer available for preview.")

    if draft_df.empty:
        return

    row = draft_df.iloc[0]
    scene = str(row.get("Scene_Type", "Unknown")).strip()
    objects = str(row.get("Objects_Detected", "Unknown")).strip()
    extracted_text = str(row.get("Text_Extracted", "Unknown")).strip()
    confidence_raw = row.get("Confidence_Score", 0)
    try:
        confidence = float(confidence_raw)
        if pd.isna(confidence):
            confidence = 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    scene_display = "—" if scene.lower() in ("unknown", "nan", "") else scene
    col_scene, col_confidence = st.columns(2)
    col_scene.metric("Scene classification", scene_display)
    col_confidence.metric("Detection confidence", f"{confidence:.0%}")
    st.progress(confidence)

    if objects.lower() not in ("unknown", "nan", ""):
        chips = "".join(
            f'<span style="display:inline-block;background:#EDE9FE;color:#5B21B6;'
            f'padding:3px 9px;margin:2px 3px;border-radius:999px;'
            f'font-size:.8rem;font-weight:700">{_html.escape(item.strip())}</span>'
            for item in objects.split(",")
            if item.strip()
        )
        if chips:
            st.markdown("**Detected objects**")
            st.markdown(chips, unsafe_allow_html=True)

    if extracted_text.lower() not in ("unknown", "nan", ""):
        st.markdown("**Text found in image**")
        st.markdown(
            f'<div style="background:#F8FAFC;border-left:4px solid {ACCENT};'
            f'border-radius:0 8px 8px 0;padding:12px 16px;font-size:.9rem;'
            f'line-height:1.7;color:#334155;white-space:pre-wrap">'
            f'{_html.escape(extracted_text)}</div>',
            unsafe_allow_html=True,
        )


def _show_pdf_evidence(draft_df: pd.DataFrame, file_path: str | None = None) -> None:
    if draft_df.empty:
        return
    row = draft_df.iloc[0]

    fields = [
        ("Incident_Type", "Incident type"),
        ("Date", "Date"),
        ("Location", "Location"),
        ("Officer", "Officer"),
    ]
    cols = st.columns(4)
    for col, (field, label) in zip(cols, fields):
        val = str(row.get(field, "Unknown"))
        col.metric(label, val if val not in ("Unknown", "nan", "") else "—")

    # Show full extracted text from the file, falling back to the 240-char Summary
    full_text = ""
    if file_path:
        try:
            import fitz as _fitz
            doc = _fitz.open(file_path)
            full_text = "\n\n".join(page.get_text() for page in doc).strip()
            doc.close()
        except Exception:
            pass
    if not full_text:
        full_text = str(row.get("Summary", ""))

    if full_text and full_text.lower() not in ("unknown", "nan", ""):
        import html as _html, re as _re

        pdf_entities = []
        for etype, val in [
            ("LOCATION", row.get("Location", "")),
            ("DATE",     row.get("Date", "")),
            ("PERSON",   row.get("Officer", "")),
        ]:
            val = str(val).strip()
            if val and val.lower() not in ("unknown", "nan", ""):
                pdf_entities.append(f"{etype}: {val}")
        highlighted = (
            _highlight_entities_in_text(full_text, "; ".join(pdf_entities))
            if pdf_entities
            else _html.escape(full_text)
        )

        # Highlight the exact trigger keywords the processor matched — same patterns
        # as pdf/processor.py's _INCIDENT_KEYWORDS so the highlight proves the label
        _PDF_TRIGGER_PATTERNS = {
            "Theft / Robbery":    r"\b(?:robber(?:y|ies)|robbed|burglar(?:y|ies|s)?|theft|stolen|shoplift(?:ing|ed)?|larceny)\b",
            "Assault / Violence": r"\b(?:assault(?:s|ed)?|battery|stabb(?:ing|ed)|shooting|shots fired|homicide|murder)\b",
            "Fire / Arson":       r"\barson(?:ist)?\b",
            "Traffic Accident":   r"\b(?:collision|traffic accident|car crash|vehicle crash|hit[- ]and[- ]run)\b",
            "Public Disturbance": r"\b(?:riot(?:ing|s)?|vandalism|disturbance|trespass(?:ing)?)\b",
        }
        pattern = _PDF_TRIGGER_PATTERNS.get(str(row.get("Incident_Type", "")))
        if pattern:
            highlighted = _re.sub(
                pattern,
                lambda m: (
                    f'<span style="background:#FED7AA;color:#9A3412;'
                    f'border-radius:4px;padding:1px 4px;font-weight:600">'
                    f'{m.group(0)}</span>'
                ),
                highlighted,
                flags=_re.IGNORECASE,
            )

        st.markdown("**Extracted text**")
        st.markdown(
            f'<div style="background:#F8FAFC;border-left:4px solid {ACCENT};'
            f'border-radius:0 8px 8px 0;padding:12px 16px;font-size:.9rem;'
            f'line-height:1.7;color:#334155;white-space:pre-wrap">{highlighted}</div>',
            unsafe_allow_html=True,
        )


_ENTITY_COLORS: dict[str, tuple[str, str]] = {
    "LOCATION":     ("#DBEAFE", "#1D4ED8"),
    "PERSON":       ("#FCE7F3", "#9D174D"),
    "ORGANIZATION": ("#D1FAE5", "#065F46"),
    "DATE":         ("#FEF3C7", "#92400E"),
}


def _entity_chip(etype: str, value: str) -> str:
    bg, fg = _ENTITY_COLORS.get(etype.upper(), ("#F1F5F9", "#334155"))
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'padding:2px 8px;margin:2px 3px;border-radius:6px;'
        f'font-size:.8rem;font-weight:600">{etype}: {value}</span>'
    )


def _highlight_entities_in_text(text: str, entities_raw: str) -> str:
    """Return HTML of text with entity values wrapped in colored spans."""
    import re as _re
    import html as _html

    # Parse into [(type, value), ...]
    pairs: list[tuple[str, str]] = []
    for group in entities_raw.split(";"):
        group = group.strip()
        if ":" in group:
            etype, _, values = group.partition(":")
            etype = etype.strip().upper()
            for v in values.split(","):
                v = v.strip()
                if v and len(v) > 2:
                    pairs.append((etype, v))

    # Sort longest value first to avoid partial-match clobbering
    pairs.sort(key=lambda p: len(p[1]), reverse=True)

    # Escape HTML in source text first
    escaped = _html.escape(text)

    # Replace each entity value with a highlighted span (case-insensitive, whole-word preferred)
    used: set[str] = set()
    for etype, value in pairs:
        key = value.lower()
        if key in used:
            continue
        used.add(key)
        bg, fg = _ENTITY_COLORS.get(etype, ("#F1F5F9", "#334155"))
        span = (
            f'<span style="background:{bg};color:{fg};border-radius:4px;'
            f'padding:1px 4px;font-weight:600">{_html.escape(value)}</span>'
        )
        escaped = _re.sub(
            rf"(?i)({_re.escape(_html.escape(value))})",
            span,
            escaped,
            count=1,
        )
    return escaped


def _show_text_evidence(draft_df: pd.DataFrame) -> None:
    if draft_df.empty:
        return

    for _, row in draft_df.head(5).iterrows():
        sentiment = str(row.get("Sentiment", ""))
        topic = str(row.get("Topic", ""))
        entities_raw = str(row.get("Entities", ""))
        raw_text = str(row.get("Raw_Text", ""))

        badges = _sentiment_badge(sentiment)
        if topic and topic.lower() not in ("unknown", "nan", ""):
            badges += (
                f'&nbsp;<span style="background:#EDE9FE;color:#5B21B6;padding:3px 10px;'
                f'border-radius:999px;font-size:.8rem;font-weight:700">{topic}</span>'
            )
        st.markdown(badges, unsafe_allow_html=True)

        if raw_text and raw_text.lower() not in ("unknown", "nan", ""):
            if entities_raw and entities_raw.lower() not in ("unknown", "nan", ""):
                highlighted = _highlight_entities_in_text(raw_text, entities_raw)
            else:
                import html as _html
                highlighted = _html.escape(raw_text)
            st.markdown(
                f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;'
                f'padding:12px 14px;font-size:.88rem;line-height:1.8;color:#334155;'
                f'white-space:pre-wrap;margin-top:6px">{highlighted}</div>',
                unsafe_allow_html=True,
            )
        st.write("")


def _show_video_evidence(file_path: str | None, filename: str) -> None:
    from pathlib import Path as _Path
    import tempfile as _tempfile

    if not file_path or not _Path(file_path).exists():
        st.caption("Source file is no longer available for frame extraction.")
        return

    # Transcode to H.264 MP4 so any input format plays in the browser
    cache_key = f"video_bytes_{filename}"
    video_bytes = st.session_state.get(cache_key)
    if video_bytes is None:
        import subprocess as _sp, tempfile as _tf
        with _tf.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = _sp.run(
                [
                    "ffmpeg", "-y", "-i", file_path,
                    "-vcodec", "libx264", "-acodec", "aac",
                    "-movflags", "+faststart", tmp_path,
                ],
                capture_output=True,
                timeout=180,
            )
            if result.returncode == 0:
                video_bytes = _Path(tmp_path).read_bytes()
            else:
                logger.warning("ffmpeg preview transcode failed for %s.", filename)
                video_bytes = _Path(file_path).read_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ffmpeg preview transcode skipped for %s: %s", filename, type(exc).__name__)
            video_bytes = _Path(file_path).read_bytes()
        finally:
            _Path(tmp_path).unlink(missing_ok=True)
        st.session_state[cache_key] = video_bytes
    st.video(video_bytes)

    cache_key = f"frames_dir_{filename}"
    frames_dir: _Path | None = st.session_state.get(cache_key)

    import base64 as _b64

    def _render_gallery(paths):
        tiles = ""
        for fp in paths:
            img_b64 = _b64.b64encode(fp.read_bytes()).decode()
            tiles += (
                f'<div style="flex:0 0 30%;min-width:200px">'
                f'<img src="data:image/jpeg;base64,{img_b64}" style="width:100%;border-radius:6px">'
                f'<div style="font-size:.75rem;color:#64748B;text-align:center;margin-top:3px">{fp.stem}</div>'
                f'</div>'
            )
        return (
            f'<div style="display:flex;flex-wrap:wrap;gap:10px;max-height:480px;'
            f'overflow-y:auto;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px">'
            f'{tiles}</div>'
        )

    if frames_dir is None:
        try:
            from video.processor import process_video_stream
            frames_dir = _Path(_tempfile.mkdtemp(prefix="frames_"))
            frame_paths: list[_Path] = []
            status = st.empty()
            gallery = st.empty()

            for _row, frame_path in process_video_stream(file_path, annotated_frames_dir=frames_dir):
                if frame_path:
                    frame_paths.append(_Path(frame_path))
                    status.caption(f"Processing… {len(frame_paths)} frames done")
                    gallery.markdown(_render_gallery(frame_paths), unsafe_allow_html=True)
                    import time as _time; _time.sleep(0)

            status.caption(f"{len(frame_paths)} annotated frames")
            if not frame_paths:
                gallery.caption("No annotated frames were produced (video may have no motion).")
            st.session_state[cache_key] = frames_dir
        except Exception as exc:
            st.caption(f"Could not extract frames: {exc}")
            return
    else:
        frame_paths = sorted(_Path(frames_dir).rglob("*.jpg"))
        if not frame_paths:
            st.caption("No annotated frames were produced (video may have no motion).")
            return
        st.caption(f"{len(frame_paths)} annotated frames")
        st.markdown(_render_gallery(frame_paths), unsafe_allow_html=True)


def _show_visual_evidence(
    source_type: str,
    draft_df: pd.DataFrame,
    file_path: str | None,
    filename: str,
) -> None:
    with st.expander("Visual evidence", expanded=True):
        if source_type == "audio":
            _show_audio_evidence(draft_df, file_path)
        elif source_type == "pdf":
            _show_pdf_evidence(draft_df, file_path)
        elif source_type == "image":
            _show_image_evidence(draft_df, file_path)
        elif source_type == "video":
            _show_video_evidence(file_path, filename)
        elif source_type == "text":
            _show_text_evidence(draft_df)
        else:
            st.caption("Visual evidence is not available for this modality yet.")


# --------------------------------------------------------------------------- #
# View 1: Ingest & Convert
# --------------------------------------------------------------------------- #
def view_ingest() -> None:
    _page_head("upload_file", "Add Incident", "Choose a file and we'll turn it into a clear incident record.")

    uploaded = st.file_uploader("Choose an evidence file", type=ig.supported_extensions())
    if uploaded is None:
        st.info("You can add an audio recording, document, image, text file, or CSV file.")
        return

    uploaded_filename = _safe_upload_filename(uploaded)
    source_type = ig.detect_source_type(uploaded_filename)
    if source_type is None:
        st.error("We can't review this file type yet. Please choose an audio, document, image, video, text, or CSV file.")
        return

    label = ig.source_label(source_type)
    st.markdown(
        f'<span class="badge b-info">{_icon(SOURCE_ICON.get(label, "description"))} '
        f'Ready to review · {label}</span>', unsafe_allow_html=True)
    st.write("")

    if source_type == "audio":
        st.info("We'll create a written transcript from this recording.")

    if st.button("Review evidence", type="primary", icon=":material/play_arrow:"):
        path: Path | None = None
        with st.spinner("Reviewing your file…"):
            try:
                _clear_ingest_state()
                path = _save_upload_to_tempdir(uploaded)
                draft_df = ig.run_modality(source_type, path)
                final_df = ig.integrate_records(
                    draft_df,
                    source_type,
                    existing_incident_ids(),
                    source_filename=uploaded_filename,
                )
                _queue_review(uploaded_filename, source_type, draft_df)
                st.session_state["ingest"] = {
                    "draft": draft_df,
                    "final": final_df,
                    "filename": uploaded_filename,
                    "source_type": source_type,
                    "path": str(path),
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception("Evidence processing failed")
                _cleanup_temp_path(path)
                _clear_ingest_state()
                st.error(_friendly_error(exc, "review this evidence"))

    result = st.session_state.get("ingest")
    if not result or result.get("filename") != uploaded_filename:
        return

    final_df = result["final"]
    st.caption(f"Extractor rows: {len(result['draft'])} · Integrated incident rows: {len(final_df)}")
    if final_df.empty:
        st.info("No incidents were found in this evidence. Nothing will be inserted.")
        return
    c1, c2 = st.columns(2)
    with c1:
        _section("What we found")
        st.dataframe(result["draft"], width="stretch", hide_index=True)
    with c2:
        _section("Incident record")
        st.dataframe(_style_table(final_df), width="stretch", hide_index=True)

    _section("Visual evidence")
    _show_visual_evidence(
        result.get("source_type", source_type),
        result["draft"],
        result.get("path"),
        uploaded_filename,
    )

    if st.button("Add to incident records", type="primary", icon=":material/cloud_upload:", width="stretch"):
        try:
            summary = upload_incidents(final_df)
            st.success(f"Added {summary['inserted_count']} incident record(s).")
            _clear_ingest_state()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Incident upload failed")
            st.error(_friendly_error(exc, "add this incident"))


# --------------------------------------------------------------------------- #
# View 2: Integrate (Final Integration Task)
# --------------------------------------------------------------------------- #
def view_integrate() -> None:
    _page_head("hub", "Combine Reports", "Bring completed evidence reviews into one organized incident list.")

    _sync_current_review()
    status = _queued_review_status()
    _section("Available evidence reviews")
    cols = st.columns(len(ig.MODALITIES))
    for col, source_type in zip(cols, ig.MODALITIES):
        label = ig.source_label(source_type)
        count = status[source_type]
        count_label = "review" if count == 1 else "reviews"
        col.markdown(
            f'<div class="mcard">{_icon(SOURCE_ICON.get(label, "description"))}'
            f'<div class="mname">{label}</div><div class="mcount">{count} {count_label}</div></div>',
            unsafe_allow_html=True,
        )

    st.caption("Counts include every evidence file reviewed during this browser session.")
    if sum(status.values()) == 0:
        st.info("No completed evidence reviews are available yet. Start by adding an evidence file.")
        return

    st.write("")
    if st.button("Combine reports", type="primary", icon=":material/merge:"):
        with st.spinner("Bringing the reports together…"):
            try:
                st.session_state["master"] = _build_queued_incidents(existing_incident_ids())
            except Exception as exc:  # noqa: BLE001
                logger.exception("Report combination failed")
                st.error(_friendly_error(exc, "combine these reports"))

    master = st.session_state.get("master")
    if master is None or master.empty:
        return

    k = st.columns(3)
    _stat(k[0], "Total incidents", len(master), icon="summarize")
    _stat(k[1], "Evidence types", master["Source"].nunique(), color=ACCENT, icon="hub")
    _stat(
        k[2], "High severity", int(master["Severity"].value_counts().get("High", 0)),
        color=SEV_COLORS["High"], icon="priority_high",
    )

    st.write("")
    _section(f"Combined incident list · {len(master)} incidents")
    st.dataframe(_style_table(master), width="stretch", hide_index=True)

    chart_data = ig.to_supabase_payload_frame(master)
    cc1, cc2 = st.columns(2)
    with cc1:
        _section("Records per source")
        st.altair_chart(_hbar(chart_data["source"].value_counts(), "Source"), width="stretch")
    with cc2:
        _section("Severity by source")
        st.altair_chart(_severity_by_source(chart_data), width="stretch")

    st.download_button(
        "Download combined report", master.to_csv(index=False).encode("utf-8"),
        file_name="final_incident_dataset.csv", mime="text/csv",
        icon=":material/download:", width="stretch",
    )


# --------------------------------------------------------------------------- #
# View 3: Dashboard
# --------------------------------------------------------------------------- #
def view_dashboard() -> None:
    _page_head("insights", "Incident Overview", "See priorities, patterns, and recent activity at a glance.")

    try:
        df = load_incidents()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Incident loading failed")
        st.error(_friendly_error(exc, "load incident records"))
        return
    if df.empty:
        st.info("No incidents have been added yet. Start with **Add Incident**.")
        return

    df = ig.with_display_ids(df)

    with st.expander("Filters", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        sources = sorted(df["source"].dropna().unique().tolist())
        severities = [s for s in SEVERITY_ORDER if s in df["severity"].unique()]
        pick_source = c1.multiselect("Source", sources, default=sources)
        pick_severity = c2.multiselect("Severity", severities, default=severities)
        pick_id = c3.text_input("Incident ID", "")
        pick_event = c4.text_input("Event", "")
        pick_location = c5.text_input("Location", "")

    view = df[df["source"].isin(pick_source) & df["severity"].isin(pick_severity)]
    for column, query in (("Incident_ID", pick_id), ("event", pick_event), ("location", pick_location)):
        if query:
            view = view[view[column].astype(str).str.contains(query, case=False, regex=False, na=False)]

    counts = view["severity"].value_counts()
    k = st.columns(4)
    _stat(k[0], "Total incidents", len(view), icon="summarize")
    _stat(k[1], "High", int(counts.get("High", 0)), color=SEV_COLORS["High"], icon="local_fire_department")
    _stat(k[2], "Medium", int(counts.get("Medium", 0)), color=SEV_COLORS["Medium"], icon="warning")
    _stat(k[3], "Low", int(counts.get("Low", 0)), color=SEV_COLORS["Low"], icon="check_circle")
    st.write("")

    if view.empty:
        st.info("No incidents match the current filters.")
        return

    tab_overview, tab_breakdown, tab_records = st.tabs(["Overview", "Breakdown", "Records"])

    with tab_overview:
        c1, c2 = st.columns([1, 1.3])
        with c1:
            _section("By severity")
            st.altair_chart(_severity_donut(view), width="stretch")
        with c2:
            _section("By source")
            st.altair_chart(_hbar(view["source"].value_counts(), "Source"), width="stretch")
        timeline = _timeline(view)
        if timeline is not None:
            _section("Incidents over time")
            st.altair_chart(timeline, width="stretch")

    with tab_breakdown:
        c1, c2 = st.columns(2)
        with c1:
            _section("Severity by source")
            st.altair_chart(_severity_by_source(view), width="stretch")
        with c2:
            _section("Source × severity")
            st.altair_chart(_heatmap_source_severity(view), width="stretch")
        c3, c4 = st.columns(2)
        with c3:
            _section("Location hotspots")
            loc_chart = _top_locations(view)
            if loc_chart is not None:
                st.altair_chart(loc_chart, width="stretch")
            else:
                st.caption("No known locations yet.")
        with c4:
            _section("Top events")
            st.altair_chart(_hbar(view["event"].value_counts().head(8), "Event", color="#7C3AED"), width="stretch")

        known = _known_locations(view)
        if not known.empty:
            _section("Location hotspot table")
            hotspots = (
                known.groupby("location")
                .agg(Incidents=("incident_id", "count"), High=("severity", lambda s: int((s == "High").sum())))
                .reset_index().rename(columns={"location": "Location"})
                .sort_values(["Incidents", "High"], ascending=False).head(10)
            )
            st.dataframe(hotspots, width="stretch", hide_index=True)

    with tab_records:
        final_view = ig.to_final_csv_frame(view)
        high = final_view[final_view["severity"] == "High"]
        if not high.empty:
            _section(f"High-priority queue · {len(high)}")
            st.dataframe(_style_table(high), width="stretch", hide_index=True)
        _section(f"All incidents · {len(final_view)}")
        st.dataframe(_style_table(final_view), width="stretch", hide_index=True)
        selected_id = st.selectbox("Selected incident", view["Incident_ID"].tolist())
        selected = view.loc[view["Incident_ID"] == selected_id].iloc[0]
        st.text_area(
            "Incident summary",
            str(selected.get("incident_summary", "Unknown")),
            height=110,
            disabled=True,
        )
        st.download_button(
            "Download incident report", export_incidents_csv(),
            file_name="final_incident_dataset.csv", mime="text/csv", icon=":material/download:")


# --------------------------------------------------------------------------- #
# View 4: Manage Data (CRUD)
# --------------------------------------------------------------------------- #
@st.dialog("Add incident")
def _add_incident_dialog(existing_ids: list) -> None:
    source_type = st.selectbox("Source", list(ig.MODALITIES.keys()), format_func=ig.source_label)
    next_label = ig.generate_next_incident_id(source_type, existing_ids)
    st.caption(f"New incident ID: `{next_label}`")
    event = st.text_input("Event", "Unknown")
    location = st.text_input("Location", "Unknown")
    time_val = st.text_input("Time", "Unknown")
    severity = st.selectbox("Severity", SEVERITY_ORDER, index=1)
    incident_summary = st.text_area("Incident summary", "Unknown", height=90)
    if st.button("Save", type="primary", icon=":material/save:"):
        draft = pd.DataFrame([{
            "Event": event,
            "Location": location or "Unknown",
            "Time": time_val or "Unknown",
            "Severity": severity,
            "Summary": incident_summary or "Unknown",
        }])
        row = ig.integrate_records(draft, source_type, existing_ids)
        if incident_summary and incident_summary.strip():
            row["Incident_Summary"] = incident_summary.strip()
        try:
            upload_incidents(row)
            st.success(f"Added {row.iloc[0]['Incident_ID']}")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Manual incident creation failed")
            st.error(_friendly_error(exc, "add this incident"))


def view_manage() -> None:
    _page_head("edit_note", "Manage Incidents", "Add new incidents or keep existing details up to date.")

    notice = st.session_state.pop("manage_notice", None)
    if notice:
        st.success(notice)

    if st.button("Add incident", type="primary", icon=":material/add:"):
        _add_incident_dialog(existing_incident_ids())

    try:
        df = load_incidents()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Incident loading failed")
        st.error(_friendly_error(exc, "load incident records"))
        return
    if df.empty:
        st.info("No incidents yet. Use **Add incident** above.")
        return

    df = ig.with_display_ids(df)

    with st.expander("Bulk actions", expanded=False):
        st.caption("Update several incidents at once or remove a group. Incident IDs and sources never change.")
        filter_source_col, filter_severity_col, filter_search_col = st.columns(3)
        available_sources = sorted(df["source"].dropna().unique().tolist())
        available_severities = [
            severity for severity in SEVERITY_ORDER if severity in df["severity"].unique()
        ]
        bulk_sources = filter_source_col.multiselect(
            "Filter by source",
            available_sources,
            default=available_sources,
            key="bulk_filter_sources",
        )
        bulk_severities = filter_severity_col.multiselect(
            "Filter by severity",
            available_severities,
            default=available_severities,
            key="bulk_filter_severities",
        )
        bulk_search = filter_search_col.text_input(
            "Search ID, event, or location",
            key="bulk_filter_search",
        )

        filtered = df[
            df["source"].isin(bulk_sources)
            & df["severity"].isin(bulk_severities)
        ]
        if bulk_search:
            search_mask = pd.Series(False, index=filtered.index)
            for column in ("Incident_ID", "event", "location"):
                search_mask |= filtered[column].astype(str).str.contains(
                    bulk_search,
                    case=False,
                    regex=False,
                    na=False,
                )
            filtered = filtered[search_mask]
        target_labels = filtered["Incident_ID"].tolist()
        st.info(f"{len(target_labels)} of {len(df)} incidents selected by these filters.")

        field_labels = st.multiselect(
            "Fields to update",
            ["Event", "Location", "Time", "Severity", "Incident summary"],
            help="Only selected fields will be overwritten.",
            key="bulk_fields",
        )
        bulk_values: dict[str, str] = {}
        input_columns = st.columns(2)
        if "Event" in field_labels:
            bulk_values["event"] = input_columns[0].text_input(
                "New event", key="bulk_event"
            )
        if "Location" in field_labels:
            bulk_values["location"] = input_columns[1].text_input(
                "New location", key="bulk_location"
            )
        if "Time" in field_labels:
            bulk_values["time"] = input_columns[0].text_input(
                "New time", key="bulk_time"
            )
        if "Severity" in field_labels:
            bulk_values["severity"] = input_columns[1].selectbox(
                "New severity", SEVERITY_ORDER, index=1, key="bulk_severity"
            )
        if "Incident summary" in field_labels:
            bulk_values["incident_summary"] = st.text_area(
                "New incident summary",
                key="bulk_incident_summary",
                height=90,
            )

        target_count = len(target_labels)
        confirm_remove = st.checkbox(
            f"I understand that removing {target_count} incident(s) cannot be undone.",
            key="confirm_bulk_remove",
        )
        update_col, remove_col = st.columns(2)
        do_bulk_update = update_col.button(
            f"Update {target_count} incident(s)",
            type="primary",
            icon=":material/edit:",
            width="stretch",
            disabled=target_count == 0 or not field_labels,
        )
        remove_label = (
            "Remove all incidents"
            if target_count == len(df)
            else f"Remove {target_count} incident(s)"
        )
        do_bulk_remove = remove_col.button(
            remove_label,
            icon=":material/delete:",
            width="stretch",
            disabled=target_count == 0 or not confirm_remove,
        )

    if do_bulk_update or do_bulk_remove:
        targets = df[df["Incident_ID"].isin(target_labels)]
        succeeded = 0
        failures: list[str] = []
        for _, target in targets.iterrows():
            label = str(target["Incident_ID"])
            try:
                if do_bulk_remove:
                    incident_key = validate_incident_key(target["Incident_ID"])
                    delete_incident(incident_key)
                else:
                    incident_key = validate_incident_key(target["Incident_ID"])
                    payload = {
                        field: (
                            ig.normalize_event(value)
                            if field == "event"
                            else (str(value).strip() or "Unknown")
                        )
                        for field, value in bulk_values.items()
                    }
                    if ig.normalize_event(payload.get("event", target["event"])) == "Unknown":
                        payload["severity"] = "Low"
                    update_incident(incident_key, payload)
                succeeded += 1
            except Exception:  # noqa: BLE001
                logger.exception("Bulk incident action failed for %s", label)
                failures.append(label)

        if failures:
            action = "removed" if do_bulk_remove else "updated"
            st.error(
                f"{succeeded} incident(s) were {action}, but {len(failures)} could not be changed. "
                "Please try those records again."
            )
            return

        action = "removed" if do_bulk_remove else "updated"
        st.session_state["manage_notice"] = f"Successfully {action} {succeeded} incident(s)."
        st.rerun()

    _section("Incident list")
    st.caption("Edit any unlocked cell. Select Remove for records you no longer need, then apply your changes.")

    editable = df.loc[:, ["Incident_ID", "source", "event", "location", "time", "severity", "incident_summary"]].copy()
    editable["remove"] = False

    with st.form("incident_table_form"):
        edited = st.data_editor(
            editable,
            width="stretch",
            hide_index=True,
            disabled=["Incident_ID", "source"],
            column_order=[
                "Incident_ID",
                "source",
                "event",
                "location",
                "time",
                "severity",
                "incident_summary",
                "remove",
            ],
            column_config={
                "Incident_ID": st.column_config.TextColumn("Incident ID", width="small"),
                "source": st.column_config.TextColumn("Source", width="small"),
                "event": st.column_config.TextColumn("Event", width="large", required=True),
                "location": st.column_config.TextColumn("Location", width="medium", required=True),
                "time": st.column_config.TextColumn("Time", width="medium", required=True),
                "severity": st.column_config.SelectboxColumn(
                    "Severity",
                    options=SEVERITY_ORDER,
                    required=True,
                    width="small",
                ),
                "incident_summary": st.column_config.TextColumn(
                    "Incident summary",
                    width="large",
                    required=True,
                ),
                "remove": st.column_config.CheckboxColumn(
                    "Remove",
                    help="Checked incidents will be deleted when you apply changes.",
                    default=False,
                    width="small",
                ),
            },
            num_rows="fixed",
            key="incident_editor",
        )
        apply_changes = st.form_submit_button(
            "Apply changes",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )

    if not apply_changes:
        return

    original = df.set_index("Incident_ID", drop=False)
    updated_count = 0
    deleted_count = 0
    failures: list[str] = []

    def clean(value) -> str:
        return "Unknown" if pd.isna(value) or not str(value).strip() else str(value).strip()

    for _, row in edited.iterrows():
        label = str(row["Incident_ID"])
        current = original.loc[label]
        try:
            incident_id = validate_incident_key(current["Incident_ID"])
            if bool(row["remove"]):
                delete_incident(incident_id)
                deleted_count += 1
                continue

            changes = {
                field: (
                    ig.normalize_event(row[field])
                    if field == "event"
                    else clean(row[field])
                )
                for field in ("event", "location", "time", "severity")
                if (
                    ig.normalize_event(row[field]) != ig.normalize_event(current[field])
                    if field == "event"
                    else clean(row[field]) != clean(current[field])
                )
            }
            summary = clean(row["incident_summary"])
            if summary != clean(current["incident_summary"]):
                changes["incident_summary"] = summary
            if ig.normalize_event(row["event"]) == "Unknown":
                changes["severity"] = "Low"
            if changes:
                update_incident(incident_id, changes)
                updated_count += 1
        except Exception:  # noqa: BLE001
            logger.exception("Incident table change failed for %s", label)
            failures.append(label)

    if failures:
        saved_count = updated_count + deleted_count
        st.error(
            f"We couldn't save changes for {len(failures)} incident(s). "
            f"{saved_count} other change(s) were saved. Please try again."
        )
        return

    if not updated_count and not deleted_count:
        st.info("No changes to apply.")
        return

    parts = []
    if updated_count:
        parts.append(f"updated {updated_count}")
    if deleted_count:
        parts.append(f"removed {deleted_count}")
    st.session_state["manage_notice"] = "Changes saved: " + " and ".join(parts) + "."
    st.rerun()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _bridge_streamlit_secrets() -> None:
    try:
        secrets = dict(st.secrets)
    except Exception:
        return
    for key in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        if key in secrets and not os.environ.get(key):
            os.environ[key] = str(secrets[key])


@st.cache_resource(show_spinner=False)
def _start_whisper_preload() -> bool:
    def load() -> None:
        try:
            from audio.transcribe import preload_whisper_model

            preload_whisper_model(quiet=True)
        except Exception as exc:  # noqa: BLE001
            logger.info("Whisper preload skipped: %s", type(exc).__name__)

    threading.Thread(target=load, name="whisper-preload", daemon=True).start()
    return True


PAGES = [
    ("Add Incident", ":material/upload_file:", view_ingest),
    ("Combine Reports", ":material/hub:", view_integrate),
    ("Incident Overview", ":material/insights:", view_dashboard),
    ("Manage Incidents", ":material/edit_note:", view_manage),
]


def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    _bridge_streamlit_secrets()
    _start_whisper_preload()
    page_names = {name for name, _, _ in PAGES}
    if st.session_state.get("page") not in page_names:
        st.session_state["page"] = PAGES[0][0]

    with st.sidebar:
        st.markdown(f'<div class="sb-brand">{_icon("local_police")} Incident Analyzer</div>', unsafe_allow_html=True)
        st.markdown('<div class="sb-sub">Evidence review and incident insights</div>', unsafe_allow_html=True)
        for name, icon, _ in PAGES:
            kind = "primary" if st.session_state["page"] == name else "secondary"
            if st.button(name, icon=icon, width="stretch", type=kind, key=f"nav_{name}"):
                st.session_state["page"] = name
                st.rerun()

    view = {name: fn for name, _, fn in PAGES}[st.session_state["page"]]
    view()


if __name__ == "__main__":
    main()
