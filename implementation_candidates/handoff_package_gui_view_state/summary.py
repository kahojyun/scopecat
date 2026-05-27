"""Local GUI-ready view-state projection for handoff packages.

This candidate sits above existing handoff package reader projections. It
builds the state a future GUI could consume for measurement navigation and a
first inspection panel without rendering UI, invoking dataframe adapters,
accepting packages, or mutating storage.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from implementation_candidates.handoff_package_preview_consumption import (
    build_handoff_package_preview_consumption_summary,
)
from implementation_candidates.handoff_package_read_view import open_handoff_package_view
from implementation_candidates.handoff_package_visual_review import (
    build_handoff_package_visual_review_model_from_read_view,
)

_EXPECTED_POLICY = {
    "view_state_authority": "local_handoff_package_reader_projections",
    "package_open": "performed_via_handoff_package_read_view",
    "preview_consumption_projection": "consumed",
    "visual_review_projection": "consumed",
    "measurement_navigation": "projected_as_local_state",
    "default_selection": "first_measurement_in_package_order",
    "primary_surface_selection": "derived_from_preview_consumption_first_surface",
    "plot_rendering": "not_performed",
    "gui_components": "not_defined",
    "interactive_events": "not_performed",
    "sdk_adapter": "not_invoked",
    "dataframe_adapter": "not_invoked",
    "package_acceptance": "not_performed",
    "storage_import": "not_performed",
    "archive_handling": "not_performed",
    "package_integrity": "not_claimed",
    "schema_inference": "not_performed",
    "scan_shape_inference": "not_performed",
    "shared_measurement_schema": "not_defined",
}

_PRIMARY_SURFACES = ("plot", "table_drilldown", "review_findings")


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"handoff package GUI view state requires {owner} to be an object")
    return value


def _require_list(value: Any, owner: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"handoff package GUI view state requires {owner} to be a list")
    return value


def _require_key(mapping: dict[str, Any], key: str, owner: str) -> Any:
    if key not in mapping:
        raise ValueError(f"handoff package GUI view state requires {owner}.{key}")
    return mapping[key]


def _codes(items: list[dict[str, Any]], key: str) -> list[str]:
    return [_require_key(_require_mapping(item, "coded item"), key, "coded item") for item in items]


def _index_by_key(
    items: list[Any],
    *,
    key: str,
    owner: str,
) -> dict[str, dict[str, Any]]:
    indexed = {}
    for position, raw_item in enumerate(items):
        item_owner = f"{owner}[{position}]"
        item = _require_mapping(raw_item, item_owner)
        item_id = _require_key(item, key, item_owner)
        if item_id in indexed:
            raise ValueError(
                "handoff package GUI view state requires unique ids; "
                f"owner={owner}; duplicate={item_id}"
            )
        indexed[item_id] = item
    return indexed


def _visual_summaries_by_id(visual_model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summaries = _index_by_key(
        _require_list(
            _require_key(visual_model, "visual_summaries", "visual-review model"),
            "visual-review model.visual_summaries",
        ),
        key="visual_summary_id",
        owner="visual-review visual_summaries",
    )
    for visual_id, summary in summaries.items():
        _require_key(summary, "measurement_record_id", f"visual summary {visual_id}")
        _require_mapping(_require_key(summary, "plot", f"visual summary {visual_id}"), "plot")
    return summaries


def _visual_index_by_measurement(visual_model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _index_by_key(
        _require_list(
            _require_key(visual_model, "measurement_index", "visual-review model"),
            "visual-review model.measurement_index",
        ),
        key="measurement_record_id",
        owner="visual-review measurement_index",
    )


def _consumption_by_measurement(consumption: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _index_by_key(
        _require_list(
            _require_key(consumption, "measurements", "preview-consumption summary"),
            "preview-consumption summary.measurements",
        ),
        key="measurement_record_id",
        owner="preview-consumption measurements",
    )


def _linked_context_by_measurement(
    visual_model: dict[str, Any],
    *,
    known_measurement_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    refs = _require_list(
        _require_key(visual_model, "linked_context_refs", "visual-review model"),
        "visual-review model.linked_context_refs",
    )
    by_measurement: dict[str, list[dict[str, Any]]] = {}
    for position, raw_ref in enumerate(refs):
        ref = _require_mapping(raw_ref, f"visual-review linked_context_refs[{position}]")
        linked_measurement_ids = _require_list(
            _require_key(ref, "linked_measurement_record_ids", "visual-review linked context"),
            "visual-review linked context.linked_measurement_record_ids",
        )
        unknown_measurement_ids = sorted(set(linked_measurement_ids) - known_measurement_ids)
        if unknown_measurement_ids:
            raise ValueError(
                "handoff package GUI view state requires linked context measurement "
                f"ids to align; unknown={unknown_measurement_ids}"
            )
        projected_ref = {
            "link_id": _require_key(ref, "link_id", "visual-review linked context"),
            "kind": _require_key(ref, "kind", "visual-review linked context"),
            "label": _require_key(ref, "label", "visual-review linked context"),
            "package_state": _require_key(
                ref,
                "package_state",
                "visual-review linked context",
            ),
            "materialization": _require_key(
                ref,
                "materialization",
                "visual-review linked context",
            ),
        }
        for measurement_id in linked_measurement_ids:
            by_measurement.setdefault(measurement_id, []).append(copy.deepcopy(projected_ref))
    return by_measurement


def _validate_alignment(
    *,
    consumption: dict[str, Any],
    visual_model: dict[str, Any],
    consumption_index: dict[str, dict[str, Any]],
    visual_index: dict[str, dict[str, Any]],
    visual_summaries: dict[str, dict[str, Any]],
) -> None:
    consumption_package = _require_mapping(
        _require_key(consumption, "package", "preview-consumption summary"),
        "preview-consumption summary.package",
    )
    visual_package = _require_mapping(
        _require_key(visual_model, "package", "visual-review model"),
        "visual-review model.package",
    )
    if consumption_package.get("package_id") != visual_package.get("package_id"):
        raise ValueError("handoff package GUI view state requires package id alignment")
    if set(consumption_index) != set(visual_index):
        missing = sorted(set(consumption_index) - set(visual_index))
        extra = sorted(set(visual_index) - set(consumption_index))
        raise ValueError(
            "handoff package GUI view state requires aligned measurement ids; "
            f"missing={missing}; extra={extra}"
        )
    for measurement_id, visual_item in visual_index.items():
        visual_summary_ids = _require_list(
            _require_key(visual_item, "visual_summary_ids", "visual-review measurement item"),
            "visual-review measurement item.visual_summary_ids",
        )
        for visual_id in visual_summary_ids:
            if visual_id not in visual_summaries:
                raise ValueError(
                    "handoff package GUI view state requires visual summary ids to resolve; "
                    f"missing={visual_id}"
                )
            summary_measurement_id = visual_summaries[visual_id]["measurement_record_id"]
            if summary_measurement_id != measurement_id:
                raise ValueError(
                    "handoff package GUI view state requires visual summaries to match "
                    f"their measurement index entries; visual_summary_id={visual_id}"
                )


def _primary_surface(
    *,
    consumption_measurement: dict[str, Any],
    visual_item: dict[str, Any],
) -> dict[str, Any]:
    first_surface = _require_mapping(
        _require_key(consumption_measurement, "first_surface", "preview-consumption measurement"),
        "preview-consumption measurement.first_surface",
    )
    source_surface = _require_key(first_surface, "surface", "preview-consumption first_surface")
    if source_surface == "plot_first_visual_review":
        visual_summary_ids = _require_list(
            _require_key(visual_item, "visual_summary_ids", "visual-review measurement item"),
            "visual-review measurement item.visual_summary_ids",
        )
        if not visual_summary_ids:
            raise ValueError(
                "handoff package GUI view state requires plot surfaces to reference "
                "a visual summary"
            )
        return {
            "kind": "plot",
            "source_surface": source_surface,
            "visual_summary_id": visual_summary_ids[0],
            "basis": first_surface["basis"],
            "rendering": "not_performed",
            "does_not_claim": "rendered_plot_or_gui_component",
        }
    if source_surface == "table_drilldown":
        return {
            "kind": "table_drilldown",
            "source_surface": source_surface,
            "basis": first_surface["basis"],
            "rendering": "not_performed",
            "does_not_claim": "dataframe_adapter_or_gui_table_component",
        }
    if source_surface == "review_findings":
        return {
            "kind": "review_findings",
            "source_surface": source_surface,
            "basis": first_surface["basis"],
            "rendering": "not_performed",
            "does_not_claim": "automatic_repair_or_schema_inference",
        }
    raise ValueError(
        "handoff package GUI view state requires known preview-consumption first surface; "
        f"surface={source_surface}"
    )


def _plot_panel(
    *,
    primary_surface: dict[str, Any],
    visual_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if primary_surface["kind"] != "plot":
        return {
            "state": "not_primary_surface",
            "visual_summary_id": None,
            "rendering": "not_performed",
        }
    visual_id = primary_surface["visual_summary_id"]
    summary = visual_summaries[visual_id]
    plot = _require_mapping(_require_key(summary, "plot", "visual summary"), "visual summary.plot")
    series = _require_mapping(_require_key(plot, "series", "visual summary plot"), "plot.series")
    return {
        "state": "ready_for_gui_renderer",
        "visual_summary_id": visual_id,
        "kind": plot["kind"],
        "title_label": series["label"],
        "candidate_position": plot["candidate_position"],
        "duplicate_candidate": plot["duplicate_candidate"],
        "x_axis": copy.deepcopy(plot["x_axis"]),
        "y_axis": copy.deepcopy(plot["y_axis"]),
        "point_count": series["point_count"],
        "point_data": "available_from_visual_review_model",
        "rendering": "not_performed",
    }


def _table_panel(visual_item: dict[str, Any]) -> dict[str, Any]:
    table_drilldown = _require_mapping(
        _require_key(visual_item, "table_drilldown", "visual-review measurement item"),
        "visual-review measurement item.table_drilldown",
    )
    primary_table = _require_mapping(
        _require_key(table_drilldown, "primary_table", "table_drilldown"),
        "table_drilldown.primary_table",
    )
    preview_table = _require_mapping(
        _require_key(table_drilldown, "preview_table", "table_drilldown"),
        "table_drilldown.preview_table",
    )
    primary_columns = _require_list(
        _require_key(primary_table, "columns", "table_drilldown.primary_table"),
        "table_drilldown.primary_table.columns",
    )
    preview_columns = _require_list(
        _require_key(preview_table, "columns", "table_drilldown.preview_table"),
        "table_drilldown.preview_table.columns",
    )
    return {
        "state": "available_as_drilldown",
        "primary_table": {
            "columns": list(primary_columns),
            "row_count": _require_key(
                primary_table,
                "row_count",
                "table_drilldown.primary_table",
            ),
        },
        "preview_table": {
            "columns": list(preview_columns),
            "row_count": _require_key(
                preview_table,
                "row_count",
                "table_drilldown.preview_table",
            ),
        },
        "dataframe_adapter": "not_invoked",
    }


def _findings_panel(
    *,
    visual_item: dict[str, Any],
    consumption_measurement: dict[str, Any],
) -> dict[str, Any]:
    attention_items = copy.deepcopy(
        _require_list(
            _require_key(visual_item, "attention_items", "visual-review measurement item"),
            "visual-review measurement item.attention_items",
        )
    )
    declared_preview = _require_mapping(
        _require_key(
            consumption_measurement, "declared_preview", "preview-consumption measurement"
        ),
        "preview-consumption measurement.declared_preview",
    )
    declared_preview_findings = _require_list(
        _require_key(declared_preview, "finding_codes", "preview-consumption declared_preview"),
        "preview-consumption declared_preview.finding_codes",
    )
    finding_codes = list(
        dict.fromkeys(
            list(consumption_measurement["finding_codes"]) + list(declared_preview_findings)
        )
    )
    return {
        "state": "visible",
        "attention_codes": _codes(attention_items, "code"),
        "finding_codes": finding_codes,
        "attention_items": attention_items,
    }


def _available_actions(primary_surface: dict[str, Any]) -> list[dict[str, str]]:
    actions = [
        {
            "action": "open_table_drilldown",
            "state": "available",
            "does_not_claim": "dataframe_adapter_invoked",
        },
        {
            "action": "copy_dataframe_code",
            "state": "not_defined",
            "does_not_claim": "stable_sdk_or_dataframe_api",
        },
        {
            "action": "accept_package",
            "state": "not_performed",
            "does_not_claim": "storage_import",
        },
    ]
    if primary_surface["kind"] == "plot":
        actions.insert(
            0,
            {
                "action": "render_primary_plot",
                "state": "deferred_to_gui_renderer",
                "does_not_claim": "plot_rendered_by_candidate",
            },
        )
    return actions


def _measurement_state(
    *,
    consumption_measurement: dict[str, Any],
    visual_item: dict[str, Any],
    visual_summaries: dict[str, dict[str, Any]],
    linked_context_by_measurement: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    measurement_id = consumption_measurement["measurement_record_id"]
    primary_surface = _primary_surface(
        consumption_measurement=consumption_measurement,
        visual_item=visual_item,
    )
    linked_context_refs = copy.deepcopy(linked_context_by_measurement.get(measurement_id, []))
    return {
        "measurement_record_id": measurement_id,
        "label": consumption_measurement["label"],
        "primary_surface": primary_surface,
        "plot_panel": _plot_panel(
            primary_surface=primary_surface,
            visual_summaries=visual_summaries,
        ),
        "table_panel": _table_panel(visual_item),
        "context_panel": {
            "state": "visible",
            "linked_context_count": len(linked_context_refs),
            "linked_context_refs": linked_context_refs,
        },
        "findings_panel": _findings_panel(
            visual_item=visual_item,
            consumption_measurement=consumption_measurement,
        ),
        "available_actions": _available_actions(primary_surface),
    }


def _navigation_item(measurement_state: dict[str, Any]) -> dict[str, Any]:
    findings_panel = measurement_state["findings_panel"]
    return {
        "measurement_record_id": measurement_state["measurement_record_id"],
        "label": measurement_state["label"],
        "primary_surface": measurement_state["primary_surface"]["kind"],
        "attention_count": len(findings_panel["attention_items"]),
        "finding_codes": list(findings_panel["finding_codes"]),
        "linked_context_count": measurement_state["context_panel"]["linked_context_count"],
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "gui_view_state_projected",
            "severity": "info",
            "basis": "Existing local handoff package projections were shaped into measurement navigation and selected-measurement panels.",
            "does_not_claim": "live_gui_or_final_gui_contract",
        },
        {
            "code": "plot_rendering_deferred",
            "severity": "info",
            "basis": "Plot panel state carries visual summary ids, axes, labels, and point counts for a future renderer.",
            "does_not_claim": "plot_rendered_or_plotting_library_selected",
        },
        {
            "code": "dataframe_and_import_not_invoked",
            "severity": "info",
            "basis": "Table drilldown and actions remain local view-state facts; dataframe adapters and package acceptance are not invoked.",
            "does_not_claim": "dataframe_api_or_storage_import",
        },
    ]


def build_handoff_package_gui_view_state(package_dir: Path) -> dict[str, Any]:
    """Build a local GUI-ready view-state summary for a handoff package."""

    read_view = open_handoff_package_view(package_dir)
    visual_model = build_handoff_package_visual_review_model_from_read_view(read_view)
    consumption = build_handoff_package_preview_consumption_summary(package_dir)

    visual_index = _visual_index_by_measurement(visual_model)
    visual_summaries = _visual_summaries_by_id(visual_model)
    consumption_index = _consumption_by_measurement(consumption)
    _validate_alignment(
        consumption=consumption,
        visual_model=visual_model,
        consumption_index=consumption_index,
        visual_index=visual_index,
        visual_summaries=visual_summaries,
    )
    measurement_ids = list(read_view.measurement_ids)
    if set(measurement_ids) != set(consumption_index):
        missing = sorted(set(measurement_ids) - set(consumption_index))
        extra = sorted(set(consumption_index) - set(measurement_ids))
        raise ValueError(
            "handoff package GUI view state requires read-view measurement ids "
            f"to align with consumed projections; missing={missing}; extra={extra}"
        )
    linked_context = _linked_context_by_measurement(
        visual_model,
        known_measurement_ids=set(measurement_ids),
    )
    measurement_states = [
        _measurement_state(
            consumption_measurement=consumption_index[measurement_id],
            visual_item=visual_index[measurement_id],
            visual_summaries=visual_summaries,
            linked_context_by_measurement=linked_context,
        )
        for measurement_id in measurement_ids
    ]
    selected_measurement_id = measurement_ids[0] if measurement_ids else None
    selected_measurement = measurement_states[0] if measurement_states else None

    return {
        "artifact_posture": "review_summary",
        "gui_view_state_policy": copy.deepcopy(_EXPECTED_POLICY),
        "package": {
            "package_id": read_view.package_id,
            "display_name": read_view.display_name,
            "preview_classification": read_view.preview_classification,
            "measurement_count": len(read_view.measurement_ids),
            "selected_measurement_id": selected_measurement_id,
            "primary_surface_counts": {
                surface: sum(
                    1
                    for measurement in measurement_states
                    if measurement["primary_surface"]["kind"] == surface
                )
                for surface in _PRIMARY_SURFACES
            },
        },
        "navigation": {
            "measurement_list": [_navigation_item(item) for item in measurement_states],
            "default_selection": {
                "measurement_record_id": selected_measurement_id,
                "basis": "first_measurement_in_package_order",
            },
        },
        "selected_measurement": copy.deepcopy(selected_measurement),
        "measurement_states": measurement_states,
        "consumed_projections": {
            "preview_consumption": {
                "performed": True,
                "measurement_ids": measurement_ids,
                "first_surface_counts": copy.deepcopy(
                    consumption["package"]["first_surface_counts"]
                ),
            },
            "visual_review": {
                "performed": True,
                "visual_summary_count": visual_model["package"]["visual_summary_count"],
                "measurement_index_count": len(visual_model["measurement_index"]),
            },
        },
        "attention": _attention(),
    }
