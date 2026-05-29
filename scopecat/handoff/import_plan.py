"""Non-mutating import plan for reviewed handoff packages."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier
from scopecat.handoff.inspect import write_inspection_artifact
from scopecat.handoff.package import HandoffLinkedContext, HandoffMeasurement, HandoffPackage
from scopecat.handoff.receiving import HandoffReceivingGateRun, run_receiving_gate

_EXPECTED_SCHEMA = "scopecat.handoff_import_plan.v0"
_EXPECTED_POLICY = {
    "workflow_authority": "approved_import_planning_request",
    "package_open": "read_only_declared_preview",
    "inspection_artifact": "optional_local_static_review_artifact",
    "receiving_gate": "required_before_import_plan",
    "import_plan": "non_mutating_measurement_acceptance_plan",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "archive_handling": "not_performed",
    "signature_validation": "not_performed",
    "conflict_detection": "not_performed",
    "final_storage_schema": "not_defined",
    "rollback": "not_defined",
}


@dataclass(frozen=True)
class HandoffImportPlanRequest:
    """Approved non-mutating import-plan request."""

    request_id: str
    requested_package_id: str
    measurement_selection: str
    requested_measurement_ids: tuple[str, ...] = ()

    def measurement_ids_for(self, package: HandoffPackage) -> tuple[str, ...]:
        if self.requested_package_id != package.package_id:
            raise ValueError("requested package id must match opened package")
        if self.measurement_selection == "all_measurements":
            return package.measurement_ids
        missing = set(self.requested_measurement_ids) - set(package.measurement_ids)
        if missing:
            raise ValueError("requested measurement ids must exist in opened package")
        return self.requested_measurement_ids

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "request_id": self.request_id,
            "approval_state": "approved",
            "requested_package_id": self.requested_package_id,
            "measurement_scope": {
                "selection": self.measurement_selection,
            },
        }
        if self.measurement_selection == "selected_measurements":
            result["measurement_scope"]["measurement_record_ids"] = list(
                self.requested_measurement_ids
            )
        return result


@dataclass(frozen=True)
class HandoffMeasurementImportPlan:
    """One non-mutating planned measurement import entry."""

    measurement: HandoffMeasurement

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurement_record_id": self.measurement.measurement_record_id,
            "action": "plan_import_measurement_record",
            "source": {
                "package_path": self.measurement.primary_package_path,
                "format": self.measurement.primary_format,
                "observed_size_bytes": self.measurement.observed_size_bytes,
                "integrity_check": self.measurement.integrity_check,
            },
            "destination": {
                "storage_schema": "not_assigned",
                "storage_path": "not_assigned",
                "conflict_resolution": "not_decided",
            },
            "requires_next_decision": [
                "storage_schema",
                "destination_record_identity",
                "conflict_policy",
                "acceptance_mutation",
                "rollback_policy",
            ],
        }


@dataclass(frozen=True)
class HandoffLinkedContextImportPlan:
    """Reference-only linked-context handling for the import plan."""

    linked_context: HandoffLinkedContext

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.linked_context.link_id,
            "kind": self.linked_context.kind,
            "action": "keep_reference_only",
            "materialization": self.linked_context.materialization,
            "linked_measurement_record_ids": list(
                self.linked_context.linked_measurement_record_ids
            ),
            "does_not_claim": "linked_context_payload_import",
        }


@dataclass(frozen=True)
class HandoffImportPlanRun:
    """Read-only import-plan result for a receiving-reviewed package."""

    request: HandoffImportPlanRequest
    package: HandoffPackage
    receiving_gate: HandoffReceivingGateRun
    measurement_plans: tuple[HandoffMeasurementImportPlan, ...]
    linked_context_plans: tuple[HandoffLinkedContextImportPlan, ...]
    inspection_receipt: dict[str, Any] | None = None

    @property
    def import_plan_allowed(self) -> bool:
        return self.receiving_gate.acceptance_allowed

    @property
    def classification(self) -> str:
        if self.import_plan_allowed:
            return "ready_for_import_acceptance_decision"
        return "blocked_before_import_acceptance"

    def to_dict(self) -> dict[str, Any]:
        steps = [
            "open_package",
            "run_receiving_gate",
            *(["write_inspection_artifact"] if self.inspection_receipt is not None else []),
            "build_import_plan",
        ]
        return {
            "artifact_posture": "local_import_plan_receipt",
            "import_plan_policy": copy.deepcopy(_EXPECTED_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": steps,
                "does_not_claim": [
                    "storage_mutation",
                    "package_import_or_acceptance",
                    "archive_extraction",
                    "signature_or_authenticity_validation",
                    "conflict_detection",
                    "final_storage_schema",
                    "rollback_policy",
                ],
            },
            "request": self.request.to_dict(),
            "package": {
                "package_id": self.package.package_id,
                "display_name": self.package.display_name,
                "preview_classification": self.package.preview_classification,
                "measurement_ids": list(self.package.measurement_ids),
            },
            "receiving_gate": {
                "classification": self.receiving_gate.classification,
                "acceptance_allowed": self.receiving_gate.acceptance_allowed,
                "integrity_classification": self.receiving_gate.integrity_report.classification,
            },
            "import_plan": {
                "allowed": self.import_plan_allowed,
                "planned_measurement_imports": [plan.to_dict() for plan in self.measurement_plans],
                "linked_context": [plan.to_dict() for plan in self.linked_context_plans],
                "next_required_decision": (
                    "choose_storage_acceptance_conflict_and_rollback_policy"
                    if self.import_plan_allowed
                    else "resolve_receiving_gate_before_import_acceptance"
                ),
            },
            "inspection_receipt": copy.deepcopy(self.inspection_receipt),
        }


def run_import_plan(
    source: dict[str, Any],
    *,
    package_dir: str | Path,
    inspection_output_dir: str | Path | None = None,
    overwrite_inspection: bool = False,
) -> HandoffImportPlanRun:
    """Build a non-mutating import plan for a reviewed handoff package."""

    request, receiving_gate_source = _parse_source(source)
    receiving_gate = run_receiving_gate(receiving_gate_source, package_dir=package_dir)
    inspection_receipt = None
    if inspection_output_dir is not None:
        inspection_receipt = write_inspection_artifact(
            receiving_gate.package,
            output_dir=Path(inspection_output_dir),
            overwrite=overwrite_inspection,
        )
    return _build_import_plan_run(
        request,
        receiving_gate=receiving_gate,
        inspection_receipt=inspection_receipt,
    )


def build_import_plan(
    request: HandoffImportPlanRequest,
    *,
    receiving_gate: HandoffReceivingGateRun,
) -> HandoffImportPlanRun:
    """Build an import plan from typed route-local prior workflow state."""

    return _build_import_plan_run(request, receiving_gate=receiving_gate)


def _build_import_plan_run(
    request: HandoffImportPlanRequest,
    *,
    receiving_gate: HandoffReceivingGateRun,
    inspection_receipt: dict[str, Any] | None = None,
) -> HandoffImportPlanRun:
    """Build an import plan result from typed prior state and local receipt."""

    package = receiving_gate.package
    if inspection_receipt is not None:
        _validate_inspection_receipt(inspection_receipt, package_id=package.package_id)
    selected_measurement_ids = request.measurement_ids_for(package)
    measurement_plans: tuple[HandoffMeasurementImportPlan, ...] = ()
    linked_context_plans: tuple[HandoffLinkedContextImportPlan, ...] = ()
    if receiving_gate.acceptance_allowed:
        selected_measurements = tuple(
            package.measurement(item) for item in selected_measurement_ids
        )
        measurement_plans = tuple(
            HandoffMeasurementImportPlan(measurement) for measurement in selected_measurements
        )
        selected_id_set = set(selected_measurement_ids)
        linked_context_plans = tuple(
            HandoffLinkedContextImportPlan(item)
            for item in package.linked_context
            if selected_id_set.intersection(item.linked_measurement_record_ids)
        )
    return HandoffImportPlanRun(
        request=request,
        package=package,
        receiving_gate=receiving_gate,
        measurement_plans=measurement_plans,
        linked_context_plans=linked_context_plans,
        inspection_receipt=inspection_receipt,
    )


def _validate_inspection_receipt(receipt: dict[str, Any], *, package_id: str) -> None:
    if not isinstance(receipt, dict):
        raise ValueError("inspection receipt must be an object")
    if receipt.get("artifact_posture") != "review_summary":
        raise ValueError("inspection receipt posture is unsupported")
    if receipt.get("package_id") != package_id:
        raise ValueError("inspection receipt package_id must match import plan package")
    html_artifact = receipt.get("html_artifact")
    if not isinstance(html_artifact, dict):
        raise ValueError("inspection receipt html_artifact must be an object")
    if html_artifact.get("portable_package_member") is not False:
        raise ValueError("inspection receipt must stay local to review")


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _parse_source(source: dict[str, Any]) -> tuple[HandoffImportPlanRequest, dict[str, Any]]:
    source = _require_mapping(source, "handoff import plan source")
    _require_keys(
        source,
        {
            "import_plan_schema",
            "import_plan_policy",
            "receiving_gate_source",
            "import_plan_request",
        },
        "handoff import plan source",
    )
    if source["import_plan_schema"] != _EXPECTED_SCHEMA:
        raise ValueError("import_plan_schema is unsupported")
    if source["import_plan_policy"] != _EXPECTED_POLICY:
        raise ValueError("import_plan_policy is unsupported")

    receiving_gate_source = _require_mapping(
        source["receiving_gate_source"],
        "receiving_gate_source",
    )
    request = _parse_request(source["import_plan_request"])
    return request, copy.deepcopy(receiving_gate_source)


def _parse_request(source: Any) -> HandoffImportPlanRequest:
    request = _require_mapping(source, "import_plan_request")
    _require_keys(
        request,
        {"request_id", "approval_state", "requested_package_id", "measurement_scope"},
        "import_plan_request",
    )
    if request["approval_state"] != "approved":
        raise ValueError("handoff import planning requires approved request")
    scope = _require_mapping(request["measurement_scope"], "import_plan_request.measurement_scope")
    selection = validate_public_identifier(
        scope.get("selection"),
        "import_plan_request.measurement_scope.selection",
    )
    if selection == "all_measurements":
        _require_keys(
            scope,
            {"selection"},
            "import_plan_request.measurement_scope",
        )
        requested_measurement_ids: tuple[str, ...] = ()
    elif selection == "selected_measurements":
        _require_keys(
            scope,
            {"selection", "measurement_record_ids"},
            "import_plan_request.measurement_scope",
        )
        requested_measurement_ids = _parse_measurement_ids(scope["measurement_record_ids"])
    else:
        raise ValueError("measurement scope selection is unsupported")

    return HandoffImportPlanRequest(
        request_id=validate_public_identifier(
            request["request_id"], "import_plan_request.request_id"
        ),
        requested_package_id=validate_public_identifier(
            request["requested_package_id"],
            "import_plan_request.requested_package_id",
        ),
        measurement_selection=selection,
        requested_measurement_ids=requested_measurement_ids,
    )


def _parse_measurement_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("measurement_record_ids must be a list")
    measurement_ids = tuple(
        validate_public_identifier(item, "measurement_record_ids item") for item in value
    )
    if not measurement_ids:
        raise ValueError("measurement_record_ids must not be empty")
    if len(set(measurement_ids)) != len(measurement_ids):
        raise ValueError("measurement_record_ids must be unique")
    return measurement_ids
