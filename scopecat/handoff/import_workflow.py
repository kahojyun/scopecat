"""Operator-facing receiving/import workflow composition."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    validate_public_identifier,
    validate_relative_path,
    validate_strict_child_path,
)
from scopecat.handoff.acceptance_preflight import (
    HandoffAcceptanceDestination,
    HandoffAcceptancePreflightRun,
    run_acceptance_preflight,
)
from scopecat.handoff.storage_acceptance import (
    HandoffStorageAcceptanceRequest,
    HandoffStorageAcceptanceRun,
    run_storage_acceptance_from_preflight,
)

_EXPECTED_SCHEMA = "scopecat.handoff_import_workflow.v0"
_EXPECTED_POLICY = {
    "workflow_authority": "operator_import_workflow_review",
    "acceptance_preflight": "required_before_operator_decision_receipt",
    "operator_decision": "explicit_approve_reject_or_needs_review",
    "storage_acceptance": "only_after_approved_operator_decision",
    "review_state": "local_session_receipt",
    "storage_schema": "candidate_storage_acceptance_only",
    "conflict_resolution": "not_performed",
    "final_storage_schema": "not_defined",
    "archive_handling": "not_performed",
    "signature_validation": "not_performed",
    "linked_context_payload_import": "not_performed",
}
_DECISIONS = {
    "approved_for_storage_acceptance",
    "rejected_after_review",
    "needs_review",
}


@dataclass(frozen=True)
class HandoffImportWorkflowRequest:
    """Operator decision for the local receiving/import workflow."""

    request_id: str
    requested_package_id: str
    operator_decision: str
    operator_reason: str | None = None
    storage_acceptance_request: HandoffStorageAcceptanceRequest | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "import_workflow_request.request_id")
        validate_public_identifier(
            self.requested_package_id,
            "import_workflow_request.requested_package_id",
        )
        if self.operator_decision not in _DECISIONS:
            raise ValueError("import workflow operator_decision is unsupported")
        if self.operator_decision == "approved_for_storage_acceptance":
            if self.operator_reason is not None:
                raise ValueError("approved import workflow must not carry operator_reason")
            if not isinstance(
                self.storage_acceptance_request,
                HandoffStorageAcceptanceRequest,
            ):
                raise ValueError("approved import workflow requires storage_acceptance_request")
            return
        _validate_operator_reason(self.operator_reason)
        if self.storage_acceptance_request is not None:
            raise ValueError(
                "storage_acceptance_request is allowed only for approved import workflows"
            )

    @property
    def mutation_approved(self) -> bool:
        return self.operator_decision == "approved_for_storage_acceptance"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "requested_package_id": self.requested_package_id,
            "operator_decision": self.operator_decision,
            "operator_reason": self.operator_reason,
            "storage_acceptance_request": (
                None
                if self.storage_acceptance_request is None
                else self.storage_acceptance_request.to_dict()
            ),
        }


@dataclass(frozen=True)
class HandoffImportWorkflowRun:
    """Local session receipt for an operator-facing handoff import workflow."""

    request: HandoffImportWorkflowRequest
    preflight: HandoffAcceptancePreflightRun
    storage_acceptance: HandoffStorageAcceptanceRun | None = None

    @property
    def classification(self) -> str:
        if self.request.operator_decision == "rejected_after_review":
            return "rejected_after_review"
        if self.request.operator_decision == "needs_review":
            return "needs_operator_review"
        if self.storage_acceptance is None:
            return "blocked_before_storage_acceptance"
        if self.storage_acceptance.classification == "accepted_into_storage":
            return "accepted_into_storage"
        if self.storage_acceptance.classification == "rolled_back_after_write_failure":
            return "rolled_back_after_write_failure"
        if self.preflight.classification == "blocked_by_destination_collision":
            return "blocked_by_destination_collision"
        if self.preflight.classification == "blocked_by_destination_guardrail":
            return "blocked_by_destination_guardrail"
        if self.preflight.classification == "blocked_before_acceptance_preflight":
            return "blocked_before_acceptance_preflight"
        return "blocked_before_storage_acceptance"

    @property
    def accepted(self) -> bool:
        return self.classification == "accepted_into_storage"

    def to_dict(self) -> dict[str, Any]:
        storage_summary = (
            None if self.storage_acceptance is None else self.storage_acceptance.to_dict()
        )
        return {
            "artifact_posture": "local_import_workflow_receipt",
            "import_workflow_policy": copy.deepcopy(_EXPECTED_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": self._steps(),
                "does_not_claim": [
                    "final_storage_schema",
                    "broad_import_workflow",
                    "existing_record_update",
                    "conflict_resolution",
                    "crash_recovery",
                    "archive_extraction",
                    "signature_or_authenticity_validation",
                    "linked_context_payload_import",
                ],
            },
            "request": self.request.to_dict(),
            "review_state": {
                "operator_decision": self.request.operator_decision,
                "operator_reason": self.request.operator_reason,
                "mutation_approved": self.request.mutation_approved,
                "final_state": self.classification,
                "next_action": self._next_action(),
            },
            "package": {
                "package_id": self.preflight.import_plan.package.package_id,
                "preview_classification": self.preflight.import_plan.package.preview_classification,
                "measurement_ids": list(self.preflight.import_plan.package.measurement_ids),
            },
            "preflight": {
                "classification": self.preflight.classification,
                "allowed": self.preflight.acceptance_preflight_allowed,
                "destination_observation": [
                    item.to_dict() for item in self.preflight.destination_observations
                ],
            },
            "storage_acceptance": storage_summary,
        }

    def _steps(self) -> list[str]:
        steps = [
            "run_acceptance_preflight",
            "record_operator_decision",
        ]
        if self.request.mutation_approved:
            steps.append("run_storage_acceptance")
        return steps

    def _next_action(self) -> str:
        if self.classification == "accepted_into_storage":
            return "use_local_storage_acceptance_receipt"
        if self.classification == "rejected_after_review":
            return "record_rejection_without_storage_mutation"
        if self.classification == "needs_operator_review":
            return "complete_operator_review_before_storage_acceptance"
        if self.classification == "blocked_by_destination_collision":
            return "choose_available_destinations_before_storage_acceptance"
        if self.classification == "blocked_by_destination_guardrail":
            return "repair_destination_guardrail_before_storage_acceptance"
        if self.classification == "rolled_back_after_write_failure":
            return "review_rollback_and_retry_with_fresh_preflight"
        if self.classification == "blocked_before_acceptance_preflight":
            return "resolve_receiving_gate_or_import_plan_before_storage_acceptance"
        return "review_storage_acceptance_error_before_retry"


@dataclass(frozen=True)
class HandoffImportWorkflowReceiptSummary:
    """Read-only operator summary of a local import workflow receipt."""

    package_id: str
    measurement_ids: tuple[str, ...]
    final_state: str
    next_action: str
    operator_decision: str
    operator_reason: str | None
    mutation_approved: bool
    preflight_classification: str
    storage_acceptance_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_import_workflow_receipt_summary",
            "summary_policy": {
                "source": "local_import_workflow_receipt",
                "authority": "read_only_operator_continuation_summary",
                "storage_mutation": "not_performed",
                "continuation_authority": "fresh_workflow_request_required",
                "portable_export": "not_produced",
            },
            "package_id": self.package_id,
            "measurement_ids": list(self.measurement_ids),
            "final_state": self.final_state,
            "next_action": self.next_action,
            "operator_decision": self.operator_decision,
            "operator_reason": self.operator_reason,
            "mutation_approved": self.mutation_approved,
            "preflight_classification": self.preflight_classification,
            "storage_acceptance_performed": self.storage_acceptance_performed,
            "does_not_claim": [
                "storage_mutation",
                "continuation_authorization",
                "fresh_preflight",
                "destination_recheck",
                "package_reopen",
                "durable_review_state",
                "public_import_api",
            ],
        }


def run_import_workflow(
    source: dict[str, Any],
    *,
    package_dir: str | Path,
    storage_root: str | Path,
) -> HandoffImportWorkflowRun:
    """Run the local receiving/import workflow through one operator decision."""

    request, preflight_source = _parse_source(source)
    preflight = run_acceptance_preflight(
        preflight_source,
        package_dir=package_dir,
        storage_root=storage_root,
    )
    return run_import_workflow_from_preflight(
        request,
        preflight=preflight,
        package_dir=package_dir,
        storage_root=storage_root,
    )


def run_import_workflow_from_preflight(
    request: HandoffImportWorkflowRequest,
    *,
    preflight: HandoffAcceptancePreflightRun,
    package_dir: str | Path,
    storage_root: str | Path,
) -> HandoffImportWorkflowRun:
    """Run the operator workflow from an already typed acceptance preflight."""

    _validate_against_preflight(request=request, preflight=preflight)
    _validate_roots_against_preflight(
        package_dir=package_dir,
        storage_root=storage_root,
        preflight=preflight,
    )
    storage_acceptance: HandoffStorageAcceptanceRun | None = None
    if request.mutation_approved:
        storage_request = request.storage_acceptance_request
        if storage_request is None:
            raise ValueError("approved import workflow requires storage_acceptance_request")
        storage_acceptance = run_storage_acceptance_from_preflight(
            storage_request,
            preflight=preflight,
            package_dir=package_dir,
            storage_root=storage_root,
        )
    return HandoffImportWorkflowRun(
        request=request,
        preflight=preflight,
        storage_acceptance=storage_acceptance,
    )


def summarize_import_workflow_receipt(
    receipt: dict[str, Any],
) -> HandoffImportWorkflowReceiptSummary:
    """Summarize a local import workflow receipt without authorizing continuation."""

    receipt = _require_mapping(receipt, "handoff import workflow receipt")
    _require_keys(
        receipt,
        {
            "artifact_posture",
            "import_workflow_policy",
            "workflow",
            "request",
            "review_state",
            "package",
            "preflight",
            "storage_acceptance",
        },
        "handoff import workflow receipt",
    )
    if receipt["artifact_posture"] != "local_import_workflow_receipt":
        raise ValueError("handoff import workflow receipt posture is unsupported")
    if receipt["import_workflow_policy"] != _EXPECTED_POLICY:
        raise ValueError("handoff import workflow receipt policy is unsupported")

    workflow = _require_mapping(receipt["workflow"], "handoff import workflow receipt.workflow")
    review_state = _require_mapping(
        receipt["review_state"],
        "handoff import workflow receipt.review_state",
    )
    package = _require_mapping(receipt["package"], "handoff import workflow receipt.package")
    preflight = _require_mapping(
        receipt["preflight"],
        "handoff import workflow receipt.preflight",
    )

    final_state = _read_public_id(review_state, "final_state", "review_state.final_state")
    workflow_classification = _read_public_id(
        workflow,
        "classification",
        "workflow.classification",
    )
    if final_state != workflow_classification:
        raise ValueError("handoff import workflow receipt final state is inconsistent")

    operator_decision = _read_public_id(
        review_state,
        "operator_decision",
        "review_state.operator_decision",
    )
    if operator_decision not in _DECISIONS:
        raise ValueError("handoff import workflow receipt operator decision is unsupported")
    operator_reason = _parse_operator_reason(review_state.get("operator_reason"))
    if operator_decision == "approved_for_storage_acceptance":
        if operator_reason is not None:
            raise ValueError("approved import workflow receipt must not carry operator_reason")
    else:
        _validate_operator_reason(operator_reason)

    mutation_approved = _read_bool(
        review_state,
        "mutation_approved",
        "review_state.mutation_approved",
    )
    if mutation_approved != (operator_decision == "approved_for_storage_acceptance"):
        raise ValueError("handoff import workflow receipt mutation approval is inconsistent")

    storage_acceptance = receipt["storage_acceptance"]
    storage_acceptance_performed = _storage_acceptance_performed(
        storage_acceptance,
        mutation_approved=mutation_approved,
        final_state=final_state,
    )

    return HandoffImportWorkflowReceiptSummary(
        package_id=_read_public_id(package, "package_id", "package.package_id"),
        measurement_ids=_read_measurement_ids(package),
        final_state=final_state,
        next_action=_read_public_id(review_state, "next_action", "review_state.next_action"),
        operator_decision=operator_decision,
        operator_reason=operator_reason,
        mutation_approved=mutation_approved,
        preflight_classification=_read_public_id(
            preflight,
            "classification",
            "preflight.classification",
        ),
        storage_acceptance_performed=storage_acceptance_performed,
    )


def _validate_against_preflight(
    *,
    request: HandoffImportWorkflowRequest,
    preflight: HandoffAcceptancePreflightRun,
) -> None:
    if request.requested_package_id != preflight.import_plan.package.package_id:
        raise ValueError("import workflow package id must match acceptance preflight")


def _validate_roots_against_preflight(
    *,
    package_dir: str | Path,
    storage_root: str | Path,
    preflight: HandoffAcceptancePreflightRun,
) -> None:
    if str(Path(package_dir).resolve()) != preflight.package_dir:
        raise ValueError("import workflow package_dir must match acceptance preflight")
    if str(Path(storage_root).resolve()) != preflight.storage_root:
        raise ValueError("import workflow storage_root must match acceptance preflight")


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _read_public_id(source: dict[str, Any], key: str, owner: str) -> str:
    return validate_public_identifier(source.get(key), owner)


def _read_bool(source: dict[str, Any], key: str, owner: str) -> bool:
    value = source.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{owner} must be a boolean")
    return value


def _read_measurement_ids(package: dict[str, Any]) -> tuple[str, ...]:
    measurement_ids = package.get("measurement_ids")
    if not isinstance(measurement_ids, list):
        raise ValueError("package.measurement_ids must be a list")
    return tuple(
        validate_public_identifier(item, "package.measurement_ids item") for item in measurement_ids
    )


def _storage_acceptance_performed(
    storage_acceptance: Any,
    *,
    mutation_approved: bool,
    final_state: str,
) -> bool:
    if not mutation_approved:
        if storage_acceptance is not None:
            raise ValueError(
                "non-approved import workflow receipt must not carry storage_acceptance"
            )
        return False
    storage_receipt = _require_mapping(
        storage_acceptance,
        "handoff import workflow receipt.storage_acceptance",
    )
    acceptance = _require_mapping(
        storage_receipt.get("acceptance"),
        "handoff import workflow receipt.storage_acceptance.acceptance",
    )
    performed = _read_bool(
        acceptance,
        "performed",
        "storage_acceptance.acceptance.performed",
    )
    if final_state == "accepted_into_storage" and not performed:
        raise ValueError("accepted import workflow receipt must report performed storage")
    if final_state != "accepted_into_storage" and performed:
        raise ValueError("blocked import workflow receipt must not report performed storage")
    return performed


def _parse_source(
    source: dict[str, Any],
) -> tuple[HandoffImportWorkflowRequest, dict[str, Any]]:
    source = _require_mapping(source, "handoff import workflow source")
    _require_keys(
        source,
        {
            "import_workflow_schema",
            "import_workflow_policy",
            "acceptance_preflight_source",
            "import_workflow_request",
        },
        "handoff import workflow source",
    )
    if source["import_workflow_schema"] != _EXPECTED_SCHEMA:
        raise ValueError("import_workflow_schema is unsupported")
    if source["import_workflow_policy"] != _EXPECTED_POLICY:
        raise ValueError("import_workflow_policy is unsupported")
    request = _parse_request(source["import_workflow_request"])
    preflight_source = _require_mapping(
        source["acceptance_preflight_source"],
        "acceptance_preflight_source",
    )
    return request, copy.deepcopy(preflight_source)


def _parse_request(source: Any) -> HandoffImportWorkflowRequest:
    request = _require_mapping(source, "import_workflow_request")
    _require_keys(
        request,
        {
            "request_id",
            "requested_package_id",
            "operator_decision",
            "operator_reason",
            "storage_acceptance_request",
        },
        "import_workflow_request",
    )
    storage_acceptance_request = _parse_optional_storage_request(
        request["storage_acceptance_request"]
    )
    return HandoffImportWorkflowRequest(
        request_id=validate_public_identifier(
            request["request_id"],
            "import_workflow_request.request_id",
        ),
        requested_package_id=validate_public_identifier(
            request["requested_package_id"],
            "import_workflow_request.requested_package_id",
        ),
        operator_decision=validate_public_identifier(
            request["operator_decision"],
            "import_workflow_request.operator_decision",
        ),
        operator_reason=_parse_operator_reason(request["operator_reason"]),
        storage_acceptance_request=storage_acceptance_request,
    )


def _parse_operator_reason(source: Any) -> str | None:
    if source is None:
        return None
    if not isinstance(source, str):
        raise ValueError("import_workflow_request.operator_reason must be a string")
    return _validate_operator_reason(source)


def _validate_operator_reason(reason: str | None) -> str:
    if reason is None:
        raise ValueError("rejected or needs-review import workflow requires operator_reason")
    if not reason.strip():
        raise ValueError("import workflow operator_reason must not be empty")
    if len(reason) > 500:
        raise ValueError("import workflow operator_reason must be at most 500 characters")
    if any(ord(character) < 32 for character in reason):
        raise ValueError("import workflow operator_reason must be single-line text")
    return reason


def _parse_optional_storage_request(source: Any) -> HandoffStorageAcceptanceRequest | None:
    if source is None:
        return None
    request = _require_mapping(source, "storage_acceptance_request")
    _require_keys(
        request,
        {
            "request_id",
            "approval_state",
            "requested_package_id",
            "approved_destinations",
        },
        "storage_acceptance_request",
    )
    if request["approval_state"] != "approved":
        raise ValueError("handoff import workflow requires approved storage request")
    return HandoffStorageAcceptanceRequest(
        request_id=validate_public_identifier(
            request["request_id"],
            "storage_acceptance_request.request_id",
        ),
        requested_package_id=validate_public_identifier(
            request["requested_package_id"],
            "storage_acceptance_request.requested_package_id",
        ),
        approved_destinations=_parse_destinations(request["approved_destinations"]),
    )


def _parse_destinations(source: Any) -> tuple[HandoffAcceptanceDestination, ...]:
    if not isinstance(source, list):
        raise ValueError("storage acceptance destinations must be a list")
    if not source:
        raise ValueError("storage acceptance destinations must not be empty")
    destinations = tuple(_parse_destination(item) for item in source)
    measurement_ids = [item.measurement_record_id for item in destinations]
    if len(set(measurement_ids)) != len(measurement_ids):
        raise ValueError("storage acceptance destinations measurement ids must be unique")
    destination_record_ids = [item.destination_record_id for item in destinations]
    if len(set(destination_record_ids)) != len(destination_record_ids):
        raise ValueError("storage acceptance destinations record ids must be unique")
    return destinations


def _parse_destination(source: Any) -> HandoffAcceptanceDestination:
    destination = _require_mapping(source, "storage acceptance destination")
    _require_keys(
        destination,
        {
            "measurement_record_id",
            "destination_record_id",
            "record_dir",
            "primary_data_path",
            "manifest_path",
            "storage_schema",
        },
        "storage acceptance destination",
    )
    record_dir = validate_relative_path(
        destination["record_dir"],
        "storage acceptance destination record_dir",
    )
    primary_data_path = validate_strict_child_path(
        destination["primary_data_path"],
        record_dir,
        "storage acceptance destination primary_data_path",
    )
    manifest_path = validate_strict_child_path(
        destination["manifest_path"],
        record_dir,
        "storage acceptance destination manifest_path",
    )
    if primary_data_path == manifest_path:
        raise ValueError("storage acceptance destination paths must be unique")
    storage_schema = validate_public_identifier(
        destination["storage_schema"],
        "storage acceptance destination storage_schema",
    )
    if storage_schema != "measurement_record_directory_candidate_v0":
        raise ValueError("storage acceptance destination storage_schema is unsupported")
    return HandoffAcceptanceDestination(
        measurement_record_id=validate_public_identifier(
            destination["measurement_record_id"],
            "storage acceptance destination measurement_record_id",
        ),
        destination_record_id=validate_public_identifier(
            destination["destination_record_id"],
            "storage acceptance destination destination_record_id",
        ),
        record_dir=record_dir,
        primary_data_path=primary_data_path,
        manifest_path=manifest_path,
        storage_schema=storage_schema,
    )
