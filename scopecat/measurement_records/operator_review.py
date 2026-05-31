"""Read-only operator review over measurement-record local summaries."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records.creation import (
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.read_model_catalog import (
    MeasurementRecordCatalogRequest,
    MeasurementRecordCatalogRun,
    catalog_measurement_record_read_models_from_request,
)
from scopecat.measurement_records.running_inspection import (
    MeasurementRecordRunningInspectionRequest,
    MeasurementRecordRunningInspectionRun,
    inspect_running_measurement_record_from_request,
    summarize_running_measurement_inspection,
)

OPERATOR_REVIEW_SCHEMA = "scopecat.measurement_record_operator_review.v0"
OPERATOR_REVIEW_POLICY = {
    "catalog_authority": "record_local_projected_read_models",
    "running_inspection_authority": "caller_declared_running_inspection_requests",
    "selected_record_authority": "catalog_entry_or_running_inspection_summary",
    "storage_mutation": "not_performed",
    "record_discovery": "catalog_records_dir_only",
    "update_receipt_discovery": "not_performed",
    "read_model_refresh": "not_performed",
    "manifest_replacement": "not_performed",
    "gui_state": "not_persisted",
}
DOES_NOT_CLAIM = [
    "canonical_storage_authority",
    "record_repair",
    "read_model_refresh",
    "update_receipt_discovery",
    "primary_data_revalidation_beyond_child_operations",
    "lifecycle_finalization",
    "manifest_replacement",
    "storage_mutation",
    "gui_review_state",
    "public_export_schema",
]


@dataclass(frozen=True)
class MeasurementRecordOperatorReviewRequest:
    """Read-only request for an operator-facing local record review."""

    request_id: str
    records_dir: str = "records"
    selected_record_id: str | None = None
    verify_source_digests: bool = True
    running_inspection_requests: tuple[MeasurementRecordRunningInspectionRequest, ...] = ()
    latest_row_limit: int = 3

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "operator review request_id")
        validate_relative_path(self.records_dir, "operator review records_dir")
        if self.selected_record_id is not None:
            validate_public_identifier(
                self.selected_record_id,
                "operator review selected_record_id",
            )
        if not isinstance(self.verify_source_digests, bool):
            raise ValueError("operator review verify_source_digests must be boolean")
        if not isinstance(self.running_inspection_requests, tuple):
            raise ValueError("operator review running_inspection_requests must be a tuple")
        for request in self.running_inspection_requests:
            if not isinstance(request, MeasurementRecordRunningInspectionRequest):
                raise ValueError(
                    "operator review running_inspection_requests must contain "
                    "MeasurementRecordRunningInspectionRequest objects"
                )
        _validate_positive_integer(self.latest_row_limit, "operator review latest_row_limit")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "records_dir": self.records_dir,
            "selected_record_id": self.selected_record_id,
            "verify_source_digests": self.verify_source_digests,
            "running_inspection_requests": [
                request.to_dict() for request in self.running_inspection_requests
            ],
            "latest_row_limit": self.latest_row_limit,
        }


@dataclass(frozen=True)
class MeasurementRecordOperatorReviewRun:
    """Read-only local review composed from catalog and running inspection views."""

    request: MeasurementRecordOperatorReviewRequest
    storage_root: Path
    catalog_run: MeasurementRecordCatalogRun
    running_inspection_runs: tuple[MeasurementRecordRunningInspectionRun, ...] = ()
    running_inspection_failures: tuple[dict[str, str], ...] = ()
    review_findings: tuple[dict[str, str], ...] = ()

    @property
    def classification(self) -> str:
        if self.review_findings:
            return "measurement_record_operator_review_needed"
        return "measurement_record_operator_review_ready"

    def to_dict(self) -> dict[str, Any]:
        running_summaries = [
            summarize_running_measurement_inspection(
                run,
                latest_row_limit=self.request.latest_row_limit,
            )
            for run in self.running_inspection_runs
        ]
        return {
            "artifact_posture": "local_measurement_record_operator_review",
            "operator_review_policy": copy.deepcopy(OPERATOR_REVIEW_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "catalog_record_read_models",
                    "run_declared_running_inspections",
                    "project_selected_record_summary",
                    "aggregate_review_findings",
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "storage_root": str(self.storage_root),
            "catalog": {
                "classification": self.catalog_run.classification,
                "entry_count": len(self.catalog_run.entries),
                "entries": [copy.deepcopy(entry) for entry in self.catalog_run.entries],
                "review_findings": [
                    copy.deepcopy(finding) for finding in self.catalog_run.review_findings
                ],
            },
            "running_inspections": running_summaries,
            "selected_record": _selected_record_summary(
                self.request.selected_record_id,
                self.catalog_run.entries,
                running_summaries,
            ),
            "review_findings": [copy.deepcopy(finding) for finding in self.review_findings],
            "next_action": _next_action(
                selected_record_id=self.request.selected_record_id,
                selected_record=_selected_record_summary(
                    self.request.selected_record_id,
                    self.catalog_run.entries,
                    running_summaries,
                ),
                entries=self.catalog_run.entries,
                running_summaries=running_summaries,
                findings=self.review_findings,
            ),
        }


def review_measurement_records(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordOperatorReviewRun:
    """Compose a read-only operator review from a raw review source."""

    request = _parse_source(source)
    return review_measurement_records_from_request(request, storage_root=storage_root)


def review_measurement_records_from_request(
    request: MeasurementRecordOperatorReviewRequest,
    *,
    storage_root: str | Path,
) -> MeasurementRecordOperatorReviewRun:
    """Compose a read-only operator review from a typed review request."""

    root = Path(storage_root)
    catalog_run = catalog_measurement_record_read_models_from_request(
        MeasurementRecordCatalogRequest(
            request_id=f"{request.request_id}-catalog",
            records_dir=request.records_dir,
            verify_source_digests=request.verify_source_digests,
        ),
        storage_root=root,
    )
    inspection_runs: list[MeasurementRecordRunningInspectionRun] = []
    inspection_failures: list[dict[str, str]] = []
    for inspection_request in request.running_inspection_requests:
        try:
            inspection_runs.append(
                inspect_running_measurement_record_from_request(
                    inspection_request,
                    storage_root=root,
                )
            )
        except ValueError as exc:
            inspection_failures.append(
                _finding(
                    "running_inspection_unavailable",
                    inspection_request.record_id,
                    str(exc),
                    does_not_claim="record_repair_or_update_receipt_discovery",
                )
            )

    running_summaries = [
        summarize_running_measurement_inspection(
            run,
            latest_row_limit=request.latest_row_limit,
        )
        for run in inspection_runs
    ]
    findings = _aggregate_findings(
        request,
        catalog_run,
        inspection_runs,
        tuple(inspection_failures),
        running_summaries,
    )
    return MeasurementRecordOperatorReviewRun(
        request=request,
        storage_root=catalog_run.storage_root,
        catalog_run=catalog_run,
        running_inspection_runs=tuple(inspection_runs),
        running_inspection_failures=tuple(inspection_failures),
        review_findings=tuple(findings),
    )


def _parse_source(source: dict[str, Any]) -> MeasurementRecordOperatorReviewRequest:
    if source.get("operator_review_schema") != OPERATOR_REVIEW_SCHEMA:
        raise ValueError(f"operator review source schema must be {OPERATOR_REVIEW_SCHEMA}")
    if source.get("operator_review_policy") != OPERATOR_REVIEW_POLICY:
        raise ValueError("operator review source policy is unsupported")
    request = _require_dict(source, "operator_review_request")
    running_sources = request.get("running_inspection_requests", [])
    if not isinstance(running_sources, list):
        raise ValueError("operator review running_inspection_requests must be a list")
    return MeasurementRecordOperatorReviewRequest(
        request_id=_require_text(request, "request_id"),
        records_dir=_optional_text(request, "records_dir", default="records"),
        selected_record_id=_optional_identifier(request, "selected_record_id"),
        verify_source_digests=_optional_bool(
            request,
            "verify_source_digests",
            default=True,
        ),
        running_inspection_requests=tuple(
            _parse_running_inspection_request(item) for item in running_sources
        ),
        latest_row_limit=_optional_positive_int(request, "latest_row_limit", default=3),
    )


def _parse_running_inspection_request(
    source: dict[str, Any],
) -> MeasurementRecordRunningInspectionRequest:
    if not isinstance(source, dict):
        raise ValueError("operator review running inspection request must be an object")
    paths = source.get("update_receipt_paths", [])
    if not isinstance(paths, list):
        raise ValueError("operator review update_receipt_paths must be a list")
    return MeasurementRecordRunningInspectionRequest(
        request_id=_require_text(source, "request_id"),
        record_id=_require_text(source, "record_id"),
        record_dir=_require_text(source, "record_dir"),
        writer_receipt_path=_require_text(source, "writer_receipt_path"),
        update_receipt_paths=tuple(validate_text(path, "update_receipt_path") for path in paths),
        expected_total_rows=_optional_positive_int_or_none(source, "expected_total_rows"),
        preview_row_limit=_optional_positive_int(source, "preview_row_limit", default=5),
    )


def _aggregate_findings(
    request: MeasurementRecordOperatorReviewRequest,
    catalog_run: MeasurementRecordCatalogRun,
    inspection_runs: list[MeasurementRecordRunningInspectionRun],
    inspection_failures: tuple[dict[str, str], ...],
    running_summaries: list[dict[str, Any]],
) -> list[dict[str, str]]:
    running_record_dirs = {
        _require_dict(summary, "record")["record_dir"] for summary in running_summaries
    }
    findings = []
    for finding in catalog_run.review_findings:
        if _is_running_record_missing_read_model_finding(finding, running_record_dirs):
            continue
        findings.append(_child_finding("catalog", finding))
    for run in inspection_runs:
        findings.extend(
            _child_finding("running_inspection", finding) for finding in run.review_findings
        )
    findings.extend(copy.deepcopy(finding) for finding in inspection_failures)
    if request.selected_record_id is not None:
        selected = _selected_record_summary(
            request.selected_record_id,
            catalog_run.entries,
            running_summaries,
        )
        if selected is None:
            findings.append(
                _finding(
                    "selected_record_not_visible",
                    request.selected_record_id,
                    "Selected record was not found in catalog entries or running inspections.",
                    does_not_claim="record_discovery_beyond_declared_inputs",
                )
            )
    return findings


def _is_running_record_missing_read_model_finding(
    finding: dict[str, str],
    running_record_dirs: set[str],
) -> bool:
    if finding.get("code") != "read_model_missing":
        return False
    return any(
        finding.get("target") == f"{record_dir}/record-read-model.json"
        for record_dir in running_record_dirs
    )


def _selected_record_summary(
    selected_record_id: str | None,
    entries: tuple[dict[str, Any], ...],
    running_summaries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if selected_record_id is None:
        return None
    for summary in running_summaries:
        record = _require_dict(summary, "record")
        if record.get("record_id") == selected_record_id:
            return {
                "source": "running_inspection",
                "record": copy.deepcopy(record),
                "inspection": copy.deepcopy(summary["inspection"]),
            }
    for entry in entries:
        if entry.get("record_id") == selected_record_id:
            return {
                "source": "catalog",
                "record": {
                    "record_id": entry["record_id"],
                    "record_dir": entry["record_dir"],
                    "lifecycle_state": entry["lifecycle_state"],
                },
                "primary_data": copy.deepcopy(entry["primary_data"]),
                "table": copy.deepcopy(entry["table"]),
                "finalization": copy.deepcopy(entry["finalization"]),
                "review_finding_count": entry["review_finding_count"],
            }
    return None


def _next_action(
    *,
    selected_record_id: str | None,
    selected_record: dict[str, Any] | None,
    entries: tuple[dict[str, Any], ...],
    running_summaries: list[dict[str, Any]],
    findings: tuple[dict[str, str], ...],
) -> str:
    if findings:
        return "review_measurement_record_operator_findings"
    if selected_record is not None and selected_record.get("source") == "running_inspection":
        return str(selected_record["inspection"]["next_action"])
    if selected_record is not None:
        return "review_selected_record_summary"
    if selected_record_id is not None:
        return "select_visible_record_or_update_declared_inputs"
    if entries or running_summaries:
        return "select_record_for_review"
    return "no_measurement_records_visible"


def _child_finding(source: str, finding: dict[str, str]) -> dict[str, str]:
    copied = copy.deepcopy(finding)
    copied["source"] = source
    return copied


def _finding(
    code: str,
    target: str,
    message: str,
    *,
    does_not_claim: str,
) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "target": target,
        "message": message,
        "does_not_claim": does_not_claim,
    }


def _validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _optional_text(value: dict[str, Any], field: str, *, default: str) -> str:
    if field not in value:
        return default
    return validate_text(value[field], field)


def _optional_identifier(value: dict[str, Any], field: str) -> str | None:
    if field not in value or value[field] is None:
        return None
    return validate_public_identifier(value[field], field)


def _optional_bool(value: dict[str, Any], field: str, *, default: bool) -> bool:
    if field not in value:
        return default
    if not isinstance(value[field], bool):
        raise ValueError(f"{field} must be boolean")
    return value[field]


def _optional_positive_int(value: dict[str, Any], field: str, *, default: int) -> int:
    if field not in value:
        return default
    return _validate_positive_integer(value[field], field)


def _optional_positive_int_or_none(value: dict[str, Any], field: str) -> int | None:
    if field not in value:
        return None
    return _validate_positive_integer(value[field], field)
