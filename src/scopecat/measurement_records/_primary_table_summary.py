"""Internal primary CSV table summary helpers."""

from __future__ import annotations

import copy
import csv
import io
from typing import Any

from scopecat.measurement_records._contracts import validate_relative_path, validate_text


def summarize_observed_primary_table(
    content: bytes,
    *,
    source: str,
    declared_row_count: int,
    preview_row_limit: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build a stored primary-table summary from normalized primary CSV bytes."""

    if not isinstance(content, bytes):
        raise ValueError("primary table summary content must be bytes")
    source = validate_relative_path(source, "primary table summary source")
    _validate_non_negative_integer(declared_row_count, "primary table summary declared_row_count")
    _validate_positive_integer(preview_row_limit, "primary table summary preview_row_limit")
    columns, rows = _load_rows(content, owner="primary table summary")
    findings: list[dict[str, str]] = []
    if declared_row_count != len(rows):
        findings.append(
            _finding(
                "primary_table_row_count_mismatch",
                source,
                "Observed row count differs from the writer receipt row count.",
            )
        )

    return (
        {
            "table_schema": "measurement_record_primary_table_summary_v0",
            "source": source,
            "format": "csv_table",
            "classification": "primary_table_review_needed" if findings else "primary_table_ready",
            "columns": [
                {
                    "name": name,
                    "position": position,
                    "declared": False,
                    "role": "undeclared",
                    "unit": None,
                }
                for position, name in enumerate(columns)
            ],
            "row_count": len(rows),
            "declared_row_count": declared_row_count,
            "rows": copy.deepcopy(rows),
            "preview": {
                "row_limit": preview_row_limit,
                "columns": list(columns),
                "rows": copy.deepcopy(rows[:preview_row_limit]),
            },
        },
        findings,
    )


def _load_rows(content: bytes, *, owner: str) -> tuple[list[str], list[dict[str, str]]]:
    decoded = _decode_csv(content, owner=owner)
    reader = csv.reader(io.StringIO(decoded, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError(f"{owner} requires a CSV header") from exc

    if not header:
        raise ValueError(f"{owner} requires a CSV header")
    for index, name in enumerate(header):
        _validate_column_name(name, f"{owner} column {index} name")
    if len(set(header)) != len(header):
        raise ValueError(f"{owner} requires unique CSV headers")

    rows = []
    for row in reader:
        if len(row) != len(header):
            raise ValueError(f"{owner} rows must match the CSV header")
        rows.append(dict(zip(header, row, strict=True)))
    return header, rows


def _decode_csv(content: bytes, *, owner: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{owner} must be utf-8 CSV") from exc


def _validate_column_name(value: Any, owner: str) -> str:
    name = validate_text(value, owner)
    if name.strip() == "":
        raise ValueError(f"{owner} must be non-blank")
    return name


def _validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def _validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def _finding(code: str, target: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "target": target,
        "message": message,
    }
