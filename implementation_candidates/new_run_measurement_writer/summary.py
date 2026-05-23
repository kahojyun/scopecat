"""Structured summary builder for new-run measurement writer events.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not write storage, read primary data files, infer
schemas, control instruments, stream live updates, render previews, or open
GUIs.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "event_authority": "explicit_writer_events",
    "primary_data_write": "declared_reference_only",
    "storage_mutation": "not_performed",
    "source_observation": "not_performed",
    "schema_inference": "not_performed",
    "hardware_control": "not_performed",
    "live_service": "not_defined",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_EVENT_TYPES = {
    "measurement_started",
    "data_recorded",
    "measurement_completed",
    "measurement_failed",
}

_FINAL_EVENT_TYPES = {"measurement_completed", "measurement_failed"}

_PREVIEW_STATUSES = {
    "preview_ready",
    "degraded_preview",
}

_WRITER_AUTHORITY = "writer_declared"
_PRIMARY_DATA_KIND = "primary_data"
_PRIMARY_DATA_FORMATS = {"csv_table"}


def _parse_event_time(value: str, event_id: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"writer event {event_id} occurred_at must be ISO timestamp") from exc


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_relative_path(path: str, owner: str) -> None:
    if not _path_is_relative(path):
        raise ValueError(f"{owner} path must be relative")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["writer_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("writer policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"writer policy {key} must be {expected}")


def _validate_preview_metadata(source: dict[str, Any]) -> None:
    preview = source["declared_preview_metadata"]
    primary_data = source["primary_data"]

    if preview["metadata_authority"] != _WRITER_AUTHORITY:
        raise ValueError("preview metadata authority must stay writer_declared")
    if preview["status"] not in _PREVIEW_STATUSES:
        raise ValueError("unsupported preview metadata status")

    if preview["status"] == "preview_ready":
        if preview["data_shape"] is None:
            raise ValueError("preview-ready metadata requires data_shape")
        declared_columns = preview["declared_columns"]
        declared_names = {column["name"] for column in declared_columns}
        if len(declared_names) != len(declared_columns):
            raise ValueError("declared preview columns must have unique names")
        axis_order = preview["data_shape"]["axis_order"]
        if not declared_names or not axis_order:
            raise ValueError("preview-ready metadata requires declared columns and axis order")
        if any(axis not in declared_names for axis in axis_order):
            raise ValueError("preview axis order must reference declared columns")
        for candidate in preview["plot_candidates"]:
            if candidate["source"] != primary_data["path"]:
                raise ValueError("plot candidate source must match primary data path")
            if candidate["x"] not in declared_names or candidate["y"] not in declared_names:
                raise ValueError("plot candidate axes must reference declared columns")
        return

    if preview["data_shape"] is not None:
        raise ValueError("degraded preview must not carry data_shape")
    if preview["declared_columns"] or preview["plot_candidates"]:
        raise ValueError("degraded preview must not carry declared columns or plot candidates")
    if not preview.get("warning_code") or not preview.get("message"):
        raise ValueError("degraded preview requires warning_code and message")


def _events_by_id(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output = {}
    for event in events:
        event_id = event["event_id"]
        if event_id in output:
            raise ValueError(f"duplicate event_id: {event_id}")
        output[event_id] = event
    return output


def _validate_events(source: dict[str, Any]) -> None:
    events = source["writer_events"]
    if len(events) < 3:
        raise ValueError("writer events require start, data, and final events")
    _events_by_id(events)

    event_types = [event["event_type"] for event in events]
    unsupported = sorted(set(event_types) - _EVENT_TYPES)
    if unsupported:
        raise ValueError(f"unsupported writer event type: {unsupported[0]}")
    if event_types[0] != "measurement_started":
        raise ValueError("first writer event must be measurement_started")
    if sum(event_type == "measurement_started" for event_type in event_types) != 1:
        raise ValueError("writer events require exactly one measurement_started event")
    if event_types[-1] not in _FINAL_EVENT_TYPES:
        raise ValueError("last writer event must be a final measurement event")
    if any(event_type in _FINAL_EVENT_TYPES for event_type in event_types[:-1]):
        raise ValueError("final measurement event must be last")
    if "data_recorded" not in event_types:
        raise ValueError("writer events require at least one data_recorded event")

    primary_path = source["primary_data"]["path"]
    measurement_record_id = source["measurement_record"]["measurement_record_id"]
    previous_total = 0
    previous_time: datetime | None = None
    for event in events:
        occurred_at = _parse_event_time(event["occurred_at"], event["event_id"])
        if previous_time is not None and occurred_at < previous_time:
            raise ValueError("writer event timestamps must be monotonic")
        previous_time = occurred_at

        if event["measurement_record_id"] != measurement_record_id:
            raise ValueError("writer event measurement_record_id must match measurement record")
        if event["event_type"] == "data_recorded":
            _validate_relative_path(event["primary_data_path"], "data-recorded event")
            if event["primary_data_path"] != primary_path:
                raise ValueError("data-recorded event path must match primary data path")
            rows_recorded = event["rows_recorded"]
            total_rows_recorded = event["total_rows_recorded"]
            if rows_recorded <= 0:
                raise ValueError("data-recorded rows_recorded must be positive")
            if total_rows_recorded != previous_total + rows_recorded:
                raise ValueError("data-recorded total must equal previous total plus rows_recorded")
            previous_total = total_rows_recorded

    final_event = events[-1]
    if final_event["event_type"] == "measurement_failed":
        if not final_event.get("reason"):
            raise ValueError("failed measurement final event requires reason")
    elif final_event.get("reason"):
        raise ValueError("completed measurement final event must not carry reason")
    if final_event["final_recorded_points"] != previous_total:
        raise ValueError("final recorded points must match data-recorded total")
    expected_points = events[0]["expected_points"]
    if expected_points <= 0:
        raise ValueError("expected points must be positive")
    if final_event["event_type"] == "measurement_completed" and previous_total != expected_points:
        raise ValueError("completed measurement must record expected points")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    primary_data = source["primary_data"]
    _validate_relative_path(primary_data["path"], "primary data")
    if primary_data["authority"] != _WRITER_AUTHORITY:
        raise ValueError("primary data authority must stay writer_declared")
    if primary_data["kind"] != _PRIMARY_DATA_KIND:
        raise ValueError("primary data kind must stay primary_data")
    if primary_data["format"] not in _PRIMARY_DATA_FORMATS:
        raise ValueError("primary data format is unsupported")
    _validate_preview_metadata(source)
    _validate_events(source)


def _preview_summary(source: dict[str, Any]) -> dict[str, Any]:
    preview = source["declared_preview_metadata"]
    if preview["status"] == "preview_ready":
        return {
            "status": "preview_ready",
            "metadata_authority": preview["metadata_authority"],
            "shape_kind": preview["data_shape"]["kind"],
            "axis_order": list(preview["data_shape"]["axis_order"]),
            "declared_roles": copy.deepcopy(preview["declared_columns"]),
            "plot_candidates": [
                {
                    "x": candidate["x"],
                    "y": candidate["y"],
                    "source": candidate["source"],
                }
                for candidate in preview["plot_candidates"]
            ],
            "warnings": [],
        }

    return {
        "status": "degraded_preview",
        "metadata_authority": preview["metadata_authority"],
        "shape_kind": None,
        "axis_order": [],
        "declared_roles": [],
        "plot_candidates": [],
        "warnings": [
            {
                "code": preview["warning_code"],
                "message": preview["message"],
            }
        ],
    }


def _event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        event_type = event["event_type"]
        counts[event_type] = counts.get(event_type, 0) + 1
    return dict(sorted(counts.items()))


def _classification(source: dict[str, Any]) -> str:
    final_event = source["writer_events"][-1]
    if final_event["event_type"] == "measurement_failed":
        return "failed_record_needs_review"
    if source["declared_preview_metadata"]["status"] != "preview_ready":
        return "recorded_needs_preview_metadata_review"
    return "recorded_ready_for_review"


def _lifecycle_summary(source: dict[str, Any]) -> dict[str, Any]:
    start_event = source["writer_events"][0]
    final_event = source["writer_events"][-1]
    return {
        "state": "completed" if final_event["event_type"] == "measurement_completed" else "failed",
        "started_at": start_event["occurred_at"],
        "ended_at": final_event["occurred_at"],
        "recording_enabled": start_event["recording_enabled"],
        "final_event_id": final_event["event_id"],
    }


def _progress_summary(source: dict[str, Any]) -> dict[str, Any]:
    start_event = source["writer_events"][0]
    final_event = source["writer_events"][-1]
    expected_points = start_event["expected_points"]
    recorded_points = final_event["final_recorded_points"]
    return {
        "expected_points": expected_points,
        "recorded_points": recorded_points,
        "complete": final_event["event_type"] == "measurement_completed"
        and recorded_points == expected_points,
        "basis": "explicit_writer_event_counts",
    }


def _normalized_events(source: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for event in source["writer_events"]:
        item = {
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "occurred_at": event["occurred_at"],
            "measurement_record_id": event["measurement_record_id"],
        }
        if event["event_type"] == "measurement_started":
            item["expected_points"] = event["expected_points"]
            item["recording_enabled"] = event["recording_enabled"]
        elif event["event_type"] == "data_recorded":
            item["primary_data_path"] = event["primary_data_path"]
            item["rows_recorded"] = event["rows_recorded"]
            item["total_rows_recorded"] = event["total_rows_recorded"]
        else:
            item["final_recorded_points"] = event["final_recorded_points"]
            item["reason"] = event.get("reason")
        output.append(item)
    return output


def _findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    final_event = source["writer_events"][-1]
    preview = source["declared_preview_metadata"]

    if final_event["event_type"] == "measurement_failed":
        findings.append(
            {
                "measurement_record_id": source["measurement_record"]["measurement_record_id"],
                "subject_type": "lifecycle",
                "subject_id": final_event["event_id"],
                "severity": "review",
                "finding": "measurement_failed",
                "basis": final_event["reason"],
                "does_not_claim": "hardware_failure_or_retry_policy",
            }
        )

    if preview["status"] == "degraded_preview":
        findings.append(
            {
                "measurement_record_id": source["measurement_record"]["measurement_record_id"],
                "subject_type": "preview_metadata",
                "subject_id": preview["metadata_authority"],
                "severity": "review",
                "finding": preview["warning_code"],
                "basis": preview["message"],
                "does_not_claim": "record_cannot_be_saved_or_plotted_later",
            }
        )

    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "writer_events_only",
            "severity": "info",
            "basis": "The measurement record is summarized from explicit writer events.",
            "does_not_claim": "observed_instrument_state",
        },
        {
            "code": "storage_write_not_performed",
            "severity": "review",
            "basis": "Primary data persistence is represented as a declared reference only.",
            "does_not_claim": "record_written_to_store",
        },
        {
            "code": "source_data_not_read",
            "severity": "review",
            "basis": "Primary data paths are declared references, not opened or parsed.",
            "does_not_claim": "file_contents_verified",
        },
        {
            "code": "schema_inference_not_performed",
            "severity": "review",
            "basis": "Preview metadata must be declared by the writer events or caller.",
            "does_not_claim": "automatic_schema_detection",
        },
        {
            "code": "hardware_control_not_performed",
            "severity": "review",
            "basis": "Writer events record measurement lifecycle facts without controlling instruments.",
            "does_not_claim": "instrument_command_or_safety_authority",
        },
    ]


def build_new_run_measurement_writer_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured new-run writer summary from explicit event input."""
    _validate_references(source)
    measurement_record = source["measurement_record"]
    return {
        "writer_policy": copy.deepcopy(source["writer_policy"]),
        "measurement_record": {
            "measurement_record_id": measurement_record["measurement_record_id"],
            "label": measurement_record["label"],
            "experiment_type": measurement_record["experiment_type"],
            "target": measurement_record["target"],
            "source_kind": measurement_record["source_kind"],
            "lifecycle": _lifecycle_summary(source),
            "progress": _progress_summary(source),
            "primary_data": copy.deepcopy(source["primary_data"]),
            "preview": _preview_summary(source),
            "event_counts": _event_counts(source["writer_events"]),
            "classification": _classification(source),
        },
        "writer_events": _normalized_events(source),
        "writer_findings": _findings(source),
        "attention": _attention(),
    }
