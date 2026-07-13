"""Execute one exact-cover execution plan through a single durable Run."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scopecat._execution.domain_executor import (
    DomainSynchronousCompletionPending,
    domain_runtime_terminal_problem,
    execute_domain_job_values,
    execute_domain_run,
    measurement_recording_terminal_problem,
)
from scopecat._execution.engine import ExecutionEngineResult
from scopecat._execution.events import emit_run_finished, emit_run_started
from scopecat._execution.evidence import (
    RAW_MEASUREMENTS_DATASET_ID,
    build_execution_manifest,
    build_execution_summary,
    build_instrument_state_evidence,
    raw_measurement_schema,
)
from scopecat._execution.executor import execute_prepared_local_effects, execute_run
from scopecat._execution.measurement_fragments import (
    BoundLocalCollectionFragment,
    bind_local_collection_fragment,
    local_collection_fragment,
)
from scopecat._execution.persistence import (
    validate_measurement_index_shape,
    validate_raw_measurement_dataset,
)
from scopecat._execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat._execution.program import ResourceClaim
from scopecat._execution.run_lifecycle import commit_terminal_evidence
from scopecat._storage.local import (
    LocalCollectionRepository,
    LocalExecutionJournal,
    LocalMeasurementRecordCommitter,
    LocalPayloadEvidenceCommitter,
    LocalResourceLeaseManager,
    LocalRunStore,
)
from scopecat.errors import (
    DomainFetchFailed,
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    DomainSubmissionIndeterminate,
    MeasurementRecordingError,
    ProblemFailure,
    RunFailed,
    RunIndeterminate,
)
from scopecat.execution_backend import (
    PreparedDomainJobUnit,
    PreparedExecutionPlan,
)
from scopecat.ids import new_run_id
from scopecat.measurement_projection import project_measurement_records
from scopecat.measurement_recording import commit_projected_measurement_records
from scopecat.measurement_values import (
    ClosedMeasurementProductValues,
    ClosedMeasurementValueFragment,
    MeasurementValueCandidate,
    assemble_measurement_values,
    seal_measurement_value_fragment,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionSummary
from scopecat.models.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.models.run_plan import RunPlanPointInstrumentExecution, RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
)
from scopecat.results import MeasurementRecord
from scopecat.runtime import RuntimeEventSink, RuntimePayloadObserver


class _DomainUnitEffectFailed(Exception):
    """Stop the local lane after a captured domain-boundary failure."""


def execute_execution_plan(
    *,
    config: ConfigProfileSnapshot,
    prepared: PreparedExecutionPlan,
    request: RunRequest | None,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    """Execute one trusted exact-cover plan without backend-specific workflow forks."""

    point = prepared.point_unit
    domains = prepared.domain_units
    if point is not None and not domains:
        return execute_run(
            config=config,
            plan=point.bound_plan,
            request=request,
            instrument_provider=point.provider,
            execution=RunPlanPointInstrumentExecution(
                unit_id=point.id,
                backend_id=point.backend_id,
                provider_id=point.prepared.provider_id,
            ),
            workspace=workspace,
            config_source=config_source,
            event_sink=event_sink,
            payload_observer=payload_observer,
        )
    if point is None and len(domains) == 1:
        return execute_domain_run(
            config=config,
            prepared=domains[0].prepared,
            request=request,
            workspace=workspace,
            config_source=config_source,
            event_sink=event_sink,
        )
    return _execute_composite_run(
        config=config,
        prepared=prepared,
        request=request,
        workspace=workspace,
        config_source=config_source,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def _execute_composite_run(
    *,
    config: ConfigProfileSnapshot,
    prepared: PreparedExecutionPlan,
    request: RunRequest | None,
    workspace: str | Path,
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
    plan = prepared.run_plan_record()
    run_id = new_run_id()
    storage = LocalRunStore(Path(workspace))
    accepted = RunManifest(
        run_id=run_id,
        lifecycle="accepted",
        config_source=config_source,
    )
    storage.write_run_skeleton(
        manifest=accepted,
        request=request,
        plan=plan,
        config=config,
    )
    storage.write_manifest(accepted.model_copy(update={"lifecycle": "running"}))

    instrument_ids = [] if point is None else list(point.prepared.instrument_order)
    emit_run_started(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=plan.experiment_id,
        point_count=plan.point_count,
        instrument_ids=instrument_ids,
        output_ids=[record.id for record in plan.records],
    )

    journal = LocalExecutionJournal(workspace, run_id=run_id)
    measurements = LocalMeasurementRecordCommitter(workspace, run_id=run_id)
    readbacks = LocalCollectionRepository(workspace, run_id=run_id)
    payloads = LocalPayloadEvidenceCommitter(workspace, run_id=run_id)
    domain_values: dict[str, ClosedMeasurementProductValues] = {}
    domain_failure: tuple[PreparedDomainJobUnit, BaseException] | None = None

    def execute_domain_units() -> None:
        nonlocal domain_failure
        for unit in prepared.domain_units:
            try:
                domain_values[unit.id] = execute_domain_job_values(
                    unit.prepared,
                    run_id=run_id,
                    journal=journal,
                )
            except BaseException as error:
                domain_failure = (unit, error)
                raise _DomainUnitEffectFailed(unit.id) from error

    local_result: ExecutionEngineResult | None = None
    setup_problems: list[Problem] = []
    direct_interruption: BaseException | None = None
    resource_failure: BaseException | None = None
    claims = tuple(
        ResourceClaim(id=claim.id, kind=claim.kind)
        for claim in prepared.resource_claims
    )
    try:
        with LocalResourceLeaseManager(workspace).acquire(claims):
            if point is not None and local_prepared is not None:
                local_result, setup_problems = execute_prepared_local_effects(
                    config=config,
                    prepared=local_prepared,
                    provider=point.provider,
                    run_id=run_id,
                    workspace=workspace,
                    journal=journal,
                    measurements=measurements,
                    readbacks=readbacks,
                    payloads=payloads,
                    event_sink=event_sink,
                    payload_observer=payload_observer,
                    engine_runner=lambda engine: engine.run_around_point_set(
                        execute_domain_units
                    ),
                    acquire_resources=False,
                )
            else:
                try:
                    execute_domain_units()
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
                "composite_resource_lease_failed",
                "composite execution resource lease failed",
                run_id=run_id,
                operation_id="composite.resources",
                error=resource_failure,
            )
        )
    elif resource_failure is not None:
        certainty = "indeterminate"
        interruption = resource_failure
        problems.append(
            runtime_problem(
                "composite_resource_lease_interrupted",
                "composite execution resource lease was interrupted",
                run_id=run_id,
                operation_id="composite.resources",
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
            commit_projected_measurement_records(projected, measurements, journal)
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
                    operation_id="composite.measurements",
                )
            )
        except Exception as error:
            problems.append(
                problem_from_exception(
                    "composite_measurement_assembly_failed",
                    "composite measurement assembly failed",
                    run_id=run_id,
                    operation_id="composite.measurements",
                    error=error,
                )
            )
        except BaseException as error:
            interruption = error
            certainty = "indeterminate"
            problems.append(
                runtime_problem(
                    "composite_measurement_assembly_interrupted",
                    "composite measurement assembly was interrupted",
                    run_id=run_id,
                    operation_id="composite.measurements",
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
    expected_schema = raw_measurement_schema(plan.expected_dataset_schema)
    problems.extend(
        contextualize_problems(
            validate_measurement_index_shape(
                measurements=committed_measurements,
                expected_indices=set(range(plan.point_count)),
                duplicate_code="composite_measurement_point_duplicate",
                duplicate_message="composite measurements repeat point index",
                unknown_code="composite_measurement_point_unknown",
                unknown_message="composite measurements contain unknown point index",
                missing_observables_code="composite_measurement_observables_missing",
                missing_observables_message=(
                    "composite measurement records require at least one observable"
                ),
            ),
            run_id=run_id,
            operation_id="composite.validate-measurements",
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
            operation_id="composite.validate-dataset",
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
        plan=plan,
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
        config_source=config_source,
        include_instrument_state=instrument_state is not None,
    ).model_copy(update={"created_at": accepted.created_at})
    commit_terminal_evidence(
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
        experiment_id=plan.experiment_id,
        outcome=outcome,
        completed_point_count=summary.completed_point_count,
        point_count=plan.point_count,
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
    domain_values: dict[str, ClosedMeasurementProductValues],
    run_id: str,
    readbacks: LocalCollectionRepository,
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
        values = domain_values[unit.id]
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
            operation_id="composite.local",
        )
    )


def _domain_failure_problems(
    unit: PreparedDomainJobUnit,
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
    committer: LocalMeasurementRecordCommitter,
    *,
    run_id: str,
    problems: list[Problem],
) -> tuple[list[MeasurementRecord], bool]:
    try:
        return list(committer.measurements()), False
    except Exception as error:
        problems.append(
            problem_from_exception(
                "composite_measurement_reload_failed",
                "committed composite measurements could not be reloaded",
                run_id=run_id,
                operation_id="composite.measurements.reload",
                error=error,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
            )
        )
        problems.append(
            runtime_problem(
                "composite_measurement_reload_terminalized",
                "the run was terminalized without trusting its measurement chunks",
                run_id=run_id,
                operation_id="composite.measurements.reload",
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
    plan: RunPlanRecord,
    outcome: RunOutcome,
    local_result: ExecutionEngineResult | None,
    measurements: list[MeasurementRecord],
    instrument_ids: list[str],
    problems: list[Problem],
) -> ExecutionSummary:
    if local_result is not None:
        return build_execution_summary(
            result=replace(local_result, measurements=tuple(measurements)),
            outcome=outcome,
            instrument_ids=instrument_ids,
            point_count=plan.point_count,
            problems=problems,
        )
    completed_point_count = (
        plan.point_count
        if outcome.result == "succeeded"
        else len({record.point_index for record in measurements})
    )
    return ExecutionSummary(
        run_id=outcome.run_id,
        experiment_id=plan.experiment_id,
        outcome=outcome,
        point_count=plan.point_count,
        completed_point_count=completed_point_count,
        measurement_count=len(measurements),
        instrument_ids=instrument_ids,
        problem_count=len(problems),
        problems=tuple(problems),
    )


__all__ = ["execute_execution_plan"]
