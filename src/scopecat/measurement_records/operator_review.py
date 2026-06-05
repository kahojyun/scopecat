"""Read-only operator review over measurement-record local summaries."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
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
from scopecat.measurement_records.read_model_catalog import (
    MeasurementRecordCatalogRequest,
    MeasurementRecordCatalogRun,
    catalog_measurement_record_read_models_from_request,
)
from scopecat.measurement_records.read_model_shared import _json_bytes
from scopecat.measurement_records.recorded_reference import (
    list_measurement_record_references,
)

OPERATOR_REVIEW_RECEIPT_SCHEMA = "measurement_record_operator_review_receipt_v0"
OPERATOR_REVIEW_RECEIPT_SUMMARY_SCHEMA = (
    "scopecat.measurement_record_operator_review_receipt_summary.v0"
)
OPERATOR_REVIEW_RECEIPT_DIR = "operator-reviews"
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
OPERATOR_DISPOSITIONS = {"recorded_for_continuation", "recorded_as_reviewed"}
SELECTED_RECORD_SOURCES = {"catalog", "not_visible"}
REVIEW_NEXT_ACTIONS = {
    "no_measurement_records_visible",
    "ready_for_later_finalization_decision",
    "review_measurement_record_operator_findings",
    "review_selected_record_summary",
    "select_record_for_review",
    "select_visible_record_or_update_declared_inputs",
}


@dataclass(frozen=True)
class _SelectedRecordPosture:
    record_id: str | None
    source: str | None

    @classmethod
    def from_expected_selected_record(
        cls,
        requested_record_id: str | None,
        selected_record: dict[str, Any] | None,
    ) -> _SelectedRecordPosture:
        source = None
        if selected_record is not None:
            source = validate_text(selected_record.get("source"), "selected record source")
        if source is None and requested_record_id is not None:
            source = "not_visible"
        if source is not None and source not in SELECTED_RECORD_SOURCES:
            raise ValueError("selected_record source is unsupported")
        return cls(record_id=requested_record_id, source=source)


@dataclass(frozen=True)
class MeasurementRecordOperatorReviewRequest:
    """Read-only request for an operator-facing local record review."""

    request_id: str
    records_dir: str = "records"
    selected_record_id: str | None = None
    verify_source_digests: bool = True

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "records_dir": self.records_dir,
            "selected_record_id": self.selected_record_id,
            "verify_source_digests": self.verify_source_digests,
        }


@dataclass(frozen=True)
class MeasurementRecordOperatorReviewRun:
    """Read-only local review composed from catalog and reference views."""

    request: MeasurementRecordOperatorReviewRequest
    storage_root: Path
    catalog_run: MeasurementRecordCatalogRun
    recorded_reference_review: dict[str, Any] | None = None
    review_findings: tuple[dict[str, str], ...] = ()

    @property
    def classification(self) -> str:
        if self.review_findings:
            return "measurement_record_operator_review_needed"
        return "measurement_record_operator_review_ready"

    def to_dict(self) -> dict[str, Any]:
        selected_record = _selected_record_summary(
            self.request.selected_record_id,
            self.catalog_run.entries,
        )
        return {
            "artifact_posture": "local_measurement_record_operator_review",
            "classification": self.classification,
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
            "recorded_references": (
                copy.deepcopy(self.recorded_reference_review)
                if self.recorded_reference_review is not None
                else {
                    "artifact_posture": "local_measurement_record_recorded_reference_review",
                    "entries": [],
                    "review_findings": [],
                }
            ),
            "selected_record": selected_record,
            "review_findings": [copy.deepcopy(finding) for finding in self.review_findings],
            "next_action": _next_action(
                selected_record_id=self.request.selected_record_id,
                selected_record=selected_record,
                entries=self.catalog_run.entries,
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
            "classification": self.classification,
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
    recorded_reference_review = list_measurement_record_references(
        storage_root=root,
        records_dir=request.records_dir,
    )
    findings = _aggregate_findings(
        request,
        catalog_run,
        recorded_reference_review,
    )
    return MeasurementRecordOperatorReviewRun(
        request=request,
        storage_root=catalog_run.storage_root,
        catalog_run=catalog_run,
        recorded_reference_review=recorded_reference_review,
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
    }


def _parse_operator_review_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != OPERATOR_REVIEW_RECEIPT_SCHEMA:
        raise ValueError("operator review receipt schema is unsupported")
    if receipt.get("artifact_posture") != "local_measurement_record_operator_review_receipt":
        raise ValueError("operator review receipt artifact_posture is unsupported")

    receipt_request = _require_dict(receipt, "receipt_request")
    receipt_request_id = validate_public_identifier(
        receipt_request.get("request_id"),
        "receipt request_id",
    )
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
    saved_catalog = _require_dict(saved_review, "catalog")
    saved_entries = _require_list(saved_catalog, "entries")
    requested_selected_id = _optional_identifier(review_request, "selected_record_id")
    selected_record = saved_review.get("selected_record")
    if selected_record is not None and not isinstance(selected_record, dict):
        raise ValueError("operator review receipt selected_record must be an object")
    expected_selected_record = _selected_record_summary(
        requested_selected_id,
        tuple(saved_entries),
    )
    if selected_record != expected_selected_record:
        raise ValueError("saved operator review selected_record must match review snapshot")
    findings = _require_list(saved_review, "review_findings")
    finding_codes = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("operator review finding must be an object")
        finding_codes.append(
            validate_public_identifier(finding.get("code"), "operator review finding code")
        )
    next_action = _validate_review_next_action(
        saved_review.get("next_action"),
        "saved operator review next_action",
    )
    operator_review_request_id = validate_public_identifier(
        review_request.get("request_id"),
        "saved operator review request_id",
    )
    operator_review_classification = validate_text(
        saved_review.get("classification"),
        "saved operator review classification",
    )
    expected_classification = (
        "measurement_record_operator_review_needed"
        if finding_codes
        else "measurement_record_operator_review_ready"
    )
    if operator_review_classification != expected_classification:
        raise ValueError("saved operator review classification must match findings")
    if (
        requested_selected_id is not None
        and expected_selected_record is None
        and "selected_record_not_visible" not in finding_codes
    ):
        raise ValueError("saved operator review missing selected record must be a finding")
    expected_next_action = _next_action(
        selected_record_id=requested_selected_id,
        selected_record=expected_selected_record,
        entries=tuple(saved_entries),
        findings=tuple(findings),
    )
    if next_action != expected_next_action:
        raise ValueError("saved operator review next_action must match review snapshot")

    summary = _require_dict(receipt, "summary")
    if summary.get("operator_review_request_id") != operator_review_request_id:
        raise ValueError("receipt summary request_id must match operator review")
    if summary.get("operator_review_classification") != operator_review_classification:
        raise ValueError("receipt summary classification must match operator review")
    selected_record_posture = _SelectedRecordPosture.from_expected_selected_record(
        requested_selected_id,
        expected_selected_record,
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
    classification = validate_text(
        saved_review.get("classification"),
        "saved operator review classification",
    )
    if classification not in {
        "measurement_record_operator_review_ready",
        "measurement_record_operator_review_needed",
    }:
        raise ValueError("saved operator review classification is unsupported")


def _aggregate_findings(
    request: MeasurementRecordOperatorReviewRequest,
    catalog_run: MeasurementRecordCatalogRun,
    recorded_reference_review: dict[str, Any],
) -> list[dict[str, str]]:
    findings = []
    for finding in catalog_run.review_findings:
        findings.append(_child_finding("catalog", finding))
    for entry in catalog_run.entries:
        if entry["review_finding_count"] > 0:
            findings.append(_entry_review_finding(entry))
    findings.extend(
        _child_finding("recorded_reference", finding)
        for finding in recorded_reference_review["review_findings"]
    )
    if request.selected_record_id is not None:
        selected = _selected_record_summary(
            request.selected_record_id,
            catalog_run.entries,
        )
        if selected is None:
            findings.append(
                _finding(
                    "selected_record_not_visible",
                    request.selected_record_id,
                    "Selected record was not found in catalog entries.",
                )
            )
    return findings


def _entry_review_finding(entry: dict[str, Any]) -> dict[str, str]:
    return _finding(
        "read_model_review_findings_present",
        entry["record_id"],
        "Projected read model includes review findings.",
    )


def _operator_review_receipt(
    request: MeasurementRecordOperatorReviewReceiptRequest,
    operator_review: MeasurementRecordOperatorReviewRun,
) -> dict[str, Any]:
    review_dict = operator_review.to_dict()
    return {
        "schema": OPERATOR_REVIEW_RECEIPT_SCHEMA,
        "artifact_posture": "local_measurement_record_operator_review_receipt",
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


def _validate_review_next_action(value: Any, owner: str) -> str:
    next_action = validate_text(value, owner)
    if next_action not in REVIEW_NEXT_ACTIONS:
        raise ValueError(f"{owner} is not a review-only action")
    return next_action


class _ReceiptWriteFailure(RuntimeError):
    pass


def _selected_record_summary(
    selected_record_id: str | None,
    entries: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    if selected_record_id is None:
        return None
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
    findings: tuple[dict[str, str], ...],
) -> str:
    if findings:
        return "review_measurement_record_operator_findings"
    if selected_record is not None:
        return "review_selected_record_summary"
    if selected_record_id is not None:
        return "select_visible_record_or_update_declared_inputs"
    if entries:
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
) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "target": target,
        "message": message,
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
