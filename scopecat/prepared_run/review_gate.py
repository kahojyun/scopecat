"""Manual prepared-run review gate engineering prototype.

This module composes explicit prior review summaries into one local manual
pre-run review projection. It deliberately does not start runs, control
hardware, write parameters, sync dependencies, mutate workspaces, read storage,
probe runtimes, import or execute code, open GUIs, or define a shared gate
schema.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

EXPECTED_REVIEW_GATE_POLICY = {
    "gate_authority": "explicit_prepared_run_review_composition",
    "input_sources": "explicit_prior_review_summaries",
    "review_scope": "manual_pre_run_context_review",
    "automatic_run_start": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "dependency_resolution": "not_performed",
    "dependency_sync": "not_performed",
    "package_install": "not_performed",
    "runtime_probe": "not_performed",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "workspace_mutation": "not_performed",
    "environment_operation": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "manual_review_state_only",
    "gui_workflow": "not_defined",
    "shared_gate_schema": "not_defined",
}


@dataclass(frozen=True, init=False)
class PreparedRunReviewGateRequest:
    """Typed local request over explicit prior prepared-run review summaries."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> PreparedRunReviewGateRequest:
        """Build the typed local request from the raw-dictionary edge shape."""

        return cls(source=source)

    @property
    def prepared_run_context_id(self) -> str:
        return self._source["review_gate_request"]["prepared_run_context_id"]

    @property
    def measurement_id(self) -> str:
        return self._source["review_gate_request"]["measurement_id"]

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True)
class ReviewItem:
    """One review area state in the local manual pre-run gate."""

    area: str
    state: str
    reason_codes: tuple[str, ...]
    finding_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "area": self.area,
            "state": self.state,
            "reason_codes": list(self.reason_codes),
            "finding_count": self.finding_count,
        }


@dataclass(frozen=True, init=False)
class AggregatedReviewFinding:
    """A child finding carried into the prepared-run review projection."""

    source_area: str
    code: str
    severity: str
    _basis: Any = field(repr=False)
    does_not_claim: str

    def __init__(
        self,
        *,
        source_area: str,
        code: str,
        severity: str,
        basis: Any,
        does_not_claim: str,
    ) -> None:
        object.__setattr__(self, "source_area", source_area)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "_basis", copy.deepcopy(basis))
        object.__setattr__(self, "does_not_claim", does_not_claim)

    @property
    def basis(self) -> Any:
        return copy.deepcopy(self._basis)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_area": self.source_area,
            "code": self.code,
            "severity": self.severity,
            "basis": self.basis,
            "does_not_claim": self.does_not_claim,
        }


@dataclass(frozen=True, init=False)
class PreparedRunReviewGateResult:
    """Local manual pre-run review gate result."""

    _review_gate_policy: dict[str, Any] = field(repr=False)
    _review_gate_request: dict[str, Any] = field(repr=False)
    _gate_decision: dict[str, Any] = field(repr=False)
    _prepared_run_context: dict[str, Any] = field(repr=False)
    review_items: tuple[ReviewItem, ...]
    aggregated_review_findings: tuple[AggregatedReviewFinding, ...]
    _attention: tuple[dict[str, str], ...] = field(repr=False)

    def __init__(
        self,
        *,
        review_gate_policy: dict[str, Any],
        review_gate_request: dict[str, Any],
        gate_decision: dict[str, Any],
        prepared_run_context: dict[str, Any],
        review_items: tuple[ReviewItem, ...],
        aggregated_review_findings: tuple[AggregatedReviewFinding, ...],
        attention: tuple[dict[str, str], ...],
    ) -> None:
        object.__setattr__(self, "_review_gate_policy", copy.deepcopy(review_gate_policy))
        object.__setattr__(self, "_review_gate_request", copy.deepcopy(review_gate_request))
        object.__setattr__(self, "_gate_decision", copy.deepcopy(gate_decision))
        object.__setattr__(self, "_prepared_run_context", copy.deepcopy(prepared_run_context))
        object.__setattr__(self, "review_items", tuple(review_items))
        object.__setattr__(self, "aggregated_review_findings", tuple(aggregated_review_findings))
        object.__setattr__(
            self,
            "_attention",
            tuple(copy.deepcopy(item) for item in attention),
        )

    @property
    def overall_state(self) -> str:
        return self._gate_decision["overall_state"]

    @property
    def review_gate_policy(self) -> dict[str, Any]:
        return copy.deepcopy(self._review_gate_policy)

    @property
    def review_gate_request(self) -> dict[str, Any]:
        return copy.deepcopy(self._review_gate_request)

    @property
    def gate_decision(self) -> dict[str, Any]:
        return copy.deepcopy(self._gate_decision)

    @property
    def prepared_run_context(self) -> dict[str, Any]:
        return copy.deepcopy(self._prepared_run_context)

    @property
    def attention(self) -> tuple[dict[str, str], ...]:
        return tuple(copy.deepcopy(item) for item in self._attention)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_gate_policy": self.review_gate_policy,
            "review_gate_request": self.review_gate_request,
            "gate_decision": self.gate_decision,
            "prepared_run_context": self.prepared_run_context,
            "review_items": [item.to_dict() for item in self.review_items],
            "aggregated_review_findings": [
                finding.to_dict() for finding in self.aggregated_review_findings
            ],
            "attention": [copy.deepcopy(item) for item in self._attention],
        }


def compose_prepared_run_review_gate(
    request: PreparedRunReviewGateRequest,
) -> PreparedRunReviewGateResult:
    """Compose a typed local manual pre-run review gate result."""

    source = request.source
    items = _review_items(source)
    overall_state = _overall_state(items)
    return PreparedRunReviewGateResult(
        review_gate_policy=source["review_gate_policy"],
        review_gate_request=source["review_gate_request"],
        gate_decision={
            "overall_state": overall_state,
            "recommended_action": _recommended_action(overall_state),
            "run_start_claim": "not_claimed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "environment_operation": "not_performed",
            "code_import_execution": "not_performed",
        },
        prepared_run_context=_prepared_context_by_id(source)[request.prepared_run_context_id],
        review_items=items,
        aggregated_review_findings=_aggregated_findings(source),
        attention=_attention(),
    )


def build_prepared_run_review_gate_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for the manual pre-run review gate."""

    request = PreparedRunReviewGateRequest.from_dict(source)
    return compose_prepared_run_review_gate(request).to_dict()


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["review_gate_policy"]
    if set(policy) != set(EXPECTED_REVIEW_GATE_POLICY):
        raise ValueError("prepared-run review gate policy shape")
    for key, expected in EXPECTED_REVIEW_GATE_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"prepared-run review gate policy {key} must be {expected}")


def _prepared_context_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(
        source["prepared_run_context_summary"]["prepared_run_contexts"],
        "prepared_run_context_id",
    )


def _validate_prepared_context_summary(source: dict[str, Any]) -> None:
    summary = source["prepared_run_context_summary"]
    policy = summary["prepared_run_context_policy"]
    for key in (
        "hardware_control",
        "parameter_write_back",
        "setup_mutation",
        "environment_sync",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"prepared run context summary {key} must be not_performed")
    _prepared_context_by_id(source)


def _validate_parameter_gate_summary(source: dict[str, Any]) -> None:
    summary = source["parameter_state_gate_summary"]
    policy = summary["gate_policy"]
    for key in (
        "automatic_run_start",
        "parameter_write_back",
        "hardware_control",
        "fresh_storage_read",
        "catalog_discovery",
        "storage_mutation",
        "environment_sync",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"parameter-state gate summary {key} must be not_performed")
    decision = summary["gate_decision"]
    if decision["run_start_claim"] != "not_claimed":
        raise ValueError("parameter-state gate summary must not claim run start")
    if decision["parameter_write_back"] != "not_performed":
        raise ValueError("parameter-state gate summary must not write parameters")
    if decision["hardware_control"] != "not_performed":
        raise ValueError("parameter-state gate summary must not control hardware")


def _validate_scope_alignment_summary(source: dict[str, Any]) -> None:
    summary = source["scope_alignment_summary"]
    policy = summary["alignment_policy"]
    for key in (
        "automatic_run_start",
        "parameter_write_back",
        "hardware_control",
        "fresh_storage_read",
        "catalog_discovery",
        "setup_mutation",
        "environment_sync",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"scope alignment summary {key} must be not_performed")


def _validate_environment_review_summary(source: dict[str, Any]) -> None:
    summary = source["environment_review_summary"]
    policy = summary["environment_review_bundle_policy"]
    for key in (
        "dependency_resolution",
        "dependency_sync",
        "package_install",
        "runtime_probe",
        "code_import_execution",
        "hardware_probe",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"environment review summary {key} must be not_performed")
    if policy["readiness_claim"] != "not_claimed":
        raise ValueError("environment review summary must not claim readiness")
    if policy["managed_runner"] != "not_defined":
        raise ValueError("environment review summary must not define managed runner")


def _validate_environment_operation_review_summary(source: dict[str, Any]) -> None:
    summary = source.get("environment_operation_review_summary")
    if summary is None:
        return

    policy = summary["environment_operation_review_policy"]
    expected = {
        "summary_policy": "review_summary",
        "bundle_authority": "explicit_prior_environment_operation_summaries",
        "composition_authority": "review_projection_only",
        "filesystem_inspection": "not_performed",
        "manifest_read": "not_performed",
        "lockfile_read": "not_performed",
        "process_execution": "not_performed",
        "dependency_output_parsing": "not_performed",
        "dependency_resolution": "not_performed",
        "dependency_sync": "externally_reported_not_verified_by_scopecat",
        "package_install": "externally_reported_not_verified_by_scopecat",
        "runtime_probe": "not_performed",
        "code_import_execution": "not_performed",
        "hardware_probe": "not_performed",
        "run_blocking_decision": "not_made",
        "readiness_claim": "not_claimed",
        "shared_environment_schema": "not_defined",
    }
    for key, expected_value in expected.items():
        if policy[key] != expected_value:
            raise ValueError(f"environment operation review summary {key} must be {expected_value}")

    status = summary["operation_review_status"]
    findings = summary["operation_review_findings"]
    if status not in {
        "external_sync_reported_success_with_review_limits",
        "operation_review_has_findings",
    }:
        raise ValueError("unsupported environment operation review status")
    if findings and status != "operation_review_has_findings":
        raise ValueError("environment operation findings require operation_review_has_findings")
    if not findings and status == "operation_review_has_findings":
        raise ValueError("operation_review_has_findings requires review findings")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["review_gate_request"]
    prepared_contexts = _prepared_context_by_id(source)
    prepared_context_id = request["prepared_run_context_id"]
    if prepared_context_id not in prepared_contexts:
        raise ValueError("review gate request references missing prepared run context")
    prepared_context = prepared_contexts[prepared_context_id]
    if prepared_context["manual_run_target"]["measurement_id"] != request["measurement_id"]:
        raise ValueError("review gate request measurement_id must match prepared run target")
    if (
        source["parameter_state_gate_summary"]["prepared_run_context"]["prepared_run_context_id"]
        != prepared_context_id
    ):
        raise ValueError("parameter-state gate prepared_run_context_id must match request")
    if (
        source["scope_alignment_summary"]["scope_summary"]["prepared_run_context_id"]
        != prepared_context_id
    ):
        raise ValueError("scope alignment prepared_run_context_id must match request")
    if (
        source["scope_alignment_summary"]["scope_summary"]["measurement_id"]
        != request["measurement_id"]
    ):
        raise ValueError("scope alignment measurement_id must match request")
    for bundle in source["environment_review_summary"]["review_bundles"]:
        if bundle["prepared_run_context_id"] != prepared_context_id:
            raise ValueError("environment review bundle prepared_run_context_id must match request")
    operation_summary = source.get("environment_operation_review_summary")
    if (
        operation_summary is not None
        and operation_summary["operation_review_request"]["prepared_run_context_id"]
        != prepared_context_id
    ):
        raise ValueError("environment operation review prepared_run_context_id must match request")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_prepared_context_summary(source)
    _validate_parameter_gate_summary(source)
    _validate_scope_alignment_summary(source)
    _validate_environment_review_summary(source)
    _validate_environment_operation_review_summary(source)
    _validate_request(source)


def _review_item(
    *,
    area: str,
    state: str,
    reason_codes: list[str],
    finding_count: int,
) -> ReviewItem:
    return ReviewItem(
        area=area,
        state=state,
        reason_codes=tuple(reason_codes),
        finding_count=finding_count,
    )


def _prepared_context_findings(
    source: dict[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    prepared_context_id = source["review_gate_request"]["prepared_run_context_id"]
    return [
        finding
        for finding in source["prepared_run_context_summary"][key]
        if finding["prepared_run_context_id"] == prepared_context_id
    ]


def _required_context_item(source: dict[str, Any]) -> ReviewItem:
    findings = _prepared_context_findings(source, "missing_context_findings")
    return _review_item(
        area="required_context",
        state="blocked_by_required_context" if findings else "ready_for_manual_review",
        reason_codes=[finding["finding"] for finding in findings],
        finding_count=len(findings),
    )


def _workspace_item(source: dict[str, Any]) -> ReviewItem:
    findings = _prepared_context_findings(source, "workspace_context_findings")
    return _review_item(
        area="workspace",
        state="needs_workspace_review" if findings else "ready_for_manual_review",
        reason_codes=[finding["finding"] for finding in findings],
        finding_count=len(findings),
    )


def _parameter_item(source: dict[str, Any]) -> ReviewItem:
    decision = source["parameter_state_gate_summary"]["gate_decision"]
    state_map = {
        "ready_for_manual_run_review": "ready_for_manual_review",
        "needs_parameter_review": "needs_parameter_review",
        "blocked_by_required_parameter_context": "blocked_by_required_context",
    }
    return _review_item(
        area="parameter_state",
        state=state_map[decision["gate_state"]],
        reason_codes=list(decision["reason_codes"]),
        finding_count=len(source["parameter_state_gate_summary"]["review_findings"]),
    )


def _scope_item(source: dict[str, Any]) -> ReviewItem:
    summary = source["scope_alignment_summary"]
    state_map = {
        "scope_alignment_ready": "ready_for_manual_review",
        "scope_alignment_needs_review": "needs_scope_review",
        "scope_alignment_blocked_for_review": "needs_scope_review",
    }
    return _review_item(
        area="scope_alignment",
        state=state_map[summary["classification"]],
        reason_codes=[finding["code"] for finding in summary["review_findings"]],
        finding_count=len(summary["review_findings"]),
    )


def _environment_item(source: dict[str, Any]) -> ReviewItem:
    findings = source["environment_review_summary"]["environment_review_findings"]
    return _review_item(
        area="environment",
        state="needs_environment_review" if findings else "ready_for_manual_review",
        reason_codes=[finding["finding"] for finding in findings],
        finding_count=len(findings),
    )


def _environment_operation_item(source: dict[str, Any]) -> ReviewItem | None:
    summary = source.get("environment_operation_review_summary")
    if summary is None:
        return None

    findings = summary["operation_review_findings"]
    return _review_item(
        area="environment_operation",
        state=("needs_environment_operation_review" if findings else "ready_for_manual_review"),
        reason_codes=[finding["code"] for finding in findings],
        finding_count=len(findings),
    )


def _review_items(source: dict[str, Any]) -> tuple[ReviewItem, ...]:
    items = [
        _required_context_item(source),
        _parameter_item(source),
        _scope_item(source),
        _workspace_item(source),
        _environment_item(source),
    ]
    environment_operation_item = _environment_operation_item(source)
    if environment_operation_item is not None:
        items.append(environment_operation_item)
    return tuple(items)


def _overall_state(items: tuple[ReviewItem, ...]) -> str:
    states = {item.state for item in items}
    if "blocked_by_required_context" in states:
        return "blocked_by_required_context"
    needs_review = sorted(state for state in states if state != "ready_for_manual_review")
    if needs_review:
        return "manual_pre_run_review_needed"
    return "ready_for_manual_review"


def _recommended_action(overall_state: str) -> str:
    if overall_state == "ready_for_manual_review":
        return "present_manual_pre_run_review"
    if overall_state == "blocked_by_required_context":
        return "repair_required_context_before_manual_pre_run_review"
    return "review_flagged_context_areas_before_manual_pre_run_review"


def _finding(
    source_area: str,
    source_finding: dict[str, Any],
    *,
    code_key: str,
) -> AggregatedReviewFinding:
    return AggregatedReviewFinding(
        source_area=source_area,
        code=source_finding[code_key],
        severity="review",
        basis=source_finding["basis"],
        does_not_claim=source_finding["does_not_claim"],
    )


def _aggregated_findings(source: dict[str, Any]) -> tuple[AggregatedReviewFinding, ...]:
    findings = []
    findings.extend(
        _finding("required_context", finding, code_key="finding")
        for finding in _prepared_context_findings(source, "missing_context_findings")
    )
    findings.extend(
        _finding("workspace", finding, code_key="finding")
        for finding in _prepared_context_findings(source, "workspace_context_findings")
    )
    findings.extend(
        _finding("parameter_state", finding, code_key="code")
        for finding in source["parameter_state_gate_summary"]["review_findings"]
    )
    findings.extend(
        _finding("scope_alignment", finding, code_key="code")
        for finding in source["scope_alignment_summary"]["review_findings"]
    )
    findings.extend(
        _finding("environment", finding, code_key="finding")
        for finding in source["environment_review_summary"]["environment_review_findings"]
    )
    operation_summary = source.get("environment_operation_review_summary")
    if operation_summary is not None:
        findings.extend(
            _finding("environment_operation", finding, code_key="code")
            for finding in operation_summary["operation_review_findings"]
        )
    return tuple(findings)


def _attention() -> tuple[dict[str, str], ...]:
    return (
        {
            "code": "manual_review_gate_only",
            "severity": "info",
            "basis": "The gate composes prior review summaries into one manual pre-run review state.",
            "does_not_claim": "run_can_start_or_hardware_safe",
        },
        {
            "code": "no_fresh_observation_or_operation",
            "severity": "review",
            "basis": "The gate does not inspect files, storage, environments, runtimes, or hardware.",
            "does_not_claim": "fresh_readiness_or_integrity_check",
        },
        {
            "code": "parameter_write_back_not_performed",
            "severity": "review",
            "basis": "The gate does not apply selected parameter values.",
            "does_not_claim": "parameter_application",
        },
        {
            "code": "execution_not_granted",
            "severity": "review",
            "basis": "The gate does not import code, sync dependencies, or start a run.",
            "does_not_claim": "execution_permission",
        },
        {
            "code": "environment_operation_review_optional",
            "severity": "info",
            "basis": "An environment-operation review bundle may be consumed as prior review evidence when present.",
            "does_not_claim": "environment_operation_performed_by_gate",
        },
    )
