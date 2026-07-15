"""Execute one exact-cover execution plan through a single durable Run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

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
    build_execution_summary,
    build_instrument_state_evidence,
    raw_measurement_schema,
)
from scopecat.execution.local.engine import (
    CapturedMiddleEffectFailure,
    ExecutionEngine,
    ExecutionEngineResult,
)
from scopecat.execution.local.executor import execute_prepared_local_effects
from scopecat.execution.local.measurement_fragments import (
    BoundLocalCollectionFragment,
    bind_local_collection_fragment,
    local_collection_fragment,
)
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.execution.persistence import (
    validate_measurement_index_shape,
    validate_raw_measurement_dataset,
)
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
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
    ClosedMeasurementProductValues,
    ClosedMeasurementValueFragment,
    MeasurementValueCandidate,
    assemble_measurement_values,
    seal_measurement_value_fragment,
)
from scopecat.planning.backend import (
    PreparedDomainJob,
    PreparedExecutionPlan,
    PreparedExecutionSegment,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.execution import ExecutionSummary
from scopecat.records.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest
from scopecat.runs.lifecycle import commit_terminal_evidence


class _DomainUnitEffectFailed(CapturedMiddleEffectFailure):
    """Stop the local lane after a captured domain-boundary failure."""


def execute_execution_plan(
    *,
    config: ConfigProfileSnapshot,
    prepared: PreparedExecutionPlan,
    request: RunRequest | None,
    services: ExecutionServices,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    """Execute one trusted exact-cover plan without backend-specific workflow forks."""

    return _execute_unified_run(
        config=config,
        prepared=prepared,
        request=request,
        services=services,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def _execute_unified_run(
    *,
    config: ConfigProfileSnapshot,
    prepared: PreparedExecutionPlan,
    request: RunRequest | None,
    services: ExecutionServices,
    config_source: RunConfigSource | None,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> tuple[RunManifest, ExecutionSummary]:
    point = prepared.point_unit
    local_binding = _bind_local_fragment(prepared)
    local_prepared = (
        None
        if point is None
        else replace(
            point.prepared,
            program=replace(point.prepared.program, record_projections=()),
        )
    )
    program = prepared.linked_points.linked_plan.program
    projection = prepared.projection.projection
    point_count = len(prepared.linked_points.point_domain.points)
    experiment_id = program.id
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

    instrument_ids = [] if point is None else list(point.prepared.instrument_order)
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
    domain_values: dict[str, list[ClosedMeasurementProductValues]] = {
        unit.id: [] for unit in prepared.domain_units
    }
    unit_id_by_job = {
        job.id: unit.id for unit in prepared.domain_units for job in unit.jobs
    }
    domain_failure: tuple[PreparedDomainJob, BaseException] | None = None

    def execute_domain_segment(segment: PreparedExecutionSegment) -> None:
        nonlocal domain_failure
        for job in segment.domain_jobs:
            try:
                domain_values[unit_id_by_job[job.id]].append(
                    execute_domain_job_values(
                        job.prepared,
                        run_id=run_id,
                        journal=journal,
                    )
                )
            except BaseException as error:
                domain_failure = (job, error)
                raise _DomainUnitEffectFailed(job.id) from error

    segment_effects = tuple(
        (
            segment.point_indices,
            lambda selected=segment: execute_domain_segment(selected),
        )
        for segment in prepared.segments
    )

    local_result: ExecutionEngineResult | None = None
    setup_problems: list[Problem] = []
    direct_interruption: BaseException | None = None
    resource_failure: BaseException | None = None
    claims = tuple(
        ResourceClaim(id=claim.id, kind=claim.kind)
        for claim in prepared.resource_claims
    )
    try:
        with services.resources.acquire(claims):
            if point is not None and local_prepared is not None:
                engine_runner: (
                    Callable[[ExecutionEngine], ExecutionEngineResult] | None
                ) = (
                    None
                    if not prepared.domain_units
                    else lambda engine: engine.run_around_point_segments(
                        segment_effects
                    )
                )
                local_result, setup_problems = execute_prepared_local_effects(
                    config=config,
                    prepared=local_prepared,
                    provider=point.provider,
                    run_id=run_id,
                    journal=journal,
                    measurements=measurements,
                    readbacks=readbacks,
                    payloads=payloads,
                    event_sink=event_sink,
                    payload_observer=payload_observer,
                    transition_observer=transition_observer,
                    engine_runner=engine_runner,
                )
            else:
                try:
                    for segment in prepared.segments:
                        execute_domain_segment(segment)
                except _DomainUnitEffectFailed:
                    pass
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
            fragments = _measurement_fragments(
                prepared,
                local_binding=local_binding,
                domain_values=domain_values,
                run_id=run_id,
                readbacks=readbacks,
            )
            values = assemble_measurement_values(
                prepared.value_assembly,
                fragments,
            )
            projected = project_measurement_records(
                prepared.projection,
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
    summary = _execution_summary(
        experiment_id=experiment_id,
        point_count=point_count,
        outcome=outcome,
        local_result=local_result,
        measurements=committed_measurements,
        instrument_ids=instrument_ids,
        problems=problems,
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
        summary=summary,
        instrument_state=instrument_state,
        measurements=committed_measurements,
        manifest=manifest,
    )
    emit_run_finished(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=experiment_id,
        outcome=outcome,
        completed_point_count=summary.completed_point_count,
        point_count=point_count,
        measurement_count=len(committed_measurements),
        problem_count=len(problems),
        compute_evaluated_node_count=(
            0 if local_result is None else local_result.compute_evaluated_node_count
        ),
        compute_reused_node_count=(
            0 if local_result is None else local_result.compute_reused_node_count
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
    return manifest, summary


def _bind_local_fragment(
    prepared: PreparedExecutionPlan,
) -> BoundLocalCollectionFragment | None:
    point = prepared.point_unit
    if point is None or not point.product_use_ids:
        return None
    return bind_local_collection_fragment(
        prepared.value_assembly,
        point.id,
        point.prepared.program,
    )


def _measurement_fragments(
    prepared: PreparedExecutionPlan,
    *,
    local_binding: BoundLocalCollectionFragment | None,
    domain_values: dict[str, list[ClosedMeasurementProductValues]],
    run_id: str,
    readbacks: CollectionRecordRepository,
) -> tuple[ClosedMeasurementValueFragment, ...]:
    fragments: list[ClosedMeasurementValueFragment] = []
    if local_binding is not None:
        fragments.append(
            local_collection_fragment(
                local_binding,
                run_id=run_id,
                repository=readbacks,
                receipts=readbacks.receipts(),
            )
        )
    for unit in prepared.domain_units:
        if not unit.product_use_ids:
            continue
        value_batches = domain_values[unit.id]
        fragments.append(
            seal_measurement_value_fragment(
                prepared.value_assembly,
                unit.id,
                tuple(
                    MeasurementValueCandidate(
                        value.logical_point_id,
                        value.product_use_id,
                        value.value,
                    )
                    for values in value_batches
                    for value in values.values
                ),
            )
        )
    return tuple(fragments)


def _local_problems(
    *,
    setup_problems: list[Problem],
    result: ExecutionEngineResult | None,
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
    unit: PreparedDomainJob,
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
                        "the domain runtime returned pending after its adapter "
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
                    operation_id=prepared.semantic_operation_id,
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
                    operation_id=prepared.semantic_operation_id,
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
                operation_id=prepared.semantic_operation_id,
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


def _execution_summary(
    *,
    experiment_id: str,
    point_count: int,
    outcome: RunOutcome,
    local_result: ExecutionEngineResult | None,
    measurements: list[MeasurementRecord],
    instrument_ids: list[str],
    problems: list[Problem],
) -> ExecutionSummary:
    if local_result is not None:
        completed_indices = {record.point_index for record in measurements}
        return build_execution_summary(
            result=replace(
                local_result,
                measurements=tuple(measurements),
                points=tuple(
                    point
                    for point in local_result.points
                    if point.point_index in completed_indices
                ),
            ),
            outcome=outcome,
            instrument_ids=instrument_ids,
            point_count=point_count,
            problems=problems,
        )
    completed_point_count = (
        point_count
        if outcome.result == "succeeded"
        else len({record.point_index for record in measurements})
    )
    return ExecutionSummary(
        run_id=outcome.run_id,
        experiment_id=experiment_id,
        outcome=outcome,
        point_count=point_count,
        completed_point_count=completed_point_count,
        measurement_count=len(measurements),
        instrument_ids=instrument_ids,
        problem_count=len(problems),
        problems=tuple(problems),
    )


__all__ = ["execute_execution_plan"]
