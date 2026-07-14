"""Run execution and run artifact workflow use cases."""

from __future__ import annotations

from typing import cast

from scopecat.application.services import WorkspaceServices
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.invocation import PreparedInvocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_prepared_invocation,
)
from scopecat.compiler.linking.linked import LinkedPlan
from scopecat.compiler.pipeline import link_experiment
from scopecat.config.candidates import (
    CandidateConfig,
    materialize_candidate_config,
    resolve_candidate_config_snapshot,
)
from scopecat.config.resolution import (
    ConfigProfileInput,
    ResolvedConfig,
    resolve_config_source,
)
from scopecat.execution.local.plan_executor import execute_execution_plan
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.kernel.errors import CheckFailed, DataIntegrityError, ProblemFailure
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.measurements.results import MeasurementDatasetReadContract
from scopecat.planning.backend import (
    ExecutionBackend,
    ExecutionOptions,
    PreparedExecutionPlan,
)
from scopecat.planning.checks import (
    CheckPhase,
    CheckPhaseReport,
    CheckStatus,
    ExperimentCheckReport,
)
from scopecat.planning.preview import build_execution_plan_preview
from scopecat.planning.preview_models import (
    ExperimentPreview,
    PreviewExperimentResult,
    ValidateExperimentResult,
)
from scopecat.records.artifact import RunArtifactEntry, RunDatasetEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource, RunManifest
from scopecat.records.run_plan import RunPlanRecord
from scopecat.records.run_request import RunRequest
from scopecat.runs.access import (
    list_artifacts,
    list_payload_entries,
    read_artifact_bytes,
    read_artifact_json,
    read_artifact_text,
    read_data_array_artifact,
    read_data_table_artifact,
    read_record_json,
    require_artifact,
    require_dataset,
    require_record,
)
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunDetails,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.measurements import read_measurement_dataset
from scopecat.runs.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    RUN_PLAN_REF,
    RUN_REQUEST_REF,
)
from scopecat.runs.repository import RunRepository


def list_runs(*, services: WorkspaceServices) -> list[RunManifest]:
    return services.runs.list_runs()


def load_run(*, run_id: str, services: WorkspaceServices) -> RunDetails:
    return RunDetails(manifest=services.runs.read_manifest(run_id))


def load_run_config(
    *, run_id: str, services: WorkspaceServices
) -> ConfigProfileSnapshot:
    """Load only the accepted configuration snapshot for a run."""

    storage = services.runs
    _require_run_ref(
        storage=storage,
        run_id=run_id,
        ref=CONFIG_PROFILE_SNAPSHOT_REF,
        code="run.config_missing",
        label="accepted configuration snapshot",
    )
    return storage.read_config_profile_snapshot(run_id)


def load_run_request(*, run_id: str, services: WorkspaceServices) -> RunRequest | None:
    """Load operator intent when the run originated from structured authoring."""

    storage = services.runs
    storage.read_manifest(run_id)
    if not storage.exists(run_id, RUN_REQUEST_REF):
        return None
    return storage.read_model(run_id, RUN_REQUEST_REF, RunRequest)


def load_run_plan(*, run_id: str, services: WorkspaceServices) -> RunPlanRecord:
    """Load only the accepted plan evidence for a run."""

    storage = services.runs
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
    storage: RunRepository,
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
    *, run_id: str, services: WorkspaceServices, kind: str | None = None
) -> tuple[RunArtifactEntry, ...]:
    storage = services.runs
    manifest = storage.read_manifest(run_id)
    return list_artifacts(manifest, kind=kind)


def list_run_payload_entries(
    *, run_id: str, services: WorkspaceServices, kind: str | None = None
) -> tuple[RunArtifactEntry | RunDatasetEntry, ...]:
    storage = services.runs
    manifest = storage.read_manifest(run_id)
    return list_payload_entries(manifest, kind=kind)


def read_run_artifact_text(
    *,
    run_id: str,
    selector: str,
    services: WorkspaceServices,
    expected_kind: str | None = None,
) -> RunArtifactTextResult:
    storage = services.runs
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
    services: WorkspaceServices,
    expected_kind: str | None = None,
) -> RunArtifactJsonResult:
    storage = services.runs
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
    services: WorkspaceServices,
    expected_kind: str | None = None,
) -> RunRecordJsonResult:
    storage = services.runs
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
    services: WorkspaceServices,
    expected_kind: str | None = None,
) -> RunArtifactBytesResult:
    storage = services.runs
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
    services: WorkspaceServices,
    selector: str = "raw-measurements",
) -> RunMeasurementDatasetResult:
    storage = services.runs
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
    *, run_id: str, selector: str, services: WorkspaceServices
) -> RunDataTableResult:
    storage = services.runs
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
    *, run_id: str, selector: str, services: WorkspaceServices
) -> RunDataArrayResult:
    storage = services.runs
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
    services: WorkspaceServices,
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
        services=services,
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
    services: WorkspaceServices,
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
        services=services.execution,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    return manifest


def run_experiment(
    experiment: PreparedInvocation,
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    compiled_invocation = compile_prepared_invocation(experiment)
    config_result = _resolve_config_for_run(
        services=services,
        config=config,
        config_profile=config_profile,
    )
    return _start_compiled_run(
        config=config_result.config,
        experiment=compiled_invocation,
        services=services,
        execution_backend=execution_backend,
        execution_options=execution_options,
        config_source=config_result.config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def check_experiment(
    experiment: PreparedInvocation,
    *,
    services: WorkspaceServices,
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
        services=services,
        config=config,
        config_profile=config_profile,
        execution_backend=execution_backend,
        execution_options=execution_options,
    )


def _check_compiled_experiment(
    experiment: CompiledInvocation,
    *,
    authoring_phase: CheckPhaseReport,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
    execution_backend: ExecutionBackend | None,
    execution_options: ExecutionOptions | None,
) -> ExperimentCheckReport:
    try:
        config_result = _resolve_config_read_only(
            services=services,
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
            inputs=dict(experiment.assembly.source.inputs),
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
            inputs=dict(experiment.assembly.source.inputs),
            config_source=config_result.config_source,
        )

    try:
        linked = link_experiment(
            experiment,
            environment=environment,
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
        inputs=dict(experiment.assembly.source.inputs),
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
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
) -> ValidateExperimentResult:
    report = check_experiment(
        experiment,
        services=services,
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
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    execution_backend: ExecutionBackend | None = None,
    execution_options: ExecutionOptions | None = None,
) -> PreviewExperimentResult:
    validation = validate_experiment(
        experiment,
        services=services,
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
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
    if isinstance(config, CandidateConfig):
        _reject_conflicting_config_profile(config_profile)
        resolved_candidate = materialize_candidate_config(
            config,
            services=services,
        )
        return ResolvedConfig(config=resolved_candidate.config)
    return _resolve_non_candidate_config(
        services=services,
        config=config,
        config_profile=config_profile,
    )


def _resolve_config_read_only(
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
    if isinstance(config, CandidateConfig):
        _reject_conflicting_config_profile(config_profile)
        return ResolvedConfig(
            config=resolve_candidate_config_snapshot(
                config,
                services=services,
            )
        )
    return _resolve_non_candidate_config(
        services=services,
        config=config,
        config_profile=config_profile,
    )


def _resolve_non_candidate_config(
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot,
    config_profile: ConfigProfileInput | None,
) -> ResolvedConfig:
    if isinstance(config, ConfigProfileSnapshot):
        _reject_conflicting_config_profile(config_profile)
        return ResolvedConfig(config=config)
    config_entry = None if config_profile is not None and config == "active" else config
    return resolve_config_source(
        services=services,
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
