"""Run execution and run artifact workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scopecat.authoring import (
    resolve_experiment_with_config,
)
from scopecat.errors import ValidationFailed
from scopecat.execution.dry_run import (
    execute_dry_run as execute_planned_dry_run,
)
from scopecat.experiments import ExperimentSpec
from scopecat.instruments import execute_native_run
from scopecat.instruments.sdk import (
    NativeInstrumentProvider,
    NativeInstrumentProviderContext,
)
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.results import MeasurementDatasetInputDiagnostics
from scopecat.runner import RunnerAdapter, execute_runner_adapter
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
    RoutineRunExecutor,
    RoutineRunStart,
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunArtifactView,
    RunDataArrayResult,
    RunDataTableResult,
    RunDetails,
    RunMeasurementDatasetResult,
    RunMode,
    RunSummaryView,
    StartRunResult,
)
from scopecat.workflows.config import resolve_config_source


@dataclass(frozen=True)
class _RunModeExecutor:
    mode: RunMode
    native_instrument_provider: NativeInstrumentProvider | None = None

    @property
    def id(self) -> str:
        return self.mode

    def start(
        self,
        *,
        config: ConfigProfileSnapshot,
        experiment: ExperimentInput,
        workspace: str | Path,
    ) -> StartRunResult:
        return start_run(
            mode=self.mode,
            config=config,
            experiment=experiment,
            workspace=workspace,
            native_instrument_provider=self.native_instrument_provider,
        )


@dataclass(frozen=True)
class _NativeRunExecutor:
    instrument_provider: NativeInstrumentProvider

    @property
    def id(self) -> str:
        return self.instrument_provider.provider_id

    def start(
        self,
        *,
        config: ConfigProfileSnapshot,
        experiment: ExperimentInput,
        workspace: str | Path,
    ) -> StartRunResult:
        return start_run(
            mode="native_simulate",
            config=config,
            experiment=experiment,
            workspace=workspace,
            native_instrument_provider=self.instrument_provider,
        )


@dataclass(frozen=True)
class _RunnerAdapterRunExecutor:
    adapter: RunnerAdapter

    @property
    def id(self) -> str:
        return self.adapter.adapter_id

    def start(
        self,
        *,
        config: ConfigProfileSnapshot,
        experiment: ExperimentInput,
        workspace: str | Path,
    ) -> StartRunResult:
        return start_runner_adapter_run(
            config=config,
            experiment=experiment,
            adapter=self.adapter,
            workspace=workspace,
        )


@dataclass(frozen=True)
class _CallableRunExecutor:
    executor_id: str
    start_fn: RoutineRunStart

    @property
    def id(self) -> str:
        return self.executor_id

    def start(
        self,
        *,
        config: ConfigProfileSnapshot,
        experiment: ExperimentInput,
        workspace: str | Path,
    ) -> StartRunResult:
        if isinstance(experiment, ExperimentSpec):
            return self.start_fn(
                config=config,
                experiment=experiment,
                workspace=workspace,
            )
        resolved = resolve_experiment_with_config(
            experiment,
            config=config,
            workspace=workspace,
        )
        result = self.start_fn(
            config=config,
            experiment=resolved.experiment,
            workspace=workspace,
        )
        if result.resolved_experiment is not None:
            return result
        return StartRunResult(
            manifest=result.manifest,
            snapshot=result.snapshot,
            data_ref=result.data_ref,
            resolved_experiment=resolved,
        )


def list_runs(*, workspace: str | Path) -> list[RunSummaryView]:
    storage = open_run_store(workspace)
    return [RunSummaryView(manifest=manifest) for manifest in storage.list_runs()]


def load_run(*, run_id: str, workspace: str | Path) -> RunDetails:
    storage = open_run_store(workspace)
    return RunDetails(
        manifest=storage.read_manifest(run_id),
        config=storage.read_config_profile_snapshot(run_id),
        plan=storage.read_plan_snapshot(run_id),
    )


def list_run_artifacts(
    *, run_id: str, workspace: str | Path, kind: str | None = None
) -> list[RunArtifactView]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    return [
        RunArtifactView(artifact=artifact)
        for artifact in list_artifacts(manifest, kind=kind)
    ]


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


def start_dry_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInput,
    workspace: str | Path,
) -> StartRunResult:
    if isinstance(experiment, ExperimentSpec):
        manifest, snapshot = execute_planned_dry_run(
            config=config,
            experiment=experiment,
            workspace=workspace,
        )
        return StartRunResult(manifest=manifest, snapshot=snapshot)

    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "unsupported_dry_run_experiment_input",
                "dry-run requires an ExperimentSpec",
                "experiment",
            )
        ]
    )


def start_run(
    *,
    mode: RunMode,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInput,
    workspace: str | Path,
    native_instrument_provider: NativeInstrumentProvider | None = None,
) -> StartRunResult:
    if isinstance(experiment, ExperimentSpec):
        if mode == "dry":
            return start_dry_run(
                config=config,
                experiment=experiment,
                workspace=workspace,
            )
        if mode == "native_simulate":
            return start_native_run(
                config=config,
                experiment=experiment,
                workspace=workspace,
                instrument_provider=native_instrument_provider,
            )
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "unsupported_run_mode",
                    f"Experiment specs do not support run mode {mode}",
                    "mode",
                )
            ]
        )
    if mode == "dry":
        resolved = resolve_experiment_with_config(
            experiment,
            config=config,
            workspace=workspace,
        )
        dry_result = start_dry_run(
            config=config,
            experiment=resolved.experiment,
            workspace=workspace,
        )
        return StartRunResult(
            manifest=dry_result.manifest,
            snapshot=dry_result.snapshot,
            data_ref=dry_result.data_ref,
            resolved_experiment=resolved,
        )
    resolved = resolve_experiment_with_config(
        experiment,
        config=config,
        workspace=workspace,
    )
    experiment_spec = resolved.experiment
    if mode == "native_simulate":
        native_result = start_native_run(
            config=config,
            experiment=experiment_spec,
            workspace=workspace,
            instrument_provider=native_instrument_provider,
        )
        return StartRunResult(
            manifest=native_result.manifest,
            snapshot=native_result.snapshot,
            data_ref=native_result.data_ref,
            resolved_experiment=resolved,
        )
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "unsupported_run_mode",
                f"unsupported run mode {mode}",
                "mode",
            )
        ]
    )


def start_native_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInput,
    workspace: str | Path,
    instrument_provider: NativeInstrumentProvider | None = None,
) -> StartRunResult:
    if instrument_provider is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_native_instrument_provider",
                    "native execution requires an explicit instrument provider",
                    "instrument_provider",
                )
            ]
        )
    if isinstance(experiment, ExperimentSpec):
        provider_result = instrument_provider.provide(
            NativeInstrumentProviderContext(config=config, experiment=experiment)
        )
        diagnostics = list(provider_result.diagnostics)
        if has_blocking_diagnostics(diagnostics):
            raise ValidationFailed(diagnostics)
        manifest, snapshot = execute_native_run(
            config=config,
            experiment=experiment,
            instruments=list(provider_result.instruments),
            workspace=workspace,
        )
        return StartRunResult(
            manifest=manifest,
            snapshot=snapshot,
            data_ref=snapshot.data_ref,
        )
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "unsupported_native_experiment_input",
                "native execution requires an ExperimentSpec",
                "experiment",
            )
        ]
    )


def start_runner_adapter_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentInput,
    adapter: RunnerAdapter,
    workspace: str | Path,
) -> StartRunResult:
    if isinstance(experiment, ExperimentSpec):
        manifest, snapshot = execute_runner_adapter(
            config=config,
            experiment=experiment,
            adapter=adapter,
            workspace=workspace,
        )
        return StartRunResult(
            manifest=manifest,
            snapshot=snapshot,
            data_ref=snapshot.data_ref,
        )
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "unsupported_runner_adapter_experiment_input",
                "runner adapter execution requires an ExperimentSpec",
                "experiment",
            )
        ]
    )


def run_experiment(
    experiment: ExperimentInput,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    mode: RunMode = "dry",
    native_instrument_provider: NativeInstrumentProvider | None = None,
) -> StartRunResult:
    if isinstance(config, ConfigProfileSnapshot):
        config_snapshot = config
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
    else:
        config_entry = (
            None if config_profile is not None and config == "active" else config
        )
        source = resolve_config_source(
            workspace=workspace,
            config_profile=config_profile,
            config_entry=config_entry,
        )
        config_snapshot = source.config
    return start_run(
        mode=mode,
        config=config_snapshot,
        experiment=experiment,
        workspace=workspace,
        native_instrument_provider=native_instrument_provider,
    )


def run_mode_executor(
    mode: RunMode,
    *,
    native_instrument_provider: NativeInstrumentProvider | None = None,
) -> RoutineRunExecutor:
    return _RunModeExecutor(
        mode=mode,
        native_instrument_provider=native_instrument_provider,
    )


def native_run_executor(
    instrument_provider: NativeInstrumentProvider,
) -> RoutineRunExecutor:
    return _NativeRunExecutor(instrument_provider=instrument_provider)


def runner_adapter_executor(adapter: RunnerAdapter) -> RoutineRunExecutor:
    return _RunnerAdapterRunExecutor(adapter=adapter)


def callable_run_executor(
    executor_id: str,
    start: RoutineRunStart,
) -> RoutineRunExecutor:
    return _CallableRunExecutor(executor_id=executor_id, start_fn=start)


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
