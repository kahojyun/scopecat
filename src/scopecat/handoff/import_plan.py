"""Non-mutating import plan for reviewed handoff packages."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier
from scopecat.handoff.errors import promote_handoff_contract_error
from scopecat.handoff.package import HandoffLinkedContext, HandoffMeasurement, HandoffPackage
from scopecat.handoff.receiving import HandoffReceivingGateRun


@dataclass(frozen=True)
class HandoffImportPlanRequest:
    """Approved non-mutating import-plan request."""

    request_id: str
    requested_package_id: str
    measurement_selection: str
    requested_measurement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "import_plan_request.request_id")
        validate_public_identifier(
            self.requested_package_id,
            "import_plan_request.requested_package_id",
        )
        validate_public_identifier(
            self.measurement_selection,
            "import_plan_request.measurement_scope.selection",
        )
        if self.measurement_selection == "all_measurements":
            if self.requested_measurement_ids:
                raise ValueError("all_measurements scope must not carry measurement ids")
            return
        if self.measurement_selection != "selected_measurements":
            raise ValueError("measurement scope selection is unsupported")
        if not self.requested_measurement_ids:
            raise ValueError("measurement_record_ids must not be empty")
        for item in self.requested_measurement_ids:
            validate_public_identifier(item, "measurement_record_ids item")
        if len(set(self.requested_measurement_ids)) != len(self.requested_measurement_ids):
            raise ValueError("measurement_record_ids must be unique")

    def measurement_ids_for(self, package: HandoffPackage) -> tuple[str, ...]:
        if self.requested_package_id != package.package_id:
            raise ValueError("requested package id must match opened package")
        if self.measurement_selection == "all_measurements":
            return package.measurement_ids
        if self.measurement_selection != "selected_measurements":
            raise ValueError("measurement scope selection is unsupported")
        missing = set(self.requested_measurement_ids) - set(package.measurement_ids)
        if missing:
            raise ValueError("requested measurement ids must exist in opened package")
        return self.requested_measurement_ids

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "request_id": self.request_id,
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
            },
        }


@dataclass(frozen=True)
class HandoffLinkedContextImportPlan:
    """Reference-only linked-context handling for the import plan."""

    linked_context: HandoffLinkedContext

    def to_dict(self) -> dict[str, Any]:
        result = {
            "link_id": self.linked_context.link_id,
            "kind": self.linked_context.kind,
            "action": "keep_reference_only",
            "materialization": self.linked_context.materialization,
            "linked_measurement_record_ids": list(
                self.linked_context.linked_measurement_record_ids
            ),
        }
        if self.linked_context.context_reference is not None:
            result["context_reference"] = copy.deepcopy(self.linked_context.context_reference)
        return result


@dataclass(frozen=True)
class HandoffImportPlanRun:
    """Read-only import-plan result for a receiving-reviewed package."""

    request: HandoffImportPlanRequest
    package: HandoffPackage
    receiving_gate: HandoffReceivingGateRun
    measurement_plans: tuple[HandoffMeasurementImportPlan, ...]
    linked_context_plans: tuple[HandoffLinkedContextImportPlan, ...]

    @property
    def import_plan_allowed(self) -> bool:
        return self.receiving_gate.acceptance_allowed

    @property
    def classification(self) -> str:
        if self.import_plan_allowed:
            return "ready_for_import_acceptance_decision"
        return "blocked_before_import_acceptance"

    @property
    def block_reason(self) -> str | None:
        return _import_plan_block_reason(
            import_plan_allowed=self.import_plan_allowed,
            receiving_gate_classification=self.receiving_gate.classification,
            receiving_block_reason=self.receiving_gate.block_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_import_plan_receipt",
            "classification": self.classification,
            "block_reason": self.block_reason,
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
            },
        }


def build_import_plan(
    request: HandoffImportPlanRequest,
    *,
    receiving_gate: HandoffReceivingGateRun,
) -> HandoffImportPlanRun:
    """Build an import plan from typed route-local prior workflow state."""

    try:
        return _build_import_plan_run(request, receiving_gate=receiving_gate)
    except ValueError as exc:
        raise promote_handoff_contract_error(exc, operation="build_import_plan") from exc


def _build_import_plan_run(
    request: HandoffImportPlanRequest,
    *,
    receiving_gate: HandoffReceivingGateRun,
) -> HandoffImportPlanRun:
    """Build an import plan result from typed prior state and local receipt."""

    package = receiving_gate.package
    measurement_plans: tuple[HandoffMeasurementImportPlan, ...] = ()
    linked_context_plans: tuple[HandoffLinkedContextImportPlan, ...] = ()
    if receiving_gate.acceptance_allowed:
        selected_measurement_ids = request.measurement_ids_for(package)
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
    )


def _import_plan_block_reason(
    *,
    import_plan_allowed: bool,
    receiving_gate_classification: str,
    receiving_block_reason: str | None,
) -> str | None:
    if import_plan_allowed:
        return None
    if receiving_block_reason is not None:
        return receiving_block_reason
    if receiving_gate_classification != "ready_for_acceptance_mutation":
        return "receiving_gate_not_ready"
    return "import_plan_not_ready"
