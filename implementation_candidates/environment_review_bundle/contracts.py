"""Candidate-local contract checks for environment review bundles.

The bundle still accepts JSON-shaped fixture input. This module validates and
normalizes selected composition facts before summary code projects them into
review output. It is not a shared environment schema.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

EXPECTED_POLICY = {
    "summary_policy": "review_summary",
    "bundle_authority": "explicit_prior_environment_review_summaries",
    "prepared_context_source": "declared_prepared_run_context_summary",
    "rerun_source": "declared_reference_based_rerun_preparation_summary",
    "comparison_source": "declared_environment_comparison_summary",
    "file_observation_source": "declared_environment_file_observation_summary",
    "readiness_source": "declared_environment_readiness_plan_summary",
    "dependency_resolution": "not_performed",
    "dependency_sync": "not_performed",
    "package_install": "not_performed",
    "runtime_probe": "not_performed",
    "code_import_execution": "not_performed",
    "hardware_probe": "not_performed",
    "managed_runner": "not_defined",
    "readiness_claim": "not_claimed",
    "shared_environment_schema": "not_defined",
}

POLICY_ATTENTION_MATRIX = (
    {
        "policy_key": "summary_policy",
        "policy_value": "review_summary",
        "code": "environment_review_bundle_only",
        "severity": "info",
        "basis": "The bundle composes explicit prior environment review summaries.",
        "does_not_claim": "new_environment_observation_or_operation",
    },
    {
        "policy_key": "dependency_resolution",
        "policy_value": "not_performed",
        "code": "dependency_resolution_not_performed",
        "severity": "review",
        "basis": "Declared comparison and file observation facts are not dependency resolution.",
        "does_not_claim": "resolved_environment",
    },
    {
        "policy_key": "dependency_sync",
        "policy_value": "not_performed",
        "code": "dependency_sync_not_performed",
        "severity": "review",
        "basis": "The bundle does not run uv sync or synchronize package state.",
        "does_not_claim": "synchronized_environment",
    },
    {
        "policy_key": "package_install",
        "policy_value": "not_performed",
        "code": "package_install_not_performed",
        "severity": "review",
        "basis": "The bundle does not install, update, or remove packages.",
        "does_not_claim": "installed_environment",
    },
    {
        "policy_key": "runtime_probe",
        "policy_value": "not_performed",
        "code": "runtime_probe_not_performed",
        "severity": "review",
        "basis": "The bundle does not inspect interpreters, installed packages, shells, or tools.",
        "does_not_claim": "runtime_available_or_compatible",
    },
    {
        "policy_key": "code_import_execution",
        "policy_value": "not_performed",
        "code": "code_execution_not_granted",
        "severity": "review",
        "basis": "The bundle does not import, load, or execute selected code.",
        "does_not_claim": "execution_permission",
    },
    {
        "policy_key": "hardware_probe",
        "policy_value": "not_performed",
        "code": "hardware_probe_not_performed",
        "severity": "review",
        "basis": "External runtime notes remain review facts, not hardware checks.",
        "does_not_claim": "control_pc_or_hardware_ready",
    },
    {
        "policy_key": "managed_runner",
        "policy_value": "not_defined",
        "code": "managed_runner_not_defined",
        "severity": "review",
        "basis": "The bundle does not define managed-runner behavior or run lifecycle control.",
        "does_not_claim": "managed_runner_available",
    },
    {
        "policy_key": "readiness_claim",
        "policy_value": "not_claimed",
        "code": "runnable_readiness_not_claimed",
        "severity": "review",
        "basis": "Aggregated environment findings do not decide whether a run can start.",
        "does_not_claim": "run_can_start",
    },
    {
        "policy_key": "shared_environment_schema",
        "policy_value": "not_defined",
        "code": "shared_environment_schema_not_defined",
        "severity": "review",
        "basis": "The bundle validates a slice-local contract, not a shared environment schema.",
        "does_not_claim": "shared_environment_schema",
    },
)

EXPECTED_ENVIRONMENT_CLAIMS = {
    "readiness_claim": "not_checked",
    "sync_claim": "not_synced",
    "execution_claim": "not_imported_loaded_or_executed",
    "hardware_claim": "not_probed",
}

EXPECTED_READINESS_PLAN_CLAIMS = {
    "readiness_claim": "not_checked",
    "sync_claim": "not_performed",
    "execution_claim": "not_imported_loaded_or_executed",
    "hardware_claim": "not_probed",
}

EXPECTED_BUNDLE_CLAIM = "environment_review_bundle_only"
EXPECTED_PREPARED_CONTEXT_CLAIM = "manual_run_context_only"
EXPECTED_RERUN_CLAIM = "manual_rerun_seed_summary_only"
EXPECTED_COMPARISON_CLAIM = "declared_environment_fact_comparison_only"

ENVIRONMENT_RECORD_STATUSES = {
    "declared",
    "declared_with_review_findings",
}
ENVIRONMENT_ROLES = {
    "selected_reference_environment",
    "current_environment",
}
FILE_OBSERVATION_CLASSIFICATIONS = {
    "environment_files_observed_match_declared_facts",
    "environment_files_observed_with_review_findings",
    "environment_files_observed_with_mismatch",
    "environment_files_unavailable_for_review",
}
COMPARISON_FINDINGS_REQUIRING_REVIEW = {
    "declared_environment_fact_changed",
    "declared_environment_fact_missing",
    "declared_environment_fact_unverified",
    "declared_environment_fact_unsupported",
}
COMPARISON_FINDINGS_IGNORED_FOR_REVIEW = {
    "declared_environment_fact_same",
}
FILE_OBSERVATION_FINDINGS = {
    "environment_file_unavailable",
    "environment_file_digest_mismatch",
    "environment_file_size_mismatch",
    "environment_file_parse_failed",
}
READINESS_FINDINGS = {
    "check_review_required",
    "check_blocked",
    "check_unsupported",
}
COMPARISON_STATE_COUNTS = {
    "changed",
    "missing",
    "same_declared",
    "unsupported",
    "unverified",
}
OBSERVATION_STATUS_COUNTS = {
    "observed",
    "unavailable",
}
READINESS_CHECK_STATE_COUNTS = {
    "planned",
    "review_required",
    "blocked",
    "unsupported",
}
FILE_FINDING_DOES_NOT_CLAIM = {
    "environment_file_unavailable": "environment_repair_or_dependency_sync",
    "environment_file_digest_mismatch": "dependency_resolution_or_file_repair",
    "environment_file_size_mismatch": "dependency_resolution_or_file_repair",
    "environment_file_parse_failed": "dependency_resolution_or_runtime_compatibility",
}
FILE_FINDINGS_REQUIRING_UNAVAILABLE_STATUS = {
    "environment_file_unavailable",
}
FILE_FINDINGS_REQUIRING_OBSERVED_STATUS = {
    "environment_file_digest_mismatch",
    "environment_file_size_mismatch",
    "environment_file_parse_failed",
}
FILE_OBSERVATION_CLASSIFICATION_FINDINGS = {
    "environment_files_observed_match_declared_facts": set(),
    "environment_files_observed_with_review_findings": {
        "environment_file_parse_failed",
    },
    "environment_files_observed_with_mismatch": {
        "environment_file_digest_mismatch",
        "environment_file_size_mismatch",
    },
    "environment_files_unavailable_for_review": {
        "environment_file_unavailable",
    },
}
FILE_OBSERVATION_CLASSIFICATIONS_REQUIRING_OBSERVED_STATUS = {
    "environment_files_observed_with_review_findings",
    "environment_files_observed_with_mismatch",
}
READINESS_FINDING_DOES_NOT_CLAIM = {
    "check_review_required": {
        "environment_files_observed_or_verified",
        "external_tool_available_or_compatible",
        "legacy_environment_migrated",
        "resolved_environment",
        "runtime_available_or_compatible",
    },
    "check_blocked": {
        "control_pc_or_hardware_ready",
        "environment_files_observed_or_verified",
        "external_tool_available_or_compatible",
        "legacy_environment_migrated",
        "resolved_environment",
        "run_can_start",
        "runtime_available_or_compatible",
        "synchronized_environment",
    },
    "check_unsupported": {
        "external_tool_available_or_compatible",
        "legacy_environment_migrated",
        "run_can_start",
        "runtime_available_or_compatible",
        "supported_environment_operation",
    },
}
SOURCE_KEYS = {
    "environment_review_bundle_policy",
    "review_bundles",
    "prepared_run_contexts",
    "rerun_preparations",
    "environment_contexts",
    "environment_comparisons",
    "environment_file_observations",
    "environment_readiness_plans",
    "comparison_findings",
    "file_observation_findings",
    "readiness_findings",
}

PREPARED_RUN_CONTEXT_KEYS = {
    "prepared_run_context_id",
    "label",
    "scope",
    "selected_context_count",
    "preparation_claim",
}
RERUN_PREPARATION_KEYS = {
    "rerun_preparation_id",
    "selected_reference_id",
    "prepared_run_context_id",
    "reference_measurement_id",
    "current_measurement_id",
    "preparation_claim",
}
ENVIRONMENT_CONTEXT_KEYS = {
    "environment_id",
    "label",
    "role",
    "record_status",
    "scope",
    "environment_claims",
}
ENVIRONMENT_COMPARISON_KEYS = {
    "comparison_id",
    "baseline_environment_id",
    "comparison_environment_id",
    "comparison_claim",
    "fact_count",
    "finding_state_counts",
}
ENVIRONMENT_FILE_OBSERVATION_KEYS = {
    "file_observation_id",
    "environment_id",
    "classification",
    "observation_status_counts",
    "review_finding_count",
}
REVIEW_BUNDLE_KEYS = {
    "bundle_id",
    "label",
    "selected_reference_id",
    "rerun_preparation_id",
    "prepared_run_context_id",
    "reference_managed_code_version_id",
    "reference_environment_id",
    "current_environment_id",
    "environment_comparison_id",
    "environment_file_observation_id",
    "environment_readiness_plan_id",
    "bundle_claim",
}
COMPARISON_FINDING_KEYS = {
    "bundle_id",
    "comparison_id",
    "finding",
    "basis",
}
FILE_OBSERVATION_FINDING_KEYS = {
    "bundle_id",
    "file_observation_id",
    "finding",
    "basis",
    "does_not_claim",
}
READINESS_FINDING_KEYS = {
    "bundle_id",
    "readiness_plan_id",
    "finding",
    "basis",
    "does_not_claim",
}
COMPARISON_FINDING_STATES = {
    "declared_environment_fact_changed": "changed",
    "declared_environment_fact_missing": "missing",
    "declared_environment_fact_same": "same_declared",
    "declared_environment_fact_unverified": "unverified",
    "declared_environment_fact_unsupported": "unsupported",
}
READINESS_FINDING_STATES = {
    "check_review_required": "review_required",
    "check_blocked": "blocked",
    "check_unsupported": "unsupported",
}


@dataclass(frozen=True)
class EnvironmentReviewBundlePolicy:
    values: dict[str, str]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "EnvironmentReviewBundlePolicy":
        _require_shape(
            value,
            set(EXPECTED_POLICY),
            "environment review bundle policy",
        )
        for key, expected in EXPECTED_POLICY.items():
            if value[key] != expected:
                raise ValueError(f"environment review bundle policy {key} must be {expected}")
        return cls(values=dict(value))

    def to_summary(self) -> dict[str, str]:
        return copy.deepcopy(self.values)


@dataclass(frozen=True)
class Scope:
    managed_code_version_id: str
    editable_workspace_id: str
    prepared_run_context_id: str

    @classmethod
    def parse(cls, value: dict[str, Any], *, owner: str) -> "Scope":
        expected_keys = {
            "managed_code_version_id",
            "editable_workspace_id",
            "prepared_run_context_id",
        }
        _require_shape(value, expected_keys, f"{owner} scope")
        for key in expected_keys:
            if not isinstance(value[key], str) or not value[key]:
                raise ValueError(f"{owner} scope {key} must be a non-empty string")
        return cls(
            managed_code_version_id=value["managed_code_version_id"],
            editable_workspace_id=value["editable_workspace_id"],
            prepared_run_context_id=value["prepared_run_context_id"],
        )

    def to_summary(self) -> dict[str, str]:
        return {
            "managed_code_version_id": self.managed_code_version_id,
            "editable_workspace_id": self.editable_workspace_id,
            "prepared_run_context_id": self.prepared_run_context_id,
        }


@dataclass(frozen=True)
class PreparedRunContextRef:
    prepared_run_context_id: str
    label: str
    scope: Scope
    selected_context_count: int
    preparation_claim: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "PreparedRunContextRef":
        _require_shape(value, PREPARED_RUN_CONTEXT_KEYS, "prepared run context")
        if value["preparation_claim"] != EXPECTED_PREPARED_CONTEXT_CLAIM:
            raise ValueError("prepared run context claim must stay manual_run_context_only")
        return cls(
            prepared_run_context_id=_required_str(
                value, "prepared_run_context_id", "prepared run context"
            ),
            label=_required_str(value, "label", "prepared run context"),
            scope=Scope.parse(value["scope"], owner="prepared run context"),
            selected_context_count=_required_non_negative_int(
                value, "selected_context_count", "prepared run context"
            ),
            preparation_claim=value["preparation_claim"],
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "prepared_run_context_id": self.prepared_run_context_id,
            "label": self.label,
            "scope": self.scope.to_summary(),
            "selected_context_count": self.selected_context_count,
            "preparation_claim": self.preparation_claim,
        }


@dataclass(frozen=True)
class RerunPreparationRef:
    rerun_preparation_id: str
    selected_reference_id: str
    prepared_run_context_id: str
    reference_measurement_id: str
    current_measurement_id: str
    preparation_claim: str

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "RerunPreparationRef":
        _require_shape(value, RERUN_PREPARATION_KEYS, "rerun preparation")
        if value["preparation_claim"] != EXPECTED_RERUN_CLAIM:
            raise ValueError("rerun preparation claim must stay manual_rerun_seed_summary_only")
        return cls(
            rerun_preparation_id=_required_str(value, "rerun_preparation_id", "rerun preparation"),
            selected_reference_id=_required_str(
                value, "selected_reference_id", "rerun preparation"
            ),
            prepared_run_context_id=_required_str(
                value, "prepared_run_context_id", "rerun preparation"
            ),
            reference_measurement_id=_required_str(
                value, "reference_measurement_id", "rerun preparation"
            ),
            current_measurement_id=_required_str(
                value, "current_measurement_id", "rerun preparation"
            ),
            preparation_claim=value["preparation_claim"],
        )

    def to_summary(self) -> dict[str, str]:
        return {
            "rerun_preparation_id": self.rerun_preparation_id,
            "selected_reference_id": self.selected_reference_id,
            "prepared_run_context_id": self.prepared_run_context_id,
            "reference_measurement_id": self.reference_measurement_id,
            "current_measurement_id": self.current_measurement_id,
            "preparation_claim": self.preparation_claim,
        }


@dataclass(frozen=True)
class EnvironmentContextRef:
    environment_id: str
    label: str
    role: str
    record_status: str
    scope: Scope
    environment_claims: dict[str, str]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "EnvironmentContextRef":
        _require_shape(value, ENVIRONMENT_CONTEXT_KEYS, "environment context")
        role = _required_str(value, "role", "environment context")
        record_status = _required_str(value, "record_status", "environment context")
        if role not in ENVIRONMENT_ROLES:
            raise ValueError("environment context role is unsupported")
        if record_status not in ENVIRONMENT_RECORD_STATUSES:
            raise ValueError("environment context record_status must stay declaration-only")
        claims = value["environment_claims"]
        _require_shape(
            claims,
            set(EXPECTED_ENVIRONMENT_CLAIMS),
            "environment context claims",
        )
        for key, expected in EXPECTED_ENVIRONMENT_CLAIMS.items():
            if claims[key] != expected:
                raise ValueError(f"environment context {key} must be {expected}")
        return cls(
            environment_id=_required_str(value, "environment_id", "environment context"),
            label=_required_str(value, "label", "environment context"),
            role=role,
            record_status=record_status,
            scope=Scope.parse(value["scope"], owner="environment context"),
            environment_claims=dict(claims),
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "label": self.label,
            "role": self.role,
            "record_status": self.record_status,
            "scope": self.scope.to_summary(),
            "environment_claims": copy.deepcopy(self.environment_claims),
        }


@dataclass(frozen=True)
class EnvironmentComparisonRef:
    comparison_id: str
    baseline_environment_id: str
    comparison_environment_id: str
    comparison_claim: str
    fact_count: int
    finding_state_counts: dict[str, int]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "EnvironmentComparisonRef":
        _require_shape(value, ENVIRONMENT_COMPARISON_KEYS, "environment comparison")
        if value["comparison_claim"] != EXPECTED_COMPARISON_CLAIM:
            raise ValueError("environment comparison claim must stay declared-only")
        fact_count = _required_non_negative_int(value, "fact_count", "environment comparison")
        finding_state_counts = _validate_count_map(
            value["finding_state_counts"],
            allowed=COMPARISON_STATE_COUNTS,
            owner="environment comparison finding_state_counts",
        )
        if sum(finding_state_counts.values()) != fact_count:
            raise ValueError("environment comparison fact_count must match finding_state_counts")
        return cls(
            comparison_id=_required_str(value, "comparison_id", "environment comparison"),
            baseline_environment_id=_required_str(
                value, "baseline_environment_id", "environment comparison"
            ),
            comparison_environment_id=_required_str(
                value, "comparison_environment_id", "environment comparison"
            ),
            comparison_claim=value["comparison_claim"],
            fact_count=fact_count,
            finding_state_counts=finding_state_counts,
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "baseline_environment_id": self.baseline_environment_id,
            "comparison_environment_id": self.comparison_environment_id,
            "comparison_claim": self.comparison_claim,
            "fact_count": self.fact_count,
            "finding_state_counts": copy.deepcopy(self.finding_state_counts),
        }


@dataclass(frozen=True)
class EnvironmentFileObservationRef:
    file_observation_id: str
    environment_id: str
    classification: str
    observation_status_counts: dict[str, int]
    review_finding_count: int

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "EnvironmentFileObservationRef":
        _require_shape(value, ENVIRONMENT_FILE_OBSERVATION_KEYS, "environment file observation")
        classification = _required_str(value, "classification", "environment file observation")
        if classification not in FILE_OBSERVATION_CLASSIFICATIONS:
            raise ValueError("environment file observation classification is unsupported")
        return cls(
            file_observation_id=_required_str(
                value, "file_observation_id", "environment file observation"
            ),
            environment_id=_required_str(value, "environment_id", "environment file observation"),
            classification=classification,
            observation_status_counts=_validate_count_map(
                value["observation_status_counts"],
                allowed=OBSERVATION_STATUS_COUNTS,
                owner="environment file observation status counts",
            ),
            review_finding_count=_required_non_negative_int(
                value, "review_finding_count", "environment file observation"
            ),
        )

    def with_review_finding_count(self, count: int) -> "EnvironmentFileObservationRef":
        return EnvironmentFileObservationRef(
            file_observation_id=self.file_observation_id,
            environment_id=self.environment_id,
            classification=self.classification,
            observation_status_counts=dict(self.observation_status_counts),
            review_finding_count=count,
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "file_observation_id": self.file_observation_id,
            "environment_id": self.environment_id,
            "classification": self.classification,
            "observation_status_counts": copy.deepcopy(self.observation_status_counts),
            "review_finding_count": self.review_finding_count,
        }


@dataclass(frozen=True)
class EnvironmentReadinessPlanRef:
    readiness_plan_id: str
    declared_environment_id: str
    scope: Scope
    check_count: int
    check_state_counts: dict[str, int]
    claims: dict[str, str]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "EnvironmentReadinessPlanRef":
        claim_keys = set(EXPECTED_READINESS_PLAN_CLAIMS)
        allowed_keys = {
            "readiness_plan_id",
            "declared_environment_id",
            "scope",
            "check_count",
            "check_state_counts",
            *claim_keys,
        }
        _require_shape(value, allowed_keys, "readiness plan")
        claims = {key: value[key] for key in claim_keys}
        for key, expected in EXPECTED_READINESS_PLAN_CLAIMS.items():
            if claims[key] != expected:
                raise ValueError(f"readiness plan {key} must be {expected}")
        check_count = _required_non_negative_int(value, "check_count", "readiness plan")
        check_state_counts = _validate_count_map(
            value["check_state_counts"],
            allowed=READINESS_CHECK_STATE_COUNTS,
            owner="readiness plan check_state_counts",
        )
        if sum(check_state_counts.values()) != check_count:
            raise ValueError("readiness plan check_count must match check_state_counts")
        return cls(
            readiness_plan_id=_required_str(value, "readiness_plan_id", "readiness plan"),
            declared_environment_id=_required_str(
                value, "declared_environment_id", "readiness plan"
            ),
            scope=Scope.parse(value["scope"], owner="readiness plan"),
            check_count=check_count,
            check_state_counts=check_state_counts,
            claims=claims,
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "readiness_plan_id": self.readiness_plan_id,
            "declared_environment_id": self.declared_environment_id,
            "scope": self.scope.to_summary(),
            "check_count": self.check_count,
            "check_state_counts": copy.deepcopy(self.check_state_counts),
            "readiness_claim": self.claims["readiness_claim"],
            "sync_claim": self.claims["sync_claim"],
            "execution_claim": self.claims["execution_claim"],
            "hardware_claim": self.claims["hardware_claim"],
        }


@dataclass(frozen=True)
class EnvironmentReviewFinding:
    bundle_id: str
    source_kind: str
    source_id: str
    finding: str
    basis: str
    does_not_claim: str

    def to_summary(self) -> dict[str, str]:
        return {
            "bundle_id": self.bundle_id,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "severity": "review",
            "finding": self.finding,
            "basis": self.basis,
            "does_not_claim": self.does_not_claim,
        }


@dataclass(frozen=True)
class EnvironmentReviewBundle:
    bundle_id: str
    label: str
    selected_reference_id: str
    rerun_preparation: RerunPreparationRef
    prepared_context: PreparedRunContextRef
    reference_environment: EnvironmentContextRef
    current_environment: EnvironmentContextRef
    comparison: EnvironmentComparisonRef
    file_observation: EnvironmentFileObservationRef
    readiness_plan: EnvironmentReadinessPlanRef
    comparison_findings: tuple[EnvironmentReviewFinding, ...]
    file_observation_findings: tuple[EnvironmentReviewFinding, ...]
    readiness_findings: tuple[EnvironmentReviewFinding, ...]
    bundle_claim: str

    @classmethod
    def parse(
        cls,
        value: dict[str, Any],
        *,
        prepared_contexts: dict[str, dict[str, Any]],
        reruns: dict[str, dict[str, Any]],
        environments: dict[str, dict[str, Any]],
        comparisons: dict[str, dict[str, Any]],
        file_observations: dict[str, dict[str, Any]],
        readiness_plans: dict[str, dict[str, Any]],
    ) -> "EnvironmentReviewBundle":
        _require_shape(value, REVIEW_BUNDLE_KEYS, "environment review bundle")
        if value["bundle_claim"] != EXPECTED_BUNDLE_CLAIM:
            raise ValueError(f"environment review bundle claim must be {EXPECTED_BUNDLE_CLAIM}")

        prepared_context = PreparedRunContextRef.parse(
            _required(
                prepared_contexts,
                _required_str(value, "prepared_run_context_id", "environment review bundle"),
                "environment review bundle references missing prepared run context",
            )
        )
        rerun = RerunPreparationRef.parse(
            _required(
                reruns,
                _required_str(value, "rerun_preparation_id", "environment review bundle"),
                "environment review bundle references missing rerun preparation",
            )
        )
        reference_environment = EnvironmentContextRef.parse(
            _required(
                environments,
                _required_str(value, "reference_environment_id", "environment review bundle"),
                "environment review bundle references missing reference environment",
            )
        )
        current_environment = EnvironmentContextRef.parse(
            _required(
                environments,
                _required_str(value, "current_environment_id", "environment review bundle"),
                "environment review bundle references missing current environment",
            )
        )
        comparison = EnvironmentComparisonRef.parse(
            _required(
                comparisons,
                _required_str(value, "environment_comparison_id", "environment review bundle"),
                "environment review bundle references missing environment comparison",
            )
        )
        file_observation = EnvironmentFileObservationRef.parse(
            _required(
                file_observations,
                _required_str(
                    value, "environment_file_observation_id", "environment review bundle"
                ),
                "environment review bundle references missing file observation",
            )
        )
        readiness_plan = EnvironmentReadinessPlanRef.parse(
            _required(
                readiness_plans,
                _required_str(value, "environment_readiness_plan_id", "environment review bundle"),
                "environment review bundle references missing readiness plan",
            )
        )

        _validate_bundle_alignment(
            value,
            prepared_context=prepared_context,
            rerun=rerun,
            reference_environment=reference_environment,
            current_environment=current_environment,
            comparison=comparison,
            file_observation=file_observation,
            readiness_plan=readiness_plan,
        )

        return cls(
            bundle_id=_required_str(value, "bundle_id", "environment review bundle"),
            label=_required_str(value, "label", "environment review bundle"),
            selected_reference_id=_required_str(
                value, "selected_reference_id", "environment review bundle"
            ),
            rerun_preparation=rerun,
            prepared_context=prepared_context,
            reference_environment=reference_environment,
            current_environment=current_environment,
            comparison=comparison,
            file_observation=file_observation,
            readiness_plan=readiness_plan,
            comparison_findings=(),
            file_observation_findings=(),
            readiness_findings=(),
            bundle_claim=value["bundle_claim"],
        )

    def with_findings(
        self,
        *,
        comparison_findings: tuple[EnvironmentReviewFinding, ...],
        file_observation_findings: tuple[EnvironmentReviewFinding, ...],
        readiness_findings: tuple[EnvironmentReviewFinding, ...],
    ) -> "EnvironmentReviewBundle":
        return EnvironmentReviewBundle(
            bundle_id=self.bundle_id,
            label=self.label,
            selected_reference_id=self.selected_reference_id,
            rerun_preparation=self.rerun_preparation,
            prepared_context=self.prepared_context,
            reference_environment=self.reference_environment,
            current_environment=self.current_environment,
            comparison=self.comparison,
            file_observation=self.file_observation.with_review_finding_count(
                len(file_observation_findings)
            ),
            readiness_plan=self.readiness_plan,
            comparison_findings=comparison_findings,
            file_observation_findings=file_observation_findings,
            readiness_findings=readiness_findings,
            bundle_claim=self.bundle_claim,
        )

    def comparison_review_finding_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.comparison_findings:
            counts[finding.finding] = counts.get(finding.finding, 0) + 1
        return dict(sorted(counts.items()))

    def classification(self) -> str:
        if self.file_observation_findings:
            return "environment_review_has_file_observation_findings"
        if self.readiness_findings:
            return "environment_review_has_planned_check_findings"
        if self.comparison_findings:
            return "environment_review_has_declared_difference_findings"
        return "environment_review_has_no_review_findings"

    def to_summary(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "label": self.label,
            "selected_reference_id": self.selected_reference_id,
            "rerun_preparation_id": self.rerun_preparation.rerun_preparation_id,
            "prepared_run_context_id": self.prepared_context.prepared_run_context_id,
            "reference_environment_id": self.reference_environment.environment_id,
            "current_environment_id": self.current_environment.environment_id,
            "environment_comparison_id": self.comparison.comparison_id,
            "environment_file_observation_id": self.file_observation.file_observation_id,
            "environment_readiness_plan_id": self.readiness_plan.readiness_plan_id,
            "comparison_review_finding_counts": self.comparison_review_finding_counts(),
            "file_observation_finding_count": len(self.file_observation_findings),
            "readiness_finding_count": len(self.readiness_findings),
            "classification": self.classification(),
            "bundle_claim": self.bundle_claim,
        }

    def findings(self) -> tuple[EnvironmentReviewFinding, ...]:
        return (
            *self.comparison_findings,
            *self.file_observation_findings,
            *self.readiness_findings,
        )


@dataclass(frozen=True)
class EnvironmentReviewBundleContract:
    """Validated environment review bundle composition facts."""

    policy: EnvironmentReviewBundlePolicy
    bundles: tuple[EnvironmentReviewBundle, ...]

    def prepared_contexts(self) -> tuple[PreparedRunContextRef, ...]:
        return tuple(_unique_by_id(bundle.prepared_context for bundle in self.bundles))

    def rerun_preparations(self) -> tuple[RerunPreparationRef, ...]:
        return tuple(_unique_by_id(bundle.rerun_preparation for bundle in self.bundles))

    def environment_contexts(self) -> tuple[EnvironmentContextRef, ...]:
        environments = []
        for bundle in self.bundles:
            environments.append(bundle.reference_environment)
            environments.append(bundle.current_environment)
        return tuple(_unique_by_id(environments))

    def comparisons(self) -> tuple[EnvironmentComparisonRef, ...]:
        return tuple(_unique_by_id(bundle.comparison for bundle in self.bundles))

    def file_observations(self) -> tuple[EnvironmentFileObservationRef, ...]:
        self._validate_file_observation_classifications()
        return tuple(
            observation.with_review_finding_count(len(findings))
            for observation, findings in self._file_observation_finding_groups().values()
        )

    def _file_observation_finding_groups(
        self,
    ) -> dict[str, tuple[EnvironmentFileObservationRef, list[EnvironmentReviewFinding]]]:
        observations: dict[str, EnvironmentFileObservationRef] = {}
        finding_groups: dict[str, list[EnvironmentReviewFinding]] = {}
        for bundle in self.bundles:
            record_id = bundle.file_observation.file_observation_id
            observations.setdefault(record_id, bundle.file_observation)
            finding_groups.setdefault(record_id, []).extend(bundle.file_observation_findings)
        return {
            record_id: (observation, finding_groups.get(record_id, []))
            for record_id, observation in observations.items()
        }

    def _validate_file_observation_classifications(self) -> None:
        for observation, findings in self._file_observation_finding_groups().values():
            allowed_findings = FILE_OBSERVATION_CLASSIFICATION_FINDINGS[observation.classification]
            finding_codes = {finding.finding for finding in findings}
            if finding_codes and not finding_codes.issubset(allowed_findings):
                raise ValueError(
                    "environment file observation classification must match review findings"
                )
            if (
                not findings
                and observation.classification != "environment_files_observed_match_declared_facts"
            ):
                raise ValueError(
                    "environment file observation classification must match review findings"
                )
            if (
                findings
                and observation.classification == "environment_files_observed_match_declared_facts"
            ):
                raise ValueError(
                    "environment file observation classification must match review findings"
                )

    def validate(self) -> "EnvironmentReviewBundleContract":
        self._validate_file_observation_classifications()
        self._validate_file_observation_status_counts()
        return self

    def _validate_file_observation_status_counts(self) -> None:
        for observation, findings in self._file_observation_finding_groups().values():
            unavailable_count = observation.observation_status_counts.get("unavailable", 0)
            observed_count = observation.observation_status_counts.get("observed", 0)
            if (
                observation.classification == "environment_files_observed_match_declared_facts"
                and unavailable_count > 0
            ):
                raise ValueError(
                    "environment file observation status counts must match classification"
                )
            if (
                observation.classification
                in FILE_OBSERVATION_CLASSIFICATIONS_REQUIRING_OBSERVED_STATUS
                and (observed_count == 0 or unavailable_count > 0)
            ):
                raise ValueError(
                    "environment file observation status counts must match classification"
                )
            if (
                observation.classification == "environment_files_unavailable_for_review"
                and unavailable_count == 0
            ):
                raise ValueError(
                    "environment file observation status counts must match classification"
                )
            unavailable_findings = [
                finding
                for finding in findings
                if finding.finding in FILE_FINDINGS_REQUIRING_UNAVAILABLE_STATUS
            ]
            observed_findings = [
                finding
                for finding in findings
                if finding.finding in FILE_FINDINGS_REQUIRING_OBSERVED_STATUS
            ]
            if (
                unavailable_findings
                and observation.observation_status_counts.get("unavailable", 0) == 0
            ):
                raise ValueError("environment file observation status counts must match findings")
            if observed_findings and observation.observation_status_counts.get("observed", 0) == 0:
                raise ValueError("environment file observation status counts must match findings")

    def readiness_plans(self) -> tuple[EnvironmentReadinessPlanRef, ...]:
        return tuple(_unique_by_id(bundle.readiness_plan for bundle in self.bundles))

    def findings(self) -> tuple[EnvironmentReviewFinding, ...]:
        return tuple(finding for bundle in self.bundles for finding in bundle.findings())

    def finding_source_counts(self) -> dict[str, int]:
        counts = {
            "environment_comparison": 0,
            "environment_file_observation": 0,
            "environment_readiness_plan": 0,
        }
        for finding in self.findings():
            counts[finding.source_kind] += 1
        return counts


def _required(records: dict[str, Any], record_id: str, message: str) -> Any:
    if record_id not in records:
        raise ValueError(message)
    return records[record_id]


def _unique_by_id(records: Any) -> list[Any]:
    output = []
    seen = set()
    for record in records:
        record_id = _record_id(record)
        if record_id not in seen:
            output.append(record)
            seen.add(record_id)
    return output


def _record_id(record: Any) -> str:
    for attr in (
        "prepared_run_context_id",
        "rerun_preparation_id",
        "environment_id",
        "comparison_id",
        "file_observation_id",
        "readiness_plan_id",
    ):
        if hasattr(record, attr):
            return getattr(record, attr)
    raise TypeError(f"unsupported contract record type: {type(record)!r}")


def _require_shape(value: Any, expected_keys: set[str], owner: str) -> None:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ValueError(f"{owner} must match expected shape")


def _required_str(value: dict[str, Any], key: str, owner: str) -> str:
    if key not in value:
        raise ValueError(f"{owner} must match expected shape")
    item = value[key]
    if not isinstance(item, str) or not item:
        raise ValueError(f"{owner} {key} must be a non-empty string")
    return item


def _required_non_negative_int(value: dict[str, Any], key: str, owner: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ValueError(f"{owner} {key} must be a non-negative integer")
    return item


def _validate_count_map(value: Any, *, allowed: set[str], owner: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be a mapping")
    counts: dict[str, int] = {}
    for key, count in value.items():
        if key not in allowed:
            raise ValueError(f"{owner} has unsupported state: {key}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"{owner} values must be non-negative integers")
        counts[key] = count
    return counts


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError(f"{key} records must be a list")
    output = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"{key} record must be a mapping")
        record_key = _required_str(record, key, f"{key} record")
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _required_list(value: Any, owner: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{owner} must be a list")
    return value


def _validate_bundle_alignment(
    bundle: dict[str, Any],
    *,
    prepared_context: PreparedRunContextRef,
    rerun: RerunPreparationRef,
    reference_environment: EnvironmentContextRef,
    current_environment: EnvironmentContextRef,
    comparison: EnvironmentComparisonRef,
    file_observation: EnvironmentFileObservationRef,
    readiness_plan: EnvironmentReadinessPlanRef,
) -> None:
    if rerun.prepared_run_context_id != prepared_context.prepared_run_context_id:
        raise ValueError("rerun preparation must point at bundled prepared run context")
    if rerun.selected_reference_id != bundle["selected_reference_id"]:
        raise ValueError("rerun preparation selected reference must match bundle")
    if prepared_context.scope.prepared_run_context_id != prepared_context.prepared_run_context_id:
        raise ValueError("prepared run context scope must reference itself")
    if reference_environment.role != "selected_reference_environment":
        raise ValueError("reference environment role must match bundle")
    if current_environment.role != "current_environment":
        raise ValueError("current environment role must match bundle")
    if current_environment.scope != prepared_context.scope:
        raise ValueError("current environment scope must match prepared run context")
    if (
        reference_environment.scope.managed_code_version_id
        != bundle["reference_managed_code_version_id"]
    ):
        raise ValueError("reference environment must match bundled reference managed code version")
    if comparison.baseline_environment_id != reference_environment.environment_id:
        raise ValueError("environment comparison baseline must match bundled reference environment")
    if comparison.comparison_environment_id != current_environment.environment_id:
        raise ValueError(
            "environment comparison current side must match bundled current environment"
        )
    if file_observation.environment_id != current_environment.environment_id:
        raise ValueError("file observation must reference bundled current environment")
    if readiness_plan.declared_environment_id != current_environment.environment_id:
        raise ValueError("readiness plan must reference bundled current environment")
    if readiness_plan.scope != prepared_context.scope:
        raise ValueError("readiness plan scope must match prepared run context")


def _comparison_finding(
    value: dict[str, Any], bundle: EnvironmentReviewBundle
) -> tuple[str, EnvironmentReviewFinding | None]:
    _require_shape(value, COMPARISON_FINDING_KEYS, "comparison finding")
    if (
        _required_str(value, "comparison_id", "comparison finding")
        != bundle.comparison.comparison_id
    ):
        raise ValueError("comparison finding source must match bundled comparison")
    finding = _required_str(value, "finding", "comparison finding")
    basis = _required_str(value, "basis", "comparison finding")
    if finding in COMPARISON_FINDINGS_IGNORED_FOR_REVIEW:
        return COMPARISON_FINDING_STATES[finding], None
    if finding not in COMPARISON_FINDINGS_REQUIRING_REVIEW:
        raise ValueError("comparison finding is unsupported")
    return (
        COMPARISON_FINDING_STATES[finding],
        EnvironmentReviewFinding(
            bundle_id=bundle.bundle_id,
            source_kind="environment_comparison",
            source_id=bundle.comparison.comparison_id,
            finding=finding,
            basis=basis,
            does_not_claim="runtime_compatibility_or_runnable_readiness",
        ),
    )


def _file_observation_finding(
    value: dict[str, Any], bundle: EnvironmentReviewBundle
) -> EnvironmentReviewFinding:
    _require_shape(value, FILE_OBSERVATION_FINDING_KEYS, "file observation finding")
    if (
        _required_str(value, "file_observation_id", "file observation finding")
        != bundle.file_observation.file_observation_id
    ):
        raise ValueError("file observation finding source must match bundled observation")
    finding = _required_str(value, "finding", "file observation finding")
    if finding not in FILE_OBSERVATION_FINDINGS:
        raise ValueError("file observation finding is unsupported")
    expected_does_not_claim = FILE_FINDING_DOES_NOT_CLAIM[finding]
    does_not_claim = _required_str(value, "does_not_claim", "file observation finding")
    if does_not_claim != expected_does_not_claim:
        raise ValueError("file observation finding does_not_claim is unsupported")
    return EnvironmentReviewFinding(
        bundle_id=bundle.bundle_id,
        source_kind="environment_file_observation",
        source_id=bundle.file_observation.file_observation_id,
        finding=finding,
        basis=_required_str(value, "basis", "file observation finding"),
        does_not_claim=expected_does_not_claim,
    )


def _readiness_finding(
    value: dict[str, Any], bundle: EnvironmentReviewBundle
) -> EnvironmentReviewFinding:
    _require_shape(value, READINESS_FINDING_KEYS, "readiness finding")
    if (
        _required_str(value, "readiness_plan_id", "readiness finding")
        != bundle.readiness_plan.readiness_plan_id
    ):
        raise ValueError("readiness finding source must match bundled readiness plan")
    finding = _required_str(value, "finding", "readiness finding")
    if finding not in READINESS_FINDINGS:
        raise ValueError("readiness finding is unsupported")
    does_not_claim = _required_str(value, "does_not_claim", "readiness finding")
    if does_not_claim not in READINESS_FINDING_DOES_NOT_CLAIM[finding]:
        raise ValueError("readiness finding does_not_claim is unsupported")
    return EnvironmentReviewFinding(
        bundle_id=bundle.bundle_id,
        source_kind="environment_readiness_plan",
        source_id=bundle.readiness_plan.readiness_plan_id,
        finding=finding,
        basis=_required_str(value, "basis", "readiness finding"),
        does_not_claim=does_not_claim,
    )


def _attach_findings(
    bundles: dict[str, EnvironmentReviewBundle],
    source: dict[str, Any],
) -> tuple[EnvironmentReviewBundle, ...]:
    comparison_findings: dict[str, list[EnvironmentReviewFinding]] = {
        bundle_id: [] for bundle_id in bundles
    }
    comparison_state_counts: dict[str, dict[str, int]] = {bundle_id: {} for bundle_id in bundles}
    file_findings: dict[str, list[EnvironmentReviewFinding]] = {
        bundle_id: [] for bundle_id in bundles
    }
    readiness_findings: dict[str, list[EnvironmentReviewFinding]] = {
        bundle_id: [] for bundle_id in bundles
    }

    for value in _required_list(source["comparison_findings"], "comparison_findings"):
        bundle = _bundle_for_finding(bundles, value, "comparison finding")
        state, finding = _comparison_finding(value, bundle)
        comparison_state_counts[bundle.bundle_id][state] = (
            comparison_state_counts[bundle.bundle_id].get(state, 0) + 1
        )
        if finding is not None:
            comparison_findings[bundle.bundle_id].append(finding)
    for value in _required_list(source["file_observation_findings"], "file_observation_findings"):
        bundle = _bundle_for_finding(bundles, value, "file observation finding")
        file_findings[bundle.bundle_id].append(_file_observation_finding(value, bundle))
    for value in _required_list(source["readiness_findings"], "readiness_findings"):
        bundle = _bundle_for_finding(bundles, value, "readiness finding")
        readiness_findings[bundle.bundle_id].append(_readiness_finding(value, bundle))

    for bundle in bundles.values():
        _validate_comparison_state_counts(
            bundle.comparison.finding_state_counts,
            comparison_state_counts[bundle.bundle_id],
        )
        _validate_readiness_finding_counts(
            bundle.readiness_plan.check_state_counts,
            readiness_findings[bundle.bundle_id],
        )

    return tuple(
        bundle.with_findings(
            comparison_findings=tuple(comparison_findings[bundle.bundle_id]),
            file_observation_findings=tuple(file_findings[bundle.bundle_id]),
            readiness_findings=tuple(readiness_findings[bundle.bundle_id]),
        )
        for bundle in bundles.values()
    )


def _bundle_for_finding(
    bundles: dict[str, EnvironmentReviewBundle],
    finding: dict[str, Any],
    owner: str,
) -> EnvironmentReviewBundle:
    if not isinstance(finding, dict):
        raise ValueError(f"{owner} must match expected shape")
    bundle_id = _required_str(finding, "bundle_id", owner)
    if bundle_id not in bundles:
        raise ValueError(f"{owner} must reference bundled review bundle")
    return bundles[bundle_id]


def _validate_comparison_state_counts(
    expected_counts: dict[str, int],
    finding_counts: dict[str, int],
) -> None:
    normalized = {state: finding_counts.get(state, 0) for state in COMPARISON_STATE_COUNTS}
    if expected_counts != normalized:
        raise ValueError("environment comparison finding_state_counts must match findings")


def _validate_readiness_finding_counts(
    check_state_counts: dict[str, int],
    findings: list[EnvironmentReviewFinding],
) -> None:
    finding_counts = {state: 0 for state in READINESS_FINDING_STATES.values()}
    for finding in findings:
        state = READINESS_FINDING_STATES[finding.finding]
        finding_counts[state] += 1
    for state, count in finding_counts.items():
        if check_state_counts.get(state, 0) != count:
            raise ValueError("readiness plan check_state_counts must match findings")


def validate_environment_review_bundle_contract(
    source: dict[str, Any],
) -> EnvironmentReviewBundleContract:
    """Validate raw environment review bundle input before projection."""
    _require_shape(source, SOURCE_KEYS, "environment review bundle source")
    policy = EnvironmentReviewBundlePolicy.parse(source["environment_review_bundle_policy"])
    prepared_contexts = _records_by_key(source["prepared_run_contexts"], "prepared_run_context_id")
    reruns = _records_by_key(source["rerun_preparations"], "rerun_preparation_id")
    environments = _records_by_key(source["environment_contexts"], "environment_id")
    comparisons = _records_by_key(source["environment_comparisons"], "comparison_id")
    file_observations = _records_by_key(
        source["environment_file_observations"], "file_observation_id"
    )
    readiness_plans = _records_by_key(source["environment_readiness_plans"], "readiness_plan_id")

    _records_by_key(source["review_bundles"], "bundle_id")
    bundles = {
        value["bundle_id"]: EnvironmentReviewBundle.parse(
            value,
            prepared_contexts=prepared_contexts,
            reruns=reruns,
            environments=environments,
            comparisons=comparisons,
            file_observations=file_observations,
            readiness_plans=readiness_plans,
        )
        for value in source["review_bundles"]
    }

    return EnvironmentReviewBundleContract(
        policy=policy,
        bundles=_attach_findings(bundles, source),
    ).validate()
