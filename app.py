"""Multimodal Incident Analyzer — Streamlit app (Stage 5: Dashboard / UI).

Owned by the Integration & Dashboard Lead (Student 6). Four views:

1. Ingest & Convert — upload one file, run its modality processor, convert the
   draft output to the final schema, and insert it into Supabase.
2. Integrate — UNION every modality's output CSV into the unified master
   dataset (the assignment's Final Integration Task) and push it to Supabase.
3. Dashboard — read incidents from Supabase, filter, chart, export the final CSV.
4. Manage Data — add / edit / delete rows via the CRUD helpers.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from integration import integration as ig
from cloud_deployment.supabase_client import (
    delete_incident,
    query_incidents,
    update_incident,
)
from cloud_deployment.upload_service import upload_incidents

st.set_page_config(
    page_title="Incident Analyzer", page_icon=":material/emergency:",
    layout="wide", initial_sidebar_state="expanded",
)

SEVERITY_ORDER = list(ig.SEVERITY_LEVELS)  # Low, Medium, High
SEV_COLORS = {"Low": "#16A34A", "Medium": "#D97706", "High": "#DC2626"}
# Material Symbol names per modality.
SOURCE_ICON = {"Audio": "mic", "PDF": "description", "Image": "image", "Video": "movie", "Text": "forum"}
FINAL_COLS = list(ig.FINAL_CSV_COLUMNS)

ACCENT = "#4F46E5"


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
def _hint(error: Exception) -> str:
    cause = getattr(error, "__cause__", None)
    return f"{error} ({cause})" if cause else str(error)


def load_incidents() -> pd.DataFrame:
    rows = query_incidents(limit=1000)
    df = pd.DataFrame(rows)
    if not df.empty and "id" in df.columns:
        df = df.sort_values("id", ascending=False, ignore_index=True)
    return df


def existing_incident_ids() -> list:
    try:
        return [r.get("incident_id") for r in query_incidents(limit=1000) if r.get("incident_id") is not None]
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def connection_ok() -> bool:
    try:
        query_incidents(limit=1)
        return True
    except Exception:
        return False


def _save_upload_to_tempdir(uploaded) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="incident_"))
    path = tmpdir / uploaded.name
    path.write_bytes(uploaded.getbuffer())
    return path


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
    return styler


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
# View 1: Ingest & Convert
# --------------------------------------------------------------------------- #
def view_ingest() -> None:
    _page_head("upload_file", "Ingest & Convert", "Upload one evidence file → AI extraction → final schema → Supabase.")

    uploaded = st.file_uploader("Upload one evidence file", type=ig.supported_extensions())
    if uploaded is None:
        st.info("Supported: audio (.wav .mp3 .m4a), PDF, image (.jpg .png), video (.mp4 .mov), text (.txt). "
                "Try `samples/social_post.txt`.")
        return

    source_type = ig.detect_source_type(uploaded.name)
    if source_type is None:
        st.error(f"Unsupported file type: {Path(uploaded.name).suffix or '(none)'}")
        return

    label = ig.source_label(source_type)
    st.markdown(
        f'<span class="badge b-info">{_icon(SOURCE_ICON.get(label, "description"))} '
        f'Detected: {label} · prefix {ig.source_prefix(source_type)}-</span>', unsafe_allow_html=True)
    st.write("")

    transcript = None
    if source_type == "audio":
        if not st.toggle("Transcribe with Whisper (needs torch + ffmpeg)", value=False):
            transcript = st.text_area(
                "Transcript (audio is analysed from this text)",
                value="There is a fire, people are trapped on the second floor of Main Street.", height=100)

    if st.button("Process file", type="primary", icon=":material/play_arrow:"):
        with st.spinner("Running modality processor + integration…"):
            try:
                path = _save_upload_to_tempdir(uploaded)
                draft_df = ig.run_modality(source_type, path, transcript=transcript)
                final_df = ig.build_incidents(draft_df, source_type, existing_incident_ids())
                st.session_state["ingest"] = {"draft": draft_df, "final": final_df, "filename": uploaded.name}
            except Exception as exc:  # noqa: BLE001
                st.session_state.pop("ingest", None)
                st.error(f"Processing failed: {_hint(exc)}")

    result = st.session_state.get("ingest")
    if not result or result.get("filename") != uploaded.name:
        return

    final_df = result["final"]
    c1, c2 = st.columns(2)
    with c1:
        _section("1 · Draft output (modality schema)")
        st.dataframe(result["draft"], width="stretch", hide_index=True)
    with c2:
        _section("2 · Final schema (ready for Supabase)")
        st.dataframe(_style_table(ig.to_final_csv_frame(final_df)), width="stretch", hide_index=True)

    d1, d2 = st.columns(2)
    d1.download_button(
        "Download final CSV", ig.to_final_csv_frame(final_df).to_csv(index=False).encode("utf-8"),
        file_name=f"{result['filename']}_incidents.csv", mime="text/csv",
        icon=":material/download:", width="stretch")
    if d2.button("Upload to Supabase", type="primary", icon=":material/cloud_upload:", width="stretch"):
        try:
            summary = upload_incidents(final_df)
            st.success(f"Inserted {summary['inserted_count']} row(s) into Supabase.")
            st.session_state.pop("ingest", None)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Upload failed: {_hint(exc)}")


# --------------------------------------------------------------------------- #
# View 2: Integrate (Final Integration Task)
# --------------------------------------------------------------------------- #
def view_integrate() -> None:
    _page_head("hub", "Integrate", "UNION every modality's output into one unified incident dataset.")

    status = ig.modality_output_status()
    _section("Modality outputs detected")
    cols = st.columns(len(ig.MODALITIES))
    for col, source_type in zip(cols, ig.MODALITIES):
        label = ig.source_label(source_type)
        col.markdown(
            f'<div class="mcard">{_icon(SOURCE_ICON.get(label, "description"))}'
            f'<div class="mname">{label}</div><div class="mcount">{status[source_type]} rows</div></div>',
            unsafe_allow_html=True)

    if sum(status.values()) == 0:
        st.warning("No modality output CSVs found. Each modality writes to its `*/output/` folder.")
        return

    st.write("")
    if st.button("Build unified dataset", type="primary", icon=":material/merge:"):
        with st.spinner("Merging all modalities…"):
            try:
                st.session_state["master"] = ig.build_master_dataset(existing_incident_ids())
            except Exception as exc:  # noqa: BLE001
                st.error(f"Merge failed: {_hint(exc)}")

    master = st.session_state.get("master")
    if master is None or master.empty:
        return

    final_view = ig.to_final_csv_frame(master)
    k = st.columns(3)
    _stat(k[0], "Total incidents", len(master), icon="summarize")
    _stat(k[1], "Modalities merged", master["source"].nunique(), color=ACCENT, icon="hub")
    _stat(k[2], "High severity", int(master["severity"].value_counts().get("High", 0)),
          color=SEV_COLORS["High"], icon="priority_high")

    st.write("")
    _section(f"Unified master dataset · {len(final_view)} incidents")
    st.dataframe(_style_table(final_view), width="stretch", hide_index=True)
    cc1, cc2 = st.columns(2)
    with cc1:
        _section("Records per source")
        st.altair_chart(_hbar(master["source"].value_counts(), "Source"), width="stretch")
    with cc2:
        _section("Severity by source")
        st.altair_chart(_severity_by_source(master), width="stretch")

    a, b, c = st.columns(3)
    a.download_button(
        "Download final CSV", final_view.to_csv(index=False).encode("utf-8"),
        file_name="final_incident_dataset.csv", mime="text/csv", icon=":material/download:", width="stretch")
    if b.button("Save to repo", icon=":material/save:", width="stretch",
                help="Write integration/output/final_incident_dataset.csv"):
        path = ig.write_final_dataset(master)
        st.success(f"Saved {path.relative_to(ig.PROJECT_ROOT)}")
    if c.button("Upload all to Supabase", type="primary", icon=":material/cloud_upload:", width="stretch"):
        try:
            summary = upload_incidents(master)
            st.success(f"Inserted {summary['inserted_count']} incidents into Supabase.")
            st.session_state.pop("master", None)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Upload failed: {_hint(exc)}")


# --------------------------------------------------------------------------- #
# View 3: Dashboard
# --------------------------------------------------------------------------- #
def view_dashboard() -> None:
    _page_head("insights", "Dashboard", "Live analytics over the Supabase incidents table.")

    try:
        df = load_incidents()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read from Supabase: {_hint(exc)}")
        return
    if df.empty:
        st.info("No incidents yet. Add some from **Ingest & Convert** or **Integrate**.")
        return

    df = ig.with_display_ids(df)

    with st.expander("Filters", expanded=False):
        c1, c2, c3 = st.columns(3)
        sources = sorted(df["source"].dropna().unique().tolist())
        severities = [s for s in SEVERITY_ORDER if s in df["severity"].unique()]
        pick_source = c1.multiselect("Source", sources, default=sources)
        pick_severity = c2.multiselect("Severity", severities, default=severities)
        search = c3.text_input("Search ID / event / location", "")

    view = df[df["source"].isin(pick_source) & df["severity"].isin(pick_severity)]
    if search:
        mask = pd.Series(False, index=view.index)
        for column in ("Incident_ID", "event", "location"):
            mask |= view[column].astype(str).str.contains(search, case=False, na=False)
        view = view[mask]

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
        high = final_view[final_view["Severity"] == "High"]
        if not high.empty:
            _section(f"High-priority queue · {len(high)}")
            st.dataframe(_style_table(high), width="stretch", hide_index=True)
        _section(f"All incidents · {len(final_view)}")
        st.dataframe(_style_table(final_view), width="stretch", hide_index=True)
        st.download_button(
            "Export final CSV (6 columns)", final_view.to_csv(index=False).encode("utf-8"),
            file_name="final_incident_dataset.csv", mime="text/csv", icon=":material/download:")


# --------------------------------------------------------------------------- #
# View 4: Manage Data (CRUD)
# --------------------------------------------------------------------------- #
@st.dialog("Add incident")
def _add_incident_dialog(existing_ids: list) -> None:
    source_type = st.selectbox("Source", list(ig.MODALITIES.keys()), format_func=ig.source_label)
    next_number = ig.next_incident_number(existing_ids)
    next_label = ig.display_id(ig.source_label(source_type), next_number)
    st.caption(f"New ID: `{next_label}`  (stored as incident_id = {next_number})")
    event = st.text_input("Event", "Unknown")
    location = st.text_input("Location", "Unknown")
    time_val = st.text_input("Time", "Unknown")
    severity = st.selectbox("Severity", SEVERITY_ORDER, index=1)
    if st.button("Save", type="primary", icon=":material/save:"):
        row = pd.DataFrame([{
            "incident_id": next_number, "source": ig.source_label(source_type),
            "event": event or "Unknown", "location": location or "Unknown",
            "time": time_val or "Unknown", "severity": severity}])
        try:
            upload_incidents(row)
            st.success(f"Added {next_label}")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Add failed: {_hint(exc)}")


def view_manage() -> None:
    _page_head("edit_note", "Manage Data", "Add, edit, or delete incidents directly in Supabase.")

    if st.button("Add incident", type="primary", icon=":material/add:"):
        _add_incident_dialog(existing_incident_ids())

    try:
        df = load_incidents()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read from Supabase: {_hint(exc)}")
        return
    if df.empty:
        st.info("No incidents yet. Use **Add incident** above.")
        return

    df = ig.with_display_ids(df)
    st.dataframe(_style_table(ig.to_final_csv_frame(df)), width="stretch", hide_index=True)

    st.divider()
    _section("Edit / delete a row")
    selected_label = st.selectbox("Select incident", df["Incident_ID"].tolist())
    current = df[df["Incident_ID"] == selected_label].iloc[0]
    selected_id = int(current["incident_id"])

    with st.form("edit_form"):
        event = st.text_input("Event", str(current.get("event", "")))
        location = st.text_input("Location", str(current.get("location", "")))
        time_val = st.text_input("Time", str(current.get("time", "")))
        sev_default = SEVERITY_ORDER.index(current["severity"]) if current.get("severity") in SEVERITY_ORDER else 1
        severity = st.selectbox("Severity", SEVERITY_ORDER, index=sev_default)
        c1, c2 = st.columns(2)
        do_update = c1.form_submit_button("Save changes", type="primary", icon=":material/save:", width="stretch")
        do_delete = c2.form_submit_button("Delete", icon=":material/delete:", width="stretch")

    if do_update:
        try:
            update_incident(selected_id, {"event": event, "location": location, "time": time_val, "severity": severity})
            st.success(f"Updated {selected_label}")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Update failed: {_hint(exc)}")
    if do_delete:
        try:
            delete_incident(selected_id)
            st.success(f"Deleted {selected_label}")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Delete failed: {_hint(exc)}")


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


PAGES = [
    ("Ingest & Convert", ":material/upload_file:", view_ingest),
    ("Integrate", ":material/hub:", view_integrate),
    ("Dashboard", ":material/insights:", view_dashboard),
    ("Manage Data", ":material/edit_note:", view_manage),
]


def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    _bridge_streamlit_secrets()
    st.session_state.setdefault("page", PAGES[0][0])

    with st.sidebar:
        st.markdown(f'<div class="sb-brand">{_icon("local_police")} Incident Analyzer</div>', unsafe_allow_html=True)
        st.markdown('<div class="sb-sub">Multimodal Crime / Incident Reports</div>', unsafe_allow_html=True)
        for name, icon, _ in PAGES:
            kind = "primary" if st.session_state["page"] == name else "secondary"
            if st.button(name, icon=icon, width="stretch", type=kind, key=f"nav_{name}"):
                st.session_state["page"] = name
                st.rerun()
        st.divider()
        if connection_ok():
            st.markdown(f'<span class="badge b-ok">{_icon("cloud_done")} Supabase connected</span>', unsafe_allow_html=True)
        else:
            st.markdown(f'<span class="badge b-bad">{_icon("cloud_off")} Supabase offline</span>', unsafe_allow_html=True)
        st.markdown('<div class="sb-sub" style="margin-top:.8rem;">Student 6 — Integration &amp; Dashboard</div>',
                    unsafe_allow_html=True)

    view = {name: fn for name, _, fn in PAGES}[st.session_state["page"]]
    view()


if __name__ == "__main__":
    main()
