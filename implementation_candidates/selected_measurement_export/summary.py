"""Structured summary builder for a selected measurement export candidate.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read source data, copy files, create archives,
render Markdown, infer schemas, or traverse relation graphs.
"""

from __future__ import annotations

import copy
from typing import Any


def _selected_measurements(source: dict[str, Any]) -> list[dict[str, Any]]:
    selected_ids = source["selected_export_set"]["selected_legacy_data_ids"]
    measurements_by_id = {
        measurement["legacy_data_id"]: measurement for measurement in source["measurements"]
    }
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("selected_export_set contains duplicate measurement IDs")
    if any(selected_id not in measurements_by_id for selected_id in selected_ids):
        raise ValueError("selected_export_set references a missing measurement")
    return [measurements_by_id[selected_id] for selected_id in selected_ids]


def _selected_id_set(source: dict[str, Any]) -> set[int]:
    return set(source["selected_export_set"]["selected_legacy_data_ids"])


def _primary_data_item(measurement: dict[str, Any]) -> dict[str, Any]:
    for item in measurement["default_bundle"]:
        if item["kind"] == "primary_data":
            if item["path"] != measurement["source_file"]:
                raise ValueError(
                    "primary_data path must match source_file for fixture "
                    f"measurement {measurement['legacy_data_id']}"
                )
            return item
    raise ValueError(f"measurement {measurement['legacy_data_id']} has no primary data")


def _preview_summary(measurement: dict[str, Any]) -> dict[str, Any]:
    preview = measurement["preview_metadata"]
    if preview["status"] == "preview_ready":
        for candidate in preview["plot_candidates"]:
            if candidate["source"] != measurement["source_file"]:
                raise ValueError(
                    "plot candidate source must match source_file for fixture "
                    f"measurement {measurement['legacy_data_id']}"
                )
        return {
            "status": "preview_ready",
            "metadata_authority": preview["metadata_authority"],
            "shape_kind": preview["data_shape"]["kind"],
            "axis_order": preview["data_shape"]["axis_order"],
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

    if preview["status"] == "degraded_preview":
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

    raise ValueError(
        f"unsupported preview status for measurement {measurement['legacy_data_id']}: "
        f"{preview['status']}"
    )


def _measurement_summary(measurement: dict[str, Any]) -> dict[str, Any]:
    primary_data = _primary_data_item(measurement)
    return {
        "role": "selected_measurement",
        "legacy_data_id": measurement["legacy_data_id"],
        "experiment_label": measurement["experiment_label"],
        "experiment_type": measurement["experiment_type"],
        "target": measurement["target"],
        "source_file": measurement["source_file"],
        "export_source": measurement["export_source"],
        "primary_data_authority": primary_data["authority"],
        "source_transform_policy": measurement["source_transform_expectation"]["policy"],
        "default_bundle": copy.deepcopy(measurement["default_bundle"]),
        "preview": _preview_summary(measurement),
    }


def _linked_context_summary(item: dict[str, Any]) -> dict[str, Any]:
    output = {
        "kind": item["kind"],
        "label": item["label"],
        "path": item["path"],
        "include_status": item["include_status"],
        "relation": item["relation"],
        "authority": item["authority"],
        "linked_legacy_data_ids": item["linked_legacy_data_ids"],
    }
    return output


def _linked_context_for_selected(source: dict[str, Any]) -> list[dict[str, Any]]:
    selected_ids = _selected_id_set(source)
    return [
        item
        for item in source["linked_context"]
        if selected_ids.intersection(item["linked_legacy_data_ids"])
    ]


def _warnings(
    source: dict[str, Any],
    selected_measurements: list[dict[str, Any]],
    linked_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings = [
        {
            "code": "local_only_path",
            "subject": "legacy_source_location.local_path",
            "message": "Original local path is redaction-sensitive and not portable.",
            "public_safe_value": source["legacy_source_location"]["display_path"],
        }
    ]

    warnings.extend(
        {
            "code": measurement["preview_metadata"]["warning_code"],
            "subject": f"measurement:{measurement['legacy_data_id']}",
            "message": (
                f"Measurement {measurement['legacy_data_id']} can still be "
                "exported, but preview shape and column roles are missing."
            ),
        }
        for measurement in selected_measurements
        if measurement["preview_metadata"]["status"] == "degraded_preview"
    )

    warnings.extend(
        {
            "code": "missing_companion",
            "subject": item["path"],
            "message": (
                f"A user-declared companion for measurement "
                f"{item['linked_legacy_data_ids'][0]} is absent from the fixture."
            ),
        }
        for item in linked_context
        if item["include_status"] == "missing"
    )
    return warnings


def build_selected_measurement_export_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary from explicit selected measurement export input."""
    selected = source["selected_export_set"]
    selected_measurements = _selected_measurements(source)
    linked_context = _linked_context_for_selected(source)

    return {
        "selected_export_set": {
            "selection_mode": selected["selection_mode"],
            "selected_legacy_data_ids": list(selected["selected_legacy_data_ids"]),
            "traversal_policy": selected["traversal_policy"],
        },
        "measurements": [
            _measurement_summary(measurement) for measurement in selected_measurements
        ],
        "linked_context": [_linked_context_summary(item) for item in linked_context],
        "warnings": _warnings(source, selected_measurements, linked_context),
    }
