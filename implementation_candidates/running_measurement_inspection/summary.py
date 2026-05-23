"""Structured summary builder for running measurement inspection.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read source data, poll live services, render
plots, save monitor state, mutate scan plans, control hardware, or define a
final lifecycle, reader, plotting, GUI, storage, import, or export contract.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in ("Users", "private", "home", "tmp"))
_SOURCE_IDENTITY_AUTHORITIES = {"LAB_LOCAL"}


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


def _validate_source_identity(measurement: dict[str, Any]) -> None:
    source_identity = measurement["source_identity"]
    if measurement["local_path_public_safe"] is not False:
        raise ValueError("measurement local path must remain non-public-safe")
    if ":" not in source_identity:
        raise ValueError("measurement source_identity must include authority")
    authority, path = source_identity.split(":", 1)
    if authority not in _SOURCE_IDENTITY_AUTHORITIES:
        raise ValueError("measurement source_identity authority is unsupported")
    if (
        not path
        or not path.startswith("/redacted/")
        or "\\" in path
        or re.match(r"^[A-Za-z]:", path)
        or any(marker in path for marker in _PRIVATE_PATH_MARKERS)
    ):
        raise ValueError("measurement source_identity must be public-safe and redacted")


def _validate_count(value: int, owner: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")


def _validate_progress(progress: dict[str, Any]) -> None:
    if progress["source"] != "fixture_declared":
        raise ValueError("progress source must stay fixture_declared")
    for key in ("recorded_points", "expected_points"):
        _validate_count(progress[key], f"progress {key}")
    if progress["recorded_points"] > progress["expected_points"]:
        raise ValueError("recorded_points must not exceed expected_points")

    latest = progress["latest_completed_unit"]
    current = progress["current_partial_unit"]
    if latest["complete"] is not True:
        raise ValueError("latest completed unit must be complete")
    if latest["default_preview_candidate"] is not True:
        raise ValueError("latest completed unit must be the default preview candidate")
    if current["complete"] is not False:
        raise ValueError("current partial unit must remain incomplete")
    if current["default_preview_candidate"] is not False:
        raise ValueError("current partial unit must not be the default preview candidate")

    if latest["kind"] == "sweep":
        _validate_repeated_sweep_progress(progress)
        return
    if latest["kind"] == "rectangular_prefix":
        _validate_rectangular_prefix_progress(progress)
        return
    raise ValueError(f"unsupported latest completed unit kind: {latest['kind']}")


def _validate_repeated_sweep_progress(progress: dict[str, Any]) -> None:
    for key in ("recorded_sweeps", "expected_sweeps", "points_per_sweep"):
        _validate_count(progress[key], f"progress {key}")
    if progress["recorded_sweeps"] > progress["expected_sweeps"]:
        raise ValueError("recorded_sweeps must not exceed expected_sweeps")
    if progress["expected_points"] != progress["expected_sweeps"] * progress["points_per_sweep"]:
        raise ValueError("sweep expected_points must match expected_sweeps")

    latest = progress["latest_completed_unit"]
    current = progress["current_partial_unit"]
    if current["kind"] != "sweep":
        raise ValueError("current partial unit kind must match sweep progress")
    _validate_count(latest["sweep_index"], "latest completed sweep index")
    _validate_count(latest["row_count"], "latest completed sweep row_count")
    _validate_count(current["sweep_index"], "current partial sweep index")
    _validate_count(current["recorded_points"], "current partial sweep recorded_points")
    _validate_count(current["expected_points"], "current partial sweep expected_points")
    if latest["row_count"] != progress["points_per_sweep"]:
        raise ValueError("latest completed sweep row_count must match points_per_sweep")
    if current["expected_points"] != progress["points_per_sweep"]:
        raise ValueError("current partial sweep expected_points must match points_per_sweep")
    if current["recorded_points"] > current["expected_points"]:
        raise ValueError("current partial sweep recorded_points must not exceed expected_points")
    if latest["sweep_index"] + 1 != progress["recorded_sweeps"]:
        raise ValueError("latest completed sweep index must match recorded_sweeps")
    if current["sweep_index"] != progress["recorded_sweeps"]:
        raise ValueError("current partial sweep index must follow recorded_sweeps")
    completed_points = progress["recorded_sweeps"] * progress["points_per_sweep"]
    if completed_points + current["recorded_points"] != progress["recorded_points"]:
        raise ValueError("sweep progress counts must match recorded_points")


def _validate_rectangular_prefix_progress(progress: dict[str, Any]) -> None:
    for key in ("recorded_rows", "expected_rows", "points_per_row"):
        _validate_count(progress[key], f"progress {key}")
    if progress["recorded_rows"] > progress["expected_rows"]:
        raise ValueError("recorded_rows must not exceed expected_rows")
    if progress["expected_points"] != progress["expected_rows"] * progress["points_per_row"]:
        raise ValueError("rectangular prefix expected_points must match expected_rows")

    latest = progress["latest_completed_unit"]
    current = progress["current_partial_unit"]
    if current["kind"] != "grid_row":
        raise ValueError("current partial unit kind must match rectangular prefix progress")
    _validate_count(latest["completed_rows"], "latest completed rectangular rows")
    _validate_count(latest["point_count"], "latest completed rectangular point_count")
    _validate_count(current["recorded_points"], "current partial grid row recorded_points")
    _validate_count(current["expected_points"], "current partial grid row expected_points")
    if latest["completed_rows"] != progress["recorded_rows"]:
        raise ValueError("latest completed rows must match recorded_rows")
    if latest["point_count"] != latest["completed_rows"] * progress["points_per_row"]:
        raise ValueError("rectangular prefix point_count must match completed rows")
    if current["expected_points"] != progress["points_per_row"]:
        raise ValueError("current partial grid row expected_points must match points_per_row")
    if current["recorded_points"] > current["expected_points"]:
        raise ValueError("current partial grid row recorded_points must not exceed expected_points")
    if current["outer_axis"] != latest["outer_axis"]:
        raise ValueError("current partial grid row outer_axis must match latest completed unit")
    if current["outer_value"] <= latest["last_completed_outer_value"]:
        raise ValueError("current partial grid row outer_value must follow completed prefix")
    if progress["recorded_rows"] == progress["expected_rows"]:
        raise ValueError("current partial grid row requires incomplete recorded_rows")
    completed_points = progress["recorded_rows"] * progress["points_per_row"]
    if completed_points + current["recorded_points"] != progress["recorded_points"]:
        raise ValueError("rectangular prefix counts must match recorded_points")


def _validate_latest_data_reference(source: dict[str, Any]) -> None:
    reference = source["latest_data_reference"]
    _validate_relative_path(reference["path"], "latest data reference")
    if reference["kind"] != "partial_recorded_table":
        raise ValueError("latest data reference kind must stay partial_recorded_table")
    if reference["source"] != "recorded_file":
        raise ValueError("latest data reference source must stay recorded_file")
    _validate_latest_completed_filter(source)


def _validate_latest_completed_filter(source: dict[str, Any]) -> None:
    reference = source["latest_data_reference"]
    latest = source["progress"]["latest_completed_unit"]
    declared_names = {column["name"] for column in source["preview_metadata"]["declared_columns"]}
    latest_filter = reference["latest_completed_filter"]
    if latest_filter["column"] not in declared_names:
        raise ValueError("latest completed filter column must reference declared columns")

    if latest["kind"] == "sweep":
        if set(latest_filter) != {"column", "equals"}:
            raise ValueError("sweep latest completed filter must match expected shape")
        _validate_count(latest_filter["equals"], "sweep latest completed filter equals")
        if latest_filter["column"] != "sweep_index":
            raise ValueError("sweep latest completed filter column must be sweep_index")
        if latest_filter["equals"] != latest["sweep_index"]:
            raise ValueError("sweep latest completed filter must match latest sweep index")
        return

    if latest["kind"] == "rectangular_prefix":
        if set(latest_filter) != {"column", "max_inclusive"}:
            raise ValueError("rectangular latest completed filter must match expected shape")
        if latest_filter["column"] != latest["outer_axis"]:
            raise ValueError("rectangular latest completed filter column must match outer axis")
        if latest_filter["max_inclusive"] != latest["last_completed_outer_value"]:
            raise ValueError("rectangular latest completed filter must match latest outer value")
        return

    raise ValueError(f"unsupported latest completed unit kind: {latest['kind']}")


def _validate_preview_metadata(source: dict[str, Any]) -> None:
    preview = source["preview_metadata"]
    if preview["status"] != "preview_ready":
        raise ValueError("running inspection preview status must stay preview_ready")
    if preview["metadata_source"] != "fixture_declared":
        raise ValueError("preview metadata source must stay fixture_declared")
    if preview["data_shape"] is None:
        raise ValueError("preview-ready running inspection requires data_shape")

    declared_names = {column["name"] for column in preview["declared_columns"]}
    axis_order = preview["data_shape"]["axis_order"]
    if not declared_names or not axis_order:
        raise ValueError("preview-ready running inspection requires columns and axis order")
    if any(axis not in declared_names for axis in axis_order):
        raise ValueError("preview axis order must reference declared columns")

    data_path = source["latest_data_reference"]["path"]
    for candidate in preview["plot_candidates"]:
        if candidate["source"] != data_path:
            raise ValueError("plot candidate source must match latest data reference path")
        for axis_key in ("x", "y", "z"):
            if axis_key in candidate and candidate[axis_key] not in declared_names:
                raise ValueError("plot candidate axes must reference declared columns")


def _declared_column_names(source: dict[str, Any]) -> set[str]:
    return {column["name"] for column in source["preview_metadata"]["declared_columns"]}


def _declared_axis_names(source: dict[str, Any]) -> set[str]:
    return set(source["preview_metadata"]["data_shape"]["axis_order"])


def _validate_ephemeral_monitor_state(source: dict[str, Any]) -> None:
    state = source["ephemeral_monitor_state"]
    declared_columns = _declared_column_names(source)
    declared_axes = _declared_axis_names(source)
    if state["durable"] is not False:
        raise ValueError("ephemeral monitor state must not be durable")
    keys = set(state)
    if keys == {"durable", "selected_range", "temporary_fit_preview"}:
        _validate_selected_range(state["selected_range"], declared_columns)
        _validate_temporary_fit_preview(state["temporary_fit_preview"])
        return
    if keys == {"durable", "selected_region", "temporary_feature_preview"}:
        _validate_selected_region(state["selected_region"], declared_columns)
        _validate_temporary_feature_preview(state["temporary_feature_preview"], declared_axes)
        return
    raise ValueError("ephemeral monitor state shape is not supported by this candidate")


def _validate_selected_range(value: dict[str, Any], declared_columns: set[str]) -> None:
    if set(value) != {"axis", "min", "max"}:
        raise ValueError("selected range must match expected shape")
    if value["axis"] not in declared_columns:
        raise ValueError("selected range axis must reference declared columns")
    if value["min"] > value["max"]:
        raise ValueError("selected range min must not exceed max")


def _validate_selected_region(value: dict[str, Any], declared_columns: set[str]) -> None:
    if set(value) != {"x_axis", "x_min", "x_max", "y_axis", "y_min", "y_max"}:
        raise ValueError("selected region must match expected shape")
    if value["x_axis"] not in declared_columns or value["y_axis"] not in declared_columns:
        raise ValueError("selected region axes must reference declared columns")
    if value["x_min"] > value["x_max"] or value["y_min"] > value["y_max"]:
        raise ValueError("selected region bounds must be ordered")


def _validate_temporary_fit_preview(value: dict[str, Any]) -> None:
    if set(value) != {"kind", "status", "fit_over", "vertex_x", "claim_guard"}:
        raise ValueError("temporary fit preview must match expected shape")
    if value["status"] != "preview_only":
        raise ValueError("temporary fit preview status must stay preview_only")
    if value["fit_over"] != "latest_completed_unit":
        raise ValueError("temporary fit preview must be computed over latest_completed_unit")


def _validate_temporary_feature_preview(value: dict[str, Any], declared_axes: set[str]) -> None:
    if set(value) != {"kind", "status", "computed_over", "minimum_at", "claim_guard"}:
        raise ValueError("temporary feature preview must match expected shape")
    if value["status"] != "preview_only":
        raise ValueError("temporary feature preview status must stay preview_only")
    if value["computed_over"] != "latest_completed_unit":
        raise ValueError("temporary feature preview must be computed over latest_completed_unit")
    if not isinstance(value["minimum_at"], dict) or not value["minimum_at"]:
        raise ValueError("temporary feature preview minimum_at must be declared")
    if set(value["minimum_at"]) != declared_axes:
        raise ValueError("temporary feature preview minimum_at must reference declared axes")


def _validate_saved_decisions(source: dict[str, Any]) -> None:
    if source["saved_decisions"]:
        raise ValueError("saved decisions are not supported by this running inspection candidate")


def _validate_source(source: dict[str, Any]) -> None:
    _validate_source_identity(source["measurement"])
    if source["lifecycle"]["source"] != "fixture_declared":
        raise ValueError("lifecycle source must stay fixture_declared")
    if source["attention_policy"]["source"] != "fixture_declared":
        raise ValueError("attention policy source must stay fixture_declared")
    _validate_progress(source["progress"])
    _validate_preview_metadata(source)
    _validate_latest_data_reference(source)
    _validate_ephemeral_monitor_state(source)
    _validate_saved_decisions(source)


def _parse_instant(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("running inspection timestamps must be UTC Z instants")
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _latest_data_age_seconds(source: dict[str, Any]) -> int:
    observed_at = _parse_instant(source["observed_at"])
    last_update_at = _parse_instant(source["lifecycle"]["last_update_at"])
    delta_seconds = (observed_at - last_update_at).total_seconds()
    if delta_seconds < 0:
        raise ValueError("observed_at must not be before lifecycle.last_update_at")
    return int(delta_seconds)


def _measurement_summary(measurement: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement_id": measurement["measurement_id"],
        "legacy_data_id": measurement["legacy_data_id"],
        "label": measurement["label"],
        "experiment_type": measurement["experiment_type"],
        "target": measurement["target"],
        "source_identity": measurement["source_identity"],
    }


def _preview_summary(source: dict[str, Any]) -> dict[str, Any]:
    preview = source["preview_metadata"]
    data_shape = preview["data_shape"]
    summary = {
        "status": preview["status"],
        "metadata_source": preview["metadata_source"],
        "shape_kind": data_shape["kind"],
        "axis_order": list(data_shape["axis_order"]),
    }
    for optional_key in (
        "repeat_axis",
        "row_order",
        "grid_assumption",
        "expected_axis_cardinality",
    ):
        if optional_key in data_shape:
            summary[optional_key] = copy.deepcopy(data_shape[optional_key])
    summary["declared_roles"] = copy.deepcopy(preview["declared_columns"])
    summary["plot_candidates"] = copy.deepcopy(preview["plot_candidates"])
    return summary


def _strip_claim_guards(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_claim_guards(item) for key, item in value.items() if key != "claim_guard"
        }
    if isinstance(value, list):
        return [_strip_claim_guards(item) for item in value]
    return copy.deepcopy(value)


def _attention(source: dict[str, Any], latest_data_age_seconds: int) -> list[dict[str, str]]:
    stale_after_seconds = source["attention_policy"]["stale_after_seconds"]
    if latest_data_age_seconds <= stale_after_seconds:
        return []
    return [
        {
            "code": "latest_data_stale",
            "subject": "lifecycle.last_update_at",
            "basis": "latest_data_age_seconds > stale_after_seconds",
            "message": (
                f"Latest update is {latest_data_age_seconds} seconds before "
                "the fixture observation time."
            ),
        }
    ]


def build_running_measurement_inspection_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured running-inspection summary from explicit fixture input."""
    _validate_source(source)
    latest_data_age_seconds = _latest_data_age_seconds(source)
    return {
        "measurement": _measurement_summary(source["measurement"]),
        "lifecycle": copy.deepcopy(source["lifecycle"]),
        "progress": copy.deepcopy(source["progress"]),
        "preview": _preview_summary(source),
        "latest_data_reference": copy.deepcopy(source["latest_data_reference"]),
        "attention_basis": {
            "observed_at": source["observed_at"],
            "latest_data_age_seconds": latest_data_age_seconds,
            "stale_after_seconds": source["attention_policy"]["stale_after_seconds"],
            "source": source["attention_policy"]["source"],
        },
        "ephemeral_monitor_state": _strip_claim_guards(source["ephemeral_monitor_state"]),
        "saved_decisions": copy.deepcopy(source["saved_decisions"]),
        "attention": _attention(source, latest_data_age_seconds),
    }
