"""Run execution and run artifact workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from scopecat.application.services import WorkspaceServices
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.invocation import PreparedInvocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_prepared_invocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    link_verified_program,
    specialize_linked_program,
)
from scopecat.config.candidates import CandidateConfig
from scopecat.config.resolution import (
    ConfigProfileInput,
    resolve_experiment_config,
)
from scopecat.execution.interpreter import admit_run, execute_admitted_run
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.execution.program import RunProgram
from scopecat.kernel.errors import CheckFailed, DataIntegrityError, ProblemFailure
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    model_location,
)
from scopecat.measurements.results import MeasurementDatasetReadContract
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.system import ExperimentSystem
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource, RunManifest
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
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.measurements import read_measurement_dataset
from scopecat.runs.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    RUN_REQUEST_REF,
)
from scopecat.runs.repository import RunRepository


@dataclass(frozen=True, slots=True)
class PlannedRun:
    """Transient program paired with the facts and capabilities used to plan it.

    Keeping the system here ensures execution uses the provider built from the
    same accepted config that compiled the program.
    """

    config: ConfigProfileSnapshot
    request: RunRequest | None
    program: RunProgram
    config_source: RunConfigSource | None = None
    system: ExperimentSystem | None = field(default=None, repr=False, compare=False)


def list_runs(*, services: WorkspaceServices) -> list[RunManifest]:
    return services.runs.list_runs()


def load_run(*, run_id: str, services: WorkspaceServices) -> RunManifest:
    return services.runs.read_manifest(run_id)


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
) -> tuple[RunContentEntry, ...]:
    storage = services.runs
    manifest = storage.read_manifest(run_id)
    return list_artifacts(manifest, kind=kind)


def list_run_payload_entries(
    *, run_id: str, services: WorkspaceServices, kind: str | None = None
) -> tuple[RunContentEntry, ...]:
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
            artifact=artifact,
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
            artifact=artifact,
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
            record=record,
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
            artifact=artifact,
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
            dataset=dataset_entry,
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
            dataset=dataset_entry,
        ),
    )


def start_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: PreparedInvocation,
    services: WorkspaceServices,
    system: ExperimentSystem | None = None,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    compiled_invocation = compile_prepared_invocation(experiment)
    planned = _plan_compiled_run(
        config=config,
        experiment=compiled_invocation,
        system=system,
        config_source=config_source,
    )
    return _execute_planned_run(
        planned,
        services=services,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def _plan_compiled_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: CompiledInvocation,
    system: ExperimentSystem | None,
    config_source: RunConfigSource | None,
) -> PlannedRun:
    environment = validate_config_environment(config)
    if not environment.valid:
        raise CheckFailed(environment.problems)
    resolved = resolve_compiled_invocation(
        experiment,
        environment=environment,
        config_source=config_source,
    )
    linked = specialize_linked_program(
        link_verified_program(resolved.verified_program, environment)
    )
    program = _compile_run_program(
        system,
        config=config,
        linked=linked,
    )
    return PlannedRun(
        config=config,
        request=resolved.request,
        program=program,
        config_source=config_source,
        system=system,
    )


def _execute_planned_run(
    planned: PlannedRun,
    *,
    services: WorkspaceServices,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> RunManifest:
    accepted = admit_run(
        config=planned.config,
        request=planned.request,
        repository=services.runs,
        config_source=planned.config_source,
    )
    return execute_admitted_run(
        run_id=accepted.run_id,
        program=planned.program,
        services=services.execution,
        instrument_provider=(
            None if planned.system is None else planned.system.provider
        ),
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def plan_experiment(
    experiment: PreparedInvocation,
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    system: ExperimentSystem | None = None,
) -> PlannedRun:
    """Compile a runnable program without creating durable run state."""

    compiled_invocation = compile_prepared_invocation(experiment)
    config_result = resolve_experiment_config(
        services=services,
        config=config,
        config_profile=config_profile,
    )
    return _plan_compiled_run(
        config=config_result.config,
        experiment=compiled_invocation,
        system=system,
        config_source=config_result.config_source,
    )


def plan_scratch_experiment(
    experiment: PreparedInvocation,
    *,
    config: ConfigProfileSnapshot,
    system: ExperimentSystem,
) -> PlannedRun:
    """Plan notebook code against an explicit snapshot without workspace I/O."""

    return _plan_compiled_run(
        config=config,
        experiment=compile_prepared_invocation(experiment),
        system=system,
        config_source=None,
    )


def run_experiment(
    experiment: PreparedInvocation,
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    system: ExperimentSystem | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    planned = plan_experiment(
        experiment,
        services=services,
        config=config,
        config_profile=config_profile,
        system=system,
    )
    return _execute_planned_run(
        planned,
        services=services,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def check_experiment(
    experiment: PreparedInvocation,
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    system: ExperimentSystem | None = None,
) -> ExperimentCheckResult:
    """Check whether an invocation can produce a user preview.

    Authoring is deliberately compiled before resolving the selected config.
    A failure therefore cannot trigger config resolution or file I/O.
    """

    try:
        compiled_invocation = compile_prepared_invocation(experiment)
    except CheckFailed as error:
        return ExperimentCheckResult(problems=error.problems, preview=None)
    return _check_compiled_experiment(
        compiled_invocation,
        services=services,
        config=config,
        config_profile=config_profile,
        system=system,
    )


def _check_compiled_experiment(
    experiment: CompiledInvocation,
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
    system: ExperimentSystem | None,
) -> ExperimentCheckResult:
    try:
        config_result = resolve_experiment_config(
            services=services,
            config=config,
            config_profile=config_profile,
        )
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, ProblemPhase.CONFIGURATION):
            raise
        return ExperimentCheckResult(problems=error.problems, preview=None)
    environment = validate_config_environment(config_result.config)
    if not environment.valid:
        return ExperimentCheckResult(
            problems=environment.problems,
            preview=None,
        )

    try:
        resolved = resolve_compiled_invocation(
            experiment,
            environment=environment,
            config_source=config_result.config_source,
        )
        linked = specialize_linked_program(
            link_verified_program(resolved.verified_program, environment)
        )
        program = _compile_run_program(
            system,
            config=config_result.config,
            linked=linked,
        )
        preview = build_run_program_preview(program)
        planning_problems: tuple[Problem, ...] = ()
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, ProblemPhase.PLANNING):
            raise
        planning_problems = error.problems
        preview = None

    return ExperimentCheckResult(
        problems=(*environment.problems, *planning_problems),
        preview=preview,
    )


def _compile_run_program(
    system: ExperimentSystem | None,
    *,
    config: ConfigProfileSnapshot,
    linked: LinkedPlan,
) -> RunProgram:
    """Compile one linked experiment into the sole executable program."""

    if system is None:
        raise CheckFailed(
            (
                blocking_problem(
                    "execution.experiment_system_missing",
                    "experiment planning requires an explicit experiment system",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.PLANNING,
                    location=model_location("run_options", "experiment_system"),
                ),
            )
        )

    try:
        program_candidate = cast(
            "object",
            system.compile(linked, config=config),
        )
        if not isinstance(program_candidate, RunProgram):
            msg = "experiment system must return RunProgram"
            raise TypeError(msg)
        return program_candidate
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
                    "experiment_system_prepare_failed",
                    "experiment system could not prepare the linked program",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.PLANNING,
                    location=model_location("experiment_system"),
                    details={
                        "error_type": type(error).__qualname__,
                    },
                ),
            )
        ) from error


def _problems_match_phase(
    problems: tuple[Problem, ...],
    phase: ProblemPhase,
) -> bool:
    return all(problem.phase is phase for problem in problems)


def _artifact_supports_text(artifact: RunContentEntry) -> bool:
    media_type = artifact.media_type
    return media_type is not None and (
        media_type.startswith("text/")
        or media_type in {"application/json", "application/x-ndjson"}
    )


def _artifact_media_label(artifact: RunContentEntry) -> str:
    if artifact.media_type is None:
        return "unknown"
    return artifact.media_type
