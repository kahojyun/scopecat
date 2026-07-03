"""Run execution and run artifact workflow use cases."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from scopecat.authoring import (
    ResolvedExperiment,
    resolve_experiment_with_config,
)
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, PlanSnapshot, plan_experiment
from scopecat.instruments import execute_run
from scopecat.instruments.sdk import (
    InstrumentProvider,
    InstrumentProviderContext,
)
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunManifest
from scopecat.planning.validation import has_blocking_diagnostics, validate_config
from scopecat.results import MeasurementDatasetInputDiagnostics
from scopecat.runs import (
    list_artifacts,
    open_run_store,
    read_artifact_bytes,
    read_artifact_json,
    read_artifact_text,
    read_data_array_artifact,
    read_data_table_artifact,
    read_measurement_dataset,
    require_artifact,
)
from scopecat.workflows._diagnostics import diagnostic as _diagnostic
from scopecat.workflows._types import (
    ConfigProfileInput,
    ExperimentInput,
    PreviewExperimentResult,
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunDetails,
    RunMeasurementDatasetResult,
    ValidateExperimentResult,
)
from scopecat.workflows.config import resolve_config_source


def list_runs(*, workspace: str | Path) -> list[RunManifest]:
    storage = open_run_store(workspace)
    return storage.list_runs()


def load_run(*, run_id: str, workspace: str | Path) -> RunDetails:
    storage = open_run_store(workspace)
    return RunDetails(
        manifest=storage.read_manifest(run_id),
        config=storage.read_config_profile_snapshot(run_id),
        plan=storage.read_plan_snapshot(run_id),
    )


def list_run_artifacts(
    *, run_id: str, workspace: str | Path, kind: str | None = None
) -> tuple[Artifact, ...]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    return list_artifacts(manifest, kind=kind)


def read_run_artifact_text(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    expected_kind: str | None = None,
) -> RunArtifactTextResult:
    storage = open_run_store(workspace)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    if not _artifact_supports_text(artifact):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "unsupported_artifact_media_type",
                    "unsupported artifact media type: "
                    f"{_artifact_media_label(artifact)}",
                    "artifact",
                )
            ]
        )
    return RunArtifactTextResult(
        artifact=artifact,
        content=read_artifact_text(
            storage=storage,
            run_id=run_id,
            selector=selector,
            expected_kind=expected_kind,
        ),
    )


def read_run_artifact_json(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    expected_kind: str | None = None,
) -> RunArtifactJsonResult:
    storage = open_run_store(workspace)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return RunArtifactJsonResult(
        artifact=artifact,
        content=read_artifact_json(
            storage=storage,
            run_id=run_id,
            selector=selector,
            expected_kind=expected_kind,
        ),
    )


def read_run_artifact_bytes(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    expected_kind: str | None = None,
) -> RunArtifactBytesResult:
    storage = open_run_store(workspace)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return RunArtifactBytesResult(
        artifact=artifact,
        content=read_artifact_bytes(
            storage=storage,
            run_id=run_id,
            selector=selector,
            expected_kind=expected_kind,
        ),
    )


def read_run_measurement_dataset(
    *,
    run_id: str,
    workspace: str | Path,
    selector: str = "raw-measurements",
) -> RunMeasurementDatasetResult:
    storage = open_run_store(workspace)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="measurement_dataset",
    )
    dataset = read_measurement_dataset(
        storage=storage,
        run_id=run_id,
        artifact=artifact,
        diagnostics=MeasurementDatasetInputDiagnostics(
            missing_code="run_measurement_dataset_missing",
            empty_code="run_measurement_dataset_empty",
            invalid_code="run_measurement_dataset_invalid",
            missing_schema_code="run_measurement_dataset_missing_schema",
            invalid_schema_code="run_measurement_dataset_invalid_schema",
            noun="run measurement dataset",
            diagnostic_path=artifact.path,
        ),
    )
    return RunMeasurementDatasetResult(artifact=artifact, dataset=dataset)


def read_run_data_table(
    *, run_id: str, selector: str, workspace: str | Path
) -> RunDataTableResult:
    storage = open_run_store(workspace)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="data_table",
    )
    return RunDataTableResult(
        artifact=artifact,
        table=read_data_table_artifact(
            storage=storage,
            run_id=run_id,
            selector=selector,
        ),
    )


def read_run_data_array(
    *, run_id: str, selector: str, workspace: str | Path
) -> RunDataArrayResult:
    storage = open_run_store(workspace)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="data_array",
    )
    return RunDataArrayResult(
        artifact=artifact,
        array=read_data_array_artifact(
            storage=storage,
            run_id=run_id,
            selector=selector,
        ),
    )


def start_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInput,
    workspace: str | Path,
    instrument_provider: InstrumentProvider | None = None,
) -> RunManifest:
    experiment, _ = _resolve_experiment_input(
        experiment,
        config=config,
        workspace=workspace,
    )
    if instrument_provider is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_instrument_provider",
                    "run execution requires an explicit instrument provider",
                    "instrument_provider",
                )
            ]
        )
    provider_result = instrument_provider.provide(
        InstrumentProviderContext(config=config, experiment=experiment)
    )
    diagnostics = list(provider_result.diagnostics)
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    manifest, _ = execute_run(
        config=config,
        experiment=experiment,
        instruments=list(provider_result.instruments),
        workspace=workspace,
    )
    return manifest


def run_experiment(
    experiment: ExperimentInput,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    instrument_provider: InstrumentProvider | None = None,
) -> RunManifest:
    config_snapshot = _resolve_config_snapshot(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )
    return start_run(
        config=config_snapshot,
        experiment=experiment,
        workspace=workspace,
        instrument_provider=instrument_provider,
    )


def validate_experiment(
    experiment: ExperimentInput,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
) -> ValidateExperimentResult:
    config_snapshot = _resolve_config_snapshot(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )
    experiment, resolved = _resolve_experiment_input(
        experiment,
        config=config_snapshot,
        workspace=workspace,
    )
    diagnostics = list(validate_config(config_snapshot))
    plan = None
    if config_snapshot.parameter_build is None:
        diagnostics.append(
            _diagnostic(
                "blocker",
                "missing_parameter_build_snapshot",
                "experiment validation requires a parameter build snapshot",
                "parameter_build",
            )
        )
    if not has_blocking_diagnostics(diagnostics):
        assert config_snapshot.parameter_build is not None
        plan = plan_experiment(experiment, config_snapshot.parameter_build)
        diagnostics.extend(_plan_diagnostics(plan))
    return ValidateExperimentResult(
        experiment=experiment,
        config=config_snapshot,
        diagnostics=tuple(diagnostics),
        plan=plan,
        resolved_experiment=resolved,
    )


def preview_experiment(
    experiment: ExperimentInput,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
) -> PreviewExperimentResult:
    validation = validate_experiment(
        experiment,
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )
    if not validation.ok:
        raise ValidationFailed(list(validation.diagnostics))
    assert validation.plan is not None
    return PreviewExperimentResult(
        experiment=validation.experiment,
        config=validation.config,
        plan=validation.plan,
        diagnostics=validation.diagnostics,
        resolved_experiment=validation.resolved_experiment,
    )


def _resolve_config_snapshot(
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot,
    config_profile: ConfigProfileInput | None,
) -> ConfigProfileSnapshot:
    if isinstance(config, ConfigProfileSnapshot):
        if config_profile is not None:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "conflicting_experiment_run_config_source",
                        "provide either config or config_profile, not both",
                        "config",
                    )
                ]
            )
        return config
    config_entry = None if config_profile is not None and config == "active" else config
    return resolve_config_source(
        workspace=workspace,
        config_profile=config_profile,
        config_entry=config_entry,
    ).config


def _resolve_experiment_input(
    experiment: ExperimentInput,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
) -> tuple[ExperimentSpec, ResolvedExperiment | None]:
    if isinstance(experiment, ExperimentSpec):
        return experiment, None
    resolved = resolve_experiment_with_config(
        experiment,
        config=config,
        workspace=workspace,
    )
    return resolved.experiment, resolved


def _plan_diagnostics(plan: PlanSnapshot) -> list[Diagnostic]:
    return [Diagnostic.model_validate(diagnostic) for diagnostic in plan.diagnostics]


def _artifact_supports_text(artifact: Artifact) -> bool:
    media_type = artifact.media_type
    if media_type is not None and (
        media_type.startswith("text/")
        or media_type in {"application/json", "application/x-ndjson"}
    ):
        return True
    return PurePosixPath(artifact.path).suffix in {".md", ".json", ".jsonl"}


def _artifact_media_label(artifact: Artifact) -> str:
    if artifact.media_type is None:
        return "unknown"
    return artifact.media_type
