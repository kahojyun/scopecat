"""Approved uv sync intent implementation candidate.

This module validates one explicit ``uv sync`` command intent and returns the
bounded argv a later executor could review or run. It does not execute the
process, inspect the filesystem, read manifests or lockfiles, resolve
dependencies, install packages, probe runtimes, import code, execute selected
code, probe hardware, or claim runnable readiness.
"""

from __future__ import annotations

from typing import Any

from implementation_candidates.uv_sync_intent.contracts import (
    POLICY_ATTENTION_MATRIX,
    UvSyncIntentContract,
    normalize_dependency_group,
    validate_uv_sync_intent_contract,
)


def build_uv_sync_intent_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a side-effect-free uv sync command-intent summary."""
    contract = validate_uv_sync_intent_contract(source)
    return _build_from_contract(contract)


def _build_from_contract(contract: UvSyncIntentContract) -> dict[str, Any]:
    return {
        "uv_sync_intent_policy": contract.policy.to_summary(),
        "sync_request": contract.request.to_summary(),
        "prepared_run_context": contract.prepared_context.to_summary(),
        "declared_environment": contract.declared_environment.to_summary(),
        "intent_status": "ready_for_external_review",
        "command_intent": _command_intent(contract),
        "intent_findings": [],
        "attention": _attention(contract.policy.values),
    }


def _command_intent(contract: UvSyncIntentContract) -> dict[str, Any]:
    request = contract.request
    declared_groups = contract.declared_environment.modern_python_environment.dependency_groups
    group_matches = _dependency_group_matches(
        requested_groups=request.dependency_groups,
        declared_groups=declared_groups,
    )
    normalized_requested_groups = [
        normalize_dependency_group(group) for group in request.dependency_groups
    ]
    normalized_declared_groups = [normalize_dependency_group(group) for group in declared_groups]
    command_groups = [match["declared_environment_group"] for match in group_matches]
    return {
        "manager": "uv",
        "operation": "sync",
        "working_directory": request.working_directory,
        "argv": _uv_sync_argv(command_groups),
        "environment_variables": [],
        "dependency_group_selection": {
            "include_project_dependencies": request.include_project_dependencies,
            "requested_groups": list(request.dependency_groups),
            "declared_environment_groups": list(declared_groups),
            "normalized_requested_groups": normalized_requested_groups,
            "normalized_declared_environment_groups": normalized_declared_groups,
            "group_matches": group_matches,
            "project_dependencies": "included",
            "default_dependency_groups": "excluded",
            "command_dependency_groups": command_groups,
        },
        "lock_policy": request.lock_policy,
        "command_policy": request.command_policy,
        "expected_external_effect_if_executed": (
            "uv_may_synchronize_the_project_environment_if_the_lockfile_would_remain_unchanged"
        ),
        "does_not_claim": "process_executed_or_environment_synchronized",
    }


def _dependency_group_matches(
    *, requested_groups: tuple[str, ...], declared_groups: tuple[str, ...]
) -> list[dict[str, str]]:
    declared_by_normalized = {normalize_dependency_group(group): group for group in declared_groups}
    return [
        {
            "requested_group": group,
            "normalized_group": normalize_dependency_group(group),
            "declared_environment_group": declared_by_normalized[normalize_dependency_group(group)],
        }
        for group in requested_groups
    ]


def _uv_sync_argv(selected_groups: list[str]) -> list[str]:
    argv = ["uv", "sync", "--locked", "--no-default-groups"]
    for group in selected_groups:
        argv.extend(["--group", group])
    return argv


def _attention(policy: dict[str, str]) -> list[dict[str, str]]:
    rows = []
    for row in POLICY_ATTENTION_MATRIX:
        if policy[row["policy_key"]] == row["policy_value"]:
            rows.append(dict(row))
    return rows
