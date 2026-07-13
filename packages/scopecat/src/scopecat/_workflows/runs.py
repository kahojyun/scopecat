"""Run execution and run artifact workflow use cases."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import LinkedPlan
from scopecat._execution.execution_plan_executor import execute_execution_plan
from scopecat._storage.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    RUN_PLAN_REF,
    RUN_REQUEST_REF,
)
from scopecat._workflows.compilation import link_experiment
from scopecat._workflows.config import (
    ConfigProfileInput,
    ResolvedConfig,
    resolve_config_source,
)
from scopecat._workflows.preview import build_execution_plan_preview
from scopecat.authoring._invocation_plan import PreparedInvocation
from scopecat.authoring._resolution import (
    CompiledInvocation,
    compile_prepared_invocation,
)
from scopecat.candidate_configs import (
    CandidateConfig,
    materialize_candidate_config,
    resolve_candidate_config_snapshot,
)
from scopecat.checks import (
    CheckPhase,
    CheckPhaseReport,
    CheckStatus,
    ExperimentCheckReport,
)
from scopecat.errors import CheckFailed, DataIntegrityError, ProblemFailure
from scopecat.execution_backend import (
    ExecutionBackend,
    ExecutionOptions,
    PreparedExecutionPlan,
)
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunConfigSource, RunManifest
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.preview import (
    ExperimentPreview,
    PreviewExperimentResult,
    ValidateExperimentResult,
)
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.results import MeasurementDatasetReadContract
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
from scopecat.runtime import RuntimeEventSink, RuntimePayloadObserver


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
        code="run.config_missing",
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
        code="run.plan_missing",
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
    raise DataIntegrityError(
        [
            blocking_problem(
                code,
                f"run is missing its {label}",
                category=ProblemCategory.DATA_INTEGRITY,
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(run_id=run_id, ref=ref),
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
        raise CheckFailed(
            [
                blocking_problem(
                    "run.artifact_media_type_unsupported",
                    "run artifact media type does not support text access",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location("run_manifest", "artifacts", selector),
                    details={"media_type": _artifact_media_label(artifact)},
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
        contract=MeasurementDatasetReadContract(
            missing_code="run.measurement_dataset.missing",
            empty_code="run.measurement_dataset.empty",
            invalid_code="run.measurement_dataset.invalid",
            missing_schema_code="run.measurement_dataset.schema_missing",
            invalid_schema_code="run.measurement_dataset.schema_invalid",
            noun="run measurement dataset",
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
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    compiled_invocation = compile_prepared_invocation(experiment)
    return _start_compiled_run(
        config=config,
        experiment=compiled_invocation,
        workspace=workspace,
        execution_backend=execution_backend,
        execution_options=execution_options,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def _start_compiled_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: CompiledInvocation,
    workspace: str | Path,
    execution_backend: ExecutionBackend | None,
    execution_options: ExecutionOptions | None,
    config_source: RunConfigSource | None,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> RunManifest:
    environment = validate_config_environment(config)
    if not environment.valid:
        raise CheckFailed(environment.problems)
    linked = link_experiment(
        experiment,
        environment=environment,
        workspace=workspace,
        config_source=config_source,
    )
    if has_blocking_problems(linked.problems):
        raise CheckFailed(linked.problems)
    prepared = _prepare_execution_backend(
        execution_backend,
        config=config,
        linked=linked.plan,
        options=execution_options,
    )
    manifest, _ = execute_execution_plan(
        config=config,
        prepared=prepared,
        request=linked.request,
        workspace=workspace,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    return manifest


def run_experiment(
    experiment: PreparedInvocation,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    compiled_invocation = compile_prepared_invocation(experiment)
    config_result = _resolve_config_for_run(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )
    return _start_compiled_run(
        config=config_result.config,
        experiment=compiled_invocation,
        workspace=workspace,
        execution_backend=execution_backend,
        execution_options=execution_options,
        config_source=config_result.config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def check_experiment(
    experiment: PreparedInvocation,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
) -> ExperimentCheckReport:
    """Check an invocation once through each compiler phase.

    Authoring is deliberately compiled before resolving the selected config.
    A failure therefore cannot trigger registry, candidate-config, or file I/O.
    """

    try:
        compiled_invocation = compile_prepared_invocation(experiment)
    except CheckFailed as error:
        return _authoring_failure_report(error.problems)
    authoring_phase = CheckPhaseReport(
        phase=CheckPhase.AUTHORING,
        status=CheckStatus.PASSED,
    )
    return _check_compiled_experiment(
        compiled_invocation,
        authoring_phase=authoring_phase,
        workspace=workspace,
        config=config,
        config_profile=config_profile,
        execution_backend=execution_backend,
        execution_options=execution_options,
    )


def _check_compiled_experiment(
    experiment: CompiledInvocation,
    *,
    authoring_phase: CheckPhaseReport,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
    execution_backend: ExecutionBackend | None,
    execution_options: ExecutionOptions | None,
) -> ExperimentCheckReport:
    try:
        config_result = _resolve_config_read_only(
            workspace=workspace,
            config=config,
            config_profile=config_profile,
        )
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, CheckPhase.CONFIGURATION):
            raise
        return ExperimentCheckReport(
            phases=(
                authoring_phase,
                CheckPhaseReport(
                    phase=CheckPhase.CONFIGURATION,
                    status=CheckStatus.FAILED,
                    problems=error.problems,
                ),
                _skipped_phase(CheckPhase.PLANNING),
            ),
            template_id=experiment.request.template_id,
            inputs=dict(experiment.inputs),
        )
    environment = validate_config_environment(config_result.config)
    configuration_status = (
        CheckStatus.PASSED if environment.valid else CheckStatus.FAILED
    )
    configuration_phase = CheckPhaseReport(
        phase=CheckPhase.CONFIGURATION,
        status=configuration_status,
        problems=environment.problems,
    )
    if not environment.valid:
        return ExperimentCheckReport(
            phases=(
                authoring_phase,
                configuration_phase,
                _skipped_phase(CheckPhase.PLANNING),
            ),
            template_id=experiment.request.template_id,
            inputs=dict(experiment.inputs),
            config_source=config_result.config_source,
        )

    try:
        linked = link_experiment(
            experiment,
            environment=environment,
            workspace=workspace,
            config_source=config_result.config_source,
        )
        planning_problems = _new_problems(
            linked.problems,
            excluding=environment.problems,
        )
        if has_blocking_problems(planning_problems):
            summary = None
        else:
            prepared = _prepare_execution_backend(
                execution_backend,
                config=config_result.config,
                linked=linked.plan,
                options=execution_options,
            )
            summary = _build_execution_plan_preview(prepared)
        planning_status = (
            CheckStatus.FAILED
            if has_blocking_problems(planning_problems)
            else CheckStatus.PASSED
        )
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, CheckPhase.PLANNING):
            raise
        planning_problems = error.problems
        planning_status = CheckStatus.FAILED
        summary = None
        linked = None

    return ExperimentCheckReport(
        phases=(
            authoring_phase,
            configuration_phase,
            CheckPhaseReport(
                phase=CheckPhase.PLANNING,
                status=planning_status,
                problems=planning_problems,
            ),
        ),
        summary=summary,
        template_id=(
            linked.template_id if linked is not None else experiment.request.template_id
        ),
        inputs=(dict(linked.inputs) if linked is not None else dict(experiment.inputs)),
        config_source=(
            linked.config_source if linked is not None else config_result.config_source
        ),
    )


def _authoring_failure_report(
    problems: tuple[Problem, ...],
) -> ExperimentCheckReport:
    return ExperimentCheckReport(
        phases=(
            CheckPhaseReport(
                phase=CheckPhase.AUTHORING,
                status=CheckStatus.FAILED,
                problems=problems,
            ),
            _skipped_phase(CheckPhase.CONFIGURATION),
            _skipped_phase(CheckPhase.PLANNING),
        )
    )


def _skipped_phase(phase: CheckPhase) -> CheckPhaseReport:
    return CheckPhaseReport(
        phase=phase,
        status=CheckStatus.SKIPPED,
    )


def _new_problems(
    problems: tuple[Problem, ...],
    *,
    excluding: tuple[Problem, ...],
) -> tuple[Problem, ...]:
    excluded = {id(problem) for problem in excluding}
    return tuple(problem for problem in problems if id(problem) not in excluded)


def _prepare_execution_backend(
    backend: ExecutionBackend | None,
    *,
    config: ConfigProfileSnapshot,
    linked: LinkedPlan,
    options: ExecutionOptions | None,
) -> PreparedExecutionPlan:
    """Normalize one execution-backend boundary into planning findings."""

    if backend is None:
        raise CheckFailed(
            (
                blocking_problem(
                    "execution.execution_backend_missing",
                    "experiment planning requires an explicit execution backend",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.PLANNING,
                    location=model_location("run_options", "execution_backend"),
                ),
            )
        )

    try:
        backend_id = backend.backend_id
        if type(backend_id) is not str or not backend_id:
            msg = "execution backend identity must be a non-empty string"
            raise TypeError(msg)
        prepared_candidate = cast(
            "object",
            backend.prepare(linked, config=config, options=options),
        )
        if not isinstance(prepared_candidate, PreparedExecutionPlan):
            msg = "execution backend must return PreparedExecutionPlan"
            raise TypeError(msg)
        prepared = prepared_candidate
        if prepared.backend_id != backend_id:
            msg = "prepared execution plan does not retain its backend identity"
            raise ValueError(msg)
        if prepared.linked_points.linked_plan.verified_program is not (
            linked.verified_program
        ):
            msg = "prepared execution plan belongs to a different linked program"
            raise ValueError(msg)
        return prepared
    except ProblemFailure as error:
        raise CheckFailed(
            tuple(
                problem.model_copy(update={"phase": ProblemPhase.PLANNING})
                for problem in error.problems
            )
        ) from error
    except Exception as error:
        raise CheckFailed(
            (
                blocking_problem(
                    "execution_backend_prepare_failed",
                    "execution backend could not prepare the linked program",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.PLANNING,
                    location=model_location("execution_backend"),
                    details={
                        "backend_id": _safe_execution_backend_id(backend),
                        "error_type": type(error).__qualname__,
                    },
                ),
            )
        ) from error


def _safe_execution_backend_id(backend: ExecutionBackend) -> str | None:
    try:
        backend_id = backend.backend_id
    except Exception:
        return None
    return backend_id if type(backend_id) is str and backend_id else None


def _build_execution_plan_preview(
    prepared: PreparedExecutionPlan,
) -> ExperimentPreview:
    return build_execution_plan_preview(prepared)


def _problems_match_phase(
    problems: tuple[Problem, ...],
    phase: CheckPhase,
) -> bool:
    return all(problem.phase.value == phase.value for problem in problems)


def validate_experiment(
    experiment: PreparedInvocation,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
) -> ValidateExperimentResult:
    report = check_experiment(
        experiment,
        workspace=workspace,
        config=config,
        config_profile=config_profile,
        execution_backend=execution_backend,
        execution_options=execution_options,
    )
    planning_ran = (
        report.for_phase(CheckPhase.PLANNING).status is not CheckStatus.SKIPPED
    )
    return ValidateExperimentResult(
        problems=report.problems,
        summary=report.summary,
        template_id=report.template_id if planning_ran else None,
        inputs=dict(report.inputs) if planning_ran else {},
        config_source=report.config_source,
    )


def preview_experiment(
    experiment: PreparedInvocation,
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
) -> PreviewExperimentResult:
    validation = validate_experiment(
        experiment,
        workspace=workspace,
        config=config,
        config_profile=config_profile,
        execution_backend=execution_backend,
        execution_options=execution_options,
    )
    if not validation.ok:
        raise CheckFailed(validation.problems)
    assert validation.summary is not None
    return PreviewExperimentResult(
        summary=validation.summary,
        problems=validation.problems,
        template_id=validation.template_id,
        inputs=dict(validation.inputs),
        config_source=validation.config_source,
    )


def _resolve_config_for_run(
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
    if isinstance(config, CandidateConfig):
        _reject_conflicting_config_profile(config_profile)
        resolved_candidate = materialize_candidate_config(
            config,
            workspace=workspace,
        )
        return ResolvedConfig(config=resolved_candidate.config)
    return _resolve_non_candidate_config(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )


def _resolve_config_read_only(
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
    if isinstance(config, CandidateConfig):
        _reject_conflicting_config_profile(config_profile)
        return ResolvedConfig(
            config=resolve_candidate_config_snapshot(
                config,
                workspace=workspace,
            )
        )
    return _resolve_non_candidate_config(
        workspace=workspace,
        config=config,
        config_profile=config_profile,
    )


def _resolve_non_candidate_config(
    *,
    workspace: str | Path,
    config: str | ConfigProfileSnapshot,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
    if isinstance(config, ConfigProfileSnapshot):
        _reject_conflicting_config_profile(config_profile)
        return ResolvedConfig(config=config)
    config_entry = None if config_profile is not None and config == "active" else config
    return resolve_config_source(
        workspace=workspace,
        config_profile=config_profile,
        config_entry=config_entry,
    )


def _reject_conflicting_config_profile(
    config_profile: ConfigProfileInput | None,
) -> None:
    if config_profile is None:
        return
    raise CheckFailed(
        [
            blocking_problem(
                "config.source_conflict",
                "provide either config or config_profile, not both",
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.CONFIGURATION,
                location=model_location("run_options", "config"),
            )
        ]
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
