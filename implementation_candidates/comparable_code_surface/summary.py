"""Structured summary builder for comparable code surfaces.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read source files, inspect Git state, perform a
semantic source diff, discover dependencies, import code, execute code, restore
environments, materialize workspaces, or define workflow/DAG contracts.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "fact_source": "declared_fixture_code_facts",
    "comparison_scope": "explicit_code_surface_files",
    "content_comparison": "digest_and_capture_state_only",
    "semantic_source_diff": "not_performed",
    "internal_git_inspection": "not_performed",
    "environment_readiness": "not_performed",
    "code_import": "not_performed",
    "code_execution": "not_performed",
    "workspace_materialization": "not_performed",
}
_CODE_CAPTURE_STATES = {
    "content_captured",
    "reference_only",
    "missing",
    "redacted",
    "excluded",
}
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _surface_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["code_surfaces"], "surface_id")


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["comparison_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected comparison policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"comparable code surface policy {key} must be {expected}")


def _file_by_path(surface: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(surface["file_facts"], "path")


def _validate_file_fact(surface_id: str, file_fact: dict[str, Any]) -> None:
    path = file_fact["path"]
    if not _path_is_relative(path):
        raise ValueError(f"code surface {surface_id} contains non-relative file path")

    capture_state = file_fact["capture_state"]
    if capture_state not in _CODE_CAPTURE_STATES:
        raise ValueError("code surface has unsupported code capture state")

    content_state = file_fact.get("content_state")
    if capture_state == "content_captured":
        if content_state is None:
            raise ValueError("content-captured code facts require content_state")
        if content_state["digest_algorithm"] != "sha256":
            raise ValueError("code surface integrity hint must use sha256")
        if not _SHA256_DIGEST.fullmatch(content_state["digest"]):
            raise ValueError("code surface digest must be a sha256-prefixed hex digest")
    elif content_state is not None:
        raise ValueError("non-content-captured code facts must not carry content_state")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    surfaces = _surface_by_id(source)

    for surface in source["code_surfaces"]:
        _file_by_path(surface)
        for file_fact in surface["file_facts"]:
            _validate_file_fact(surface["surface_id"], file_fact)

    _records_by_key(source["comparison_sets"], "comparison_id")
    for comparison in source["comparison_sets"]:
        baseline_surface_id = comparison["baseline_surface_id"]
        comparison_surface_id = comparison["comparison_surface_id"]
        if baseline_surface_id not in surfaces:
            raise ValueError(
                f"comparison references missing baseline surface: {baseline_surface_id}"
            )
        if comparison_surface_id not in surfaces:
            raise ValueError(
                f"comparison references missing comparison surface: {comparison_surface_id}"
            )
        if baseline_surface_id == comparison_surface_id:
            raise ValueError("comparison must use two distinct code surfaces")


def _capture_state_counts(surface: dict[str, Any]) -> dict[str, int]:
    counts = {state: 0 for state in sorted(_CODE_CAPTURE_STATES)}
    for file_fact in surface["file_facts"]:
        counts[file_fact["capture_state"]] += 1
    return {state: count for state, count in counts.items() if count}


def _surface_summary(surface: dict[str, Any]) -> dict[str, Any]:
    counts = _capture_state_counts(surface)
    return {
        "surface_id": surface["surface_id"],
        "surface_kind": surface["surface_kind"],
        "authority": surface["authority"],
        "record_status": surface["record_status"],
        "file_count": len(surface["file_facts"]),
        "content_captured_count": counts.get("content_captured", 0),
        "non_content_comparable_count": len(surface["file_facts"])
        - counts.get("content_captured", 0),
        "capture_state_counts": counts,
    }


def _file_fact_summary(surface: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for file_fact in surface["file_facts"]:
        summary = {
            "surface_id": surface["surface_id"],
            "path": file_fact["path"],
            "role": file_fact["role"],
            "recorded_form": file_fact["recorded_form"],
            "capture_state": file_fact["capture_state"],
        }
        if file_fact["capture_state"] == "content_captured":
            summary["digest"] = file_fact["content_state"]["digest"]
            summary["observed_at"] = file_fact["content_state"]["observed_at"]
        summaries.append(summary)
    return summaries


def _capture_state(file_fact: dict[str, Any] | None) -> str:
    if file_fact is None:
        return "absent"
    return file_fact["capture_state"]


def _finding_for_path(
    comparison: dict[str, Any],
    baseline_file: dict[str, Any] | None,
    comparison_file: dict[str, Any] | None,
) -> dict[str, Any]:
    baseline_state = _capture_state(baseline_file)
    comparison_state = _capture_state(comparison_file)

    if baseline_file is None or comparison_file is None:
        finding = "missing"
        basis = "Path is present on only one declared code surface."
        does_not_claim = "deleted_or_added_by_user_intent"
    elif "redacted" in {baseline_state, comparison_state}:
        finding = "redacted"
        basis = "At least one side is declared redacted, so content is intentionally hidden."
        does_not_claim = "content_equality_or_difference"
    elif "excluded" in {baseline_state, comparison_state}:
        finding = "not_compared"
        basis = "At least one side is declared excluded from content comparison."
        does_not_claim = "content_equality_or_difference"
    elif {baseline_state, comparison_state} != {"content_captured"}:
        finding = "unverified"
        basis = "At least one side lacks captured content for digest comparison."
        does_not_claim = "content_equality_or_difference"
    else:
        baseline_digest = baseline_file["content_state"]["digest"]
        comparison_digest = comparison_file["content_state"]["digest"]
        if baseline_digest == comparison_digest:
            finding = "same_observed"
            basis = "Both sides are content-captured with the same declared digest."
            does_not_claim = "semantic_equivalence_or_runnable_readiness"
        else:
            finding = "changed"
            basis = "Both sides are content-captured with different declared digests."
            does_not_claim = "semantic_source_diff_or_cause_attribution"

    return {
        "comparison_id": comparison["comparison_id"],
        "path": baseline_file["path"] if baseline_file is not None else comparison_file["path"],
        "finding": finding,
        "baseline_surface_id": comparison["baseline_surface_id"],
        "comparison_surface_id": comparison["comparison_surface_id"],
        "baseline_capture_state": baseline_state,
        "comparison_capture_state": comparison_state,
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _findings_for_comparison(
    comparison: dict[str, Any],
    baseline_surface: dict[str, Any],
    comparison_surface: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_files = _file_by_path(baseline_surface)
    comparison_files = _file_by_path(comparison_surface)
    paths = sorted(set(baseline_files) | set(comparison_files))
    return [
        _finding_for_path(comparison, baseline_files.get(path), comparison_files.get(path))
        for path in paths
    ]


def _finding_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        code = finding["finding"]
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _comparison_set_summary(
    comparison: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "comparison_id": comparison["comparison_id"],
        "baseline_surface_id": comparison["baseline_surface_id"],
        "comparison_surface_id": comparison["comparison_surface_id"],
        "comparison_purpose": comparison["comparison_purpose"],
        "compared_path_count": len(findings),
        "finding_counts": _finding_counts(findings),
    }


def _all_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    surfaces = _surface_by_id(source)
    return [
        finding
        for comparison in source["comparison_sets"]
        for finding in _findings_for_comparison(
            comparison,
            surfaces[comparison["baseline_surface_id"]],
            surfaces[comparison["comparison_surface_id"]],
        )
    ]


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["comparison_policy"]
    attention = []
    if policy["content_comparison"] == "digest_and_capture_state_only":
        attention.append(
            {
                "code": "comparison_uses_declared_integrity_hints",
                "severity": "info",
                "basis": "Comparison uses declared capture states and digests only.",
                "does_not_claim": "file_content_was_read_by_builder",
            }
        )
    if policy["semantic_source_diff"] == "not_performed":
        attention.append(
            {
                "code": "semantic_source_diff_not_performed",
                "severity": "review",
                "basis": "Changed files are identified by declared digest difference only.",
                "does_not_claim": "semantic_change_or_cause_attribution",
            }
        )
    if policy["internal_git_inspection"] == "not_performed":
        attention.append(
            {
                "code": "internal_git_not_inspected",
                "severity": "info",
                "basis": "Git state remains outside this comparison boundary.",
                "does_not_claim": "git_clean_or_dirty_status",
            }
        )
    if policy["environment_readiness"] == "not_performed":
        attention.append(
            {
                "code": "environment_readiness_not_checked",
                "severity": "review",
                "basis": "Environment files, dependency sync, and runnable readiness are not checked.",
                "does_not_claim": "runnable_environment",
            }
        )
    if policy["code_import"] == "not_performed" and policy["code_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_not_imported_or_executed",
                "severity": "review",
                "basis": "Comparison does not import, load, or execute code files.",
                "does_not_claim": "execution_permission_or_runtime_behavior",
            }
        )
    if policy["workspace_materialization"] == "not_performed":
        attention.append(
            {
                "code": "workspace_materialization_not_performed",
                "severity": "info",
                "basis": "No editable workspace is created by this comparison slice.",
                "does_not_claim": "restored_or_materialized_workspace",
            }
        )
    return attention


def build_comparable_code_surface_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured comparable-code-surface summary from explicit facts."""
    _validate_references(source)
    findings = _all_findings(source)
    findings_by_comparison = {
        comparison["comparison_id"]: [
            finding
            for finding in findings
            if finding["comparison_id"] == comparison["comparison_id"]
        ]
        for comparison in source["comparison_sets"]
    }
    return {
        "comparison_policy": copy.deepcopy(source["comparison_policy"]),
        "code_surfaces": [_surface_summary(surface) for surface in source["code_surfaces"]],
        "file_facts": [
            file_summary
            for surface in source["code_surfaces"]
            for file_summary in _file_fact_summary(surface)
        ],
        "comparison_sets": [
            _comparison_set_summary(
                comparison,
                findings_by_comparison[comparison["comparison_id"]],
            )
            for comparison in source["comparison_sets"]
        ],
        "code_file_findings": findings,
        "attention": _attention(source),
    }
