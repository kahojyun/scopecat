"""Plot-first local review projection for opened handoff packages.

This candidate sits above the read-only package read view. It organizes the
facts a user is likely to inspect first after opening a package: declared plots,
axis metadata, structured context, linked-context notices, and review findings.
It does not render plots, generate captions, import packages, or define a final
GUI or SDK.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from implementation_candidates.handoff_package_read_view import (
    HandoffPackageReadView,
    MeasurementReadView,
    open_handoff_package_view,
)

_EXPECTED_POLICY = {
    "view_model_authority": "read_only_handoff_package_read_view",
    "primary_orientation": "plot_first",
    "caption_text_generation": "not_performed",
    "plot_rendering": "not_performed",
    "table_drilldown": "available_as_summary_facts",
    "dataframe_adapter": "not_defined",
    "gui_component_model": "not_defined",
    "package_acceptance": "not_performed",
    "storage_import": "not_performed",
    "archive_handling": "not_performed",
    "package_integrity": "not_claimed",
    "schema_inference": "not_performed",
    "shared_measurement_schema": "not_defined",
}


def _column_lookup(measurement: MeasurementReadView) -> dict[str, dict[str, str]]:
    return {column["name"]: dict(column) for column in measurement.declared_preview_columns}


def _axis(column_name: str, columns: dict[str, dict[str, str]]) -> dict[str, str | None]:
    try:
        column = columns[column_name]
    except KeyError as exc:
        raise ValueError("handoff package visual review requires plot axis metadata") from exc
    return {
        "name": column_name,
        "label": column["label"],
        "unit": column.get("unit"),
        "role": column.get("role"),
    }


def _linked_context_refs(measurement: MeasurementReadView) -> list[dict[str, Any]]:
    return [
        {
            "link_id": item["link_id"],
            "kind": item["kind"],
            "label": item["label"],
            "package_state": item["package_state"],
            "materialization": item["materialization"],
        }
        for item in measurement.linked_context
    ]


def _visual_summary_id(
    *,
    measurement_record_id: str,
    position: int,
) -> str:
    return f"{measurement_record_id}-visual-{position}"


def _duplicate_plot_positions(plot_series: tuple[Any, ...]) -> set[int]:
    seen: set[tuple[str, str, str]] = set()
    duplicates = set()
    for position, series in enumerate(plot_series, start=1):
        candidate_key = (series.source, series.x_name, series.y_name)
        if candidate_key in seen:
            duplicates.add(position)
        seen.add(candidate_key)
    return duplicates


def _attention_items(
    measurement: MeasurementReadView,
    *,
    plot_series: tuple[Any, ...],
) -> list[dict[str, Any]]:
    items = [
        {
            "code": finding["finding"],
            "severity": finding["severity"],
            "subject_type": finding["subject_type"],
            "subject_id": finding["subject_id"],
        }
        for finding in measurement.findings
    ]
    if not plot_series:
        items.append(
            {
                "code": "no_declared_plot_candidates",
                "severity": "review",
                "subject_type": "measurement",
                "subject_id": measurement.measurement_record_id,
            }
        )
    return items


def _measurement_facts(measurement: MeasurementReadView) -> dict[str, Any]:
    primary_table = measurement.primary_table()
    preview_table = measurement.preview_table()
    plot_series = measurement.plot_series()
    duplicate_positions = _duplicate_plot_positions(plot_series)
    visual_attention = _attention_items(
        measurement,
        plot_series=plot_series,
    )
    measurement_attention = copy.deepcopy(visual_attention)
    if duplicate_positions:
        measurement_attention.append(
            {
                "code": "duplicate_declared_plot_candidate",
                "severity": "review",
                "subject_type": "measurement",
                "subject_id": measurement.measurement_record_id,
            }
        )
    return {
        "primary_table": primary_table,
        "preview_table": preview_table,
        "plot_series": plot_series,
        "declared_columns": _column_lookup(measurement),
        "linked_context_refs": _linked_context_refs(measurement),
        "duplicate_positions": duplicate_positions,
        "measurement_attention_items": measurement_attention,
        "visual_attention_items": visual_attention,
    }


def _visual_summaries(
    measurement: MeasurementReadView,
    facts: dict[str, Any],
) -> list[dict[str, Any]]:
    primary_table = facts["primary_table"]
    preview_table = facts["preview_table"]
    columns = facts["declared_columns"]
    linked_context = facts["linked_context_refs"]
    attention = facts["visual_attention_items"]
    duplicate_positions = facts["duplicate_positions"]

    summaries = []
    for position, series in enumerate(facts["plot_series"], start=1):
        visual_summary_id = _visual_summary_id(
            measurement_record_id=measurement.measurement_record_id,
            position=position,
        )
        is_duplicate = position in duplicate_positions
        visual_attention = copy.deepcopy(attention)
        if is_duplicate:
            visual_attention.append(
                {
                    "code": "duplicate_declared_plot_candidate",
                    "severity": "review",
                    "subject_type": "plot_candidate",
                    "subject_id": visual_summary_id,
                }
            )
        summaries.append(
            {
                "visual_summary_id": visual_summary_id,
                "measurement_record_id": measurement.measurement_record_id,
                "measurement_label": measurement.label,
                "visual_priority": "primary_review_surface",
                "plot": {
                    "kind": "declared_xy_series",
                    "candidate_position": position,
                    "duplicate_candidate": is_duplicate,
                    "source": series.source,
                    "x_axis": _axis(series.x_name, columns),
                    "y_axis": _axis(series.y_name, columns),
                    "series": {
                        "label": measurement.label,
                        "point_count": len(series.points),
                        "points": series.to_records(),
                    },
                    "rendering": "not_performed",
                },
                "structured_context": {
                    "experiment_type": measurement.experiment_type,
                    "target": measurement.target,
                    "primary_table": {
                        "columns": list(primary_table.columns),
                        "row_count": primary_table.row_count,
                    },
                    "preview_table": {
                        "columns": list(preview_table.columns),
                        "row_count": preview_table.row_count,
                    },
                    "linked_context_refs": copy.deepcopy(linked_context),
                },
                "attention_items": visual_attention,
            }
        )
    return summaries


def _measurement_index_item(
    measurement: MeasurementReadView,
    visual_summary_ids: list[str],
    facts: dict[str, Any],
) -> dict[str, Any]:
    primary_table = facts["primary_table"]
    preview_table = facts["preview_table"]
    return {
        "measurement_record_id": measurement.measurement_record_id,
        "label": measurement.label,
        "experiment_type": measurement.experiment_type,
        "target": measurement.target,
        "integrity_check": measurement.integrity_check,
        "visual_summary_ids": list(visual_summary_ids),
        "table_drilldown": {
            "primary_table": {
                "columns": list(primary_table.columns),
                "row_count": primary_table.row_count,
            },
            "preview_table": {
                "columns": list(preview_table.columns),
                "row_count": preview_table.row_count,
            },
            "dataframe_adapter": "not_defined",
        },
        "linked_context_count": len(measurement.linked_context),
        "finding_codes": [finding["finding"] for finding in measurement.findings],
        "attention_items": copy.deepcopy(facts["measurement_attention_items"]),
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "plot_first_review_projection",
            "severity": "info",
            "basis": "Declared plot candidates are projected before table drilldown facts for package review.",
            "does_not_claim": "gui_rendering_or_caption_generation",
        },
        {
            "code": "structured_caption_facts_only",
            "severity": "info",
            "basis": "Axis metadata, context facts, linked references, and findings are emitted as structured fields.",
            "does_not_claim": "natural_language_caption_contract",
        },
        {
            "code": "package_integrity_not_claimed",
            "severity": "review",
            "basis": "The read view reports package data for review without receiving-side checksum validation.",
            "does_not_claim": "package_integrity_verified",
        },
    ]


def build_handoff_package_visual_review_model_from_read_view(
    read_view: HandoffPackageReadView,
) -> dict[str, Any]:
    """Build a plot-first local review view model from an opened package."""

    visual_summaries = []
    measurement_index = []
    for measurement in read_view.measurements:
        facts = _measurement_facts(measurement)
        measurement_visuals = _visual_summaries(measurement, facts)
        visual_summaries.extend(measurement_visuals)
        measurement_index.append(
            _measurement_index_item(
                measurement,
                [summary["visual_summary_id"] for summary in measurement_visuals],
                facts,
            )
        )

    return {
        "artifact_posture": "review_summary",
        "visual_review_policy": copy.deepcopy(_EXPECTED_POLICY),
        "package": {
            "package_id": read_view.package_id,
            "display_name": read_view.display_name,
            "preview_classification": read_view.preview_classification,
            "measurement_count": len(read_view.measurement_ids),
            "visual_summary_count": len(visual_summaries),
            "finding_codes": [finding["finding"] for finding in read_view.findings],
        },
        "visual_summaries": visual_summaries,
        "measurement_index": measurement_index,
        "linked_context_refs": _package_linked_context_refs(read_view),
        "attention": _attention(),
    }


def _package_linked_context_refs(
    read_view: HandoffPackageReadView,
) -> list[dict[str, Any]]:
    return [
        {
            "link_id": item["link_id"],
            "kind": item["kind"],
            "label": item["label"],
            "package_state": item["package_state"],
            "materialization": item["materialization"],
            "linked_measurement_record_ids": list(item["linked_measurement_record_ids"]),
        }
        for item in read_view.linked_context
    ]


def build_handoff_package_visual_review_model(package_dir: Path) -> dict[str, Any]:
    """Open a package and return the plot-first local review view model."""

    return build_handoff_package_visual_review_model_from_read_view(
        open_handoff_package_view(package_dir)
    )
