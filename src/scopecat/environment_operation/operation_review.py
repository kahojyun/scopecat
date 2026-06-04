"""Route-local environment operation review projections."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from scopecat.environment_operation.uv_sync import UvSyncFinding, UvSyncIntent, UvSyncResult

SUCCESS_STATUS = "uv_sync_completed_success"


@dataclass(frozen=True)
class EnvironmentOperationFinding:
    """Review finding surfaced by the environment operation review prototype."""

    code: str
    severity: str
    basis: str
    source: str

    @classmethod
    def from_child_finding(cls, finding: UvSyncFinding) -> EnvironmentOperationFinding:
        return cls(
            code=finding.code,
            severity=finding.severity,
            basis=finding.basis,
            source="uv_sync_result",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "basis": self.basis,
            "source": self.source,
        }


@dataclass(frozen=True, init=False)
class EnvironmentOperationReview:
    """Local review projection for one selected environment operation result."""

    review_id: str
    _intent_ref: dict[str, Any] = field(repr=False)
    _result_ref: dict[str, Any] = field(repr=False)
    review_status: str
    findings: tuple[EnvironmentOperationFinding, ...]

    def __init__(
        self,
        *,
        review_id: str,
        intent_ref: dict[str, Any],
        result_ref: dict[str, Any],
        review_status: str,
        findings: tuple[EnvironmentOperationFinding, ...],
    ) -> None:
        object.__setattr__(self, "review_id", review_id)
        object.__setattr__(self, "_intent_ref", copy.deepcopy(intent_ref))
        object.__setattr__(self, "_result_ref", copy.deepcopy(result_ref))
        object.__setattr__(self, "review_status", review_status)
        object.__setattr__(self, "findings", tuple(findings))

    @property
    def intent_ref(self) -> dict[str, Any]:
        return copy.deepcopy(self._intent_ref)

    @property
    def result_ref(self) -> dict[str, Any]:
        return copy.deepcopy(self._result_ref)

    def to_dict(self) -> dict[str, Any]:
        intent_ref = self.intent_ref
        result_ref = self.result_ref
        return {
            "operation_review_request": {
                "review_id": self.review_id,
                "expected_manager": "uv",
                "expected_operation": "sync",
                "intent_request_id": intent_ref["request_id"],
                "sync_result_id": result_ref["result_id"],
            },
            "sync_intent_ref": intent_ref,
            "sync_result_ref": result_ref,
            "operation_review_status": self.review_status,
            "operation_review_findings": [finding.to_dict() for finding in self.findings],
        }


def review_uv_sync_operation(
    intent: UvSyncIntent,
    result: UvSyncResult,
    *,
    review_id: str | None = None,
) -> EnvironmentOperationReview:
    """Review one typed route-local uv sync execution result."""

    intent_ref = intent.to_result_intent_ref()
    result_ref = _result_ref(result)
    findings = tuple(_operation_findings(intent, intent_ref, result, result_ref))
    return EnvironmentOperationReview(
        review_id=review_id or f"{result_ref['result_id']}.review",
        intent_ref=intent_ref,
        result_ref=result_ref,
        review_status=_review_status(result.result_status, findings),
        findings=findings,
    )


def _result_ref(result: UvSyncResult) -> dict[str, Any]:
    command_result = result.command_result
    intent_ref = result.intent_ref
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
        "exit_code": _require_optional_int(command_result, "exit_code", "uv sync command result"),
        "result_status": result.result_status,
        "result_findings": [finding.to_dict() for finding in result.findings],
    }


def _operation_findings(
    intent: UvSyncIntent,
    intent_ref: dict[str, Any],
    result: UvSyncResult,
    result_ref: dict[str, Any],
) -> list[EnvironmentOperationFinding]:
    findings = []
    findings.extend(_alignment_findings(intent, intent_ref, result_ref))
    for child_finding in result.findings:
        findings.append(EnvironmentOperationFinding.from_child_finding(child_finding))
    if result.result_status != SUCCESS_STATUS:
        findings.append(
            EnvironmentOperationFinding(
                code="uv_sync_result_not_success",
                severity="review",
                basis="The selected uv sync execution result did not report success.",
                source="uv_sync_result",
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
            )
        )
    if result_intent != intent_ref:
        findings.append(
            _finding(
                "sync_result_intent_ref_mismatch",
                "The selected uv sync result intent reference does not match the selected intent.",
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
            )
        )
    return findings


def _finding(code: str, basis: str) -> EnvironmentOperationFinding:
    return EnvironmentOperationFinding(
        code=code,
        severity="review",
        basis=basis,
        source="operation_review_alignment",
    )


def _review_status(result_status: str, findings: tuple[EnvironmentOperationFinding, ...]) -> str:
    if findings:
        return "operation_review_has_findings"
    if result_status == SUCCESS_STATUS:
        return "uv_sync_completed_success_reviewed"
    return "operation_review_has_findings"


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


def _require_optional_int(value: dict[str, Any], key: str, owner: str) -> int | None:
    item = value.get(key)
    if item is None:
        return None
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{owner} {key} must be an integer or null")
    return item
