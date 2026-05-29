"""Route-local environment operation review projections."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.environment_operation.uv_sync import UvSyncIntent

SUCCESS_STATUS = "uv_sync_completed_success"


@dataclass(frozen=True)
class EnvironmentOperationFinding:
    """Review finding surfaced by the environment operation review prototype."""

    code: str
    severity: str
    basis: str
    source: str
    does_not_claim: str

    @classmethod
    def from_child_finding(cls, finding: dict[str, Any]) -> EnvironmentOperationFinding:
        if not isinstance(finding, dict):
            raise ValueError("result finding must be an object")
        return cls(
            code=_require_text(finding, "code", "result finding"),
            severity=_require_text(finding, "severity", "result finding"),
            basis=_require_text(finding, "basis", "result finding"),
            source="uv_sync_result",
            does_not_claim=_require_text(finding, "does_not_claim", "result finding"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "basis": self.basis,
            "source": self.source,
            "does_not_claim": self.does_not_claim,
        }


@dataclass(frozen=True)
class EnvironmentOperationReview:
    """Local review projection for one selected environment operation result."""

    review_id: str
    intent_ref: dict[str, Any]
    result_ref: dict[str, Any]
    review_status: str
    findings: tuple[EnvironmentOperationFinding, ...]
    attention: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment_operation_review_policy": {
                "summary_policy": "review_summary",
                "review_authority": "route_local_uv_sync_execution_review",
                "manager_scope": "uv_only",
                "process_execution": "already_recorded_not_performed_by_review",
                "dependency_sync_verification": "not_performed",
                "package_install_verification": "not_performed",
                "runtime_probe": "not_performed",
                "code_import_execution": "not_performed",
                "hardware_probe": "not_performed",
                "run_blocking_decision": "not_made",
                "readiness_claim": "not_claimed",
            },
            "operation_review_request": {
                "review_id": self.review_id,
                "expected_manager": "uv",
                "expected_operation": "sync",
                "intent_request_id": self.intent_ref["request_id"],
                "sync_result_id": self.result_ref["result_id"],
            },
            "sync_intent_ref": copy.deepcopy(self.intent_ref),
            "sync_result_ref": copy.deepcopy(self.result_ref),
            "operation_review_status": self.review_status,
            "operation_review_findings": [finding.to_dict() for finding in self.findings],
            "attention": [copy.deepcopy(item) for item in self.attention],
        }


def review_uv_sync_operation(
    intent: UvSyncIntent,
    result_summary: dict[str, Any],
    *,
    review_id: str | None = None,
) -> EnvironmentOperationReview:
    """Review one route-local uv sync execution result summary."""

    parsed = _parse_result_summary(result_summary)
    intent_ref = intent.to_result_intent_ref()
    result_ref = _result_ref(parsed)
    findings = tuple(_operation_findings(intent, intent_ref, parsed, result_ref))
    return EnvironmentOperationReview(
        review_id=review_id or f"{result_ref['result_id']}.review",
        intent_ref=intent_ref,
        result_ref=result_ref,
        review_status=_review_status(parsed["result_status"], findings),
        findings=findings,
        attention=tuple(_attention()),
    )


def _parse_result_summary(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("uv sync result summary must be an object")
    for key in (
        "uv_sync_result_policy",
        "uv_sync_intent_ref",
        "command_result",
        "result_status",
        "result_findings",
    ):
        if key not in value:
            raise ValueError(f"uv sync result summary must include {key}")
    intent_ref = _require_mapping(value, "uv_sync_intent_ref", "uv sync result summary")
    command_result = _require_mapping(value, "command_result", "uv sync result summary")
    result_findings = value["result_findings"]
    if not isinstance(result_findings, list):
        raise ValueError("uv sync result summary result_findings must be a list")
    return {
        "intent_ref": intent_ref,
        "command_result": command_result,
        "result_status": _require_text(value, "result_status", "uv sync result summary"),
        "result_findings": [copy.deepcopy(item) for item in result_findings],
    }


def _result_ref(parsed: dict[str, Any]) -> dict[str, Any]:
    command_result = parsed["command_result"]
    intent_ref = parsed["intent_ref"]
    command_intent = _require_mapping(intent_ref, "command_intent", "uv sync intent ref")
    return {
        "result_id": _require_text(command_result, "result_id", "uv sync command result"),
        "intent_request_id": _require_text(
            command_result, "intent_request_id", "uv sync command result"
        ),
        "approval_id": _require_text(command_result, "approval_id", "uv sync command result"),
        "result_intent_ref": {
            "request_id": _require_text(intent_ref, "request_id", "uv sync intent ref"),
            "approval_id": _require_text(intent_ref, "approval_id", "uv sync intent ref"),
            "expected_manager": _require_text(intent_ref, "expected_manager", "uv sync intent ref"),
            "working_directory": _require_text(
                intent_ref, "working_directory", "uv sync intent ref"
            ),
            "command_intent": {
                "manager": _require_text(command_intent, "manager", "uv sync intent command"),
                "operation": _require_text(command_intent, "operation", "uv sync intent command"),
                "working_directory": _require_text(
                    command_intent, "working_directory", "uv sync intent command"
                ),
                "argv": _require_text_list(command_intent, "argv", "uv sync intent command"),
                "does_not_claim": _require_text(
                    command_intent, "does_not_claim", "uv sync intent command"
                ),
            },
        },
        "manager": _require_text(command_result, "manager", "uv sync command result"),
        "operation": _require_text(command_result, "operation", "uv sync command result"),
        "working_directory": _require_text(
            command_result, "working_directory", "uv sync command result"
        ),
        "argv": _require_text_list(command_result, "argv", "uv sync command result"),
        "execution_state": _require_text(
            command_result, "execution_state", "uv sync command result"
        ),
        "exit_code": command_result.get("exit_code"),
        "result_status": parsed["result_status"],
        "result_findings": copy.deepcopy(parsed["result_findings"]),
    }


def _operation_findings(
    intent: UvSyncIntent,
    intent_ref: dict[str, Any],
    parsed: dict[str, Any],
    result_ref: dict[str, Any],
) -> list[EnvironmentOperationFinding]:
    findings = []
    findings.extend(_alignment_findings(intent, intent_ref, result_ref))
    for child_finding in parsed["result_findings"]:
        findings.append(EnvironmentOperationFinding.from_child_finding(child_finding))
    if parsed["result_status"] != SUCCESS_STATUS:
        findings.append(
            EnvironmentOperationFinding(
                code="uv_sync_result_not_success",
                severity="review",
                basis="The selected uv sync execution result did not report success.",
                source="uv_sync_result",
                does_not_claim="synchronized_or_installed_environment",
            )
        )
    return findings


def _alignment_findings(
    intent: UvSyncIntent,
    intent_ref: dict[str, Any],
    result_ref: dict[str, Any],
) -> list[EnvironmentOperationFinding]:
    findings = []
    result_intent = result_ref["result_intent_ref"]
    if (
        result_ref["intent_request_id"] != intent.request_id
        or result_ref["approval_id"] != intent.approval_id
    ):
        findings.append(
            _finding(
                "sync_result_intent_mismatch",
                "The selected uv sync result does not reference the selected intent.",
                "result_belongs_to_selected_intent",
            )
        )
    if result_intent != intent_ref:
        findings.append(
            _finding(
                "sync_result_intent_ref_mismatch",
                "The selected uv sync result intent reference does not match the selected intent.",
                "result_intent_ref_belongs_to_selected_intent",
            )
        )
    if (
        result_ref["manager"] != "uv"
        or result_ref["operation"] != "sync"
        or result_ref["working_directory"] != intent.working_directory
        or tuple(result_ref["argv"]) != intent.argv
    ):
        findings.append(
            _finding(
                "sync_result_command_mismatch",
                "The selected uv sync result command facts do not match the selected intent.",
                "external_command_matches_selected_intent",
            )
        )
    return findings


def _finding(code: str, basis: str, does_not_claim: str) -> EnvironmentOperationFinding:
    return EnvironmentOperationFinding(
        code=code,
        severity="review",
        basis=basis,
        source="operation_review_alignment",
        does_not_claim=does_not_claim,
    )


def _review_status(result_status: str, findings: tuple[EnvironmentOperationFinding, ...]) -> str:
    if findings:
        return "operation_review_has_findings"
    if result_status == SUCCESS_STATUS:
        return "uv_sync_completed_success_with_review_limits"
    return "operation_review_has_findings"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "operation_review_only",
            "severity": "info",
            "basis": "This review composes selected uv sync intent and execution result facts.",
            "does_not_claim": "runtime_readiness_or_run_permission",
        },
        {
            "code": "package_state_not_verified",
            "severity": "review",
            "basis": "The review does not inspect synchronized or installed package state.",
            "does_not_claim": "verified_synchronized_environment",
        },
        {
            "code": "code_execution_not_granted",
            "severity": "review",
            "basis": "The review does not import, load, or execute selected experiment code.",
            "does_not_claim": "execution_permission",
        },
    ]


def _require_mapping(value: dict[str, Any], key: str, owner: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"{owner} {key} must be an object")
    return item


def _require_text(value: dict[str, Any], key: str, owner: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{owner} {key} must be text")
    return item


def _require_text_list(value: dict[str, Any], key: str, owner: str) -> list[str]:
    item = value.get(key)
    if not isinstance(item, list) or not all(isinstance(element, str) for element in item):
        raise ValueError(f"{owner} {key} must be a list of text")
    return list(item)
