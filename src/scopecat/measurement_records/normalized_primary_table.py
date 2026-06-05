"""Route-local normalized primary CSV table contract."""

from __future__ import annotations

import copy
import csv
import io
from dataclasses import dataclass
from typing import Any

from scopecat.measurement_records._contracts import validate_relative_path, validate_text

NORMALIZED_PRIMARY_TABLE_SCHEMA = "scopecat.normalized_primary_table.v0"
DECLARED_COLUMN_ROLES = {
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


@dataclass(frozen=True)
class MeasurementRecordNormalizedPrimaryColumnDeclaration:
    """Declared preview-column binding for normalized primary table bytes."""

    name: str
    role: str = "undeclared"
    label: str | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        _validate_column_name(self.name, "normalized primary table declared column name")
        if self.role not in DECLARED_COLUMN_ROLES:
            raise ValueError("normalized primary table declared column role is unsupported")
        if self.label is not None:
            validate_text(self.label, "normalized primary table declared column label")
        if self.unit is not None:
            validate_text(self.unit, "normalized primary table declared column unit")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label if self.label is not None else self.name,
            "role": self.role,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class MeasurementRecordNormalizedPrimaryTableRequest:
    """Request to summarize already-normalized primary CSV table bytes."""

    source: str
    declared_columns: tuple[MeasurementRecordNormalizedPrimaryColumnDeclaration, ...]
    declared_row_count: int | None = None
    preview_row_limit: int = 5

    def __post_init__(self) -> None:
        validate_relative_path(self.source, "normalized primary table source")
        if not self.declared_columns:
            raise ValueError("normalized primary table declared_columns must be non-empty")
        _validate_unique_declared_columns(self.declared_columns)
        if self.declared_row_count is not None:
            _validate_non_negative_integer(
                self.declared_row_count,
                "normalized primary table declared_row_count",
            )
        _validate_positive_integer(
            self.preview_row_limit,
            "normalized primary table preview_row_limit",
        )


@dataclass(frozen=True)
class MeasurementRecordNormalizedPrimaryTableRun:
    """Local side-effect-free normalized primary table summary."""

    request: MeasurementRecordNormalizedPrimaryTableRequest
    table: dict[str, Any]

    @property
    def classification(self) -> str:
        return str(self.table["classification"])

    @property
    def review_findings(self) -> tuple[dict[str, str], ...]:
        return tuple(copy.deepcopy(self.table["review_findings"]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_normalized_primary_table_summary",
            "request": _request_ref(self.request),
            "table": copy.deepcopy(self.table),
            "review_findings": [copy.deepcopy(finding) for finding in self.review_findings],
        }


def summarize_normalized_primary_table_from_request(
    request: MeasurementRecordNormalizedPrimaryTableRequest,
    *,
    content: bytes,
) -> MeasurementRecordNormalizedPrimaryTableRun:
    """Summarize normalized primary CSV bytes from a typed request."""

    if not isinstance(content, bytes):
        raise ValueError("normalized primary table content must be bytes")
    columns, rows = _load_rows(content, owner="normalized primary table")
    declared_columns = [column.to_dict() for column in request.declared_columns]
    declared_names = [column["name"] for column in declared_columns]
    missing_declared = [name for name in declared_names if name not in columns]
    if missing_declared:
        raise ValueError("normalized primary table is missing declared columns")

    findings: list[dict[str, str]] = []
    if request.declared_row_count is not None and request.declared_row_count != len(rows):
        findings.append(
            _finding(
                "normalized_table_row_count_mismatch",
                request.source,
                "Observed row count differs from the declared row count.",
            )
        )

    table = _normalized_table_summary(
        source=request.source,
        columns=columns,
        rows=rows,
        declared_columns=declared_columns,
        declared_row_count=request.declared_row_count,
        preview_columns=declared_names,
        preview_row_limit=request.preview_row_limit,
        findings=findings,
    )
    return MeasurementRecordNormalizedPrimaryTableRun(request=request, table=table)


def _request_ref(request: MeasurementRecordNormalizedPrimaryTableRequest) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": request.source,
        "declared_columns": [column.to_dict() for column in request.declared_columns],
        "preview_row_limit": request.preview_row_limit,
    }
    if request.declared_row_count is not None:
        result["declared_row_count"] = request.declared_row_count
    return result


def summarize_observed_primary_table_for_read_view(
    content: bytes,
    *,
    source: str,
    declared_row_count: int,
    preview_row_limit: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build the read-view table shape from normalized primary CSV bytes."""

    if not isinstance(content, bytes):
        raise ValueError("read view primary table content must be bytes")
    source = validate_relative_path(source, "read view primary table source")
    _validate_non_negative_integer(declared_row_count, "read view declared_row_count")
    _validate_positive_integer(preview_row_limit, "read view preview_row_limit")
    columns, rows = _load_rows(content, owner="read view primary table")
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
            "table_schema": "measurement_record_primary_table_read_v0",
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


def _normalized_table_summary(
    *,
    source: str,
    columns: list[str],
    rows: list[dict[str, str]],
    declared_columns: list[dict[str, Any]],
    declared_row_count: int | None,
    preview_columns: list[str],
    preview_row_limit: int,
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    declared_by_name = {column["name"]: column for column in declared_columns}
    return {
        "normalized_table_schema": NORMALIZED_PRIMARY_TABLE_SCHEMA,
        "classification": "normalized_table_review_needed"
        if findings
        else "normalized_table_ready",
        "source": source,
        "format": "csv_table",
        "columns": [
            _column_summary(name, position, declared_by_name.get(name))
            for position, name in enumerate(columns)
        ],
        "declared_columns": copy.deepcopy(declared_columns),
        "row_count": len(rows),
        "declared_row_count": declared_row_count,
        "rows": copy.deepcopy(rows),
        "preview": {
            "row_limit": preview_row_limit,
            "columns": list(preview_columns),
            "rows": [
                {name: row[name] for name in preview_columns} for row in rows[:preview_row_limit]
            ],
        },
        "review_findings": [copy.deepcopy(finding) for finding in findings],
    }


def _column_summary(name: str, position: int, declared: dict[str, Any] | None) -> dict[str, Any]:
    if declared is None:
        return {
            "name": name,
            "position": position,
            "declared": False,
            "label": name,
            "role": "undeclared",
            "unit": None,
        }
    return {
        "name": name,
        "position": position,
        "declared": True,
        "label": declared["label"],
        "role": declared["role"],
        "unit": declared["unit"],
    }


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


def _validate_unique_declared_columns(
    columns: tuple[MeasurementRecordNormalizedPrimaryColumnDeclaration, ...],
) -> None:
    seen = set()
    for column in columns:
        if column.name in seen:
            raise ValueError("normalized primary table declared columns must be unique")
        seen.add(column.name)


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


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _optional_text(value: dict[str, Any], field: str) -> str | None:
    if field not in value or value[field] is None:
        return None
    return validate_text(value[field], field)


def _require_list(value: dict[str, Any], field: str) -> list[Any]:
    item = value.get(field)
    if not isinstance(item, list):
        raise ValueError(f"{field} must be a list")
    return item


def _optional_positive_int(value: dict[str, Any], field: str, *, default: int) -> int:
    if field not in value:
        return default
    return _validate_positive_integer(value[field], field)


def _optional_non_negative_int(value: dict[str, Any], field: str) -> int | None:
    if field not in value or value[field] is None:
        return None
    return _validate_non_negative_integer(value[field], field)
