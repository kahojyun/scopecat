"""Dry-run orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scopecat._execution import (
    ref_for_artifact,
    write_final_execution_artifacts,
    write_planned_run_inputs,
)
from scopecat._storage import ARTIFACTS_DIR
from scopecat._storage.local import LocalRunStore
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    DryRunSnapshot,
    ExperimentSpec,
    plan_experiment,
)
from scopecat.ids import new_run_id
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionProfile
from scopecat.models.run import RunEvent, RunManifest
from scopecat.planning.validation import (
    has_blocking_diagnostics,
    validate_config,
)


def execute_dry_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentSpec,
    workspace: str | Path,
) -> tuple[RunManifest, DryRunSnapshot]:
    workspace_path = Path(workspace)
    execution = ExecutionProfile(runner_id="scopecat.planner", dry_run=True)
    diagnostics = validate_config(config)
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    if config.parameter_build is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "blocker",
                    "missing_parameter_build_snapshot",
                    "dry-run requires a parameter build snapshot",
                    "parameter_build",
                )
            ]
        )

    run_id = new_run_id()
    plan = plan_experiment(experiment, config.parameter_build)
    dry_run = DryRunSnapshot(
        run_id=run_id,
        experiment_id=experiment.id,
        runner_id=execution.runner_id,
        dry_run=execution.dry_run,
        status="completed",
        point_count=len(plan.points),
        required_runners=[execution.runner_id],
        diagnostics=plan.diagnostics,
        plan=plan,
    )
    artifact_refs = [
        Artifact(
            id="dry-run-summary",
            kind="summary",
            path=f"{ARTIFACTS_DIR}/dry-run.summary.md",
            media_type="text/markdown",
        ),
        Artifact(
            id="dry-run-snapshot",
            kind="dry_run_snapshot",
            path=f"{ARTIFACTS_DIR}/dry-run.snapshot.json",
            media_type="application/json",
        ),
    ]
    manifest = RunManifest(
        run_id=run_id,
        status="completed",
        runner_id=execution.runner_id,
        dry_run=execution.dry_run,
        workspace_ref=config.workspace_id,
        device_ref=config.device_under_test_id,
        experiment_ref=experiment.id,
        config_profile_snapshot_ref="config-profile.snapshot.json",
        plan_snapshot_ref="plan.snapshot.json",
        runner_versions={execution.runner_id: "v0"},
        events_ref="events.jsonl",
        artifact_refs=artifact_refs,
        finalization_summary="Dry-run completed without hardware access.",
    )
    events = [
        RunEvent(
            event_type="dry_run_recorded",
            message="Dry-run snapshot persisted without hardware access.",
        )
    ]
    summary = render_dry_run_summary(manifest=manifest, dry_run=dry_run)
    storage = LocalRunStore(workspace_path)
    write_planned_run_inputs(
        storage=storage,
        manifest=manifest,
        config=config,
        plan=plan,
    )
    write_final_execution_artifacts(
        storage=storage,
        manifest=manifest,
        snapshot_ref=ref_for_artifact("dry-run.snapshot.json"),
        snapshot=dry_run,
        summary_ref=ref_for_artifact("dry-run.summary.md"),
        summary=summary,
        data_ref=None,
        events=events,
    )
    return manifest, dry_run


def _diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(
        severity=severity,
        code=code,
        message=message,
        path=path,
    )


def render_dry_run_summary(
    *,
    manifest: RunManifest,
    dry_run: DryRunSnapshot,
) -> str:
    plan = dry_run.plan
    return "\n".join(
        [
            "# Scopecat Dry-Run Summary",
            "",
            f"- Run ID: {manifest.run_id}",
            f"- Experiment: {manifest.experiment_ref}",
            f"- Workspace: {manifest.workspace_ref}",
            f"- Device: {manifest.device_ref}",
            f"- Runner: {manifest.runner_id}",
            f"- Dry-run: {str(manifest.dry_run).lower()}",
            f"- Status: {manifest.status}",
            f"- Points: {dry_run.point_count}",
            f"- Parameter patches: {len(plan.parameter_patches)}",
            f"- Desired-state records: {len(plan.desired_state)}",
            f"- State patch changes: {len(plan.state_patches)}",
            f"- Acquisition: {_acquisition_summary(dry_run)}",
            f"- Result intents: {len(plan.result_intents)}",
            f"- Dataset coordinates: {_dataset_coordinates(dry_run)}",
            f"- Dataset observables: {_dataset_observables(dry_run)}",
            f"- Diagnostics: {len(plan.diagnostics)}",
            "",
            "## Points",
            "",
            _point_preview(dry_run),
            "",
            "## Parameter Patches",
            "",
            _parameter_patch_preview(dry_run),
            "",
            "## Desired State",
            "",
            _desired_state_preview(dry_run),
            "",
            "## Result Intents",
            "",
            _result_intent_preview(dry_run),
            "",
            "## Diagnostics",
            "",
            _diagnostic_lines(plan.diagnostics),
            "",
        ]
    )


def _acquisition_summary(dry_run: DryRunSnapshot) -> str:
    acquisition = dry_run.plan.acquisition
    dimensions = ", ".join(acquisition.dimensions) if acquisition.dimensions else "none"
    channels = ", ".join(acquisition.channels) if acquisition.channels else "none"
    return (
        f"{acquisition.estimated_records} records "
        f"({acquisition.kind}, record={acquisition.record}, "
        f"shots={acquisition.shots}, repetitions={acquisition.repetitions}, "
        f"dimensions={dimensions}, channels={channels})"
    )


def _point_preview(dry_run: DryRunSnapshot) -> str:
    if not dry_run.plan.points:
        return "- none"
    lines = [
        f"- point {point.point_id}: {_mapping(point.row)}"
        for point in dry_run.plan.points[:3]
    ]
    if len(dry_run.plan.points) > 3:
        lines.append(f"- ... {len(dry_run.plan.points) - 3} more")
    return "\n".join(lines)


def _parameter_patch_preview(dry_run: DryRunSnapshot) -> str:
    if not dry_run.plan.parameter_patches:
        return "- none"
    lines: list[str] = []
    for record in dry_run.plan.parameter_patches[:3]:
        patch = record.patch
        patch_ref = patch.parameter_id or patch.table_id or "unknown"
        key = patch.key or {}
        values = patch.values or (
            {"value": patch.value} if patch.value is not None else {}
        )
        lines.append(
            f"- point {record.point_id}: {patch.kind} {patch_ref} "
            f"key={_mapping(key)} values={_mapping(values)} "
            f"affected_rows={len(record.affected_rows)}"
        )
    if len(dry_run.plan.parameter_patches) > 3:
        lines.append(f"- ... {len(dry_run.plan.parameter_patches) - 3} more")
    return "\n".join(lines)


def _desired_state_preview(dry_run: DryRunSnapshot) -> str:
    if not dry_run.plan.desired_state:
        return "- none"
    lines = [
        (
            f"- point {record.point_id}: {record.resource}.{record.field} "
            f"= {_value(record.value)}"
        )
        for record in dry_run.plan.desired_state[:3]
    ]
    if len(dry_run.plan.desired_state) > 3:
        lines.append(f"- ... {len(dry_run.plan.desired_state) - 3} more")
    return "\n".join(lines)


def _result_intent_preview(dry_run: DryRunSnapshot) -> str:
    if not dry_run.plan.result_intents:
        return "- none"
    lines = [
        (
            f"- {intent.id}: {intent.kind}, record={intent.record}, "
            f"estimated_records={intent.estimated_records}"
        )
        for intent in dry_run.plan.result_intents[:3]
    ]
    if len(dry_run.plan.result_intents) > 3:
        lines.append(f"- ... {len(dry_run.plan.result_intents) - 3} more")
    return "\n".join(lines)


def _dataset_coordinates(dry_run: DryRunSnapshot) -> str:
    schema = dry_run.plan.expected_dataset_schema
    if schema is None:
        return (
            ", ".join(dry_run.plan.point_coordinate_ids)
            if dry_run.plan.point_coordinate_ids
            else "none"
        )
    if not schema.primary_coordinates:
        return "none"
    return ", ".join(schema.primary_coordinates)


def _dataset_observables(dry_run: DryRunSnapshot) -> str:
    schema = dry_run.plan.expected_dataset_schema
    if schema is None or not schema.primary_observables:
        return "none"
    return ", ".join(schema.primary_observables)


def _diagnostic_lines(diagnostics: list[dict[str, Any]]) -> str:
    if not diagnostics:
        return "- none"
    lines: list[str] = []
    for diagnostic in diagnostics:
        severity = diagnostic.get("severity", "unknown")
        code = diagnostic.get("code", "unknown")
        message = diagnostic.get("message", "")
        path = diagnostic.get("path")
        location = f" ({path})" if path else ""
        lines.append(f"- {severity}: {code}{location} - {message}")
    return "\n".join(lines)


def _mapping(values: dict[str, Any]) -> str:
    if not values:
        return "{}"
    return ", ".join(f"{key}={_value(value)}" for key, value in values.items())


def _value(value: Any) -> str:
    quantity_value = getattr(value, "value", None)
    quantity_unit = getattr(value, "unit", None)
    if quantity_unit is not None:
        return f"{quantity_value} {quantity_unit}"
    return str(value)
