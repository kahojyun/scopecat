"""Generate expected outputs from scan data-shape fixtures.

This module is a validation spike, not product code or a durable data schema.
It intentionally supports only the repository-safe fixture shapes under
``tests/fixtures/scan_data_shapes``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from decimal import Decimal, InvalidOperation
from itertools import product
from pathlib import Path, PurePosixPath
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

TRACE_DECISIONS_NOT_EARNED = [
    "final storage schema",
    "shared data-shape schema",
    "native nested storage mapping",
    "general dataframe or array API",
    "legacy importer",
    "plot rendering",
    "binary container support",
    "automatic schema inference",
    "trace alignment or resampling",
    "array-valued measurement support",
    "scientific validity or reproducibility",
]

FIXED_VECTOR_DECISIONS_NOT_EARNED = [
    "final storage schema",
    "shared data-shape schema",
    "native list or struct storage mapping",
    "general dataframe or array API",
    "legacy importer",
    "plot rendering",
    "multi-dimensional ndarray support",
    "large waveform or trace storage",
    "matrix heatmap or QST/QPT analysis support",
    "automatic schema inference",
    "scientific validity or reproducibility",
]

COMPLEX_FIXED_VECTOR_DECISIONS_NOT_EARNED = [
    "final storage schema",
    "shared data-shape schema",
    "complex primitive storage type",
    "native complex backend mapping",
    "general dataframe or array API",
    "general transform engine",
    "legacy importer",
    "plot rendering",
    "multi-dimensional ndarray support",
    "complex trace response support",
    "matrix heatmap or QST/QPT analysis support",
    "automatic schema inference",
    "scientific validity or reproducibility",
]

FIXED_VECTOR_SHAPE_POLICY = "fixed_per_row"
SUPPORTED_VECTOR_DTYPES = {"float64", "float32", "int64", "int32"}
VECTOR_DTYPE_BOUNDS = {
    "float32": (Decimal("-3.4028234663852886e38"), Decimal("3.4028234663852886e38")),
    "int32": (Decimal("-2147483648"), Decimal("2147483647")),
    "int64": (Decimal("-9223372036854775808"), Decimal("9223372036854775807")),
}
REQUIRED_TRACE_SCHEMA_FIELDS = ["independent_column", "response_column", "response_label"]
SUPPORTED_COMPLEX_LOGICAL_TYPES = {"complex64", "complex128"}
COMPLEX_LOGICAL_STORAGE_DTYPES = {
    "complex64": "float32",
    "complex128": "float64",
}
SUPPORTED_COMPLEX_REPRESENTATION = "cartesian_vector"
SUPPORTED_COMPLEX_DERIVED_COMPONENTS = ["real", "imag", "magnitude", "phase"]


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


def _format_fixed_vector_policy_failures(values: list[dict[str, Any]]) -> str:
    if not values:
        return "`none`"
    return ", ".join(f"`{item['column']}={item['shape_policy']}`" for item in values)


def _format_fixed_vector_shape_failures(values: list[dict[str, Any]]) -> str:
    if not values:
        return "`none`"
    return ", ".join(f"`{item['column']}={item['value_shape']}`" for item in values)


def _format_fixed_vector_dtype_failures(values: list[dict[str, Any]]) -> str:
    if not values:
        return "`none`"
    return ", ".join(f"`{item['column']}={item['dtype']}`" for item in values)


def _format_fixed_vector_component_failures(values: list[dict[str, Any]]) -> str:
    if not values:
        return "`none`"
    return ", ".join(f"`{item['column']}={item['failure']}`" for item in values)


def _format_fixed_vector_column_failures(values: list[dict[str, Any]]) -> str:
    if not values:
        return "`none`"
    return ", ".join(f"`index {item['index']}={item['failure']}`" for item in values)


def _format_complex_logical_failures(values: list[dict[str, Any]]) -> str:
    if not values:
        return "`none`"
    return ", ".join(f"`{item['column']}={item['failure']}`" for item in values)


def _sort_numeric_strings(values: list[Any]) -> list[Any]:
    def sort_key(value: Any) -> tuple[int, float | str]:
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, "" if value is None else str(value))

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


def _trace_shape_columns(*, axis_order: list[str], trace_ref_column: str) -> list[str]:
    return _unique_in_order([*axis_order, trace_ref_column])


def _trace_column_validation(
    *,
    declared_names: list[str],
    source_columns: list[str],
    axis_order: list[str],
    trace_ref_column: str,
) -> dict[str, list[str]]:
    shape_columns = _trace_shape_columns(axis_order=axis_order, trace_ref_column=trace_ref_column)
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


def _missing_trace_schema_fields(trace_schema: Any) -> list[str]:
    if not isinstance(trace_schema, dict):
        return REQUIRED_TRACE_SCHEMA_FIELDS
    return [
        field
        for field in REQUIRED_TRACE_SCHEMA_FIELDS
        if not isinstance(trace_schema.get(field), str) or not trace_schema[field]
    ]


def _fixed_vector_shape_columns(
    *, axis_order: list[str], vector_columns: list[dict[str, Any]]
) -> list[str]:
    return _unique_in_order([*axis_order, *[column["name"] for column in vector_columns]])


def _normalize_vector_columns(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], [{"index": None, "failure": "vector_columns_not_list", "value": value}]
    normalized_columns = []
    invalid_vector_columns = []
    for index, column in enumerate(value):
        if not isinstance(column, dict):
            invalid_vector_columns.append(
                {"index": index, "failure": "vector_column_not_object", "value": column}
            )
            continue
        name = column.get("name")
        if not isinstance(name, str) or not name:
            invalid_vector_columns.append(
                {"index": index, "failure": "vector_column_missing_name", "value": column}
            )
            continue
        normalized_columns.append(column)
    return normalized_columns, invalid_vector_columns


def _fixed_vector_column_validation(
    *,
    declared_names: list[str],
    source_columns: list[str],
    axis_order: list[str],
    vector_columns: list[dict[str, Any]],
) -> dict[str, list[str]]:
    shape_columns = _fixed_vector_shape_columns(
        axis_order=axis_order,
        vector_columns=vector_columns,
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


def _is_supported_fixed_vector_shape(value_shape: Any) -> bool:
    return (
        isinstance(value_shape, list)
        and len(value_shape) == 1
        and isinstance(value_shape[0], int)
        and not isinstance(value_shape[0], bool)
        and value_shape[0] > 0
    )


def _fixed_vector_expected_length(value_shape: list[int]) -> int:
    expected_length = 1
    for dimension in value_shape:
        expected_length *= dimension
    return expected_length


def _component_validation_failure(column: dict[str, Any]) -> str | None:
    components = column.get("components")
    value_shape = column.get("value_shape")
    if not isinstance(components, list):
        return "components_not_list"
    if not all(isinstance(component, str) for component in components):
        return "component_not_string"
    if _is_supported_fixed_vector_shape(value_shape) and len(
        components
    ) != _fixed_vector_expected_length(value_shape):
        return "component_count_mismatch"
    return None


def _complex_logical_validation_failure(
    column: dict[str, Any], *, requires_logical_value: bool
) -> str | None:
    logical_value = column.get("logical_value")
    if logical_value is None:
        return "missing_logical_value" if requires_logical_value else None
    if not isinstance(logical_value, dict):
        return "logical_value_not_object"
    if logical_value.get("type") not in SUPPORTED_COMPLEX_LOGICAL_TYPES:
        return "unsupported_logical_type"
    if column.get("dtype") != COMPLEX_LOGICAL_STORAGE_DTYPES[logical_value["type"]]:
        return "logical_type_dtype_mismatch"
    if logical_value.get("representation") != SUPPORTED_COMPLEX_REPRESENTATION:
        return "unsupported_representation"
    if column.get("value_shape") != [2]:
        return "complex_requires_value_shape_2"
    components = column.get("components", [])
    if not isinstance(components, list) or len(components) != 2:
        return "complex_requires_two_components"
    real_component = logical_value.get("real_component")
    imag_component = logical_value.get("imag_component")
    if real_component not in components or imag_component not in components:
        return "complex_components_not_declared"
    if real_component == imag_component:
        return "complex_components_not_distinct"
    if logical_value.get("derived_components") != SUPPORTED_COMPLEX_DERIVED_COMPONENTS:
        return "unsupported_derived_components"
    if logical_value.get("phase_unit") != "rad":
        return "unsupported_phase_unit"
    return None


def _fixed_vector_declaration_validation(
    *,
    shape_kind: str,
    declared_columns: list[dict[str, Any]],
    axis_order: list[str],
    vector_columns: list[dict[str, Any]],
    invalid_vector_columns: list[dict[str, Any]],
) -> dict[str, Any]:
    is_complex_shape = shape_kind == "complex_fixed_vector_response_table"
    declared_by_name = {column["name"]: column for column in declared_columns}
    invalid_axis_roles = [
        axis
        for axis in axis_order
        if axis in declared_by_name and declared_by_name[axis]["role"] != "sweep_axis"
    ]
    invalid_vector_roles = [
        column["name"]
        for column in vector_columns
        if column["name"] in declared_by_name
        and declared_by_name[column["name"]]["role"] != "vector_response"
    ]
    unsupported_shape_policies = [
        {
            "column": column["name"],
            "shape_policy": column.get("shape_policy"),
        }
        for column in vector_columns
        if column.get("shape_policy") != FIXED_VECTOR_SHAPE_POLICY
    ]
    unsupported_value_shapes = [
        {
            "column": column["name"],
            "value_shape": column.get("value_shape"),
        }
        for column in vector_columns
        if not _is_supported_fixed_vector_shape(column.get("value_shape"))
    ]
    unsupported_dtypes = [
        {
            "column": column["name"],
            "dtype": column.get("dtype"),
        }
        for column in vector_columns
        if column.get("dtype") not in SUPPORTED_VECTOR_DTYPES
    ]
    unsupported_components = [
        {
            "column": column["name"],
            "failure": failure,
            "components": column.get("components"),
        }
        for column in vector_columns
        for failure in [_component_validation_failure(column)]
        if failure is not None
    ]
    unsupported_complex_logical_values = [
        {
            "column": column["name"],
            "failure": (
                "complex_logical_value_requires_complex_shape"
                if not is_complex_shape and column.get("logical_value") is not None
                else failure
            ),
        }
        for column in vector_columns
        for failure in [
            _complex_logical_validation_failure(
                column,
                requires_logical_value=is_complex_shape,
            )
        ]
        if failure is not None or (not is_complex_shape and column.get("logical_value") is not None)
    ]
    missing_vector_columns = [] if vector_columns else ["vector_columns"]
    invalid_vector_column_failures = [
        {
            "index": item["index"],
            "failure": item["failure"],
        }
        for item in invalid_vector_columns
    ]
    declaration_failure_count = (
        len(invalid_axis_roles)
        + len(invalid_vector_roles)
        + len(unsupported_shape_policies)
        + len(unsupported_value_shapes)
        + len(unsupported_dtypes)
        + len(unsupported_components)
        + len(unsupported_complex_logical_values)
        + len(missing_vector_columns)
        + len(invalid_vector_column_failures)
    )
    return {
        "status": "pass" if not declaration_failure_count else "fail",
        "invalid_axis_roles": invalid_axis_roles,
        "invalid_vector_roles": invalid_vector_roles,
        "unsupported_shape_policies": unsupported_shape_policies,
        "unsupported_value_shapes": unsupported_value_shapes,
        "unsupported_dtypes": unsupported_dtypes,
        "unsupported_components": unsupported_components,
        "unsupported_complex_logical_values": unsupported_complex_logical_values,
        "missing_vector_columns": missing_vector_columns,
        "invalid_vector_columns": invalid_vector_column_failures,
    }


def _fixed_vector_status(*, blocking_columns: list[str], vector_validation: dict[str, Any]) -> str:
    if blocking_columns:
        return "fail"
    return "pass" if vector_validation["status"] == "pass" else "fail"


def _parse_fixed_vector_cell(value: Any) -> tuple[str, list[Any]]:
    if not isinstance(value, str):
        return "not_string", []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return "malformed_json", []
    if not isinstance(parsed, list):
        return "not_list", []
    return "parsed", parsed


def _vector_matches_dtype(values: list[Any], dtype: str) -> bool:
    if dtype not in SUPPORTED_VECTOR_DTYPES:
        return False
    for value in values:
        if isinstance(value, bool):
            return False
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return False
        if not decimal_value.is_finite():
            return False
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(coerced):
            return False
        if dtype in VECTOR_DTYPE_BOUNDS:
            lower, upper = VECTOR_DTYPE_BOUNDS[dtype]
            if decimal_value < lower or decimal_value > upper:
                return False
        if dtype.startswith("int"):
            if decimal_value != decimal_value.to_integral_value():
                return False
    return True


def _fixed_vector_plot_candidates(
    *,
    measurement: dict[str, Any],
    vector_columns: list[dict[str, Any]],
    vector_validation: dict[str, Any],
    is_complex_shape: bool,
) -> list[dict[str, Any]]:
    if vector_validation["status"] != "pass":
        return []
    return [
        {
            "title": f"{measurement['label']}: {column['label']}",
            "plot_kind": (
                "complex_component_pair_scatter" if is_complex_shape else "component_pair_scatter"
            ),
            "x_component": (
                column["logical_value"]["real_component"]
                if is_complex_shape
                else column["components"][0]
            ),
            "y_component": (
                column["logical_value"]["imag_component"]
                if is_complex_shape
                else column["components"][1]
            ),
            "vector_column": column["name"],
            "source": measurement["source_table"],
            **(
                {
                    "logical_value_type": column["logical_value"]["type"],
                    "derived_components": column["logical_value"]["derived_components"],
                }
                if is_complex_shape
                else {}
            ),
        }
        for column in vector_columns
        if column["value_shape"] == [2] and len(column["components"]) == 2
    ]


def _fixed_vector_validation(
    *,
    rows: list[dict[str, str]],
    vector_columns: list[dict[str, Any]],
    blocking_columns: list[str],
    declaration_validation: dict[str, Any],
) -> dict[str, Any]:
    if blocking_columns or declaration_validation["status"] == "fail":
        return {
            "status": "fail",
            "declaration_validation": declaration_validation,
            "column_summaries": [],
            "failed_cells": [],
        }

    column_summaries = []
    failed_cells = []
    for column in vector_columns:
        name = column["name"]
        value_shape = column["value_shape"]
        expected_length = _fixed_vector_expected_length(value_shape)
        row_count = 0
        observed_lengths: list[int] = []
        parse_failures = 0
        dtype_failures = 0
        shape_failures = 0
        for row_index, row in enumerate(rows):
            row_count += 1
            parse_status, parsed = _parse_fixed_vector_cell(row[name])
            observed_lengths.append(len(parsed) if parse_status == "parsed" else 0)
            if parse_status != "parsed":
                parse_failures += 1
                failed_cells.append(
                    {
                        "row_index": row_index,
                        "column": name,
                        "failure": parse_status,
                        "value": row[name],
                    }
                )
                continue
            if len(parsed) != expected_length:
                shape_failures += 1
                failed_cells.append(
                    {
                        "row_index": row_index,
                        "column": name,
                        "failure": "shape_mismatch",
                        "value_length": len(parsed),
                        "expected_length": expected_length,
                    }
                )
            if not _vector_matches_dtype(parsed, column["dtype"]):
                dtype_failures += 1
                failed_cells.append(
                    {
                        "row_index": row_index,
                        "column": name,
                        "failure": "dtype_mismatch",
                        "dtype": column["dtype"],
                    }
                )
        column_summaries.append(
            {
                "name": name,
                "value_shape": value_shape,
                "dtype": column["dtype"],
                "shape_policy": column["shape_policy"],
                "components": column["components"],
                **({"logical_value": column["logical_value"]} if "logical_value" in column else {}),
                "row_count": row_count,
                "observed_lengths": _unique_in_order([str(length) for length in observed_lengths]),
                "reader_ndarray_shape": [row_count, *value_shape],
                "parse_failures": parse_failures,
                "shape_failures": shape_failures,
                "dtype_failures": dtype_failures,
                "status": (
                    "pass"
                    if not parse_failures and not shape_failures and not dtype_failures
                    else "fail"
                ),
            }
        )

    return {
        "status": "pass"
        if all(column_summary["status"] == "pass" for column_summary in column_summaries)
        else "fail",
        "declaration_validation": declaration_validation,
        "column_summaries": column_summaries,
        "failed_cells": failed_cells,
    }


def _is_fixture_relative_ref(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) > 1
        and path.parts[0] == "source"
    )


def _is_contained_regular_file(root: Path, candidate: Path) -> bool:
    try:
        root_resolved = root.resolve()
        candidate_resolved = candidate.resolve(strict=True)
    except OSError:
        return False
    return (
        candidate_resolved.is_file()
        and not candidate.is_symlink()
        and candidate_resolved.is_relative_to(root_resolved)
    )


def _read_fixture_csv_table(
    fixture_root: Path, source_ref: Any
) -> tuple[list[str], list[dict[str, str]]]:
    if not _is_fixture_relative_ref(source_ref):
        return [], []
    source_path = fixture_root / source_ref
    if not _is_contained_regular_file(fixture_root, source_path):
        return [], []
    try:
        return read_csv_table(source_path)
    except (OSError, UnicodeDecodeError, csv.Error):
        return [], []


def _grid_status(
    *,
    axis_order: list[str],
    expected_axis_cardinality: dict[str, int],
    rows: list[dict[str, str]],
    missing_columns: list[str],
) -> str:
    if missing_columns:
        return "fail"
    if len(axis_order) != 2:
        return "fail"

    expected_point_count = 1
    for axis in axis_order:
        cardinality = expected_axis_cardinality.get(axis)
        if not isinstance(cardinality, int) or isinstance(cardinality, bool) or cardinality <= 0:
            return "fail"
        expected_point_count *= cardinality
    if len(rows) != expected_point_count:
        return "fail"

    observed_coordinates = [tuple(row[axis] for axis in axis_order) for row in rows]
    if len(set(observed_coordinates)) != len(observed_coordinates):
        return "fail"

    expected_values = [
        _sort_numeric_strings(list({row[axis] for row in rows})) for axis in axis_order
    ]
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
    source_columns, rows = _read_fixture_csv_table(fixture_root, measurement["source_table"])

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
        cardinality = data_shape["expected_axis_cardinality"].get(axis)
        if isinstance(cardinality, int) and not isinstance(cardinality, bool) and cardinality > 0:
            expected_point_count *= cardinality
        else:
            expected_point_count = 0
            break
    grid_status = _grid_status(
        axis_order=axis_order,
        expected_axis_cardinality=data_shape["expected_axis_cardinality"],
        rows=rows,
        missing_columns=missing_columns,
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
            "grid_assumption": data_shape["grid_assumption"],
            "axis_order": axis_order,
            "axis_cardinality": axis_cardinality,
            "expected_point_count": expected_point_count,
            "actual_row_count": len(rows),
            "status": grid_status,
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
            if grid_status == "pass"
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
            "The 2D grid shape comes from fixture declaration, not schema inference.",
            "Plot candidates are declared 2D grid plot candidates only; no rendering, fit, uncertainty, or scientific validation is provided.",
            "The fixture validates declared shape consistency only, not scientific correctness.",
        ],
        "decisions_not_earned": GRID_DECISIONS_NOT_EARNED,
    }


def _generate_ragged_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    source_columns, rows = _read_fixture_csv_table(fixture_root, measurement["source_table"])

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
    source_columns, rows = _read_fixture_csv_table(fixture_root, measurement["source_table"])

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


def _generate_trace_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    source_columns, rows = _read_fixture_csv_table(fixture_root, measurement["source_table"])

    declared_columns = source["declared_columns"]
    declared_names = _column_names(declared_columns)
    extra_columns = [name for name in source_columns if name not in declared_names]
    axis_order = data_shape["axis_order"]
    trace_ref_column = data_shape["trace_ref_column"]
    trace_schema = data_shape.get("trace_schema", {})
    missing_trace_schema_fields = _missing_trace_schema_fields(trace_schema)
    required_trace_columns = [
        trace_schema[field]
        for field in ["independent_column", "response_column"]
        if field not in missing_trace_schema_fields
    ]
    axis_order_valid = bool(axis_order)
    trace_validation = _trace_column_validation(
        declared_names=declared_names,
        source_columns=source_columns,
        axis_order=axis_order,
        trace_ref_column=trace_ref_column,
    )
    blocking_columns = trace_validation["blocking_columns"]
    blocking_trace_metadata = bool(missing_trace_schema_fields) or not axis_order_valid

    trace_refs = [] if blocking_columns else [row[trace_ref_column] for row in rows]
    unsafe_trace_refs = [ref for ref in trace_refs if not _is_fixture_relative_ref(ref)]
    outer_trace_points = (
        []
        if blocking_columns or blocking_trace_metadata
        else [
            {
                "outer_coordinate": {axis: row[axis] for axis in axis_order},
                "trace_ref": row[trace_ref_column],
            }
            for row in rows
        ]
    )
    trace_summaries = []
    missing_trace_files = []
    missing_trace_columns_by_ref: dict[str, list[str]] = {}
    for trace_point in outer_trace_points:
        trace_ref = trace_point["trace_ref"]
        outer_coordinate = trace_point["outer_coordinate"]
        if trace_ref in unsafe_trace_refs:
            trace_summaries.append(
                {
                    "outer_coordinate": outer_coordinate,
                    "trace_ref": trace_ref,
                    "status": "unsafe_reference",
                    "row_count": None,
                    "columns": [],
                    "missing_trace_columns": required_trace_columns,
                }
            )
            continue

        trace_path = fixture_root / trace_ref
        if not _is_contained_regular_file(fixture_root, trace_path):
            missing_trace_files.append(trace_ref)
            trace_summaries.append(
                {
                    "outer_coordinate": outer_coordinate,
                    "trace_ref": trace_ref,
                    "status": "missing",
                    "row_count": None,
                    "columns": [],
                    "missing_trace_columns": required_trace_columns,
                }
            )
            continue

        try:
            trace_columns, trace_rows = read_csv_table(trace_path)
        except (OSError, UnicodeDecodeError, csv.Error):
            missing_trace_files.append(trace_ref)
            trace_summaries.append(
                {
                    "outer_coordinate": outer_coordinate,
                    "trace_ref": trace_ref,
                    "status": "missing",
                    "row_count": None,
                    "columns": [],
                    "missing_trace_columns": required_trace_columns,
                }
            )
            continue
        missing_trace_columns = [
            column for column in required_trace_columns if column not in trace_columns
        ]
        if missing_trace_columns:
            missing_trace_columns_by_ref[trace_ref] = missing_trace_columns
        trace_summaries.append(
            {
                "outer_coordinate": outer_coordinate,
                "trace_ref": trace_ref,
                "status": "pass" if not missing_trace_columns else "fail",
                "row_count": len(trace_rows),
                "columns": trace_columns,
                "missing_trace_columns": missing_trace_columns,
            }
        )

    observed_coordinates = (
        [] if blocking_columns else [tuple(row[axis] for axis in axis_order) for row in rows]
    )
    duplicate_outer_coordinates = len(set(observed_coordinates)) != len(observed_coordinates)
    trace_status = (
        "pass"
        if not blocking_columns
        and not blocking_trace_metadata
        and not unsafe_trace_refs
        and not missing_trace_files
        and not missing_trace_columns_by_ref
        and not duplicate_outer_coordinates
        else "fail"
    )
    sweep_axes = _columns_by_role(declared_columns, "sweep_axis")
    trace_columns_declared = _columns_by_role(declared_columns, "trace_reference")

    return {
        "shape_summary_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "shape-input.json",
        "measurement": measurement,
        "shape": {
            "kind": data_shape["kind"],
            "axis_order": axis_order,
            "trace_ref_column": trace_ref_column,
            "trace_schema": trace_schema,
            "point_count": len(rows),
            "duplicate_outer_coordinates": duplicate_outer_coordinates,
            "status": trace_status,
        },
        "outer_trace_points": outer_trace_points,
        "declared_axes": _without_role(sweep_axes),
        "declared_trace_references": _without_role(trace_columns_declared),
        "held_conditions": source["held_conditions"],
        "column_validation": {
            "status": "pass" if not blocking_columns else "fail",
            "declared_columns": declared_names,
            "source_columns": source_columns,
            "missing_declared_columns": trace_validation["missing_declared_columns"],
            "missing_shape_columns": trace_validation["missing_shape_columns"],
            "undeclared_shape_columns": trace_validation["undeclared_shape_columns"],
            "extra_source_columns": extra_columns,
        },
        "trace_validation": {
            "status": trace_status,
            "trace_refs": trace_refs,
            "unsafe_trace_refs": unsafe_trace_refs,
            "missing_trace_files": missing_trace_files,
            "missing_trace_schema_fields": missing_trace_schema_fields,
            "missing_trace_columns_by_ref": missing_trace_columns_by_ref,
            "trace_summaries": trace_summaries,
        },
        "plot_candidates": (
            [
                {
                    "title": f"{measurement['label']}: {trace_schema['response_label']}",
                    "plot_kind": "trace_family",
                    "x": trace_schema["independent_column"],
                    "series": axis_order[0],
                    "y": trace_schema["response_column"],
                    "trace_ref_column": trace_ref_column,
                    "source": measurement["source_table"],
                }
            ]
            if trace_status == "pass"
            else []
        ),
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
            "Trace-per-point shape is declared by fixture metadata plus fixture-relative trace references, not schema inference.",
            "Trace references are checked for fixture-relative shape, containment, and openability only; no binary container, storage layout, or importer contract is earned.",
            "Plot candidates are declared trace-family candidates only; no rendering, alignment, resampling, fit, uncertainty, or scientific validation is provided.",
            "The fixture validates reference shape, trace openability, trace columns, and trace row counts only, not waveform correctness.",
        ],
        "decisions_not_earned": TRACE_DECISIONS_NOT_EARNED,
    }


def _generate_fixed_vector_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    source_columns, rows = _read_fixture_csv_table(fixture_root, measurement["source_table"])

    declared_columns = source["declared_columns"]
    declared_names = _column_names(declared_columns)
    extra_columns = [name for name in source_columns if name not in declared_names]
    axis_order = data_shape["axis_order"]
    vector_columns, invalid_vector_columns = _normalize_vector_columns(
        data_shape.get("vector_columns")
    )
    vector_column_names = [column["name"] for column in vector_columns]
    vector_column_validation = _fixed_vector_column_validation(
        declared_names=declared_names,
        source_columns=source_columns,
        axis_order=axis_order,
        vector_columns=vector_columns,
    )
    declaration_validation = _fixed_vector_declaration_validation(
        shape_kind=data_shape["kind"],
        declared_columns=declared_columns,
        axis_order=axis_order,
        vector_columns=vector_columns,
        invalid_vector_columns=invalid_vector_columns,
    )
    blocking_columns = vector_column_validation["blocking_columns"]
    vector_validation = _fixed_vector_validation(
        rows=rows,
        vector_columns=vector_columns,
        blocking_columns=blocking_columns,
        declaration_validation=declaration_validation,
    )
    observed_coordinates = (
        [] if blocking_columns else [tuple(row[axis] for axis in axis_order) for row in rows]
    )
    duplicate_coordinates = len(set(observed_coordinates)) != len(observed_coordinates)
    if duplicate_coordinates:
        vector_validation["status"] = "fail"
    is_complex_shape = data_shape["kind"] == "complex_fixed_vector_response_table"

    sweep_axes = _columns_by_role(declared_columns, "sweep_axis")
    vector_responses = [
        column
        for column in declared_columns
        if column["name"] in vector_column_names and column["role"] == "vector_response"
    ]

    return {
        "shape_summary_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "shape-input.json",
        "measurement": measurement,
        "shape": {
            "kind": data_shape["kind"],
            "vector_assumption": data_shape["vector_assumption"],
            "axis_order": axis_order,
            "row_count": len(rows),
            "duplicate_coordinates": duplicate_coordinates,
            "status": _fixed_vector_status(
                blocking_columns=blocking_columns,
                vector_validation=vector_validation,
            ),
        },
        "declared_axes": _without_role(sweep_axes),
        "declared_vector_responses": _without_role(vector_responses),
        "held_conditions": source["held_conditions"],
        "column_validation": {
            "status": (
                "pass"
                if not blocking_columns
                and not declaration_validation["invalid_axis_roles"]
                and not declaration_validation["invalid_vector_roles"]
                else "fail"
            ),
            "declared_columns": declared_names,
            "source_columns": source_columns,
            "missing_declared_columns": vector_column_validation["missing_declared_columns"],
            "missing_shape_columns": vector_column_validation["missing_shape_columns"],
            "undeclared_shape_columns": vector_column_validation["undeclared_shape_columns"],
            "invalid_axis_roles": declaration_validation["invalid_axis_roles"],
            "invalid_vector_roles": declaration_validation["invalid_vector_roles"],
            "extra_source_columns": extra_columns,
        },
        "vector_validation": vector_validation,
        "plot_candidates": _fixed_vector_plot_candidates(
            measurement=measurement,
            vector_columns=vector_columns,
            vector_validation=vector_validation,
            is_complex_shape=is_complex_shape,
        ),
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
            "Fixed-vector response shape is declared by fixture metadata, not schema inference.",
            "The reader ndarray shape is a validated convenience view over fixed-shape per-row vectors, not a general array-column API.",
            (
                "Plot candidates are declared component-pair candidates only; logical complex metadata declares real, imaginary, magnitude, and phase views without earning a primitive complex storage type or transform engine."
                if is_complex_shape
                else "Plot candidates are declared component-pair candidates only; no rendering, fit, uncertainty, or scientific validation is provided."
            ),
            "This fixture validates per-row vector parseability, fixed length, declared dtype coercion, and coordinate uniqueness only.",
        ],
        "decisions_not_earned": (
            COMPLEX_FIXED_VECTOR_DECISIONS_NOT_EARNED
            if is_complex_shape
            else FIXED_VECTOR_DECISIONS_NOT_EARNED
        ),
    }


def _generate_sidecar_summary(source: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    measurement = source["measurement"]
    data_shape = source["data_shape"]
    physical_columns, rows = _read_fixture_csv_table(fixture_root, measurement["source_table"])
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
    sweep_axis = next(
        (column for column in column_mapping if column["role"] == "sweep_axis"),
        None,
    )
    measured_response = next(
        (column for column in column_mapping if column["role"] == "measured_response"),
        None,
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
        "plot_candidates": (
            [
                {
                    "title": f"{measurement['label']}: {measured_response['label']}",
                    "x": sweep_axis["declared_name"],
                    "y": measured_response["declared_name"],
                    "source": measurement["source_table"],
                    "metadata_source": measurement["metadata_source"],
                }
            ]
            if sweep_axis is not None and measured_response is not None
            else []
        ),
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
    if kind == "trace_per_point_table":
        return _generate_trace_summary(source, fixture_root)
    if kind in {"fixed_vector_response_table", "complex_fixed_vector_response_table"}:
        return _generate_fixed_vector_summary(source, fixture_root)
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


def _generate_trace_review(summary: dict[str, Any]) -> str:
    measurement = summary["measurement"]
    shape = summary["shape"]
    validation = summary["column_validation"]
    trace_validation = summary["trace_validation"]
    rows = [
        "# Expected Trace-Per-Point Table Shape Review",
        "",
        "## Status",
        "",
        "Expected reviewer-facing output for the synthetic `trace_per_point_table`",
        "fixture. This is not a storage schema, plotting API, file importer,",
        "binary container contract, or product contract.",
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
        f"- axis order: {_format_list(shape['axis_order'])}",
        f"- trace ref column: `{shape['trace_ref_column']}`",
        f"- trace independent column: `{shape['trace_schema'].get('independent_column')}`",
        f"- trace response column: `{shape['trace_schema'].get('response_column')}`",
        f"- point count: `{shape['point_count']}`",
        f"- duplicate outer coordinates: `{shape['duplicate_outer_coordinates']}`",
        f"- status: `{shape['status']}`",
        "",
        "## Axes And Trace References",
        "",
        "| Name | Label | Role | Unit |",
        "| --- | --- | --- | --- |",
    ]
    for column in summary["declared_axes"]:
        rows.append(f"| `{column['name']}` | {column['label']} | sweep axis | `{column['unit']}` |")
    for column in summary["declared_trace_references"]:
        rows.append(
            f"| `{column['name']}` | {column['label']} | trace reference | `{column['unit']}` |"
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
            "## Trace Validation",
            "",
            f"- status: `{trace_validation['status']}`",
            f"- trace refs: {_format_list(trace_validation['trace_refs'])}",
            f"- unsafe trace refs: {_format_list(trace_validation['unsafe_trace_refs'])}",
            f"- missing trace files: {_format_list(trace_validation['missing_trace_files'])}",
            f"- missing trace schema fields: {_format_list(trace_validation['missing_trace_schema_fields'])}",
            "",
            "| Outer coordinate | Trace ref | Status | Rows | Columns | Missing trace columns |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for trace_summary in trace_validation["trace_summaries"]:
        row_count = trace_summary["row_count"]
        outer_coordinate = ", ".join(
            f"{axis}={value}" for axis, value in trace_summary["outer_coordinate"].items()
        )
        rows.append(
            f"| `{outer_coordinate}` | `{trace_summary['trace_ref']}` | "
            f"`{trace_summary['status']}` | "
            f"`{row_count if row_count is not None else 'unavailable'}` | "
            f"{_format_list(trace_summary['columns'])} | "
            f"{_format_list(trace_summary['missing_trace_columns'])} |"
        )
    rows.extend(
        [
            "",
            "## Plot Candidates",
            "",
            "| Kind | X | Series | Y | Trace ref column | Source | Boundary note |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in summary["plot_candidates"]:
        rows.append(
            f"| `{candidate['plot_kind']}` | `{candidate['x']}` | "
            f"`{candidate['series']}` | `{candidate['y']}` | "
            f"`{candidate['trace_ref_column']}` | `{candidate['source']}` | "
            f"{summary['boundary_notes'][2]} |"
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
            "- Trace-per-point shape is declared by fixture metadata plus",
            "  fixture-relative trace references, not schema inference.",
            "- Trace references are checked for fixture-relative shape, containment,",
            "  and openability only; no binary container, storage layout, or",
            "  importer contract is earned.",
            "- Plot candidates are declared trace-family candidates only; no",
            "  rendering, alignment, resampling, fit, uncertainty, or scientific",
            "  validation is provided.",
            "- This fixture validates reference shape, trace openability, trace",
            "  columns, and trace row counts only, not waveform correctness.",
            "",
            "## Reviewer Questions",
            "",
            "A reviewer should be able to answer:",
            "",
            "- which outer coordinate owns each trace reference;",
            "- whether trace references are fixture-local and openable;",
            "- which trace columns define the independent and response values;",
            "- how many rows each trace contains;",
            "- which trace-family plot candidate is declared;",
            "- that this fixture tests model adequacy, not a binary container,",
            "  storage layout, importer, or waveform analysis API.",
        ]
    )
    return "\n".join(rows) + "\n"


def _generate_fixed_vector_review(summary: dict[str, Any]) -> str:
    measurement = summary["measurement"]
    shape = summary["shape"]
    validation = summary["column_validation"]
    vector_validation = summary["vector_validation"]
    rows = [
        "# Expected Fixed-Vector Response Table Shape Review",
        "",
        "## Status",
        "",
        "Expected reviewer-facing output for the synthetic",
        f"`{shape['kind']}` fixture. This is not a storage schema,",
        "plotting API, dataframe API, general ndarray API, or product contract.",
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
        f"- vector assumption: `{shape['vector_assumption']}`",
        f"- axis order: {_format_list(shape['axis_order'])}",
        f"- row count: `{shape['row_count']}`",
        f"- duplicate coordinates: `{shape['duplicate_coordinates']}`",
        f"- status: `{shape['status']}`",
        "",
        "## Axes And Vector Responses",
        "",
        "| Name | Label | Role | Unit |",
        "| --- | --- | --- | --- |",
    ]
    for column in summary["declared_axes"]:
        rows.append(f"| `{column['name']}` | {column['label']} | sweep axis | `{column['unit']}` |")
    for column in summary["declared_vector_responses"]:
        rows.append(
            f"| `{column['name']}` | {column['label']} | vector response | `{column['unit']}` |"
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
            f"- invalid axis roles: {_format_list(validation['invalid_axis_roles'])}",
            f"- invalid vector roles: {_format_list(validation['invalid_vector_roles'])}",
            f"- extra source columns: {_format_list(validation['extra_source_columns'])}",
            "",
            "## Vector Validation",
            "",
            f"- status: `{vector_validation['status']}`",
            f"- missing vector columns: {_format_list(vector_validation['declaration_validation']['missing_vector_columns'])}",
            "- invalid vector columns: "
            f"{_format_fixed_vector_column_failures(vector_validation['declaration_validation']['invalid_vector_columns'])}",
            "- unsupported shape policies: "
            f"{_format_fixed_vector_policy_failures(vector_validation['declaration_validation']['unsupported_shape_policies'])}",
            "- unsupported value shapes: "
            f"{_format_fixed_vector_shape_failures(vector_validation['declaration_validation']['unsupported_value_shapes'])}",
            "- unsupported dtypes: "
            f"{_format_fixed_vector_dtype_failures(vector_validation['declaration_validation']['unsupported_dtypes'])}",
            "- unsupported components: "
            f"{_format_fixed_vector_component_failures(vector_validation['declaration_validation']['unsupported_components'])}",
            "- unsupported complex logical values: "
            f"{_format_complex_logical_failures(vector_validation['declaration_validation']['unsupported_complex_logical_values'])}",
            "",
            "| Column | Shape | Dtype | Components | Reader ndarray shape | Observed lengths | Status |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for vector_summary in vector_validation["column_summaries"]:
        rows.append(
            f"| `{vector_summary['name']}` | `{vector_summary['value_shape']}` | "
            f"`{vector_summary['dtype']}` | {_format_list(vector_summary['components'])} | "
            f"`{vector_summary['reader_ndarray_shape']}` | "
            f"{_format_list(vector_summary['observed_lengths'])} | "
            f"`{vector_summary['status']}` |"
        )
    rows.extend(
        [
            "",
            "Failed cells:",
            "",
        ]
    )
    if vector_validation["failed_cells"]:
        for failed_cell in vector_validation["failed_cells"]:
            rows.append(
                f"- row `{failed_cell['row_index']}` column `{failed_cell['column']}`: "
                f"`{failed_cell['failure']}`"
            )
    else:
        rows.append("- `none`")
    complex_summaries = [
        vector_summary
        for vector_summary in vector_validation["column_summaries"]
        if "logical_value" in vector_summary
    ]
    if complex_summaries:
        rows.extend(
            [
                "",
                "## Logical Value Views",
                "",
                "| Column | Logical type | Representation | Real component | Imag component | Derived views | Phase unit |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for vector_summary in complex_summaries:
            logical_value = vector_summary["logical_value"]
            rows.append(
                f"| `{vector_summary['name']}` | `{logical_value['type']}` | "
                f"`{logical_value['representation']}` | "
                f"`{logical_value['real_component']}` | "
                f"`{logical_value['imag_component']}` | "
                f"{_format_list(logical_value['derived_components'])} | "
                f"`{logical_value['phase_unit']}` |"
            )
    rows.extend(
        [
            "",
            "## Plot Candidates",
            "",
            "| Kind | Vector column | X component | Y component | Source | Boundary note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in summary["plot_candidates"]:
        rows.append(
            f"| `{candidate['plot_kind']}` | `{candidate['vector_column']}` | "
            f"`{candidate['x_component']}` | `{candidate['y_component']}` | "
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
            "- Fixed-vector response shape is declared by fixture metadata, not",
            "  schema inference.",
            "- The reader ndarray shape is a validated convenience view over",
            "  fixed-shape per-row vectors, not a general array-column API.",
            "- Plot candidates are declared component-pair candidates only; no",
            "  rendering, fit, uncertainty, or scientific validation is provided.",
            "- This fixture validates per-row vector parseability, fixed length,",
            "  declared dtype coercion, and coordinate uniqueness only.",
            "",
            "## Reviewer Questions",
            "",
            "A reviewer should be able to answer:",
            "",
            "- which column carries the fixed-shape vector response;",
            "- which components and dtype are declared for the vector values;",
            "- whether every row satisfies the declared vector length;",
            "- which reader ndarray shape can be exposed after validation;",
            "- which conservative component-pair plot candidate is declared;",
            "- that this fixture tests model adequacy, not arbitrary ndarray,",
            "  waveform, matrix heatmap, dataframe, or storage-backend support.",
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
    if kind == "trace_per_point_table":
        return _generate_trace_review(summary)
    if kind in {"fixed_vector_response_table", "complex_fixed_vector_response_table"}:
        return _generate_fixed_vector_review(summary)
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
