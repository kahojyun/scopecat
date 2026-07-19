"""Interpret the sole closed RunProgram through one durable effect journal."""

from __future__ import annotations

from scopecat.execution.effect_interpreter import (
    RunEffectResult,
)
from scopecat.execution.effects.domain import (
    DomainSynchronousCompletionPending,
    domain_runtime_terminal_problem,
    execute_domain_job_values,
    measurement_recording_terminal_problem,
)
from scopecat.execution.events import (
    RuntimeTransitionProjector,
    emit_run_finished,
    emit_run_started,
)
from scopecat.execution.evidence import (
    RAW_MEASUREMENTS_DATASET_ID,
    build_execution_manifest,
    build_instrument_state_evidence,
    raw_measurement_schema,
)
from scopecat.execution.local.collection_values import (
    BoundLocalCollectionValues,
    bind_local_collection_values,
    local_collection_value_candidates,
)
from scopecat.execution.local.executor import execute_run_local_effects
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.execution.persistence import (
    validate_measurement_index_shape,
    validate_raw_measurement_dataset,
)
from scopecat.execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat.execution.program import (
    RunDomainJob,
    RunPointRegion,
    RunProgram,
    run_local_effects,
    run_point_regions,
)
from scopecat.execution.services import (
    CollectionRecordRepository,
    ExecutionServices,
    MeasurementRecordRepository,
)
from scopecat.kernel.errors import (
    DomainFetchFailed,
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    DomainSubmissionIndeterminate,
    MeasurementRecordingError,
    ProblemFailure,
    RunFailed,
    RunIndeterminate,
)
from scopecat.kernel.ids import new_run_id
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
)
from scopecat.measurements.projection import project_measurement_records
from scopecat.measurements.recording import commit_projected_measurement_records
from scopecat.measurements.results import MeasurementRecord
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    seal_measurement_values,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest
from scopecat.runs.lifecycle import commit_terminal_evidence


def interpret_run_program(
    *,
    config: ConfigProfileSnapshot,
    program: RunProgram,
    request: RunRequest | None,
    services: ExecutionServices,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> RunManifest:
    """Interpret one closed residual effect program."""

    return _interpret_run(
        config=config,
        program=program,
        request=request,
        services=services,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def _interpret_run(
    *,
    config: ConfigProfileSnapshot,
    program: RunProgram,
    request: RunRequest | None,
    services: ExecutionServices,
    config_source: RunConfigSource | None,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> RunManifest:
    point = run_local_effects(program)
    point_regions = run_point_regions(program)
    local_binding = _bind_local_fragment(program)
    core_program = program.linked_points.linked_plan.program
    projection = program.projection.projection
    point_count = len(program.linked_points.point_domain.points)
    experiment_id = core_program.id
    run_id = new_run_id()
    storage = services.runs
    accepted = RunManifest(
        run_id=run_id,
        lifecycle="accepted",
        config_content_hash=config_content_hash(config),
        config_source=config_source,
    )
    storage.write_run_skeleton(
        manifest=accepted,
        request=request,
        config=config,
    )
    storage.write_manifest(accepted.model_copy(update={"lifecycle": "running"}))

    instrument_ids = [] if point is None else list(point.instrument_order)
    emit_run_started(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=experiment_id,
        point_count=point_count,
        instrument_ids=instrument_ids,
        output_ids=[record.id for record in projection.records],
    )

    journal = services.journal_for(run_id)
    transition_observer = RuntimeTransitionProjector(
        event_sink=event_sink,
        experiment_id=experiment_id,
        point_count=point_count,
    )
    measurements = services.measurements_for(run_id)
    readbacks = services.collections_for(run_id)
    payloads = services.payloads_for(run_id)
    domain_jobs = tuple(job for region in point_regions for job in region.domain_jobs)
    domain_values: dict[str, list[tuple[MeasurementValueCandidate, ...]]] = {}
    domain_failure: tuple[RunDomainJob, BaseException] | None = None

    def execute_domain_region(region: RunPointRegion) -> bool:
        nonlocal domain_failure
        for job in region.domain_jobs:
            try:
                domain_values.setdefault(job.source_id, []).append(
                    execute_domain_job_values(
                        job.prepared,
                        semantic_operation_id=job.id,
                        run_id=run_id,
                        journal=journal,
                    )
                )
            except BaseException as error:
                domain_failure = (job, error)
                return False
        return True

    local_result: RunEffectResult | None = None
    setup_problems: list[Problem] = []
    direct_interruption: BaseException | None = None
    resource_failure: BaseException | None = None
    claims = program.resource_claims
    try:
        with services.resources.acquire(claims):
            if point is not None:
                executed, setup_problems = execute_run_local_effects(
                    config=config,
                    effects=point,
                    run_id=run_id,
                    journal=journal,
                    readbacks=readbacks,
                    payloads=payloads,
                    event_sink=event_sink,
                    payload_observer=payload_observer,
                    transition_observer=transition_observer,
                    point_regions=(point_regions if domain_jobs else ()),
                )
                local_result = executed.result
                domain_values.update(executed.domain_values)
                domain_failure = executed.domain_failure
            else:
                try:
                    for region in point_regions:
                        if not execute_domain_region(region):
                            break
                except BaseException as error:
                    direct_interruption = error
    except BaseException as error:
        resource_failure = error

    problems = _local_problems(
        setup_problems=setup_problems,
        result=local_result,
        run_id=run_id,
    )
    certainty = (
        "indeterminate"
        if local_result is not None and local_result.uncertain
        else "known"
    )
    interruption = (
        direct_interruption
        if direct_interruption is not None
        else None
        if local_result is None
        else local_result.interruption
    )
    if isinstance(resource_failure, Exception):
        problems.append(
            problem_from_exception(
                "execution_plan_resource_lease_failed",
                "execution plan resource lease failed",
                run_id=run_id,
                operation_id="execution-plan.resources",
                error=resource_failure,
            )
        )
    elif resource_failure is not None:
        certainty = "indeterminate"
        interruption = resource_failure
        problems.append(
            runtime_problem(
                "execution_plan_resource_lease_interrupted",
                "execution plan resource lease was interrupted",
                run_id=run_id,
                operation_id="execution-plan.resources",
                category=ProblemCategory.INTERRUPTED,
                details={
                    "exception_type": type(resource_failure).__qualname__,
                },
            )
        )
    if domain_failure is not None:
        unit, error = domain_failure
        domain_problems, domain_uncertain, domain_interruption = (
            _domain_failure_problems(unit, error, run_id=run_id)
        )
        problems.extend(domain_problems)
        if domain_uncertain:
            certainty = "indeterminate"
        if domain_interruption is not None:
            interruption = domain_interruption

    # Aggregate product ownership is an exact whole-run contract. If any batch
    # fails, successful effects remain correlated in the journal, but Scopecat
    # does not publish a logically incomplete measurement dataset.
    if not has_blocking_problems(problems):
        try:
            candidates = _measurement_value_candidates(
                local_binding=local_binding,
                domain_values=domain_values,
                run_id=run_id,
                readbacks=readbacks,
            )
            values = seal_measurement_values(
                program.values,
                candidates,
            )
            projected = project_measurement_records(
                program.projection,
                values,
                run_id=run_id,
            )
            commit_projected_measurement_records(
                projected,
                measurements,
                journal,
                transition_observer=transition_observer.observe,
            )
        except MeasurementRecordingError as error:
            problems.extend(
                contextualize_problems(
                    error.problems,
                    run_id=run_id,
                    operation_id=error.operation_id,
                )
            )
            problems.append(
                measurement_recording_terminal_problem(error, run_id=run_id)
            )
            if error.write_may_have_completed:
                certainty = "indeterminate"
        except ProblemFailure as error:
            problems.extend(
                contextualize_problems(
                    error.problems,
                    run_id=run_id,
                    operation_id="execution-plan.measurements",
                )
            )
        except Exception as error:
            problems.append(
                problem_from_exception(
                    "execution_plan_measurement_assembly_failed",
                    "execution plan measurement assembly failed",
                    run_id=run_id,
                    operation_id="execution-plan.measurements",
                    error=error,
                )
            )
        except BaseException as error:
            interruption = error
            certainty = "indeterminate"
            problems.append(
                runtime_problem(
                    "execution_plan_measurement_assembly_interrupted",
                    "execution plan measurement assembly was interrupted",
                    run_id=run_id,
                    operation_id="execution-plan.measurements",
                    category=ProblemCategory.INTERRUPTED,
                    details={"exception_type": type(error).__qualname__},
                )
            )

    committed_measurements, reload_uncertain = _reload_measurements(
        measurements,
        run_id=run_id,
        problems=problems,
    )
    if reload_uncertain:
        certainty = "indeterminate"
    expected_schema = raw_measurement_schema(projection.schema)
    if committed_measurements or not has_blocking_problems(problems):
        problems.extend(
            contextualize_problems(
                validate_measurement_index_shape(
                    measurements=committed_measurements,
                    expected_indices=set(range(point_count)),
                    duplicate_code="execution_plan_measurement_point_duplicate",
                    duplicate_message="execution plan measurements repeat point index",
                    unknown_code="execution_plan_measurement_point_unknown",
                    unknown_message=(
                        "execution plan measurements contain unknown point index"
                    ),
                    missing_observables_code=(
                        "execution_plan_measurement_observables_missing"
                    ),
                    missing_observables_message=(
                        "execution plan measurement records require at least "
                        "one observable"
                    ),
                ),
                run_id=run_id,
                operation_id="execution-plan.validate-measurements",
            )
        )
        problems.extend(
            contextualize_problems(
                validate_raw_measurement_dataset(
                    records=committed_measurements,
                    expected_schema=expected_schema,
                    dataset_id=RAW_MEASUREMENTS_DATASET_ID,
                ),
                run_id=run_id,
                operation_id="execution-plan.validate-dataset",
            )
        )

    failed = has_blocking_problems(problems)
    outcome = RunOutcome(
        run_id=run_id,
        result=(
            "cancelled"
            if interruption is not None
            else "failed"
            if failed or certainty == "indeterminate"
            else "succeeded"
        ),
        certainty="indeterminate" if certainty == "indeterminate" else "known",
        termination_reason=(
            "interrupted"
            if interruption is not None
            else "effect_outcome_unknown"
            if certainty == "indeterminate"
            else "blocking_problem"
            if failed
            else "completed"
        ),
        problems=tuple(problems),
    )
    instrument_state = (
        None if local_result is None else build_instrument_state_evidence(local_result)
    )
    manifest = build_execution_manifest(
        run_id=run_id,
        outcome=outcome,
        measurements=committed_measurements,
        expected_schema=expected_schema,
        config_content_hash=accepted.config_content_hash,
        config_source=config_source,
        include_instrument_state=instrument_state is not None,
    ).model_copy(update={"created_at": accepted.created_at})
    manifest = commit_terminal_evidence(
        storage=storage,
        run_id=run_id,
        outcome=outcome,
        instrument_state=instrument_state,
        measurements=committed_measurements,
        manifest=manifest,
    )
    emit_run_finished(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=experiment_id,
        outcome=outcome,
        completed_point_count=(
            point_count
            if outcome.result == "succeeded"
            else len({record.point_index for record in committed_measurements})
        ),
        point_count=point_count,
        measurement_count=len(committed_measurements),
        problem_count=len(problems),
        compute_evaluated_node_count=(
            0 if local_result is None else local_result.compute_evaluated_node_count
        ),
        compute_payload_count=(
            0 if local_result is None else local_result.compute_payload_count
        ),
    )
    if interruption is not None:
        interruption.add_note(f"Scopecat run_id: {run_id}")
        raise interruption
    if outcome.result != "succeeded":
        if outcome.certainty == "indeterminate":
            raise RunIndeterminate(run_id=run_id, outcome=outcome)
        raise RunFailed(run_id=run_id, outcome=outcome)
    return manifest


def _bind_local_fragment(
    program: RunProgram,
) -> BoundLocalCollectionValues | None:
    point = run_local_effects(program)
    if point is None or not point.product_use_ids:
        return None
    return bind_local_collection_values(
        program.values,
        point.product_use_ids,
        point,
    )


def _measurement_value_candidates(
    *,
    local_binding: BoundLocalCollectionValues | None,
    domain_values: dict[str, list[tuple[MeasurementValueCandidate, ...]]],
    run_id: str,
    readbacks: CollectionRecordRepository,
) -> tuple[MeasurementValueCandidate, ...]:
    candidates: list[MeasurementValueCandidate] = []
    if local_binding is not None:
        candidates.extend(
            local_collection_value_candidates(
                local_binding,
                run_id=run_id,
                repository=readbacks,
                receipts=readbacks.receipts(),
            )
        )
    for value_batches in domain_values.values():
        candidates.extend(value for values in value_batches for value in values)
    return tuple(candidates)


def _local_problems(
    *,
    setup_problems: list[Problem],
    result: RunEffectResult | None,
    run_id: str,
) -> list[Problem]:
    selected = list(setup_problems)
    if result is not None:
        selected.extend(
            problem for problem in result.problems if problem not in selected
        )
    return list(
        contextualize_problems(
            selected,
            run_id=run_id,
            operation_id="execution-plan.local",
        )
    )


def _domain_failure_problems(
    unit: RunDomainJob,
    error: BaseException,
    *,
    run_id: str,
) -> tuple[list[Problem], bool, BaseException | None]:
    prepared = unit.prepared
    if isinstance(error, DomainSynchronousCompletionPending):
        return (
            [
                runtime_problem(
                    "domain_synchronous_completion_contract_violated",
                    (
                        "the domain runtime returned pending after its compiler "
                        "declared synchronous completion"
                    ),
                    run_id=run_id,
                    operation_id=error.operation_id,
                    category=ProblemCategory.PROVIDER_CONTRACT,
                    details={
                        "unit_id": unit.id,
                        "completion_contract": prepared.completion_contract,
                        "job_id": error.job_id,
                        "submission_key": error.submission_key,
                        "automatic_resume": False,
                        "operator_action": "inspect_target_job",
                    },
                )
            ],
            True,
            None,
        )
    if isinstance(error, DomainRuntimeFailure | DomainRuntimePersistenceError):
        problems = list(
            contextualize_problems(
                error.problems,
                run_id=run_id,
                operation_id=error.operation_id,
            )
        )
        problems.append(domain_runtime_terminal_problem(error, run_id=run_id))
        uncertain = (
            isinstance(error, DomainSubmissionIndeterminate)
            or (
                isinstance(error, DomainFetchFailed)
                and error.certainty == "indeterminate"
            )
            or (
                isinstance(error, DomainRuntimePersistenceError)
                and error.certainty == "indeterminate"
            )
        )
        return problems, uncertain, None
    if isinstance(error, ProblemFailure):
        return (
            list(
                contextualize_problems(
                    error.problems,
                    run_id=run_id,
                    operation_id=unit.id,
                )
            ),
            False,
            None,
        )
    if isinstance(error, Exception):
        return (
            [
                problem_from_exception(
                    "domain_execution_failed",
                    "domain execution raised outside its structured contract",
                    run_id=run_id,
                    operation_id=unit.id,
                    error=error,
                )
            ],
            False,
            None,
        )
    return (
        [
            runtime_problem(
                "domain_execution_interrupted",
                "domain execution was interrupted",
                run_id=run_id,
                operation_id=unit.id,
                phase=ProblemPhase.EXECUTION,
                category=ProblemCategory.INTERRUPTED,
                details={"exception_type": type(error).__qualname__},
            )
        ],
        True,
        error,
    )


def _reload_measurements(
    committer: MeasurementRecordRepository,
    *,
    run_id: str,
    problems: list[Problem],
) -> tuple[list[MeasurementRecord], bool]:
    try:
        return list(committer.measurements()), False
    except Exception as error:
        problems.append(
            problem_from_exception(
                "execution_plan_measurement_reload_failed",
                "committed execution plan measurements could not be reloaded",
                run_id=run_id,
                operation_id="execution-plan.measurements.reload",
                error=error,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
            )
        )
        problems.append(
            runtime_problem(
                "execution_plan_measurement_reload_terminalized",
                "the run was terminalized without trusting its measurement chunks",
                run_id=run_id,
                operation_id="execution-plan.measurements.reload",
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
                details={
                    "storage_ref": "execution-measurements",
                    "reconciliation": "inspect and validate durable measurement chunks",
                    "automatic_resume": False,
                },
            )
        )
        return [], True
