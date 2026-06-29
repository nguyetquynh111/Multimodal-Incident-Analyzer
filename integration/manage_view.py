"""Streamlit Manage Incidents view."""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from cloud_deployment.supabase_client import (
    delete_incident,
    update_incident,
    validate_incident_key,
)
from cloud_deployment.upload_service import upload_incidents
from integration import integration as ig
from integration.app_support import (
    SEVERITY_ORDER,
    existing_incident_ids,
    friendly_error as _friendly_error,
    load_incidents,
    manual_summary_override as _manual_summary_override,
    page_head as _page_head,
    section as _section,
)

logger = logging.getLogger(__name__)


@st.dialog("Add incident")
def _add_incident_dialog(existing_ids: list[str]) -> None:
    source_type = st.selectbox(
        "Source", list(ig.MODALITIES.keys()), format_func=ig.source_label
    )
    next_label = ig.generate_next_incident_id(source_type, existing_ids)
    st.caption(f"New incident ID: `{next_label}`")
    event = st.text_input("Event", "Unknown")
    location = st.text_input("Location", "Unknown")
    time_val = st.text_input("Time", "Unknown")
    severity = st.selectbox("Severity", SEVERITY_ORDER, index=1)
    incident_summary = st.text_area(
        "Incident summary",
        "",
        height=90,
        placeholder="Leave blank to auto-generate a summary.",
    )
    if st.button("Save", type="primary", icon=":material/save:"):
        draft = pd.DataFrame(
            [
                {
                    "Event": event,
                    "Location": location or "Unknown",
                    "Time": time_val or "Unknown",
                    "Severity": severity,
                    "Summary": incident_summary or "Unknown",
                }
            ]
        )
        row = ig.integrate_records(draft, source_type, existing_ids)
        summary_override = _manual_summary_override(incident_summary)
        if summary_override is not None:
            row["Incident_Summary"] = summary_override
        try:
            summary = upload_incidents(row, refresh_ids=True)
            incident_ids = ", ".join(summary.get("incident_ids", []))
            st.success(f"Added {incident_ids or row.iloc[0]['Incident_ID']}")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Manual incident creation failed")
            st.error(_friendly_error(exc, "add this incident"))


def _clean_editor_value(value: object) -> str:
    return "Unknown" if pd.isna(value) or not str(value).strip() else str(value).strip()


def _filter_incidents(
    df: pd.DataFrame,
    sources: list[str],
    severities: list[str],
    search: str,
) -> pd.DataFrame:
    filtered = df[df["source"].isin(sources) & df["severity"].isin(severities)]
    if not search:
        return filtered

    search_mask = pd.Series(False, index=filtered.index)
    for column in ("Incident_ID", "event", "location"):
        search_mask |= (
            filtered[column].astype(str).str.contains(search, case=False, regex=False)
        )
    return filtered[search_mask]


def _bulk_update_values(field_labels: list[str]) -> dict[str, str]:
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
        bulk_values["time"] = input_columns[0].text_input("New time", key="bulk_time")
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
    return bulk_values


def _bulk_action_panel(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str], bool, bool]:
    with st.expander("Bulk actions", expanded=False):
        st.caption(
            "Update several incidents at once or remove a group. Incident IDs and sources never change."
        )
        filter_source_col, filter_severity_col, filter_search_col = st.columns(3)
        available_sources = sorted(df["source"].dropna().unique().tolist())
        available_severities = [
            severity
            for severity in SEVERITY_ORDER
            if severity in df["severity"].unique()
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

        filtered = _filter_incidents(df, bulk_sources, bulk_severities, bulk_search)
        target_count = len(filtered)
        st.info(f"{target_count} of {len(df)} incidents match these filters.")

        field_labels = st.multiselect(
            "Fields to update",
            ["Event", "Location", "Time", "Severity", "Incident summary"],
            help="Only selected fields will be overwritten.",
            key="bulk_fields",
        )
        bulk_values = _bulk_update_values(field_labels)

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
    return filtered, bulk_values, do_bulk_update, do_bulk_remove


def _bulk_payload(values: dict[str, str], current_event: object) -> dict[str, str]:
    payload = {
        field: (
            ig.normalize_event(value)
            if field == "event"
            else (str(value).strip() or "Unknown")
        )
        for field, value in values.items()
    }
    if ig.normalize_event(payload.get("event", current_event)) == "Unknown":
        payload["severity"] = "Low"
    return payload


def _apply_bulk_action(
    df: pd.DataFrame,
    target_labels: list[str],
    bulk_values: dict[str, str],
    *,
    remove: bool,
) -> None:
    targets = df[df["Incident_ID"].isin(target_labels)]
    succeeded = 0
    failures: list[str] = []
    for _, target in targets.iterrows():
        label = str(target["Incident_ID"])
        try:
            incident_key = validate_incident_key(target["incident_id"])
            if remove:
                delete_incident(incident_key)
            else:
                update_incident(
                    incident_key,
                    _bulk_payload(bulk_values, target["event"]),
                )
            succeeded += 1
        except Exception:  # noqa: BLE001
            logger.exception("Bulk incident action failed for %s", label)
            failures.append(label)

    if failures:
        action = "removed" if remove else "updated"
        st.error(
            f"{succeeded} incident(s) were {action}, but {len(failures)} could not be changed. "
            "Please try those records again."
        )
        return

    action = "removed" if remove else "updated"
    st.session_state["manage_notice"] = (
        f"Successfully {action} {succeeded} incident(s)."
    )
    st.rerun()


def _editable_incidents(filtered: pd.DataFrame) -> pd.DataFrame:
    editable = filtered.loc[
        :,
        [
            "Incident_ID",
            "source",
            "event",
            "location",
            "time",
            "severity",
            "incident_summary",
        ],
    ].copy()
    editable["remove"] = False
    return editable


def _incident_table_editor(editable: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
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
                "Incident_ID": st.column_config.TextColumn(
                    "Incident ID", width="small"
                ),
                "source": st.column_config.TextColumn("Source", width="small"),
                "event": st.column_config.TextColumn(
                    "Event", width="large", required=True
                ),
                "location": st.column_config.TextColumn(
                    "Location", width="medium", required=True
                ),
                "time": st.column_config.TextColumn(
                    "Time", width="medium", required=True
                ),
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
    return edited, apply_changes


def _row_changes(row: pd.Series, current: pd.Series) -> dict[str, str]:
    changes = {
        field: (
            ig.normalize_event(row[field])
            if field == "event"
            else _clean_editor_value(row[field])
        )
        for field in ("event", "location", "time", "severity")
        if (
            ig.normalize_event(row[field]) != ig.normalize_event(current[field])
            if field == "event"
            else _clean_editor_value(row[field]) != _clean_editor_value(current[field])
        )
    }
    summary = _clean_editor_value(row["incident_summary"])
    if summary != _clean_editor_value(current["incident_summary"]):
        changes["incident_summary"] = summary
    if ig.normalize_event(row["event"]) == "Unknown":
        changes["severity"] = "Low"
    return changes


def _apply_table_changes(df: pd.DataFrame, edited: pd.DataFrame) -> None:
    original = df.set_index("Incident_ID", drop=False)
    updated_count = 0
    deleted_count = 0
    failures: list[str] = []

    for _, row in edited.iterrows():
        label = str(row["Incident_ID"])
        current = original.loc[label]
        try:
            incident_id = validate_incident_key(current["incident_id"])
            if bool(row["remove"]):
                delete_incident(incident_id)
                deleted_count += 1
                continue

            changes = _row_changes(row, current)
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


def _show_incident_list(df: pd.DataFrame, filtered: pd.DataFrame) -> None:
    _section("Incident list")
    if len(filtered) == len(df):
        st.caption(
            "Edit any unlocked cell. Select Remove for records you no longer need, then apply your changes."
        )
    else:
        st.caption(
            f"Showing {len(filtered)} of {len(df)} incidents matching the filters above. "
            "Edit any unlocked cell or select Remove, then apply your changes."
        )

    if filtered.empty:
        st.info("No incidents match the current filters.")
        return

    edited, apply_changes = _incident_table_editor(_editable_incidents(filtered))
    if apply_changes:
        _apply_table_changes(df, edited)


def _load_manage_frame() -> pd.DataFrame | None:
    try:
        df = load_incidents()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Incident loading failed")
        st.error(_friendly_error(exc, "load incident records"))
        return None
    if df.empty:
        st.info("No incidents yet. Use **Add incident** above.")
        return None
    return ig.with_display_ids(df)


def view_manage() -> None:
    _page_head(
        "edit_note",
        "Manage Incidents",
        "Add new incidents or keep existing details up to date.",
    )

    notice = st.session_state.pop("manage_notice", None)
    if notice:
        st.success(notice)

    if st.button("Add incident", type="primary", icon=":material/add:"):
        _add_incident_dialog(existing_incident_ids())

    df = _load_manage_frame()
    if df is None:
        return
    filtered, bulk_values, do_bulk_update, do_bulk_remove = _bulk_action_panel(df)
    if do_bulk_update or do_bulk_remove:
        _apply_bulk_action(
            df,
            filtered["Incident_ID"].tolist(),
            bulk_values,
            remove=do_bulk_remove,
        )
        return
    _show_incident_list(df, filtered)
