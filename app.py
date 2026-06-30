"""Streamlit UI for the incident workflow."""
from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()

import logging
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Incident Analyzer",
    page_icon=":material/emergency:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from integration import integration as ig
from cloud_deployment.exporter import export_incidents_csv
from cloud_deployment.upload_service import upload_incidents
from integration.app_support import (
    ACCENT,
    CSS as _CSS,
    SEVERITY_ORDER,
    SEV_COLORS,
    SOURCE_ICON,
    bridge_streamlit_secrets as _bridge_streamlit_secrets,
    build_queued_incidents as _build_queued_incidents,
    clear_ingest_state as _clear_ingest_state,
    cleanup_temp_path as _cleanup_temp_path,
    existing_incident_ids,
    friendly_error as _friendly_error,
    hbar as _hbar,
    heatmap_source_severity as _heatmap_source_severity,
    icon as _icon,
    known_locations as _known_locations,
    load_incidents,
    page_head as _page_head,
    queue_review as _queue_review,
    queued_review_status as _queued_review_status,
    safe_upload_filename as _safe_upload_filename,
    save_upload_to_tempdir as _save_upload_to_tempdir,
    section as _section,
    severity_by_source as _severity_by_source,
    severity_donut as _severity_donut,
    start_whisper_preload as _start_whisper_preload,
    stat as _stat,
    style_table as _style_table,
    sync_current_review as _sync_current_review,
    timeline as _timeline,
    top_locations as _top_locations,
)
from integration.manage_view import view_manage

logger = logging.getLogger(__name__)


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
    import html as _html
    import re as _re

    if file_path and Path(file_path).exists():
        st.audio(file_path)
    elif file_path:
        st.caption("Source audio is no longer available for preview.")
    if draft_df.empty:
        return
    row = draft_df.iloc[0]

    score = float(row.get("Urgency_Score", 0) or 0)
    label = "Distressed" if score >= 0.65 else "Concerned" if score >= 0.40 else "Calm"
    color = (
        SEV_COLORS["High"]
        if score >= 0.65
        else SEV_COLORS["Medium"]
        if score >= 0.40
        else SEV_COLORS["Low"]
    )
    sentiment = str(row.get("Sentiment", ""))

    col_u, col_s = st.columns(2)
    with col_u:
        st.markdown(
            f'**Urgency — <span style="color:{color}">{label}</span>** `{score:.2f}`',
            unsafe_allow_html=True,
        )
        st.progress(min(1.0, score))
    with col_s:
        st.markdown("**Sentiment**")
        st.markdown(_sentiment_badge(sentiment), unsafe_allow_html=True)

    transcript = str(row.get("Transcript", ""))
    if transcript and transcript.lower() not in ("unknown", "nan", ""):
        incident_words = [
            "fire",
            "shot",
            "shots",
            "fight",
            "accident",
            "robbery",
            "assault",
            "emergency",
            "help",
            "police",
            "ambulance",
            "knife",
            "gun",
            "dead",
            "injured",
            "hurt",
            "bleeding",
            "attack",
            "stolen",
            "crash",
        ]
        highlighted = _html.escape(transcript)
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
        detections = (
            draft_df.attrs.get("image_detections", [])
            if isinstance(draft_df, pd.DataFrame)
            else []
        )
        try:
            from images.processor import annotate_image_with_detections

            annotated_image = annotate_image_with_detections(
                file_path, detections=detections
            )
            has_boxes = bool(detections)
            st.image(
                annotated_image,
                caption="Uploaded image with detection boxes"
                if has_boxes
                else "Uploaded image",
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
            f"padding:3px 9px;margin:2px 3px;border-radius:999px;"
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
            f"border-radius:0 8px 8px 0;padding:12px 16px;font-size:.9rem;"
            f'line-height:1.7;color:#334155;white-space:pre-wrap">'
            f"{_html.escape(extracted_text)}</div>",
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

    # Prefer full extracted text when the source file is still available.
    full_text = ""
    if file_path:
        try:
            from pdf.processor import extract_pdf_text

            full_text = extract_pdf_text(file_path).strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not extract full PDF text for preview: %s", exc)
    if not full_text:
        full_text = str(row.get("Summary", ""))

    if full_text and full_text.lower() not in ("unknown", "nan", ""):
        import html as _html
        import re as _re

        pdf_entities = []
        for etype, val in [
            ("LOCATION", row.get("Location", "")),
            ("DATE", row.get("Date", "")),
            ("PERSON", row.get("Officer", "")),
        ]:
            val = str(val).strip()
            if val and val.lower() not in ("unknown", "nan", ""):
                pdf_entities.append(f"{etype}: {val}")
        highlighted = (
            _highlight_entities_in_text(full_text, "; ".join(pdf_entities))
            if pdf_entities
            else _html.escape(full_text)
        )

        # Keep UI highlighting aligned with PDF incident keywords.
        _PDF_TRIGGER_PATTERNS = {
            "Theft / Robbery": r"\b(?:robber(?:y|ies)|robbed|burglar(?:y|ies|s)?|theft|stolen|shoplift(?:ing|ed)?|larceny)\b",
            "Assault / Violence": r"\b(?:assault(?:s|ed)?|battery|stabb(?:ing|ed)|shooting|shots fired|homicide|murder)\b",
            "Fire / Arson": r"\barson(?:ist)?\b",
            "Traffic Accident": r"\b(?:collision|traffic accident|car crash|vehicle crash|hit[- ]and[- ]run)\b",
            "Public Disturbance": r"\b(?:riot(?:ing|s)?|vandalism|disturbance|trespass(?:ing)?)\b",
        }
        pattern = _PDF_TRIGGER_PATTERNS.get(str(row.get("Incident_Type", "")))
        if pattern:
            highlighted = _re.sub(
                pattern,
                lambda m: (
                    f'<span style="background:#FED7AA;color:#9A3412;'
                    f'border-radius:4px;padding:1px 4px;font-weight:600">'
                    f"{m.group(0)}</span>"
                ),
                highlighted,
                flags=_re.IGNORECASE,
            )

        st.markdown("**Extracted text**")
        st.markdown(
            f'<div style="background:#F8FAFC;border-left:4px solid {ACCENT};'
            f"border-radius:0 8px 8px 0;padding:12px 16px;font-size:.9rem;"
            f'line-height:1.7;color:#334155;white-space:pre-wrap">{highlighted}</div>',
            unsafe_allow_html=True,
        )


_ENTITY_COLORS: dict[str, tuple[str, str]] = {
    "LOCATION": ("#DBEAFE", "#1D4ED8"),
    "PERSON": ("#FCE7F3", "#9D174D"),
    "ORGANIZATION": ("#D1FAE5", "#065F46"),
    "DATE": ("#FEF3C7", "#92400E"),
}


def _entity_chip(etype: str, value: str) -> str:
    bg, fg = _ENTITY_COLORS.get(etype.upper(), ("#F1F5F9", "#334155"))
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f"padding:2px 8px;margin:2px 3px;border-radius:6px;"
        f'font-size:.8rem;font-weight:600">{etype}: {value}</span>'
    )


def _highlight_entities_in_text(text: str, entities_raw: str) -> str:
    """Return HTML of text with entity values wrapped in colored spans."""
    import re as _re
    import html as _html

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

    # Match longer values first to avoid partial replacements.
    pairs.sort(key=lambda p: len(p[1]), reverse=True)

    escaped = _html.escape(text)

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
                f"padding:12px 14px;font-size:.88rem;line-height:1.8;color:#334155;"
                f'white-space:pre-wrap;margin-top:6px">{highlighted}</div>',
                unsafe_allow_html=True,
            )
        st.write("")


def _transcoded_video_bytes(file_path: Path, filename: str) -> bytes:
    """Return browser-friendly video bytes, falling back to the original file."""

    import shutil as _shutil
    import subprocess as _sp
    import tempfile as _tempfile

    ffmpeg = _shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning(
            "ffmpeg is unavailable; using original preview for %s.", filename
        )
        return file_path.read_bytes()

    with _tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        result = _sp.run(  # noqa: S603 - file_path is an app-created temp upload.
            [
                ffmpeg,
                "-y",
                "-i",
                str(file_path),
                "-vcodec",
                "libx264",
                "-acodec",
                "aac",
                "-movflags",
                "+faststart",
                str(tmp_path),
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        if result.returncode == 0:
            return tmp_path.read_bytes()
        logger.warning("ffmpeg preview transcode failed for %s.", filename)
        return file_path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ffmpeg preview transcode skipped for %s: %s",
            filename,
            type(exc).__name__,
        )
        return file_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def _video_preview_bytes(file_path: Path, filename: str) -> bytes:
    cache_key = f"video_bytes_{filename}"
    video_bytes = st.session_state.get(cache_key)
    if video_bytes is None:
        video_bytes = _transcoded_video_bytes(file_path, filename)
        st.session_state[cache_key] = video_bytes
    return video_bytes


def _render_frame_gallery(paths: list[Path]) -> str:
    import base64 as _b64
    import html as _html

    tiles = ""
    for frame_path in paths:
        img_b64 = _b64.b64encode(frame_path.read_bytes()).decode()
        caption = _html.escape(frame_path.stem)
        tiles += (
            f'<div style="flex:0 0 30%;min-width:200px">'
            f'<img src="data:image/jpeg;base64,{img_b64}" style="width:100%;border-radius:6px">'
            f'<div style="font-size:.75rem;color:#64748B;text-align:center;margin-top:3px">{caption}</div>'
            f"</div>"
        )
    return (
        f'<div style="display:flex;flex-wrap:wrap;gap:10px;max-height:480px;'
        f'overflow-y:auto;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px">'
        f"{tiles}</div>"
    )


def _show_cached_video_frames(frames_dir: Path) -> None:
    frame_paths = sorted(frames_dir.rglob("*.jpg"))
    if not frame_paths:
        st.caption("No annotated frames were produced (video may have no motion).")
        return
    st.caption(f"{len(frame_paths)} annotated frames")
    st.markdown(_render_frame_gallery(frame_paths), unsafe_allow_html=True)


def _process_video_frames(file_path: Path, filename: str) -> None:
    import tempfile as _tempfile

    from video.processor import process_video_stream

    frames_dir = Path(_tempfile.mkdtemp(prefix="frames_"))
    frame_paths: list[Path] = []
    status = st.empty()
    gallery = st.empty()

    for _row, frame_path in process_video_stream(
        str(file_path), annotated_frames_dir=frames_dir
    ):
        if frame_path:
            frame_paths.append(Path(frame_path))
            status.caption(f"Processing… {len(frame_paths)} frames done")
            gallery.markdown(_render_frame_gallery(frame_paths), unsafe_allow_html=True)

    status.caption(f"{len(frame_paths)} annotated frames")
    if not frame_paths:
        gallery.caption("No annotated frames were produced (video may have no motion).")
    st.session_state[f"frames_dir_{filename}"] = frames_dir


def _show_video_frames(file_path: Path, filename: str) -> None:
    frames_dir: Path | None = st.session_state.get(f"frames_dir_{filename}")
    if frames_dir is not None:
        _show_cached_video_frames(frames_dir)
        return
    try:
        _process_video_frames(file_path, filename)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Video frame extraction failed")
        st.caption(f"Could not extract frames: {exc}")


def _show_video_evidence(file_path: str | None, filename: str) -> None:
    if not file_path:
        st.caption("Source file is no longer available for frame extraction.")
        return

    source_path = Path(file_path)
    if not source_path.exists():
        st.caption("Source file is no longer available for frame extraction.")
        return

    st.video(_video_preview_bytes(source_path, filename))
    _show_video_frames(source_path, filename)


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
def _uploaded_source(uploaded) -> tuple[str, str | None]:
    uploaded_filename = _safe_upload_filename(uploaded)
    source_type = ig.detect_source_type(uploaded_filename)
    if source_type is None:
        st.error(
            "We can't review this file type yet. Please choose an audio, document, image, video, text, or CSV file."
        )
    return uploaded_filename, source_type


def _reset_ingest_when_file_changes(uploaded_filename: str) -> None:
    current_result = st.session_state.get("ingest")
    if (
        isinstance(current_result, dict)
        and current_result.get("filename") != uploaded_filename
    ):
        _clear_ingest_state()


def _show_upload_ready(source_type: str) -> None:
    label = ig.source_label(source_type)
    st.markdown(
        f'<span class="badge b-info">{_icon(SOURCE_ICON.get(label, "description"))} '
        f"Ready to review · {label}</span>",
        unsafe_allow_html=True,
    )
    st.write("")

    if source_type == "audio":
        st.info("We'll create a written transcript from this recording.")


def _review_uploaded_evidence(
    uploaded, uploaded_filename: str, source_type: str
) -> None:
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


def _save_ingest_result(final_df: pd.DataFrame, result: dict) -> None:
    saved_summary = result.get("saved_summary")
    if saved_summary:
        incident_ids = ", ".join(saved_summary.get("incident_ids", []))
        suffix = f": {incident_ids}" if incident_ids else ""
        st.success(
            f"Added {saved_summary['inserted_count']} incident record(s){suffix}."
        )
        return

    if not st.button(
        "Add to incident records",
        type="primary",
        icon=":material/cloud_upload:",
        width="stretch",
    ):
        return
    try:
        summary = upload_incidents(final_df, refresh_ids=True)
        incident_ids = ", ".join(summary.get("incident_ids", []))
        suffix = f": {incident_ids}" if incident_ids else ""
        st.success(f"Added {summary['inserted_count']} incident record(s){suffix}.")
        result["saved_summary"] = summary
    except Exception as exc:  # noqa: BLE001
        logger.exception("Incident upload failed")
        st.error(_friendly_error(exc, "add this incident"))


def _show_ingest_result(uploaded_filename: str, source_type: str) -> None:
    result = st.session_state.get("ingest")
    if not result or result.get("filename") != uploaded_filename:
        return

    final_df = result["final"]
    st.caption(
        f"Extractor rows: {len(result['draft'])} · Integrated incident rows: {len(final_df)}"
    )
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

    _save_ingest_result(final_df, result)
    _section("Visual evidence")
    _show_visual_evidence(
        result.get("source_type", source_type),
        result["draft"],
        result.get("path"),
        uploaded_filename,
    )


def view_ingest() -> None:
    _page_head(
        "upload_file",
        "Add Incident",
        "Choose a file and we'll turn it into a clear incident record.",
    )

    uploaded = st.file_uploader(
        "Choose an evidence file", type=ig.supported_extensions()
    )
    if uploaded is None:
        st.info(
            "You can add an audio recording, document, image, text file, or CSV file."
        )
        return

    uploaded_filename, source_type = _uploaded_source(uploaded)
    if source_type is None:
        return
    _reset_ingest_when_file_changes(uploaded_filename)
    _show_upload_ready(source_type)

    if st.button("Review evidence", type="primary", icon=":material/play_arrow:"):
        _review_uploaded_evidence(uploaded, uploaded_filename, source_type)
    _show_ingest_result(uploaded_filename, source_type)


# --------------------------------------------------------------------------- #
# View 2: Integrate (Final Integration Task)
# --------------------------------------------------------------------------- #
def view_integrate() -> None:
    _page_head(
        "hub",
        "Combine Reports",
        "Bring completed evidence reviews into one organized incident list.",
    )

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

    st.caption(
        "Counts include every evidence file reviewed during this browser session."
    )
    if sum(status.values()) == 0:
        st.info(
            "No completed evidence reviews are available yet. Start by adding an evidence file."
        )
        return

    st.write("")
    if st.button("Combine reports", type="primary", icon=":material/merge:"):
        with st.spinner("Bringing the reports together…"):
            try:
                st.session_state["master"] = _build_queued_incidents(
                    existing_incident_ids()
                )
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
        k[2],
        "High severity",
        int(master["Severity"].value_counts().get("High", 0)),
        color=SEV_COLORS["High"],
        icon="priority_high",
    )

    st.write("")
    _section(f"Combined incident list · {len(master)} incidents")
    st.dataframe(_style_table(master), width="stretch", hide_index=True)

    chart_data = ig.to_supabase_payload_frame(master)
    cc1, cc2 = st.columns(2)
    with cc1:
        _section("Records per source")
        st.altair_chart(
            _hbar(chart_data["source"].value_counts(), "Source"), width="stretch"
        )
    with cc2:
        _section("Severity by source")
        st.altair_chart(_severity_by_source(chart_data), width="stretch")

    st.download_button(
        "Download combined report",
        master.to_csv(index=False).encode("utf-8"),
        file_name="final_incident_dataset.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
    )


# --------------------------------------------------------------------------- #
# View 3: Dashboard
# --------------------------------------------------------------------------- #
def _load_dashboard_frame() -> pd.DataFrame | None:
    try:
        df = load_incidents()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Incident loading failed")
        st.error(_friendly_error(exc, "load incident records"))
        return None
    if df.empty:
        st.info("No incidents have been added yet. Start with **Add Incident**.")
        return None
    return ig.with_display_ids(df)


def _dashboard_filters(df: pd.DataFrame) -> tuple[list[str], list[str], str, str, str]:
    with st.expander("Filters", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        sources = sorted(df["source"].dropna().unique().tolist())
        severities = [s for s in SEVERITY_ORDER if s in df["severity"].unique()]
        pick_source = c1.multiselect("Source", sources, default=sources)
        pick_severity = c2.multiselect("Severity", severities, default=severities)
        pick_id = c3.text_input("Incident ID", "")
        pick_event = c4.text_input("Event", "")
        pick_location = c5.text_input("Location", "")
    return pick_source, pick_severity, pick_id, pick_event, pick_location


def _filter_dashboard_frame(
    df: pd.DataFrame,
    sources: list[str],
    severities: list[str],
    incident_id: str,
    event: str,
    location: str,
) -> pd.DataFrame:
    view = df[df["source"].isin(sources) & df["severity"].isin(severities)]
    for column, query in (
        ("Incident_ID", incident_id),
        ("event", event),
        ("location", location),
    ):
        if query:
            view = view[
                view[column]
                .astype(str)
                .str.contains(query, case=False, regex=False, na=False)
            ]
    return view


def _dashboard_stats(view: pd.DataFrame) -> None:
    counts = view["severity"].value_counts()
    cols = st.columns(4)
    _stat(cols[0], "Total incidents", len(view), icon="summarize")
    _stat(
        cols[1],
        "High",
        int(counts.get("High", 0)),
        color=SEV_COLORS["High"],
        icon="local_fire_department",
    )
    _stat(
        cols[2],
        "Medium",
        int(counts.get("Medium", 0)),
        color=SEV_COLORS["Medium"],
        icon="warning",
    )
    _stat(
        cols[3],
        "Low",
        int(counts.get("Low", 0)),
        color=SEV_COLORS["Low"],
        icon="check_circle",
    )
    st.write("")


def _dashboard_overview_tab(view: pd.DataFrame) -> None:
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


def _location_hotspot_table(view: pd.DataFrame) -> None:
    known = _known_locations(view)
    if known.empty:
        return
    _section("Location hotspot table")
    hotspots = (
        known.groupby("location")
        .agg(
            Incidents=("incident_id", "count"),
            High=("severity", lambda s: int((s == "High").sum())),
        )
        .reset_index()
        .rename(columns={"location": "Location"})
        .sort_values(["Incidents", "High"], ascending=False)
        .head(10)
    )
    st.dataframe(hotspots, width="stretch", hide_index=True)


def _dashboard_breakdown_tab(view: pd.DataFrame) -> None:
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
        st.altair_chart(
            _hbar(view["event"].value_counts().head(8), "Event", color="#7C3AED"),
            width="stretch",
        )
    _location_hotspot_table(view)


def _dashboard_records_tab(view: pd.DataFrame) -> None:
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
        "Download incident report",
        export_incidents_csv(),
        file_name="final_incident_dataset.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def _dashboard_tabs(view: pd.DataFrame) -> None:
    tab_overview, tab_breakdown, tab_records = st.tabs(
        ["Overview", "Breakdown", "Records"]
    )
    with tab_overview:
        _dashboard_overview_tab(view)
    with tab_breakdown:
        _dashboard_breakdown_tab(view)
    with tab_records:
        _dashboard_records_tab(view)


def view_dashboard() -> None:
    _page_head(
        "insights",
        "Incident Overview",
        "See priorities, patterns, and recent activity at a glance.",
    )

    df = _load_dashboard_frame()
    if df is None:
        return
    view = _filter_dashboard_frame(df, *_dashboard_filters(df))
    _dashboard_stats(view)
    if view.empty:
        st.info("No incidents match the current filters.")
        return
    _dashboard_tabs(view)


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
        st.markdown(
            f'<div class="sb-brand">{_icon("local_police")} Incident Analyzer</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="sb-sub">Evidence review and incident insights</div>',
            unsafe_allow_html=True,
        )
        for name, icon, _ in PAGES:
            kind = "primary" if st.session_state["page"] == name else "secondary"
            if st.button(
                name, icon=icon, width="stretch", type=kind, key=f"nav_{name}"
            ):
                st.session_state["page"] = name
                st.rerun()

    view = {name: fn for name, _, fn in PAGES}[st.session_state["page"]]
    view()


if __name__ == "__main__":
    main()
