"""Interpret the sole closed RunProgram through one durable effect journal."""

from __future__ import annotations

from scopecat.execution.effect_interpreter import RunEffectResult
from scopecat.execution.effects.domain import (
    domain_runtime_terminal_problem,
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
    instrument_state_evidence_ref,
    raw_measurement_schema,
    run_outcome_ref,
)
from scopecat.execution.local.executor import execute_run_operations
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
from scopecat.execution.program import RunCoverageBlock, RunDomainJob, RunProgram
from scopecat.execution.services import (
    ExecutionServices,
    MeasurementDatasetRepository,
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
from scopecat.measurements.projection import (
    ProjectedMeasurementDataset,
    project_measurement_records,
)
from scopecat.measurements.recording import (
    append_measurement_dataset,
    seal_measurement_dataset,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    seal_measurement_values,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.measurement_recording import MeasurementDatasetAppendIndex
from scopecat.records.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest
from scopecat.runs.repository import (
    RunModelWrite,
    TerminalRunCommit,
)
from scopecat.sdk.instruments.contracts import InstrumentProvider


def interpret_run_program(
    *,
    config: ConfigProfileSnapshot,
    program: RunProgram,
    request: RunRequest | None,
    services: ExecutionServices,
    instrument_provider: InstrumentProvider | None = None,
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
        instrument_provider=instrument_provider,
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
    instrument_provider: InstrumentProvider | None,
    config_source: RunConfigSource | None,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> RunManifest:
    host = program.host
    projection = program.measurements
    point_count = len(program.points.points)
    experiment_id = program.experiment_id
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

    instrument_ids = [] if host is None else list(host.instrument_order)
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
    committed_measurement_count = 0
    append_content_hashes: list[str] = []

    def commit_coverage(
        block: RunCoverageBlock,
        candidates: tuple[MeasurementValueCandidate, ...],
    ) -> None:
        nonlocal committed_measurement_count
        values = seal_measurement_values(
            program.measurements.product_values,
            candidates,
            points=block.points,
        )
        projected = project_measurement_records(
            program.measurements,
            values,
            run_id=run_id,
            points=block.points,
        )
        block_problems = (
            *validate_measurement_index_shape(
                measurements=projected.records,
                expected_indices=set(block.point_indices),
                duplicate_code="execution_plan_measurement_point_duplicate",
                duplicate_message="execution plan measurements repeat point index",
                unknown_code="execution_plan_measurement_point_unknown",
                unknown_message=(
                    "execution plan measurements contain unknown point index"
                ),
                missing_observables_code="execution_plan_measurement_observables_missing",
                missing_observables_message=(
                    "execution plan measurement records require at least one observable"
                ),
            ),
            *validate_raw_measurement_dataset(
                records=projected.records,
                expected_schema=raw_measurement_schema(projected.schema),
                dataset_id=RAW_MEASUREMENTS_DATASET_ID,
            ),
        )
        if block_problems:
            raise ProblemFailure(block_problems)
        receipt = append_measurement_dataset(
            projected,
            measurements,
            journal,
            transition_observer=transition_observer.observe,
        )
        if receipt is not None:
            committed_measurement_count += len(projected.records)
            append_content_hashes.append(receipt.dataset_content_hash)

    effect_result: RunEffectResult | None = None
    resource_failure: BaseException | None = None
    claims = program.resource_claims
    try:
        with services.resources.acquire(claims):
            effect_result = execute_run_operations(
                config=config,
                program=program,
                run_id=run_id,
                journal=journal,
                readbacks=readbacks,
                payloads=payloads,
                payload_observer=payload_observer,
                transition_observer=transition_observer,
                instrument_provider=instrument_provider,
                coverage_observer=commit_coverage,
                resource_leases=services.resources,
            )
    except BaseException as error:
        resource_failure = error

    problems = _effect_problems(
        result=effect_result,
        run_id=run_id,
    )
    certainty = (
        "indeterminate"
        if effect_result is not None and effect_result.indeterminate
        else "known"
    )
    interruption = None if effect_result is None else effect_result.interruption
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
    if effect_result is not None and effect_result.domain_failure is not None:
        unit, error = effect_result.domain_failure
        domain_problems, domain_uncertain, domain_interruption = (
            _domain_failure_problems(unit, error, run_id=run_id)
        )
        problems.extend(domain_problems)
        if domain_uncertain:
            certainty = "indeterminate"
        if domain_interruption is not None:
            interruption = domain_interruption

    measurement_reload_required = False
    seal_receipt = None
    coverage_failure = None if effect_result is None else effect_result.coverage_failure
    if coverage_failure is not None or effect_result is not None:
        try:
            if coverage_failure is not None:
                raise coverage_failure
            if effect_result is None:
                raise RuntimeError("measurement sealing requires an effect result")
            schema = program.measurements.schema_for(effect_result.admitted_points)
            if schema is not None:
                seal_receipt = seal_measurement_dataset(
                    run_id=run_id,
                    dataset_id=schema.dataset_id,
                    recording_contract_fingerprint=(
                        program.measurements.contract_fingerprint
                    ),
                    point_count=committed_measurement_count,
                    append_content_hashes=tuple(append_content_hashes),
                    writer=measurements,
                    journal=journal,
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
            measurement_reload_required = bool(
                error.receipt is not None or error.write_may_have_completed
            )
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
            measurement_reload_required = True
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

    if measurement_reload_required:
        indices, reload_uncertain = _reload_measurement_indices(
            measurements,
            run_id=run_id,
            problems=problems,
        )
        committed_measurement_count = sum(item.record_count for item in indices)
        append_content_hashes = [item.append_content_hash for item in indices]
        if reload_uncertain:
            certainty = "indeterminate"
    admitted_points = () if effect_result is None else effect_result.admitted_points
    admitted_point_count = len(admitted_points)
    final_dataset = ProjectedMeasurementDataset(
        projection,
        run_id,
        (),
        points=admitted_points,
    )
    dataset_schema = raw_measurement_schema(final_dataset.schema)

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
        None
        if host is None or effect_result is None
        else build_instrument_state_evidence(effect_result)
    )
    manifest = build_execution_manifest(
        run_id=run_id,
        outcome=outcome,
        measurement_count=(committed_measurement_count if seal_receipt else 0),
        dataset_content_hash=(
            None if seal_receipt is None else seal_receipt.dataset_content_hash
        ),
        dataset_schema=dataset_schema,
        expected_record_count=(point_count if projection.records else None),
        config_content_hash=accepted.config_content_hash,
        config_source=config_source,
        instrument_state=instrument_state,
    ).model_copy(update={"created_at": accepted.created_at})
    models = [RunModelWrite(ref=run_outcome_ref(), value=outcome)]
    if instrument_state is not None:
        models.append(
            RunModelWrite(
                ref=instrument_state_evidence_ref(),
                value=instrument_state,
            )
        )
    manifest = storage.commit_terminal(
        TerminalRunCommit(
            manifest=manifest,
            models=tuple(models),
        )
    )
    emit_run_finished(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=experiment_id,
        outcome=outcome,
        completed_point_count=(
            admitted_point_count
            if outcome.result == "succeeded"
            else transition_observer.completed_point_count
        ),
        point_count=admitted_point_count,
        measurement_count=(committed_measurement_count if seal_receipt else 0),
        problem_count=len(problems),
        compute_evaluated_node_count=(transition_observer.compute_evaluated_node_count),
        compute_payload_count=transition_observer.compute_payload_count,
    )
    if interruption is not None:
        interruption.add_note(f"Scopecat run_id: {run_id}")
        raise interruption
    if outcome.result != "succeeded":
        if outcome.certainty == "indeterminate":
            raise RunIndeterminate(run_id=run_id, outcome=outcome)
        raise RunFailed(run_id=run_id, outcome=outcome)
    return manifest


def _effect_problems(
    *,
    result: RunEffectResult | None,
    run_id: str,
) -> list[Problem]:
    selected = () if result is None else result.problems
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


def _reload_measurement_indices(
    committer: MeasurementDatasetRepository,
    *,
    run_id: str,
    problems: list[Problem],
) -> tuple[list[MeasurementDatasetAppendIndex], bool]:
    try:
        return list(committer.append_indices()), False
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
                details={"storage_ref": "execution-measurements"},
            )
        )
        return [], True
