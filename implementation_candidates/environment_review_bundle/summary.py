"""Structured summary builder for environment review bundles.

This module is an experimental composition boundary. It deliberately consumes
explicit prior summary facts only: it does not read environment files, resolve
dependencies, sync packages, install packages, inspect runtimes, import code,
execute code, probe hardware, claim runnable readiness, or define
managed-runner behavior.
"""

from __future__ import annotations

from typing import Any

from implementation_candidates.environment_review_bundle.contracts import (
    POLICY_ATTENTION_MATRIX,
    EnvironmentReviewBundleContract,
    validate_environment_review_bundle_contract,
)


def _attention(policy: dict[str, str]) -> list[dict[str, str]]:
    return [
        {
            "code": row["code"],
            "severity": row["severity"],
            "basis": row["basis"],
            "does_not_claim": row["does_not_claim"],
        }
        for row in POLICY_ATTENTION_MATRIX
        if policy[row["policy_key"]] == row["policy_value"]
    ]


def _build_from_contract(contract: EnvironmentReviewBundleContract) -> dict[str, Any]:
    return {
        "environment_review_bundle_policy": contract.policy.to_summary(),
        "review_bundles": [bundle.to_summary() for bundle in contract.bundles],
        "prepared_run_contexts": [
            prepared_context.to_summary() for prepared_context in contract.prepared_contexts()
        ],
        "rerun_preparations": [rerun.to_summary() for rerun in contract.rerun_preparations()],
        "environment_contexts": [
            environment.to_summary() for environment in contract.environment_contexts()
        ],
        "environment_comparisons": [
            comparison.to_summary() for comparison in contract.comparisons()
        ],
        "environment_file_observations": [
            observation.to_summary() for observation in contract.file_observations()
        ],
        "environment_readiness_plans": [
            readiness_plan.to_summary() for readiness_plan in contract.readiness_plans()
        ],
        "environment_review_findings": [finding.to_summary() for finding in contract.findings()],
        "finding_source_counts": contract.finding_source_counts(),
        "attention": _attention(contract.policy.values),
    }


def build_environment_review_bundle_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build an environment review bundle from explicit prior summary facts."""
    return _build_from_contract(validate_environment_review_bundle_contract(source))
