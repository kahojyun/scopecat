"""Run execution and run artifact workflow use cases."""

from __future__ import annotations

from pathlib import Path

from scopecat._runtime.executor import execute_run
from scopecat._storage.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    RUN_PLAN_REF,
    RUN_REQUEST_REF,
)
from scopecat._workflows._diagnostics import diagnostic as _diagnostic
from scopecat._workflows.config import (
    ConfigProfileInput,
    ResolvedConfig,
    resolve_config_source,
)
from scopecat._workflows.preview import build_experiment_preview
from scopecat.authoring._invocation_plan import PreparedInvocation
from scopecat.authoring._resolution import resolve_prepared_invocation
from scopecat.errors import ValidationFailed
from scopecat.instruments import (
    RuntimeEventSink,
    RuntimePayloadObserver,
)
from scopecat.instruments.sdk import (
    InstrumentProvider,
    InstrumentProviderContext,
)
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunConfigSource, RunManifest
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.planning.validation import has_blocking_diagnostics, validate_config
from scopecat.preview import PreviewExperimentResult, ValidateExperimentResult
from scopecat.results import MeasurementDatasetInputDiagnostics
from scopecat.run_data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunDetails,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs import (
    RunStore,
    dataset_storage_ref,
    list_artifacts,
    list_payload_entries,
    open_run_store,
    read_artifact_bytes,
    read_artifact_json,
    read_artifact_text,
    read_data_array_artifact,
    read_data_table_artifact,
    read_measurement_dataset,
    read_record_json,
    require_artifact,
    require_dataset,
    require_record,
)


def list_runs(*, workspace: str | Path) -> list[RunManifest]:
    storage = open_run_store(workspace)
    return storage.list_runs()


def load_run(*, run_id: str, workspace: str | Path) -> RunDetails:
    storage = open_run_store(workspace)
    return RunDetails(manifest=storage.read_manifest(run_id))


def load_run_config(*, run_id: str, workspace: str | Path) -> ConfigProfileSnapshot:
    """Load only the accepted configuration snapshot for a run."""

    storage = open_run_store(workspace)
    _require_run_ref(
        storage=storage,
        run_id=run_id,
        ref=CONFIG_PROFILE_SNAPSHOT_REF,
        code="run_config_missing",
        label="accepted configuration snapshot",
    )
    return storage.read_config_profile_snapshot(run_id)


def load_run_request(*, run_id: str, workspace: str | Path) -> RunRequest | None:
    """Load operator intent when the run originated from structured authoring."""

    storage = open_run_store(workspace)
    storage.read_manifest(run_id)
    if not storage.exists(run_id, RUN_REQUEST_REF):
        return None
    return storage.read_model(run_id, RUN_REQUEST_REF, RunRequest)


def load_run_plan(*, run_id: str, workspace: str | Path) -> RunPlanRecord:
    """Load only the accepted plan evidence for a run."""

    storage = open_run_store(workspace)
    _require_run_ref(
        storage=storage,
        run_id=run_id,
        ref=RUN_PLAN_REF,
        code="run_plan_missing",
        label="accepted plan record",
    )
    return storage.read_model(run_id, RUN_PLAN_REF, RunPlanRecord)


def _require_run_ref(
    *,
    storage: RunStore,
    run_id: str,
    ref: str,
    code: str,
    label: str,
) -> None:
    storage.read_manifest(run_id)
    if storage.exists(run_id, ref):
        return
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                code,
                f"run is missing {label}: {ref}",
                "run",
            )
        ]
    )


def list_run_artifacts(
    *, run_id: str, workspace: str | Path, kind: str | None = None
) -> tuple[RunArtifactEntry, ...]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    return list_artifacts(manifest, kind=kind)


def list_run_payload_entries(
    *, run_id: str, workspace: str | Path, kind: str | None = None
) -> tuple[RunArtifactEntry | RunDatasetEntry, ...]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    return list_payload_entries(manifest, kind=kind)


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


def read_run_record_json(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    expected_kind: str | None = None,
) -> RunRecordJsonResult:
    storage = open_run_store(workspace)
    record = require_record(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return RunRecordJsonResult(
        record=record,
        content=read_record_json(
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
    dataset_entry = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="measurement_dataset",
    )
    dataset = read_measurement_dataset(
        storage=storage,
        run_id=run_id,
        dataset=dataset_entry,
        diagnostics=MeasurementDatasetInputDiagnostics(
            missing_code="run_measurement_dataset_missing",
            empty_code="run_measurement_dataset_empty",
            invalid_code="run_measurement_dataset_invalid",
            missing_schema_code="run_measurement_dataset_missing_schema",
            invalid_schema_code="run_measurement_dataset_invalid_schema",
            noun="run measurement dataset",
            diagnostic_path=dataset_storage_ref(dataset_entry),
        ),
    )
    return RunMeasurementDatasetResult(dataset_entry=dataset_entry, dataset=dataset)


def read_run_data_table(
    *, run_id: str, selector: str, workspace: str | Path
) -> RunDataTableResult:
    storage = open_run_store(workspace)
    dataset_entry = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="data_table",
    )
    return RunDataTableResult(
        dataset_entry=dataset_entry,
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
    dataset_entry = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="data_array",
    )
    return RunDataArrayResult(
        dataset_entry=dataset_entry,
        array=read_data_array_artifact(
            storage=storage,
            run_id=run_id,
            selector=selector,
        ),
    )


def start_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: PreparedInvocation,
    workspace: str | Path,
    instrument_provider: InstrumentProvider | None = None,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    resolved = resolve_prepared_invocation(
        experiment,
        config=config,
        workspace=workspace,
        config_source=config_source,
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
        InstrumentProviderContext(config=config)
    )
    diagnostics = list(provider_result.diagnostics)
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    manifest, _ = execute_run(
        config=config,
        experiment=resolved.experiment,
        request=resolved.request,
        instruments=list(provider_result.drivers),
        workspace=workspace,
        parameters=resolved.parameters,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    return manifest


def run_experiment(
    experiment: PreparedInvocation,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
    instrument_provider: InstrumentProvider | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    config_result = _resolve_config(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )
    return start_run(
        config=config_result.config,
        experiment=experiment,
        workspace=workspace,
        instrument_provider=instrument_provider,
        config_source=config_result.config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def validate_experiment(
    experiment: PreparedInvocation,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot = "active",
    config_profile: ConfigProfileInput | None = None,
) -> ValidateExperimentResult:
    config_result = _resolve_config(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )
    config_snapshot = config_result.config
    resolved = resolve_prepared_invocation(
        experiment,
        config=config_snapshot,
        workspace=workspace,
        config_source=config_result.config_source,
    )
    diagnostics = list(validate_config(config_snapshot))
    summary = None
    if not has_blocking_diagnostics(diagnostics):
        summary, preview_diagnostics = build_experiment_preview(
            resolved.experiment,
            resolved.parameters,
            config=config_snapshot,
        )
        diagnostics.extend(preview_diagnostics)
    return ValidateExperimentResult(
        diagnostics=tuple(diagnostics),
        summary=summary,
        template_id=resolved.template_id,
        inputs=dict(resolved.inputs),
        config_source=resolved.config_source,
    )


def preview_experiment(
    experiment: PreparedInvocation,
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
    assert validation.summary is not None
    return PreviewExperimentResult(
        summary=validation.summary,
        diagnostics=validation.diagnostics,
        template_id=validation.template_id,
        inputs=dict(validation.inputs),
        config_source=validation.config_source,
    )


def _resolve_config(
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
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
        return ResolvedConfig(config=config)
    config_entry = None if config_profile is not None and config == "active" else config
    return resolve_config_source(
        workspace=workspace,
        config_profile=config_profile,
        config_entry=config_entry,
    )


def _artifact_supports_text(artifact: RunArtifactEntry) -> bool:
    media_type = artifact.media_type
    return media_type is not None and (
        media_type.startswith("text/")
        or media_type in {"application/json", "application/x-ndjson"}
    )


def _artifact_media_label(artifact: RunArtifactEntry) -> str:
    if artifact.media_type is None:
        return "unknown"
    return artifact.media_type
