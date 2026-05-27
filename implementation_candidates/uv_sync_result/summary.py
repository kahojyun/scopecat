"""Declared uv sync result implementation candidate.

This module records a bounded external ``uv sync`` result and checks it against
a prior command intent. It does not execute processes, inspect filesystems,
read manifests or lockfiles, parse dependency output, inspect runtimes, import
code, execute selected code, probe hardware, or claim runnable readiness.
"""

from __future__ import annotations

from typing import Any

from implementation_candidates.uv_sync_result.contracts import (
    POLICY_ATTENTION_MATRIX,
    UvSyncResultContract,
    validate_uv_sync_result_contract,
)


def build_uv_sync_result_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a side-effect-free uv sync result summary."""
    contract = validate_uv_sync_result_contract(source)
    findings = _result_findings(contract)
    return {
        "uv_sync_result_policy": contract.policy.to_summary(),
        "uv_sync_intent_ref": contract.intent.to_summary(),
        "command_result": contract.result.to_summary(),
        "result_status": _result_status(contract, findings),
        "result_findings": findings,
        "attention": _attention(contract.policy.values),
    }


def _result_status(contract: UvSyncResultContract, findings: list[dict[str, str]]) -> str:
    if any(finding["code"] == "result_command_mismatch" for finding in findings):
        return "result_requires_review"
    if contract.result.execution_state == "not_run":
        return "external_sync_not_run"
    if contract.result.execution_state == "completed_failed":
        return "external_sync_reported_failure"
    return "external_sync_reported_success"


def _result_findings(contract: UvSyncResultContract) -> list[dict[str, str]]:
    findings = []
    if _command_mismatch(contract):
        findings.append(
            _finding(
                "result_command_mismatch",
                "Declared uv sync result command does not match the approved command intent.",
                "external_command_matches_approved_intent",
            )
        )
    if contract.result.execution_state == "completed_failed":
        findings.append(
            _finding(
                "uv_sync_reported_failure",
                "External uv sync result reports a non-zero exit code.",
                "synchronized_or_installed_environment",
            )
        )
    if contract.result.execution_state == "not_run":
        findings.append(
            _finding(
                "uv_sync_not_run",
                "External uv sync result declares that the command was not run.",
                "synchronized_or_installed_environment",
            )
        )
    return findings


def _command_mismatch(contract: UvSyncResultContract) -> bool:
    return (
        contract.result.manager != contract.intent.command_manager
        or contract.result.operation != contract.intent.operation
        or contract.result.working_directory != contract.intent.working_directory
        or contract.result.argv != contract.intent.argv
    )


def _finding(code: str, basis: str, does_not_claim: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _attention(policy: dict[str, str]) -> list[dict[str, str]]:
    rows = []
    for row in POLICY_ATTENTION_MATRIX:
        if policy[row["policy_key"]] == row["policy_value"]:
            rows.append(dict(row))
    return rows
