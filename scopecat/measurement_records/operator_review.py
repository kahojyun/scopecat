"""Read-only operator review over measurement-record local summaries."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import (
    path_under as _path_under_common,
)
from scopecat.measurement_records._storage import (
    sha256 as _sha256,
)
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
from scopecat.measurement_records.read_model_shared import _json_bytes
from scopecat.measurement_records.running_inspection import (
    MeasurementRecordRunningInspectionRequest,
    MeasurementRecordRunningInspectionRun,
    inspect_running_measurement_record_from_request,
    summarize_running_measurement_inspection,
)

OPERATOR_REVIEW_SCHEMA = "scopecat.measurement_record_operator_review.v0"
OPERATOR_REVIEW_RECEIPT_SCHEMA = "measurement_record_operator_review_receipt_candidate_v0"
OPERATOR_REVIEW_RECEIPT_SUMMARY_SCHEMA = (
    "scopecat.measurement_record_operator_review_receipt_summary.v0"
)
OPERATOR_REVIEW_RECEIPT_DIR = "operator-reviews"
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
OPERATOR_REVIEW_RECEIPT_POLICY = {
    "input_authority": "measurement_record_operator_review_run",
    "workflow_authority": "approved_operator_review_receipt_request",
    "receipt_materialization": "local_no_overwrite_receipt",
    "record_mutation": "not_performed",
    "review_state_authority": "local_continuation_note_only",
    "finding_resolution": "not_performed",
    "retry_authority": "not_granted",
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
RECEIPT_DOES_NOT_CLAIM = [
    "record_mutation",
    "finding_resolution",
    "retry_authority",
    "import_approval",
    "refresh_approval",
    "lifecycle_finalization",
    "canonical_review_state",
    "gui_review_state",
    "public_export_schema",
]
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
OPERATOR_DISPOSITIONS = {"recorded_for_continuation", "recorded_as_reviewed"}
SELECTED_RECORD_SOURCES = {"catalog", "running_inspection", "not_visible"}


@dataclass(frozen=True)
class _SelectedRecordPosture:
    record_id: str | None
    source: str | None

    @classmethod
    def from_saved_review(
        cls,
        review_request: dict[str, Any],
        selected_record: dict[str, Any] | None,
    ) -> _SelectedRecordPosture:
        requested_id = _optional_identifier(review_request, "selected_record_id")
        projected_id = _selected_record_id_from_saved_summary(selected_record)
        if projected_id is not None and projected_id != requested_id:
            raise ValueError("selected_record must match operator review request")
        source = _selected_record_source_from_saved_summary(selected_record)
        if source is None and requested_id is not None:
            source = "not_visible"
        if source is not None and source not in SELECTED_RECORD_SOURCES:
            raise ValueError("selected_record source is unsupported")
        return cls(record_id=requested_id, source=source)


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


@dataclass(frozen=True)
class MeasurementRecordOperatorReviewReceiptRequest:
    """Approved request to save a local operator-review receipt."""

    request_id: str
    approval_state: str
    review_receipt_path: str
    operator_disposition: str = "recorded_for_continuation"
    operator_reason: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "operator review receipt request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("operator review receipt approval_state is unsupported")
        validate_relative_path(
            self.review_receipt_path,
            "operator review receipt review_receipt_path",
        )
        _validate_operator_review_receipt_path(self.review_receipt_path)
        if self.operator_disposition not in OPERATOR_DISPOSITIONS:
            raise ValueError("operator review receipt operator_disposition is unsupported")
        if self.operator_reason is not None:
            validate_text(self.operator_reason, "operator review receipt operator_reason")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    def to_dict(self) -> dict[str, Any]:
        result = {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "review_receipt_path": self.review_receipt_path,
            "operator_disposition": self.operator_disposition,
        }
        if self.operator_reason is not None:
            result["operator_reason"] = self.operator_reason
        return result


@dataclass(frozen=True)
class MeasurementRecordOperatorReviewReceiptRun:
    """Local run receipt for saving an operator-review receipt."""

    request: MeasurementRecordOperatorReviewReceiptRequest
    operator_review: MeasurementRecordOperatorReviewRun
    storage_root: Path
    receipt_digest: str | None = None
    receipt_size_bytes: int | None = None
    save_error: str | None = None

    @property
    def saved(self) -> bool:
        return self.classification == "saved_operator_review_receipt"

    @property
    def classification(self) -> str:
        if self.save_error is not None:
            return "blocked_before_operator_review_receipt"
        if not self.request.approved:
            return "blocked_before_operator_review_receipt"
        return "saved_operator_review_receipt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_measurement_record_operator_review_receipt_run",
            "operator_review_receipt_policy": copy.deepcopy(OPERATOR_REVIEW_RECEIPT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_operator_review_receipt_request",
                    *([] if not self.saved else ["write_operator_review_receipt"]),
                ],
                "does_not_claim": list(RECEIPT_DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "operator_review": _operator_review_ref(self.operator_review),
            "receipt": {
                "saved": self.saved,
                "storage_root": str(self.storage_root),
                "review_receipt_path": self.request.review_receipt_path,
                "receipt_digest": self.receipt_digest,
                "receipt_size_bytes": self.receipt_size_bytes,
                "save_error": self.save_error,
            },
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


def save_measurement_record_operator_review_receipt(
    request: MeasurementRecordOperatorReviewReceiptRequest,
    *,
    operator_review: MeasurementRecordOperatorReviewRun,
    storage_root: str | Path,
    receipt_writer: Callable[[Path, bytes], None] | None = None,
) -> MeasurementRecordOperatorReviewReceiptRun:
    """Save a local no-overwrite receipt for an already computed operator review."""

    root = _existing_directory_root(Path(storage_root), "operator review receipt storage root")
    if root != operator_review.storage_root:
        raise ValueError("operator review receipt storage_root must match operator review")
    if not request.approved:
        return MeasurementRecordOperatorReviewReceiptRun(
            request=request,
            operator_review=operator_review,
            storage_root=root,
        )

    receipt = _operator_review_receipt(request, operator_review)
    content = _json_bytes(receipt)
    writer = receipt_writer or _write_new_file
    try:
        _write_receipt(root, request.review_receipt_path, content, writer)
    except _ReceiptWriteFailure as exc:
        return MeasurementRecordOperatorReviewReceiptRun(
            request=request,
            operator_review=operator_review,
            storage_root=root,
            save_error=str(exc),
        )
    return MeasurementRecordOperatorReviewReceiptRun(
        request=request,
        operator_review=operator_review,
        storage_root=root,
        receipt_digest=_sha256(content),
        receipt_size_bytes=len(content),
    )


def summarize_measurement_record_operator_review_receipt(
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Project a compact continuation summary from a saved operator-review receipt."""

    parsed = _parse_operator_review_receipt(receipt)
    return {
        "summary_schema": OPERATOR_REVIEW_RECEIPT_SUMMARY_SCHEMA,
        "artifact_posture": "local_measurement_record_operator_review_receipt_summary",
        "summary_policy": {
            "input_authority": "saved_operator_review_receipt",
            "record_mutation": "not_performed",
            "continuation_authority": "not_granted",
            "gui_state": "not_persisted",
            "redaction_boundary": "local_workspace_only",
        },
        "receipt": {
            "request_id": parsed["receipt_request_id"],
            "review_receipt_path": parsed["review_receipt_path"],
            "operator_disposition": parsed["operator_disposition"],
            "operator_reason": parsed["operator_reason"],
        },
        "operator_review": {
            "request_id": parsed["operator_review_request_id"],
            "classification": parsed["operator_review_classification"],
            "selected_record_id": parsed["selected_record_id"],
            "selected_record_source": parsed["selected_record_source"],
            "review_finding_codes": parsed["review_finding_codes"],
            "next_action": parsed["next_action"],
        },
        "does_not_claim": list(RECEIPT_DOES_NOT_CLAIM),
    }


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


def _parse_operator_review_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != OPERATOR_REVIEW_RECEIPT_SCHEMA:
        raise ValueError("operator review receipt schema is unsupported")
    if receipt.get("artifact_posture") != "local_measurement_record_operator_review_receipt":
        raise ValueError("operator review receipt artifact_posture is unsupported")
    if receipt.get("operator_review_receipt_policy") != OPERATOR_REVIEW_RECEIPT_POLICY:
        raise ValueError("operator review receipt policy is unsupported")

    receipt_request = _require_dict(receipt, "receipt_request")
    receipt_request_id = validate_text(receipt_request.get("request_id"), "receipt request_id")
    approval_state = validate_text(
        receipt_request.get("approval_state"),
        "receipt approval_state",
    )
    if approval_state not in APPROVAL_STATES:
        raise ValueError("receipt approval_state is unsupported")
    if approval_state != "approved":
        raise ValueError("operator review receipt summary requires approved receipt")
    review_receipt_path = validate_relative_path(
        receipt_request.get("review_receipt_path"),
        "receipt review_receipt_path",
    )
    _validate_operator_review_receipt_path(review_receipt_path)

    disposition = _require_dict(receipt, "operator_disposition")
    operator_disposition = validate_text(
        disposition.get("state"),
        "receipt operator_disposition",
    )
    if operator_disposition not in OPERATOR_DISPOSITIONS:
        raise ValueError("receipt operator_disposition is unsupported")
    if receipt_request.get("operator_disposition") != operator_disposition:
        raise ValueError("receipt operator_disposition must match receipt request")
    operator_reason = disposition.get("operator_reason")
    if operator_reason is not None:
        operator_reason = validate_text(operator_reason, "receipt operator_reason")
    if receipt_request.get("operator_reason") != operator_reason:
        raise ValueError("receipt operator_reason must match receipt request")

    saved_review = _require_dict(receipt, "operator_review")
    _validate_saved_operator_review_contract(saved_review)
    review_request = _require_dict(saved_review, "request")
    review_workflow = _require_dict(saved_review, "workflow")
    selected_record = saved_review.get("selected_record")
    if selected_record is not None and not isinstance(selected_record, dict):
        raise ValueError("operator review receipt selected_record must be an object")
    findings = _require_list(saved_review, "review_findings")
    finding_codes = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("operator review finding must be an object")
        finding_codes.append(
            validate_public_identifier(finding.get("code"), "operator review finding code")
        )
    next_action = validate_text(
        saved_review.get("next_action"),
        "saved operator review next_action",
    )
    operator_review_request_id = validate_text(
        review_request.get("request_id"),
        "saved operator review request_id",
    )
    operator_review_classification = validate_text(
        review_workflow.get("classification"),
        "saved operator review classification",
    )

    summary = _require_dict(receipt, "summary")
    if summary.get("operator_review_request_id") != operator_review_request_id:
        raise ValueError("receipt summary request_id must match operator review")
    if summary.get("operator_review_classification") != operator_review_classification:
        raise ValueError("receipt summary classification must match operator review")
    selected_record_posture = _SelectedRecordPosture.from_saved_review(
        review_request,
        selected_record,
    )
    if summary.get("selected_record_id") != selected_record_posture.record_id:
        raise ValueError("receipt summary selected_record_id must match operator review")
    if summary.get("review_finding_codes") != finding_codes:
        raise ValueError("receipt summary finding codes must match operator review")
    if summary.get("next_action") != next_action:
        raise ValueError("receipt summary next_action must match operator review")

    return {
        "receipt_request_id": receipt_request_id,
        "review_receipt_path": review_receipt_path,
        "operator_disposition": operator_disposition,
        "operator_reason": operator_reason,
        "operator_review_request_id": operator_review_request_id,
        "operator_review_classification": operator_review_classification,
        "selected_record_id": selected_record_posture.record_id,
        "selected_record_source": selected_record_posture.source,
        "review_finding_codes": finding_codes,
        "next_action": next_action,
    }


def _validate_saved_operator_review_contract(saved_review: dict[str, Any]) -> None:
    if saved_review.get("artifact_posture") != "local_measurement_record_operator_review":
        raise ValueError("saved operator review artifact_posture is unsupported")
    if saved_review.get("operator_review_policy") != OPERATOR_REVIEW_POLICY:
        raise ValueError("saved operator review policy is unsupported")
    workflow = _require_dict(saved_review, "workflow")
    classification = validate_text(
        workflow.get("classification"),
        "saved operator review classification",
    )
    if classification not in {
        "measurement_record_operator_review_ready",
        "measurement_record_operator_review_needed",
    }:
        raise ValueError("saved operator review classification is unsupported")


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


def _operator_review_receipt(
    request: MeasurementRecordOperatorReviewReceiptRequest,
    operator_review: MeasurementRecordOperatorReviewRun,
) -> dict[str, Any]:
    review_dict = operator_review.to_dict()
    return {
        "schema": OPERATOR_REVIEW_RECEIPT_SCHEMA,
        "artifact_posture": "local_measurement_record_operator_review_receipt",
        "operator_review_receipt_policy": copy.deepcopy(OPERATOR_REVIEW_RECEIPT_POLICY),
        "receipt_request": request.to_dict(),
        "operator_disposition": {
            "state": request.operator_disposition,
            "operator_reason": request.operator_reason,
        },
        "operator_review": review_dict,
        "summary": {
            "operator_review_request_id": operator_review.request.request_id,
            "operator_review_classification": operator_review.classification,
            "selected_record_id": operator_review.request.selected_record_id,
            "review_finding_codes": [
                finding["code"] for finding in operator_review.review_findings
            ],
            "next_action": review_dict["next_action"],
        },
        "does_not_claim": list(RECEIPT_DOES_NOT_CLAIM),
    }


def _operator_review_ref(run: MeasurementRecordOperatorReviewRun) -> dict[str, Any]:
    return {
        "request_id": run.request.request_id,
        "classification": run.classification,
        "selected_record_id": run.request.selected_record_id,
        "review_finding_count": len(run.review_findings),
    }


def _write_receipt(
    root: Path,
    relative_path: str,
    content: bytes,
    receipt_writer: Callable[[Path, bytes], None],
) -> None:
    target = _path_under(root, relative_path)
    _ensure_no_symlink_parents(root, relative_path, "operator review receipt target")
    if target.exists() or target.is_symlink():
        raise _ReceiptWriteFailure("operator review receipt target already exists")
    try:
        receipt_writer(target, content)
    except FileExistsError as exc:
        raise _ReceiptWriteFailure("operator review receipt target already exists") from exc
    except Exception as exc:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise _ReceiptWriteFailure(f"operator review receipt write failed: {exc}") from exc


def _write_new_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "operator review receipt path")


def _validate_operator_review_receipt_path(relative_path: str) -> None:
    if not relative_path.startswith(f"{OPERATOR_REVIEW_RECEIPT_DIR}/"):
        raise ValueError(
            "operator review receipt review_receipt_path must be under "
            f"{OPERATOR_REVIEW_RECEIPT_DIR}/"
        )


class _ReceiptWriteFailure(RuntimeError):
    pass


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


def _require_list(value: dict[str, Any], field: str) -> list[Any]:
    item = value.get(field)
    if not isinstance(item, list):
        raise ValueError(f"{field} must be a list")
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


def _selected_record_id_from_saved_summary(selected_record: dict[str, Any] | None) -> str | None:
    if selected_record is None:
        return None
    record = _require_dict(selected_record, "record")
    return validate_public_identifier(record.get("record_id"), "selected record_id")


def _selected_record_source_from_saved_summary(
    selected_record: dict[str, Any] | None,
) -> str | None:
    if selected_record is None:
        return None
    return validate_text(selected_record.get("source"), "selected record source")
