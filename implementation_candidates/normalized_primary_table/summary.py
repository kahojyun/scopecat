"""Normalized primary CSV table summary candidate.

This module validates table bytes that are already declared to be Scopecat
normalized primary data. It does not read files, parse legacy systems, infer
schemas, or expose dataframe objects.
"""

from __future__ import annotations

import copy
import csv
import io
from typing import Any

from implementation_candidates.contract_primitives import (
    validate_non_negative_integer,
    validate_positive_integer,
    validate_relative_path,
    validate_text,
)

_TABLE_SCHEMA = "scopecat.normalized_primary_table.v0"
_EXPECTED_POLICY = {
    "table_authority": "scopecat_normalized_primary_table",
    "input_authority": "caller_provided_bytes",
    "format": "csv_table",
    "file_observation": "not_performed",
    "legacy_source_parsing": "not_performed",
    "schema_inference": "not_performed",
    "scan_shape_inference": "not_performed",
    "scalar_type_inference": "not_performed",
    "dataframe_adapter": "not_invoked",
    "plot_series": "not_built",
    "storage_mutation": "not_performed",
    "stable_public_api": "not_defined",
}
_DECLARED_COLUMN_ROLES = {
    "annotation",
    "held_condition",
    "measured_response",
    "point_index",
    "progress_index",
    "repeat_index",
    "response",
    "supporting_count",
    "sweep_axis",
    "trace_kind",
    "trace_reference",
    "undeclared",
    "vector_response",
}


def _decode_csv(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("normalized primary table must be utf-8 CSV") from exc


def _validate_column_name(value: Any, owner: str) -> str:
    name = validate_text(value, owner)
    if name.strip() == "":
        raise ValueError(f"{owner} must be non-blank")
    return name


def _validate_column_role(value: Any, owner: str) -> str:
    role = validate_text(value, owner)
    if role not in _DECLARED_COLUMN_ROLES:
        raise ValueError(f"{owner} is unsupported")
    return role


def _validate_declared_columns(declared_columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(declared_columns, list) or not declared_columns:
        raise ValueError("normalized primary table declared_columns must be a non-empty list")
    seen = set()
    validated = []
    for index, column in enumerate(declared_columns):
        if not isinstance(column, dict):
            raise ValueError("normalized primary table declared column must be an object")
        name = _validate_column_name(
            column.get("name"),
            f"normalized primary table declared column {index} name",
        )
        if name in seen:
            raise ValueError("normalized primary table declared columns must be unique")
        seen.add(name)
        validated.append(
            {
                "name": name,
                "label": validate_text(
                    column.get("label", name),
                    f"normalized primary table declared column {name} label",
                ),
                "role": _validate_column_role(
                    column.get("role", "undeclared"),
                    f"normalized primary table declared column {name} role",
                ),
                "unit": None
                if column.get("unit") is None
                else validate_text(
                    column.get("unit"),
                    f"normalized primary table declared column {name} unit",
                ),
            }
        )
    return validated


def _load_rows(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    decoded = _decode_csv(content)
    reader = csv.reader(io.StringIO(decoded, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("normalized primary table requires a CSV header") from exc

    if not header:
        raise ValueError("normalized primary table requires a CSV header")
    for index, name in enumerate(header):
        _validate_column_name(name, f"normalized primary table column {index} name")
    if len(set(header)) != len(header):
        raise ValueError("normalized primary table requires unique CSV headers")

    rows = []
    for row in reader:
        if len(row) != len(header):
            raise ValueError("normalized primary table rows must match the CSV header")
        rows.append(dict(zip(header, row, strict=True)))
    return header, rows


def _column_summaries(
    columns: list[str],
    declared_columns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    declared_by_name = {column["name"]: column for column in declared_columns}
    summaries = []
    for position, name in enumerate(columns):
        declared = declared_by_name.get(name)
        if declared is None:
            summaries.append(
                {
                    "name": name,
                    "position": position,
                    "declared": False,
                    "label": name,
                    "role": "undeclared",
                    "unit": None,
                }
            )
            continue
        summaries.append(
            {
                "name": name,
                "position": position,
                "declared": True,
                "label": declared["label"],
                "role": declared["role"],
                "unit": declared["unit"],
            }
        )
    return summaries


def _finding(code: str, target: str, message: str, does_not_claim: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "target": target,
        "message": message,
        "does_not_claim": does_not_claim,
    }


def summarize_normalized_csv_table(
    content: bytes,
    *,
    source: str,
    declared_columns: list[dict[str, Any]],
    declared_row_count: int | None = None,
    preview_row_limit: int = 5,
) -> dict[str, Any]:
    """Summarize already-normalized primary CSV table bytes."""
    if not isinstance(content, bytes):
        raise ValueError("normalized primary table content must be bytes")
    source = validate_relative_path(source, "normalized primary table source")
    preview_row_limit = validate_positive_integer(
        preview_row_limit,
        "normalized primary table preview_row_limit",
    )
    if declared_row_count is not None:
        validate_non_negative_integer(
            declared_row_count,
            "normalized primary table declared_row_count",
        )

    validated_declared_columns = _validate_declared_columns(declared_columns)
    columns, rows = _load_rows(content)
    declared_names = [column["name"] for column in validated_declared_columns]
    missing_declared = [name for name in declared_names if name not in columns]
    if missing_declared:
        raise ValueError("normalized primary table is missing declared columns")

    findings = []
    if declared_row_count is not None and declared_row_count != len(rows):
        findings.append(
            _finding(
                "normalized_table_row_count_mismatch",
                source,
                "Observed row count differs from the declared row count.",
                "schema_inference_or_source_repair",
            )
        )

    return {
        "normalized_table_schema": _TABLE_SCHEMA,
        "normalized_table_policy": copy.deepcopy(_EXPECTED_POLICY),
        "classification": "normalized_table_review_needed"
        if findings
        else "normalized_table_ready",
        "source": source,
        "format": "csv_table",
        "columns": _column_summaries(columns, validated_declared_columns),
        "declared_columns": copy.deepcopy(validated_declared_columns),
        "row_count": len(rows),
        "declared_row_count": declared_row_count,
        "rows": copy.deepcopy(rows),
        "preview": {
            "row_limit": preview_row_limit,
            "columns": list(declared_names),
            "rows": [
                {name: row[name] for name in declared_names} for row in rows[:preview_row_limit]
            ],
        },
        "review_findings": findings,
    }
