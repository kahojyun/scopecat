"""Runner adapter snapshots and boundary manifests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat._boundary import plan_boundary_summary
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import PlanSnapshot
from scopecat.models.artifact import Artifact
from scopecat.models.run import RunManifest

RUNNER_ADAPTER_RUN_SNAPSHOT_SCHEMA_VERSION = "scopecat.runner_adapter_run_snapshot.v0"
RUNNER_ADAPTER_BOUNDARY_MANIFEST_SCHEMA_VERSION = (
    "scopecat.runner_adapter_boundary_manifest.v1"
)


class RunnerAdapterRunSnapshot(BaseModel):
    """Persisted result for an in-process runner adapter execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = RUNNER_ADAPTER_RUN_SNAPSHOT_SCHEMA_VERSION
    run_id: str
    experiment_id: str
    runner_id: str
    dry_run: bool
    status: str
    adapter_id: str
    adapter_version: str
    point_count: int
    measurement_count: int
    data_ref: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    plan: PlanSnapshot


class RunnerAdapterBoundaryManifest(BaseModel):
    """Persisted boundary record for runner adapter translation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.runner_adapter_boundary_manifest.v1"] = (
        RUNNER_ADAPTER_BOUNDARY_MANIFEST_SCHEMA_VERSION
    )
    run_id: str
    status: str
    runner_id: str
    adapter_id: str
    adapter_version: str
    plan_schema_version: str
    plan_content_hash: str
    config_profile_ref: str
    plan_ref: str
    desired_state_count: int
    state_patch_count: int
    acquisition_kind: str
    acquisition_record: str
    result_intent_count: int
    expected_dataset_schema_id: str | None = None
    measurement_dataset_ref: str
    adapter_artifact_refs: list[str] = Field(default_factory=list)
    adapter_artifacts: list[Artifact] = Field(default_factory=list)
    event_count: int
    point_count: int
    measurement_count: int
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_runner_adapter_boundary_manifest(
    *,
    manifest: RunManifest,
    snapshot: RunnerAdapterRunSnapshot,
    plan: PlanSnapshot,
    adapter_artifacts: Sequence[Artifact],
    event_count: int,
) -> RunnerAdapterBoundaryManifest:
    plan_summary = plan_boundary_summary(plan)
    return RunnerAdapterBoundaryManifest(
        run_id=manifest.run_id,
        status=manifest.status,
        runner_id=manifest.runner_id,
        adapter_id=snapshot.adapter_id,
        adapter_version=snapshot.adapter_version,
        plan_schema_version=plan_summary.schema_version,
        plan_content_hash=plan_summary.content_hash,
        config_profile_ref=manifest.config_profile_snapshot_ref,
        plan_ref=manifest.plan_snapshot_ref,
        desired_state_count=plan_summary.desired_state_count,
        state_patch_count=plan_summary.state_patch_count,
        acquisition_kind=plan_summary.acquisition_kind,
        acquisition_record=plan_summary.acquisition_record,
        result_intent_count=plan_summary.result_intent_count,
        expected_dataset_schema_id=plan_summary.expected_dataset_schema_id,
        measurement_dataset_ref=snapshot.data_ref,
        adapter_artifact_refs=[artifact.path for artifact in adapter_artifacts],
        adapter_artifacts=list(adapter_artifacts),
        event_count=event_count,
        point_count=snapshot.point_count,
        measurement_count=snapshot.measurement_count,
        diagnostics=list(snapshot.diagnostics),
        metadata=dict(snapshot.metadata),
    )
