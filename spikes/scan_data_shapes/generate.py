"""Generate expected outputs from scan data-shape fixtures.

This module is a validation spike, not product code or a durable data schema.
It intentionally supports only the public-safe fixture shapes under
``tests/fixtures/scan_data_shapes``.
"""

from __future__ import annotations

import argparse
import csv
import json
from itertools import product
from pathlib import Path
from typing import Any

GRID_DECISIONS_NOT_EARNED = [
    "final storage schema",
    "general dataframe API",
    "plot rendering",
    "automatic schema inference",
    "ragged or adaptive scan support",
    "trace-per-point support",
    "array-valued measurement support",
    "scientific validity or reproducibility",
]

SIDECAR_DECISIONS_NOT_EARNED = [
    "final storage schema",
    "legacy sidecar importer",
    "automatic schema inference",
    "notebook parsing",
    "plot rendering",
    "unit semantic validation",
    "scientific validity or reproducibility",
]

RAGGED_DECISIONS_NOT_EARNED = [
    "final storage schema",
    "shared data-shape schema",
    "general dataframe API",
    "legacy importer",
    "plot rendering",
    "adaptive planner semantics",
    "automatic schema inference",
    "rectangular grid coercion",
    "trace-per-point support",
    "array-valued measurement support",
    "scientific validity or reproducibility",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _column_names(columns: list[dict[str, Any]]) -> list[str]:
    return [column["name"] for column in columns]


def _columns_by_role(columns: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [column for column in columns if column["role"] == role]


def _without_role(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": column["name"],
            "label": column["label"],
            "unit": column["unit"],
        }
        for column in columns
    ]


def _format_list(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "`none`"


def _format_role(role: str) -> str:
    return role.replace("_", " ")


def _format_quantity(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _sort_numeric_strings(values: list[str]) -> list[str]:
    def sort_key(value: str) -> tuple[int, float | str]:
        try:
            return (0, float(value))
        except ValueError:
            return (1, value)

    return sorted(values, key=sort_key)


def _unique_in_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _ragged_shape_columns(
    *, axis_order: list[str], grouping_axis: str, ragged_axis: str
) -> list[str]:
    return _unique_in_order([*axis_order, grouping_axis, ragged_axis])


def _ragged_column_validation(
    *,
    declared_names: list[str],
    source_columns: list[str],
    axis_order: list[str],
    grouping_axis: str,
    ragged_axis: str,
) -> dict[str, list[str]]:
    shape_columns = _ragged_shape_columns(
        axis_order=axis_order,
        grouping_axis=grouping_axis,
        ragged_axis=ragged_axis,
    )
    missing_declared_columns = [name for name in declared_names if name not in source_columns]
    missing_shape_columns = [name for name in shape_columns if name not in source_columns]
    undeclared_shape_columns = [name for name in shape_columns if name not in declared_names]
    return {
        "missing_declared_columns": missing_declared_columns,
        "missing_shape_columns": missing_shape_columns,
        "undeclared_shape_columns": undeclared_shape_columns,
        "blocking_columns": _unique_in_order(
            [*missing_declared_columns, *missing_shape_columns, *undeclared_shape_columns]
        ),
    }


def _grid_status(
    *,
    axis_order: list[str],
    expected_axis_cardinality: dict[str, int],
    rows: list[dict[str, str]],
    missing_columns: list[str],
) -> str:
    if missing_columns:
        return "fail"

    expected_point_count = 1
    for axis in axis_order:
        expected_point_count *= expected_axis_cardinality[axis]
    if len(rows) != expected_point_count:
        return "fail"

    observed_coordinates = [tuple(row[axis] for axis in axis_order) for row in rows]
    if len(set(observed_coordinates)) != len(observed_coordinates):
        return "fail"

    expected_values = [sorted({row[axis] for row in rows}, key=float) for axis in axis_order]
    expected_coordinates = set(product(*expected_values))
    return "pass" if set(observed_coordinates) == expected_coordinates else "fail"


def _ragged_status(
    *,
    axis_order: list[str],
    grouping_axis: str,
    expected_group_point_counts: dict[str, int],
    rows: list[dict[str, str]],
    missing_columns: list[str],
) -> str:
    if missing_columns:
        return "fail"

    observed_coordinates = [tuple(row[axis] for axis in axis_order) for row in rows]
    if len(set(observed_coordinates)) != len(observed_coordinates):
        return "fail"

    observed_group_counts: dict[str, int] = {}
    for row in rows:
        group = row[grouping_axis]
        observed_group_counts[group] = observed_group_counts.get(group, 0) + 1

    return "pass" if observed_group_counts == expected_group_point_counts else "fail"


def _ragged_observed_status(
    *,
    axis_order: list[str],
    rows: list[dict[str, str]],
    missing_columns: list[str],
) -> str:
    if missing_columns:
        return "fail"

    observed_coordinates = [tuple(row[axis] for axis in axis_order) for row in rows]
    return "pass" if len(set(observed_coordinates)) == len(observed_coordinates) else "fail"


def _ragged_group_point_counts(
    *,
    grouping_axis: str,
    rows: list[dict[str, str]],
    missing_columns: list[str],
) -> dict[str, int]:
    if missing_columns:
        return {}

    group_point_counts: dict[str, int] = {}
    for row in rows:
        group = row[grouping_axis]
        group_point_counts[group] = group_point_counts.get(group, 0) + 1
    return {
        group: group_point_counts[group]
        for group in _sort_numeric_strings(list(group_point_counts))
    }


def _generate_2d_grid_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    source_columns, rows = read_csv_table(fixture_root / measurement["source_table"])

    declared_columns = source["declared_columns"]
    declared_names = _column_names(declared_columns)
    missing_columns = [name for name in declared_names if name not in source_columns]
    extra_columns = [name for name in source_columns if name not in declared_names]
    axis_order = data_shape["axis_order"]
    axis_cardinality = {
        axis: len({row[axis] for row in rows}) if axis in source_columns else 0
        for axis in axis_order
    }
    expected_point_count = 1
    for axis in axis_order:
        expected_point_count *= data_shape["expected_axis_cardinality"][axis]

    sweep_axes = _columns_by_role(declared_columns, "sweep_axis")
    measured_responses = _columns_by_role(declared_columns, "measured_response")

    return {
        "shape_summary_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "shape-input.json",
        "measurement": measurement,
        "shape": {
            "kind": data_shape["kind"],
            "grid_assumption": data_shape["grid_assumption"],
            "axis_order": axis_order,
            "axis_cardinality": axis_cardinality,
            "expected_point_count": expected_point_count,
            "actual_row_count": len(rows),
            "status": _grid_status(
                axis_order=axis_order,
                expected_axis_cardinality=data_shape["expected_axis_cardinality"],
                rows=rows,
                missing_columns=missing_columns,
            ),
        },
        "declared_axes": _without_role(sweep_axes),
        "declared_dependents": _without_role(measured_responses),
        "held_conditions": source["held_conditions"],
        "column_validation": {
            "status": "pass" if not missing_columns else "fail",
            "declared_columns": declared_names,
            "source_columns": source_columns,
            "missing_declared_columns": missing_columns,
            "extra_source_columns": extra_columns,
        },
        "plot_candidates": [
            {
                "title": f"{measurement['label']}: {column['label']}",
                "x": axis_order[1],
                "y": axis_order[0],
                "z": column["name"],
                "source": measurement["source_table"],
            }
            for column in measured_responses
        ],
        "warnings": [
            {
                "code": "extra_source_column",
                "subject": extra_columns[0] if extra_columns else None,
                "message": (
                    "Source table contains an undeclared column. It is reported "
                    "but not treated as plot metadata."
                ),
            },
        ],
        "boundary_notes": [
            "The 2D grid shape comes from fixture declaration, not schema inference.",
            "Plot candidates are declared 2D grid plot candidates only; no rendering, fit, uncertainty, or scientific validation is provided.",
            "The fixture validates declared shape consistency only, not scientific correctness.",
        ],
        "decisions_not_earned": GRID_DECISIONS_NOT_EARNED,
    }


def _generate_ragged_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    source_columns, rows = read_csv_table(fixture_root / measurement["source_table"])

    declared_columns = source["declared_columns"]
    declared_names = _column_names(declared_columns)
    extra_columns = [name for name in source_columns if name not in declared_names]
    axis_order = data_shape["axis_order"]
    grouping_axis = data_shape["grouping_axis"]
    ragged_axis = data_shape["ragged_axis"]
    ragged_validation = _ragged_column_validation(
        declared_names=declared_names,
        source_columns=source_columns,
        axis_order=axis_order,
        grouping_axis=grouping_axis,
        ragged_axis=ragged_axis,
    )
    group_point_counts = _ragged_group_point_counts(
        grouping_axis=grouping_axis,
        rows=rows,
        missing_columns=ragged_validation["blocking_columns"],
    )
    expected_group_point_counts = data_shape["expected_group_point_counts"]
    missing_expected_groups = [
        group for group in expected_group_point_counts if group not in group_point_counts
    ]
    unexpected_observed_groups = [
        group for group in group_point_counts if group not in expected_group_point_counts
    ]

    sweep_axes = _columns_by_role(declared_columns, "sweep_axis")
    measured_responses = _columns_by_role(declared_columns, "measured_response")

    return {
        "shape_summary_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "shape-input.json",
        "measurement": measurement,
        "shape": {
            "kind": data_shape["kind"],
            "ragged_assumption": data_shape["ragged_assumption"],
            "axis_order": axis_order,
            "grouping_axis": grouping_axis,
            "ragged_axis": ragged_axis,
            "expected_group_point_counts": expected_group_point_counts,
            "group_point_counts": group_point_counts,
            "missing_expected_groups": missing_expected_groups,
            "unexpected_observed_groups": unexpected_observed_groups,
            "total_row_count": len(rows),
            "status": _ragged_status(
                axis_order=axis_order,
                grouping_axis=grouping_axis,
                expected_group_point_counts=expected_group_point_counts,
                rows=rows,
                missing_columns=ragged_validation["blocking_columns"],
            ),
        },
        "declared_axes": _without_role(sweep_axes),
        "declared_dependents": _without_role(measured_responses),
        "held_conditions": source["held_conditions"],
        "column_validation": {
            "status": "pass" if not ragged_validation["blocking_columns"] else "fail",
            "declared_columns": declared_names,
            "source_columns": source_columns,
            "missing_declared_columns": ragged_validation["missing_declared_columns"],
            "missing_shape_columns": ragged_validation["missing_shape_columns"],
            "undeclared_shape_columns": ragged_validation["undeclared_shape_columns"],
            "extra_source_columns": extra_columns,
        },
        "plot_candidates": [
            {
                "title": f"{measurement['label']}: {column['label']}",
                "plot_kind": "ragged_line_family",
                "x": ragged_axis,
                "series": grouping_axis,
                "y": column["name"],
                "source": measurement["source_table"],
            }
            for column in measured_responses
        ],
        "warnings": [
            {
                "code": "extra_source_column",
                "subject": extra_column,
                "message": (
                    "Source table contains an undeclared column. It is reported "
                    "but not treated as plot metadata."
                ),
            }
            for extra_column in extra_columns
        ],
        "boundary_notes": [
            "The ragged scan shape comes from fixture declaration, not schema inference.",
            "Variable inner-axis coverage is expected for this fixture and is not treated as missing rectangular grid points.",
            "Plot candidates are declared ragged line-family candidates only; no rendering, fit, uncertainty, or scientific validation is provided.",
            "The fixture validates declared ragged coverage consistency only, not scientific correctness.",
        ],
        "decisions_not_earned": RAGGED_DECISIONS_NOT_EARNED,
    }


def _generate_ragged_observed_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    source_columns, rows = read_csv_table(fixture_root / measurement["source_table"])

    declared_columns = source["declared_columns"]
    declared_names = _column_names(declared_columns)
    extra_columns = [name for name in source_columns if name not in declared_names]
    axis_order = data_shape["axis_order"]
    grouping_axis = data_shape["grouping_axis"]
    ragged_axis = data_shape["ragged_axis"]
    ragged_validation = _ragged_column_validation(
        declared_names=declared_names,
        source_columns=source_columns,
        axis_order=axis_order,
        grouping_axis=grouping_axis,
        ragged_axis=ragged_axis,
    )
    group_point_counts = _ragged_group_point_counts(
        grouping_axis=grouping_axis,
        rows=rows,
        missing_columns=ragged_validation["blocking_columns"],
    )

    sweep_axes = _columns_by_role(declared_columns, "sweep_axis")
    measured_responses = _columns_by_role(declared_columns, "measured_response")

    return {
        "shape_summary_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "shape-input.json",
        "measurement": measurement,
        "shape": {
            "kind": data_shape["kind"],
            "coverage_policy": data_shape["coverage_policy"],
            "axis_order": axis_order,
            "grouping_axis": grouping_axis,
            "ragged_axis": ragged_axis,
            "group_point_counts": group_point_counts,
            "total_row_count": len(rows),
            "status": _ragged_observed_status(
                axis_order=axis_order,
                rows=rows,
                missing_columns=ragged_validation["blocking_columns"],
            ),
        },
        "declared_axes": _without_role(sweep_axes),
        "declared_dependents": _without_role(measured_responses),
        "held_conditions": source["held_conditions"],
        "column_validation": {
            "status": "pass" if not ragged_validation["blocking_columns"] else "fail",
            "declared_columns": declared_names,
            "source_columns": source_columns,
            "missing_declared_columns": ragged_validation["missing_declared_columns"],
            "missing_shape_columns": ragged_validation["missing_shape_columns"],
            "undeclared_shape_columns": ragged_validation["undeclared_shape_columns"],
            "extra_source_columns": extra_columns,
        },
        "plot_candidates": [
            {
                "title": f"{measurement['label']}: {column['label']}",
                "plot_kind": "ragged_observed_line_family",
                "x": ragged_axis,
                "series": grouping_axis,
                "y": column["name"],
                "source": measurement["source_table"],
            }
            for column in measured_responses
        ],
        "warnings": [
            {
                "code": "extra_source_column",
                "subject": extra_column,
                "message": (
                    "Source table contains an undeclared column. It is reported "
                    "but not treated as plot metadata."
                ),
            }
            for extra_column in extra_columns
        ],
        "boundary_notes": [
            "Observed-only ragged coverage is summarized from the fixture table after acquisition.",
            "No expected group point counts are declared, so completeness against a planned adaptive path is not claimed.",
            "Plot candidates are declared observed ragged line-family candidates only; no rendering, fit, uncertainty, or scientific validation is provided.",
            "The fixture validates observed coordinate uniqueness and declared column presence only, not scientific correctness.",
        ],
        "decisions_not_earned": RAGGED_DECISIONS_NOT_EARNED,
    }


def _generate_sidecar_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    physical_columns, rows = read_csv_table(fixture_root / measurement["source_table"])
    column_mapping = source["column_mapping"]
    mapped_physical_names = [column["physical_name"] for column in column_mapping]
    declared_names = [column["declared_name"] for column in column_mapping]
    missing_physical = [name for name in mapped_physical_names if name not in physical_columns]
    unmapped_physical = [name for name in physical_columns if name not in mapped_physical_names]
    has_unique_names = len(set(declared_names)) == len(declared_names)
    has_axis = any(column["role"] == "sweep_axis" for column in column_mapping)
    has_response = any(column["role"] == "measured_response" for column in column_mapping)
    status = (
        "pass"
        if not missing_physical and has_unique_names and has_axis and has_response
        else "fail"
    )
    sweep_axis = next(column for column in column_mapping if column["role"] == "sweep_axis")
    measured_response = next(
        column for column in column_mapping if column["role"] == "measured_response"
    )

    return {
        "shape_summary_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "shape-input.json",
        "measurement": measurement,
        "shape": {
            "kind": data_shape["kind"],
            "table_shape": data_shape["table_shape"],
            "axis_order": data_shape["axis_order"],
            "row_count": len(rows),
            "status": status,
        },
        "column_mapping": column_mapping,
        "held_conditions": source["held_conditions"],
        "column_validation": {
            "status": status,
            "physical_columns": physical_columns,
            "declared_names": declared_names,
            "missing_physical_columns": missing_physical,
            "unmapped_physical_columns": unmapped_physical,
        },
        "plot_candidates": [
            {
                "title": f"{measurement['label']}: {measured_response['label']}",
                "x": sweep_axis["declared_name"],
                "y": measured_response["declared_name"],
                "source": measurement["source_table"],
                "metadata_source": measurement["metadata_source"],
            }
        ],
        "warnings": [
            {
                "code": "legacy_source_weak_labels",
                "subject": measurement["source_table"],
                "message": (
                    "Source table uses weak physical column names; sidecar "
                    "metadata is required for interpretation."
                ),
            },
        ],
        "boundary_notes": [
            "Column meaning comes from sidecar declaration, not source header inference.",
            "Plot candidates use sidecar-declared column meaning; no source-header inference, fit, uncertainty, or scientific validation is provided.",
            "The fixture validates mapping consistency only, not semantic correctness or scientific validity.",
        ],
        "decisions_not_earned": SIDECAR_DECISIONS_NOT_EARNED,
    }


def generate_summary(fixture_root: Path) -> dict[str, Any]:
    source = load_json(fixture_root / "shape-input.json")
    kind = source["data_shape"]["kind"]
    if kind == "2d_grid_table":
        return _generate_2d_grid_summary(source, fixture_root)
    if kind == "ragged_adaptive_table":
        return _generate_ragged_summary(source, fixture_root)
    if kind == "ragged_observed_only_table":
        return _generate_ragged_observed_summary(source, fixture_root)
    if kind == "sidecar_declared_table":
        return _generate_sidecar_summary(source, fixture_root)
    raise ValueError(f"unsupported scan data-shape fixture kind: {kind}")


def _generate_2d_grid_review(summary: dict[str, Any]) -> str:
    measurement = summary["measurement"]
    shape = summary["shape"]
    validation = summary["column_validation"]
    rows = [
        "# Expected 2D Grid Table Shape Review",
        "",
        "## Status",
        "",
        "Expected reviewer-facing output for the synthetic `2d_grid_table` fixture. This",
        "is not a storage schema, plotting API, file importer, or product contract.",
        "",
        "## Measurement",
        "",
        f"- measurement: `{measurement['measurement_id']}`",
        f"- label: `{measurement['label']}`",
        f"- target: `{measurement['target']}`",
        f"- source kind: `{measurement['source_kind']}`",
        f"- source table: `{measurement['source_table']}`",
        "",
        "## Declared Shape",
        "",
        f"- kind: `{shape['kind']}`",
        f"- grid assumption: `{shape['grid_assumption']}`",
        f"- axis order: {_format_list(shape['axis_order'])}",
        f"- expected point count: `{shape['expected_point_count']}`",
        f"- actual row count: `{shape['actual_row_count']}`",
        f"- status: `{shape['status']}`",
        "",
        "## Axes And Dependents",
        "",
        "| Name | Label | Role | Unit |",
        "| --- | --- | --- | --- |",
    ]
    for column in summary["declared_axes"]:
        rows.append(f"| `{column['name']}` | {column['label']} | sweep axis | `{column['unit']}` |")
    for column in summary["declared_dependents"]:
        rows.append(
            f"| `{column['name']}` | {column['label']} | measured response | `{column['unit']}` |"
        )
    rows.extend(
        [
            "",
            "Held condition:",
            "",
        ]
    )
    for condition in summary["held_conditions"]:
        rows.append(
            f"- {condition['label']}: `{_format_quantity(condition['value'])} "
            f"{condition['unit']}` (`{condition['authority']}`)"
        )
    rows.extend(
        [
            "",
            "## Column Validation",
            "",
            f"- status: `{validation['status']}`",
            f"- declared columns: {_format_list(validation['declared_columns'])}",
            f"- source columns: {_format_list(validation['source_columns'])}",
            f"- missing declared columns: {_format_list(validation['missing_declared_columns'])}",
            f"- extra source columns: {_format_list(validation['extra_source_columns'])}",
            "",
            "## Plot Candidates",
            "",
            "| X | Y | Z | Source | Boundary note |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in summary["plot_candidates"]:
        rows.append(
            f"| `{candidate['x']}` | `{candidate['y']}` | `{candidate['z']}` | "
            f"`{candidate['source']}` | {summary['boundary_notes'][1]} |"
        )
    rows.extend(
        [
            "",
            "## Warnings",
            "",
            f"- `extra_source_column`: source table contains undeclared `{validation['extra_source_columns'][0]}`. It",
            "  is reported but not treated as plot metadata.",
            "",
            "## Boundary Notes",
            "",
            "- The 2D grid shape comes from fixture declaration, not schema inference.",
            "- Plot candidates are declared 2D grid plot candidates only; no rendering,",
            "  fit, uncertainty, or scientific validation is provided.",
            "- This fixture validates declared shape consistency only, not scientific",
            "  correctness.",
            "",
            "## Reviewer Questions",
            "",
            "A reviewer should be able to answer:",
            "",
            "- which two axes define the grid;",
            "- which measured responses can become plot candidates;",
            "- whether the grid is declared rectangular and complete;",
            "- which source columns are declared versus extra;",
            "- what is mechanically checked and what remains unvalidated;",
            "- that this fixture tests model adequacy, not a final storage or plotting API.",
        ]
    )
    return "\n".join(rows) + "\n"


def _generate_sidecar_review(summary: dict[str, Any]) -> str:
    measurement = summary["measurement"]
    shape = summary["shape"]
    validation = summary["column_validation"]
    rows = [
        "# Expected Sidecar-Declared Table Shape Review",
        "",
        "## Status",
        "",
        "Expected reviewer-facing output for the synthetic `sidecar_declared_table`",
        "fixture. This is not a storage schema, sidecar importer, plotting API, or",
        "product contract.",
        "",
        "## Measurement",
        "",
        f"- measurement: `{measurement['measurement_id']}`",
        f"- label: `{measurement['label']}`",
        f"- target: `{measurement['target']}`",
        f"- source kind: `{measurement['source_kind']}`",
        f"- source table: `{measurement['source_table']}`",
        f"- metadata source: `{measurement['metadata_source']}`",
        "",
        "## Declared Shape",
        "",
        f"- kind: `{shape['kind']}`",
        f"- table shape: `{shape['table_shape']}`",
        f"- axis order: {_format_list(shape['axis_order'])}",
        f"- row count: `{shape['row_count']}`",
        f"- status: `{shape['status']}`",
        "",
        "## Column Mapping",
        "",
        "| Physical column | Declared name | Label | Role | Unit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for column in summary["column_mapping"]:
        rows.append(
            f"| `{column['physical_name']}` | `{column['declared_name']}` | "
            f"{column['label']} | {_format_role(column['role'])} | "
            f"`{column['unit']}` |"
        )
    rows.extend(["", "Held condition:", ""])
    for condition in summary["held_conditions"]:
        rows.append(
            f"- {condition['label']}: `{_format_quantity(condition['value'])} "
            f"{condition['unit']}` (`{condition['authority']}`)"
        )
    rows.extend(
        [
            "",
            "## Column Validation",
            "",
            f"- status: `{validation['status']}`",
            f"- physical columns: {_format_list(validation['physical_columns'])}",
            f"- declared names: {_format_list(validation['declared_names'])}",
            f"- missing physical columns: {_format_list(validation['missing_physical_columns'])}",
            f"- unmapped physical columns: {_format_list(validation['unmapped_physical_columns'])}",
            "",
            "## Plot Candidates",
            "",
            "| X | Y | Source | Metadata source | Boundary note |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in summary["plot_candidates"]:
        rows.append(
            f"| `{candidate['x']}` | `{candidate['y']}` | "
            f"`{candidate['source']}` | {candidate['metadata_source']} | "
            f"{summary['boundary_notes'][1]} |"
        )
    rows.extend(
        [
            "",
            "## Warnings",
            "",
            "- `legacy_source_weak_labels`: source table uses weak physical column names;",
            "  sidecar metadata is required for interpretation.",
            "",
            "## Boundary Notes",
            "",
            "- Column meaning comes from sidecar declaration, not source header inference.",
            "- Plot candidates use sidecar-declared column meaning; no source-header",
            "  inference, fit, uncertainty, or scientific validation is provided.",
            "- This fixture validates mapping consistency only, not semantic correctness",
            "  or scientific validity.",
            "",
            "## Reviewer Questions",
            "",
            "A reviewer should be able to answer:",
            "",
            "- which physical columns map to meaningful declared names;",
            "- which metadata came from the sidecar declaration;",
            "- which axis and response can become a plot candidate;",
            "- whether the source table is weakly labeled;",
            "- what is mechanically checked and what remains unvalidated;",
            "- that this fixture tests model adequacy, not a sidecar importer or schema",
            "  inference engine.",
        ]
    )
    return "\n".join(rows) + "\n"


def _generate_ragged_review(summary: dict[str, Any]) -> str:
    measurement = summary["measurement"]
    shape = summary["shape"]
    validation = summary["column_validation"]
    rows = [
        "# Expected Ragged Adaptive Table Shape Review",
        "",
        "## Status",
        "",
        "Expected reviewer-facing output for the synthetic `ragged_adaptive_table`",
        "fixture. This is not a storage schema, plotting API, file importer, or",
        "product contract.",
        "",
        "## Measurement",
        "",
        f"- measurement: `{measurement['measurement_id']}`",
        f"- label: `{measurement['label']}`",
        f"- target: `{measurement['target']}`",
        f"- source kind: `{measurement['source_kind']}`",
        f"- source table: `{measurement['source_table']}`",
        "",
        "## Declared Shape",
        "",
        f"- kind: `{shape['kind']}`",
        f"- ragged assumption: `{shape['ragged_assumption']}`",
        f"- axis order: {_format_list(shape['axis_order'])}",
        f"- grouping axis: `{shape['grouping_axis']}`",
        f"- ragged axis: `{shape['ragged_axis']}`",
        f"- total row count: `{shape['total_row_count']}`",
        f"- status: `{shape['status']}`",
        "",
        "Group coverage:",
        "",
        "| Group | Expected points | Observed points |",
        "| --- | --- | --- |",
    ]
    for group, expected_count in shape["expected_group_point_counts"].items():
        observed_count = shape["group_point_counts"].get(group, 0)
        rows.append(f"| `{group}` | `{expected_count}` | `{observed_count}` |")
    for group in shape["unexpected_observed_groups"]:
        observed_count = shape["group_point_counts"][group]
        rows.append(f"| `{group}` | `undeclared` | `{observed_count}` |")
    rows.extend(
        [
            "",
            "## Axes And Dependents",
            "",
            "| Name | Label | Role | Unit |",
            "| --- | --- | --- | --- |",
        ]
    )
    for column in summary["declared_axes"]:
        rows.append(f"| `{column['name']}` | {column['label']} | sweep axis | `{column['unit']}` |")
    for column in summary["declared_dependents"]:
        rows.append(
            f"| `{column['name']}` | {column['label']} | measured response | `{column['unit']}` |"
        )
    rows.extend(["", "Held condition:", ""])
    for condition in summary["held_conditions"]:
        rows.append(
            f"- {condition['label']}: `{_format_quantity(condition['value'])} "
            f"{condition['unit']}` (`{condition['authority']}`)"
        )
    rows.extend(
        [
            "",
            "## Column Validation",
            "",
            f"- status: `{validation['status']}`",
            f"- declared columns: {_format_list(validation['declared_columns'])}",
            f"- source columns: {_format_list(validation['source_columns'])}",
            f"- missing declared columns: {_format_list(validation['missing_declared_columns'])}",
            f"- missing shape columns: {_format_list(validation['missing_shape_columns'])}",
            f"- undeclared shape columns: {_format_list(validation['undeclared_shape_columns'])}",
            f"- extra source columns: {_format_list(validation['extra_source_columns'])}",
            "",
            "## Plot Candidates",
            "",
            "| Kind | X | Series | Y | Source | Boundary note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in summary["plot_candidates"]:
        rows.append(
            f"| `{candidate['plot_kind']}` | `{candidate['x']}` | "
            f"`{candidate['series']}` | `{candidate['y']}` | "
            f"`{candidate['source']}` | {summary['boundary_notes'][2]} |"
        )
    rows.extend(["", "## Warnings", ""])
    if validation["extra_source_columns"]:
        for extra_column in validation["extra_source_columns"]:
            rows.extend(
                [
                    f"- `extra_source_column`: source table contains undeclared `{extra_column}`. It",
                    "  is reported but not treated as plot metadata.",
                ]
            )
    else:
        rows.append("- `none`")
    rows.extend(
        [
            "",
            "## Boundary Notes",
            "",
            "- The ragged scan shape comes from fixture declaration, not schema",
            "  inference.",
            "- Variable inner-axis coverage is expected for this fixture and is not",
            "  treated as missing rectangular grid points.",
            "- Plot candidates are declared ragged line-family candidates only; no",
            "  rendering, fit, uncertainty, or scientific validation is provided.",
            "- This fixture validates declared ragged coverage consistency only, not",
            "  scientific correctness.",
            "",
            "## Reviewer Questions",
            "",
            "A reviewer should be able to answer:",
            "",
            "- which axis groups the adaptive scan;",
            "- which inner axis has variable coverage;",
            "- whether each declared group has the expected observed point count;",
            "- which measured responses can become line-family plot candidates;",
            "- what is mechanically checked and what remains unvalidated;",
            "- that this fixture tests model adequacy, not rectangular grid coercion or",
            "  a final storage or plotting API.",
        ]
    )
    return "\n".join(rows) + "\n"


def _generate_ragged_observed_review(summary: dict[str, Any]) -> str:
    measurement = summary["measurement"]
    shape = summary["shape"]
    validation = summary["column_validation"]
    rows = [
        "# Expected Observed-Only Ragged Table Shape Review",
        "",
        "## Status",
        "",
        "Expected reviewer-facing output for the synthetic",
        "`ragged_observed_only_table` fixture. This is not a storage schema,",
        "plotting API, file importer, or product contract.",
        "",
        "## Measurement",
        "",
        f"- measurement: `{measurement['measurement_id']}`",
        f"- label: `{measurement['label']}`",
        f"- target: `{measurement['target']}`",
        f"- source kind: `{measurement['source_kind']}`",
        f"- source table: `{measurement['source_table']}`",
        "",
        "## Declared Shape",
        "",
        f"- kind: `{shape['kind']}`",
        f"- coverage policy: `{shape['coverage_policy']}`",
        f"- axis order: {_format_list(shape['axis_order'])}",
        f"- grouping axis: `{shape['grouping_axis']}`",
        f"- ragged axis: `{shape['ragged_axis']}`",
        f"- total row count: `{shape['total_row_count']}`",
        f"- status: `{shape['status']}`",
        "",
        "Observed group coverage:",
        "",
        "| Group | Observed points |",
        "| --- | --- |",
    ]
    for group, observed_count in shape["group_point_counts"].items():
        rows.append(f"| `{group}` | `{observed_count}` |")
    rows.extend(
        [
            "",
            "## Axes And Dependents",
            "",
            "| Name | Label | Role | Unit |",
            "| --- | --- | --- | --- |",
        ]
    )
    for column in summary["declared_axes"]:
        rows.append(f"| `{column['name']}` | {column['label']} | sweep axis | `{column['unit']}` |")
    for column in summary["declared_dependents"]:
        rows.append(
            f"| `{column['name']}` | {column['label']} | measured response | `{column['unit']}` |"
        )
    rows.extend(["", "Held condition:", ""])
    for condition in summary["held_conditions"]:
        rows.append(
            f"- {condition['label']}: `{_format_quantity(condition['value'])} "
            f"{condition['unit']}` (`{condition['authority']}`)"
        )
    rows.extend(
        [
            "",
            "## Column Validation",
            "",
            f"- status: `{validation['status']}`",
            f"- declared columns: {_format_list(validation['declared_columns'])}",
            f"- source columns: {_format_list(validation['source_columns'])}",
            f"- missing declared columns: {_format_list(validation['missing_declared_columns'])}",
            f"- missing shape columns: {_format_list(validation['missing_shape_columns'])}",
            f"- undeclared shape columns: {_format_list(validation['undeclared_shape_columns'])}",
            f"- extra source columns: {_format_list(validation['extra_source_columns'])}",
            "",
            "## Plot Candidates",
            "",
            "| Kind | X | Series | Y | Source | Boundary note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in summary["plot_candidates"]:
        rows.append(
            f"| `{candidate['plot_kind']}` | `{candidate['x']}` | "
            f"`{candidate['series']}` | `{candidate['y']}` | "
            f"`{candidate['source']}` | {summary['boundary_notes'][2]} |"
        )
    rows.extend(["", "## Warnings", ""])
    if validation["extra_source_columns"]:
        for extra_column in validation["extra_source_columns"]:
            rows.extend(
                [
                    f"- `extra_source_column`: source table contains undeclared `{extra_column}`. It",
                    "  is reported but not treated as plot metadata.",
                ]
            )
    else:
        rows.append("- `none`")
    rows.extend(
        [
            "",
            "## Boundary Notes",
            "",
            "- Observed-only ragged coverage is summarized from the fixture table",
            "  after acquisition.",
            "- No expected group point counts are declared, so completeness against a",
            "  planned adaptive path is not claimed.",
            "- Plot candidates are declared observed ragged line-family candidates",
            "  only; no rendering, fit, uncertainty, or scientific validation is",
            "  provided.",
            "- This fixture validates observed coordinate uniqueness and declared",
            "  column presence only, not scientific correctness.",
            "",
            "## Reviewer Questions",
            "",
            "A reviewer should be able to answer:",
            "",
            "- which groups were observed in the completed adaptive scan;",
            "- how many points each observed group contains;",
            "- which inner axis has variable coverage;",
            "- which measured responses can become line-family plot candidates;",
            "- that completeness against planned group counts is not claimed;",
            "- that this fixture tests model adequacy, not adaptive planner semantics",
            "  or a final storage or plotting API.",
        ]
    )
    return "\n".join(rows) + "\n"


def generate_review(summary: dict[str, Any]) -> str:
    kind = summary["shape"]["kind"]
    if kind == "2d_grid_table":
        return _generate_2d_grid_review(summary)
    if kind == "ragged_adaptive_table":
        return _generate_ragged_review(summary)
    if kind == "ragged_observed_only_table":
        return _generate_ragged_observed_review(summary)
    if kind == "sidecar_declared_table":
        return _generate_sidecar_review(summary)
    raise ValueError(f"unsupported scan data-shape summary kind: {kind}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_root", type=Path)
    parser.add_argument("--format", choices=["summary", "review"], default="summary")
    args = parser.parse_args()

    summary = generate_summary(args.fixture_root)
    if args.format == "summary":
        print(json.dumps(summary, indent=2))
    else:
        print(generate_review(summary), end="")


if __name__ == "__main__":
    main()
