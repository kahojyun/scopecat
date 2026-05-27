"""Environment operation review bundle implementation candidate."""

from __future__ import annotations

from typing import Any

from implementation_candidates.environment_operation_review_bundle.contracts import (
    POLICY_ATTENTION_MATRIX,
    PREFLIGHT_PASSING_STATUS,
    EnvironmentOperationReviewBundleContract,
    validate_environment_operation_review_bundle_contract,
)


def build_environment_operation_review_bundle_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a side-effect-free environment operation review bundle."""
    contract = validate_environment_operation_review_bundle_contract(source)
    findings = _operation_findings(contract)
    return {
        "environment_operation_review_policy": contract.policy.to_summary(),
        "operation_review_request": contract.request.to_summary(),
        "manifest_preflight_ref": contract.manifest.to_summary(),
        "sync_intent_ref": contract.intent.to_summary(),
        "sync_result_ref": contract.result.to_summary(),
        "operation_review_status": _operation_review_status(contract, findings),
        "operation_review_findings": findings,
        "attention": _attention(contract.policy.values),
    }


def _operation_review_status(
    contract: EnvironmentOperationReviewBundleContract, findings: list[dict[str, str]]
) -> str:
    if findings:
        return "operation_review_has_findings"
    if contract.result.result_status == "external_sync_reported_success":
        return "external_sync_reported_success_with_review_limits"
    return "operation_review_has_findings"


def _operation_findings(contract: EnvironmentOperationReviewBundleContract) -> list[dict[str, str]]:
    findings = []
    findings.extend(_alignment_findings(contract))
    if contract.manifest.preflight_status != PREFLIGHT_PASSING_STATUS:
        findings.append(
            _finding(
                "manifest_preflight_not_passed",
                "Prior modern manifest preflight status did not pass declared checks.",
                "dependency_resolution_or_dependency_sync",
                "modern_manifest_preflight",
            )
        )
    if contract.manifest.preflight_findings:
        findings.append(
            _finding(
                "manifest_preflight_has_findings",
                "Prior manifest preflight summary carries review findings.",
                "dependency_resolution_or_dependency_sync",
                "modern_manifest_preflight",
            )
        )
    if contract.result.result_findings:
        findings.append(
            _finding(
                "uv_sync_result_has_findings",
                "Prior uv sync result summary carries review findings.",
                "verified_synchronized_environment",
                "uv_sync_result",
            )
        )
    if contract.result.result_status != "external_sync_reported_success":
        findings.append(
            _finding(
                "uv_sync_result_not_success",
                "Prior uv sync result status does not report success.",
                "synchronized_or_installed_environment",
                "uv_sync_result",
            )
        )
    return findings


def _alignment_findings(contract: EnvironmentOperationReviewBundleContract) -> list[dict[str, str]]:
    request = contract.request
    manifest = contract.manifest
    intent = contract.intent
    result = contract.result
    findings = []
    if request.manifest_preflight_request_id != manifest.request_id:
        findings.append(
            _finding(
                "manifest_preflight_request_mismatch",
                "Operation review request does not match the manifest preflight request.",
                "selected_manifest_preflight_belongs_to_operation",
                "operation_review_request",
            )
        )
    if request.sync_intent_request_id != intent.request_id:
        findings.append(
            _finding(
                "sync_intent_request_mismatch",
                "Operation review request does not match the uv sync intent request.",
                "selected_sync_intent_belongs_to_operation",
                "operation_review_request",
            )
        )
    if request.sync_result_id != result.result_id:
        findings.append(
            _finding(
                "sync_result_id_mismatch",
                "Operation review request does not match the uv sync result record.",
                "selected_sync_result_belongs_to_operation",
                "operation_review_request",
            )
        )
    if {
        request.prepared_run_context_id,
        manifest.prepared_run_context_id,
        intent.prepared_run_context_id,
    } != {request.prepared_run_context_id}:
        findings.append(
            _finding(
                "prepared_run_context_mismatch",
                "Prior summaries do not share the requested prepared run context.",
                "single_prepared_context_review",
                "prior_summary_alignment",
            )
        )
    if {
        request.declared_environment_id,
        manifest.declared_environment_id,
        intent.declared_environment_id,
    } != {request.declared_environment_id}:
        findings.append(
            _finding(
                "declared_environment_mismatch",
                "Prior summaries do not share the requested declared environment.",
                "single_declared_environment_review",
                "prior_summary_alignment",
            )
        )
    if result.intent_request_id != intent.request_id or result.approval_id != intent.approval_id:
        findings.append(
            _finding(
                "sync_result_intent_mismatch",
                "Prior uv sync result does not reference the selected sync intent.",
                "result_belongs_to_selected_intent",
                "uv_sync_result",
            )
        )
    if (
        result.result_intent_request_id != intent.request_id
        or result.result_intent_approval_id != intent.approval_id
        or result.expected_manager != intent.expected_manager
        or result.result_intent_manager != intent.manager
        or result.result_intent_operation != intent.operation
        or result.result_intent_working_directory != intent.working_directory
        or result.result_intent_argv != intent.argv
        or result.result_intent_does_not_claim != intent.does_not_claim
    ):
        findings.append(
            _finding(
                "sync_result_intent_ref_mismatch",
                "Prior uv sync result intent reference does not match the selected intent.",
                "result_intent_ref_belongs_to_selected_intent",
                "uv_sync_result",
            )
        )
    if (
        result.manager != intent.manager
        or result.operation != intent.operation
        or result.working_directory != intent.working_directory
        or result.argv != intent.argv
    ):
        findings.append(
            _finding(
                "sync_result_command_mismatch",
                "Prior uv sync result command facts do not match the selected intent.",
                "external_command_matches_selected_intent",
                "uv_sync_result",
            )
        )
    return findings


def _finding(code: str, basis: str, does_not_claim: str, source: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "basis": basis,
        "source": source,
        "does_not_claim": does_not_claim,
    }


def _attention(policy: dict[str, str]) -> list[dict[str, str]]:
    rows = []
    for row in POLICY_ATTENTION_MATRIX:
        if policy[row["policy_key"]] == row["policy_value"]:
            rows.append(dict(row))
    return rows
