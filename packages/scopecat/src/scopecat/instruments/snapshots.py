"""Native run snapshots and summaries."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat._boundary import plan_boundary_summary
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import PlanSnapshot
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentStateSnapshot,
)
from scopecat.models.run import RunManifest

NATIVE_RUN_SNAPSHOT_SCHEMA_VERSION = "scopecat.native_run_snapshot.v0"
NATIVE_BOUNDARY_MANIFEST_SCHEMA_VERSION = "scopecat.native_boundary_manifest.v1"


class NativePointSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_index: int
    changed_field_count: int
    acquired_record_count: int


class NativeRunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_RUN_SNAPSHOT_SCHEMA_VERSION
    run_id: str
    experiment_id: str
    runner_id: str
    status: str
    instrument_ids: list[str]
    descriptions: list[InstrumentDescription] = Field(default_factory=list)
    initial_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    point_count: int
    measurement_count: int
    data_ref: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    points: list[NativePointSnapshot] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    plan: PlanSnapshot


class NativeBoundaryManifest(BaseModel):
    """Persisted boundary record for native execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.native_boundary_manifest.v1"] = (
        NATIVE_BOUNDARY_MANIFEST_SCHEMA_VERSION
    )
    run_id: str
    status: str
    runner_id: str
    instrument_ids: list[str] = Field(default_factory=list)
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
    event_count: int
    point_count: int
    measurement_count: int
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_native_boundary_manifest(
    *,
    manifest: RunManifest,
    snapshot: NativeRunSnapshot,
    plan: PlanSnapshot,
    event_count: int,
) -> NativeBoundaryManifest:
    plan_summary = plan_boundary_summary(plan)
    return NativeBoundaryManifest(
        run_id=manifest.run_id,
        status=manifest.status,
        runner_id=manifest.runner_id,
        instrument_ids=list(snapshot.instrument_ids),
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
        event_count=event_count,
        point_count=snapshot.point_count,
        measurement_count=snapshot.measurement_count,
        diagnostics=list(snapshot.diagnostics),
        metadata=dict(snapshot.metadata),
    )


def render_native_run_summary(
    *, manifest: RunManifest, snapshot: NativeRunSnapshot
) -> str:
    diagnostics = snapshot.diagnostics
    diagnostic_lines = (
        "\n".join(
            f"- {item.severity}: {item.code} - {item.message}" for item in diagnostics
        )
        if diagnostics
        else "- none"
    )
    patch_count = sum(point.changed_field_count for point in snapshot.points)
    acquired_count = sum(point.acquired_record_count for point in snapshot.points)
    instruments = ", ".join(snapshot.instrument_ids) if snapshot.instrument_ids else "-"
    return "\n".join(
        [
            "# Scopecat Native Run Summary",
            "",
            f"- Run ID: {manifest.run_id}",
            f"- Experiment: {manifest.experiment_ref}",
            f"- Workspace: {manifest.workspace_ref}",
            f"- Device: {manifest.device_ref}",
            f"- Runner: {manifest.runner_id}",
            f"- Status: {manifest.status}",
            f"- Instruments: {instruments}",
            f"- Points: {snapshot.point_count}",
            f"- Changed fields: {patch_count}",
            f"- Acquired records: {acquired_count}",
            f"- Measurements: {snapshot.measurement_count}",
            f"- Data: {snapshot.data_ref}",
            "",
            "## Diagnostics",
            "",
            diagnostic_lines,
            "",
        ]
    )
