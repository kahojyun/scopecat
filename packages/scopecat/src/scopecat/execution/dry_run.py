"""Dry-run orchestration."""

from __future__ import annotations

from pathlib import Path

from scopecat._execution import (
    ref_for_artifact,
    write_final_execution_artifacts,
    write_planned_run_inputs,
)
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
    snapshot_ref = ref_for_artifact("dry-run.snapshot.json")
    artifact_refs = [
        Artifact(
            id="dry-run-snapshot",
            kind="dry_run_snapshot",
            path=snapshot_ref,
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
        snapshot_ref=snapshot_ref,
        snapshot=dry_run,
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
