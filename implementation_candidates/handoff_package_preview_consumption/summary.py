"""Preview-aware local consumption summary for handoff packages.

This candidate composes existing read-only handoff package consumers. It opens
one package, projects declared preview-shape facts, projects plot-first visual
review facts, and summarizes which local first-use surface is available without
rendering plots, invoking dataframe adapters, importing packages, or mutating
storage.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from implementation_candidates.handoff_package_preview_shape_view import (
    HandoffPackagePreviewShapeView,
    PreviewShapeMeasurement,
)
from implementation_candidates.handoff_package_read_view import open_handoff_package_view
from implementation_candidates.handoff_package_visual_review import (
    build_handoff_package_visual_review_model_from_read_view,
)

_EXPECTED_POLICY = {
    "composition_authority": "read_only_handoff_package_read_view",
    "package_open": "performed_via_handoff_package_read_view",
    "preview_shape_projection": "performed",
    "visual_review_projection": "performed",
    "first_surface_selection": "composed_projection_facts",
    "table_drilldown": "projected_as_summary_facts",
    "sdk_adapter": "not_invoked",
    "dataframe_adapter": "not_invoked",
    "plot_rendering": "not_performed",
    "interactive_gui": "not_defined",
    "package_acceptance": "not_performed",
    "storage_import": "not_performed",
    "archive_handling": "not_performed",
    "package_integrity": "not_claimed",
    "schema_inference": "not_performed",
    "scan_shape_inference": "not_performed",
    "shared_measurement_schema": "not_defined",
}

_FIRST_SURFACES = (
    "plot_first_visual_review",
    "table_drilldown",
    "review_findings",
)


def _codes(items: list[dict[str, Any]] | tuple[dict[str, Any], ...], key: str) -> list[str]:
    return [_require_key(_require_mapping(item, "coded item"), key, "coded item") for item in items]


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"handoff package preview consumption requires {owner} to be an object")
    return value


def _require_list(value: Any, owner: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"handoff package preview consumption requires {owner} to be a list")
    return value


def _require_key(mapping: dict[str, Any], key: str, owner: str) -> Any:
    if key not in mapping:
        raise ValueError(f"handoff package preview consumption requires {owner}.{key}")
    return mapping[key]


def _visual_index_by_measurement(visual_model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = _require_list(
        _require_key(visual_model, "measurement_index", "visual-review model"),
        "visual-review model.measurement_index",
    )
    index = {}
    for position, raw_item in enumerate(items):
        owner = f"visual-review measurement_index[{position}]"
        item = _require_mapping(raw_item, owner)
        measurement_id = _require_key(item, "measurement_record_id", owner)
        if measurement_id in index:
            raise ValueError(
                "handoff package preview consumption requires unique visual-review "
                f"measurement ids; duplicate={measurement_id}"
            )
        index[measurement_id] = item
    return index


def _visual_summaries_by_id(visual_model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = _require_list(
        _require_key(visual_model, "visual_summaries", "visual-review model"),
        "visual-review model.visual_summaries",
    )
    summaries = {}
    for position, raw_item in enumerate(items):
        owner = f"visual-review visual_summaries[{position}]"
        item = _require_mapping(raw_item, owner)
        visual_id = _require_key(item, "visual_summary_id", owner)
        if visual_id in summaries:
            raise ValueError(
                "handoff package preview consumption requires unique visual summary ids; "
                f"duplicate={visual_id}"
            )
        _require_key(item, "measurement_record_id", owner)
        plot = _require_mapping(_require_key(item, "plot", owner), f"{owner}.plot")
        _require_key(plot, "kind", f"{owner}.plot")
        summaries[visual_id] = item
    return summaries


def _first_surface(
    *,
    preview_shape: dict[str, Any],
    visual_summary_ids: list[str],
) -> dict[str, Any]:
    if preview_shape["status"] != "declared_preview_affordance_ready":
        return {
            "surface": "review_findings",
            "basis": "preview_shape_projection_needs_review",
            "does_not_claim": "preview_plot_ready",
        }
    if visual_summary_ids:
        return {
            "surface": "plot_first_visual_review",
            "basis": "declared_plot_candidate_projected_to_visual_summary",
            "does_not_claim": "plot_rendered",
        }
    return {
        "surface": "table_drilldown",
        "basis": "read_view_tables_available_without_declared_plot_candidate",
        "does_not_claim": "plot_ready_preview",
    }


def _validate_visual_alignment(
    *,
    preview_measurement_ids: tuple[str, ...],
    visual_index: dict[str, dict[str, Any]],
    visual_summaries: dict[str, dict[str, Any]],
) -> None:
    visual_measurement_ids = set(visual_index)
    expected_measurement_ids = set(preview_measurement_ids)
    if visual_measurement_ids != expected_measurement_ids:
        missing = sorted(expected_measurement_ids - visual_measurement_ids)
        extra = sorted(visual_measurement_ids - expected_measurement_ids)
        raise ValueError(
            "handoff package preview consumption requires aligned visual-review "
            f"measurement ids; missing={missing}; extra={extra}"
        )
    missing_summary_ids = []
    cross_linked_summary_ids = []
    for measurement_id, item in visual_index.items():
        visual_summary_ids = _require_list(
            _require_key(item, "visual_summary_ids", "visual-review measurement index item"),
            "visual-review measurement index item.visual_summary_ids",
        )
        _validate_table_drilldown(item)
        _require_list(
            _require_key(item, "attention_items", "visual-review measurement index item"),
            "visual-review measurement index item.attention_items",
        )
        _require_list(
            _require_key(item, "finding_codes", "visual-review measurement index item"),
            "visual-review measurement index item.finding_codes",
        )
        _require_key(item, "linked_context_count", "visual-review measurement index item")
        for visual_id in visual_summary_ids:
            if visual_id not in visual_summaries:
                missing_summary_ids.append(visual_id)
                continue
            summary_measurement_id = _require_key(
                visual_summaries[visual_id],
                "measurement_record_id",
                "visual-review visual summary",
            )
            if summary_measurement_id != measurement_id:
                cross_linked_summary_ids.append(visual_id)
    if missing_summary_ids:
        raise ValueError(
            "handoff package preview consumption requires visual summary ids "
            f"to resolve; missing={sorted(missing_summary_ids)}"
        )
    if cross_linked_summary_ids:
        raise ValueError(
            "handoff package preview consumption requires visual summaries to match "
            f"their measurement index entries; cross_linked={sorted(cross_linked_summary_ids)}"
        )


def _validate_table_drilldown(item: dict[str, Any]) -> None:
    table_drilldown = _require_mapping(
        _require_key(item, "table_drilldown", "visual-review measurement index item"),
        "visual-review measurement index item.table_drilldown",
    )
    for table_key in ("primary_table", "preview_table"):
        table = _require_mapping(
            _require_key(table_drilldown, table_key, "visual-review table_drilldown"),
            f"visual-review table_drilldown.{table_key}",
        )
        _require_list(
            _require_key(table, "columns", f"visual-review table_drilldown.{table_key}"),
            f"visual-review table_drilldown.{table_key}.columns",
        )
        _require_key(table, "row_count", f"visual-review table_drilldown.{table_key}")
    _require_key(table_drilldown, "dataframe_adapter", "visual-review table_drilldown")


def _measurement_surface(
    *,
    preview_measurement: PreviewShapeMeasurement,
    visual_index_item: dict[str, Any],
    visual_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    preview_shape = preview_measurement.preview_shape.as_dict()
    visual_summary_ids = list(
        _require_key(
            visual_index_item,
            "visual_summary_ids",
            "visual-review measurement index item",
        )
    )
    table_drilldown = _require_mapping(
        _require_key(
            visual_index_item,
            "table_drilldown",
            "visual-review measurement index item",
        ),
        "visual-review measurement index item.table_drilldown",
    )
    primary_table = _require_mapping(
        _require_key(table_drilldown, "primary_table", "visual-review table_drilldown"),
        "visual-review table_drilldown.primary_table",
    )
    preview_table = _require_mapping(
        _require_key(table_drilldown, "preview_table", "visual-review table_drilldown"),
        "visual-review table_drilldown.preview_table",
    )
    visual_plot_kinds = [
        visual_summaries[visual_id]["plot"]["kind"] for visual_id in visual_summary_ids
    ]
    return {
        "measurement_record_id": preview_measurement.measurement_record_id,
        "label": preview_measurement.label,
        "first_surface": _first_surface(
            preview_shape=preview_shape,
            visual_summary_ids=visual_summary_ids,
        ),
        "declared_preview": {
            "kind": preview_shape["kind"],
            "preview_affordance": preview_shape["preview_affordance"],
            "status": preview_shape["status"],
            "plot_candidate_count": len(preview_shape["plot_candidates"]),
            "finding_codes": _codes(preview_shape["findings"], "finding"),
            "schema_inference": preview_shape["schema_inference"],
            "scan_shape_inference": preview_shape["scan_shape_inference"],
            "file_observation": preview_shape["file_observation"],
        },
        "visual_review": {
            "visual_summary_ids": visual_summary_ids,
            "plot_kinds": visual_plot_kinds,
            "attention_codes": _codes(visual_index_item["attention_items"], "code"),
            "plot_rendering": "not_performed",
        },
        "table_access": {
            "primary_columns": list(primary_table["columns"]),
            "primary_row_count": primary_table["row_count"],
            "preview_columns": list(preview_table["columns"]),
            "preview_row_count": preview_table["row_count"],
            "dataframe_adapter": table_drilldown["dataframe_adapter"],
        },
        "linked_context_count": visual_index_item["linked_context_count"],
        "finding_codes": list(visual_index_item["finding_codes"]),
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "preview_consumption_composed",
            "severity": "info",
            "basis": "Read view, preview-shape projection, and visual-review projection were composed into one local receipt.",
            "does_not_claim": "new_package_contract_or_stable_sdk",
        },
        {
            "code": "first_surface_selection_uses_composed_projection_facts",
            "severity": "info",
            "basis": "The receipt chooses among existing local review/use surfaces from declared preview and visual-review facts.",
            "does_not_claim": "gui_routing_or_user_preference_model",
        },
        {
            "code": "dataframe_adapter_not_invoked",
            "severity": "info",
            "basis": "Notebook/dataframe use remains an available downstream affordance and is not exercised by this composition.",
            "does_not_claim": "dataframe_api_contract",
        },
    ]


def build_handoff_package_preview_consumption_summary(package_dir: Path) -> dict[str, Any]:
    """Build a local preview-aware consumption receipt for a handoff package."""

    read_view = open_handoff_package_view(package_dir)
    preview_shape_view = HandoffPackagePreviewShapeView(read_view)
    visual_model = build_handoff_package_visual_review_model_from_read_view(read_view)
    visual_index = _visual_index_by_measurement(visual_model)
    visual_summaries = _visual_summaries_by_id(visual_model)
    _validate_visual_alignment(
        preview_measurement_ids=preview_shape_view.measurement_ids,
        visual_index=visual_index,
        visual_summaries=visual_summaries,
    )
    measurements = [
        _measurement_surface(
            preview_measurement=measurement,
            visual_index_item=visual_index[measurement.measurement_record_id],
            visual_summaries=visual_summaries,
        )
        for measurement in preview_shape_view.measurements
    ]

    return {
        "artifact_posture": "review_summary",
        "preview_consumption_policy": copy.deepcopy(_EXPECTED_POLICY),
        "package": {
            "package_id": read_view.package_id,
            "display_name": read_view.display_name,
            "preview_classification": read_view.preview_classification,
            "measurement_count": len(read_view.measurement_ids),
            "first_surface_counts": {
                surface: sum(
                    1
                    for measurement in measurements
                    if measurement["first_surface"]["surface"] == surface
                )
                for surface in _FIRST_SURFACES
            },
        },
        "read_view": {
            "performed": True,
            "measurement_ids": list(read_view.measurement_ids),
            "linked_context_count": len(read_view.linked_context),
            "finding_codes": _codes(read_view.findings, "finding"),
        },
        "preview_shape_view": {
            "performed": True,
            "measurement_ids": list(preview_shape_view.measurement_ids),
            "policy": preview_shape_view.preview_shape_policy,
        },
        "visual_review": {
            "performed": True,
            "visual_summary_count": visual_model["package"]["visual_summary_count"],
            "measurement_index_count": len(visual_model["measurement_index"]),
            "attention_codes": _codes(visual_model["attention"], "code"),
        },
        "measurements": measurements,
        "attention": _attention(),
    }
