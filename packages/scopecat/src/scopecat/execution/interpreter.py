"""Interpret the closed RunProgram through its durable effect ledger."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace

from scopecat.execution.effect_interpreter import RunEffectInterpreter
from scopecat.execution.effect_result import (
    CoverageMeasurementObserver,
    RunEffectResult,
)
from scopecat.execution.effects.domain import (
    domain_runtime_terminal_problem,
    measurement_recording_terminal_problem,
)
from scopecat.execution.evidence import (
    build_instrument_state_evidence,
    build_terminal_contents,
    instrument_state_evidence_ref,
)
from scopecat.execution.measurement_computes import (
    execute_measurement_computes,
)
from scopecat.execution.measurement_ordering import CanonicalMeasurementBuffer
from scopecat.execution.measurement_recording import (
    ingest_measurement_dataset,
    initialize_measurement_dataset,
    seal_measurement_dataset,
)
from scopecat.execution.persistence import (
    validate_run_measurements,
)
from scopecat.execution.program import (
    RunCoveredOperation,
    RunDomainJob,
    RunPointInspection,
    RunProgram,
)
from scopecat.execution.services import (
    ExecutionSession,
    RunPointProposalWriter,
)
from scopecat.kernel.errors import (
    CheckFailed,
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    MeasurementRecordingError,
    ProblemFailure,
    RunCancelled,
    RunFailed,
    RunIndeterminate,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
)
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.measurements.points import AcceptedRunPoint, PointCandidate
from scopecat.measurements.projection import (
    ProjectedMeasurementDataset,
    project_measurement_records,
)
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    seal_measurement_values,
)
from scopecat.optimization import (
    CompletedPointObservation,
    OptimizationComplete,
    PointOptimizerContext,
    PointProposalLedger,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    measurement_record_content_hash,
)
from scopecat.records.run import RunManifest
from scopecat.runs.repository import (
    RunModelWrite,
    TerminalRunCommit,
)
from scopecat.sdk.payloads import EMPTY_PAYLOAD_CODECS
from scopecat.sdk.runtime_problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)


def execute_admitted_run(
    *,
    program: RunProgram,
    session: ExecutionSession,
) -> RunManifest:
    """Execute a transient program against its authoritative accepted snapshot."""

    accepted = session.accepted
    if accepted.outcome is not None:
        msg = "terminal run cannot start execution"
        raise ValueError(msg)
    if accepted.config_content_hash != program.config_content_hash:
        msg = "run program config does not match the admitted snapshot"
        raise ValueError(msg)
    session.begin()
    return _execute_run(
        program=program,
        session=session,
    )


def _execute_run(
    *,
    program: RunProgram,
    session: ExecutionSession,
) -> RunManifest:
    host = program.host
    projection = program.measurements
    point_state = _ExecutionPointState.create(
        program,
        proposal_writer=session.point_proposals,
    )
    run_id = session.run_id
    journal = session.journal
    measurements = session.measurements
    dataset_header, header_failure, cancelled_without_effects = (
        _prepare_execution_start(program, session)
    )
    _initialize_point_plan(
        point_state,
        enabled=header_failure is None and not cancelled_without_effects,
    )
    recorded_measurement_count = 0
    completed_coverage_count = 0
    record_content_hashes: list[str] = []
    measurement_buffer = CanonicalMeasurementBuffer()

    def commit_coverage(
        points: tuple[AcceptedRunPoint, ...],
        candidates: tuple[MeasurementValueCandidate, ...],
        value_candidates: tuple[ValueRecordCandidate, ...],
    ) -> None:
        nonlocal completed_coverage_count, recorded_measurement_count
        static_value_candidates = program.measurements.static_value_candidates(points)
        all_value_candidates = (*static_value_candidates, *value_candidates)
        completed_candidates = execute_measurement_computes(
            program.measurement_computes,
            candidates,
            points=points,
            catalog=program.measurements.catalog,
            value_candidates=all_value_candidates,
        )
        values = seal_measurement_values(
            program.measurements.catalog,
            completed_candidates,
            points=points,
        )
        projected = project_measurement_records(
            program.measurements,
            values,
            run_id=run_id,
            points=points,
            value_candidates=all_value_candidates,
        )
        block_problems = (
            *validate_run_measurements(
                measurements=projected.records,
                expected_indices={point.ordinal for point in points},
            ),
        )
        if block_problems:
            raise ProblemFailure(block_problems)
        if not projection.has_dataset:
            completed_coverage_count = _advance_unrecorded_coverage(
                session,
                points,
                completed_point_count=completed_coverage_count,
            )
        else:
            ready_records = measurement_buffer.add(projected.records)
            if ready_records:
                if dataset_header is None:
                    raise ValueError("projected measurements require a dataset header")
                ingest_measurement_dataset(
                    ProjectedMeasurementDataset(projection, run_id, ready_records),
                    measurements,
                    header=dataset_header,
                )
                recorded_measurement_count += len(ready_records)
                record_content_hashes.extend(
                    measurement_record_content_hash(record) for record in ready_records
                )
        records_by_point = {
            point.ordinal: tuple(
                record
                for record in projected.records
                if record.point_index == point.ordinal
            )
            for point in points
        }
        point_state.observations.extend(
            CompletedPointObservation(
                point=point,
                records=records_by_point[point.ordinal],
            )
            for point in points
        )

    effect_result = _execute_or_cancel_effects(
        program=program,
        session=session,
        coverage_observer=commit_coverage,
        header_failure=header_failure,
        cancelled_without_effects=cancelled_without_effects,
        point_state=point_state,
    )

    problems = _effect_problems(
        result=effect_result,
        run_id=run_id,
    )
    header_problems, header_indeterminate = _header_failure_problems(
        header_failure,
        run_id=run_id,
    )
    problems.extend(header_problems)
    certainty = (
        "indeterminate"
        if effect_result.indeterminate or header_indeterminate
        else "known"
    )
    interruption = effect_result.interruption
    if effect_result.domain_failure is not None:
        unit, error = effect_result.domain_failure
        domain_problems, domain_uncertain, domain_interruption = (
            _domain_failure_problems(unit, error, run_id=run_id)
        )
        problems.extend(domain_problems)
        if domain_uncertain:
            certainty = "indeterminate"
        if domain_interruption is not None:
            interruption = domain_interruption

    seal_receipt = None
    coverage_failure = effect_result.coverage_failure
    try:
        _flush_execution_progress(
            session,
            has_dataset=dataset_header is not None,
        )
        if coverage_failure is not None:
            raise coverage_failure
        _validate_measurement_completion(
            measurement_buffer,
            successful=not problems,
        )
        if dataset_header is not None and header_failure is None:
            seal_receipt = seal_measurement_dataset(
                run_id=run_id,
                header=dataset_header,
                point_count=recorded_measurement_count,
                record_content_hashes=tuple(record_content_hashes),
                writer=measurements,
                journal=journal,
            )
    except MeasurementRecordingError as error:
        problems.extend(
            contextualize_problems(
                error.problems,
                run_id=run_id,
                operation_id=error.operation_id,
            )
        )
        problems.append(measurement_recording_terminal_problem(error, run_id=run_id))
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
                details={"exception_type": type(error).__qualname__},
            )
        )

    dataset_schema = None if dataset_header is None else dataset_header.dataset_schema

    failed = bool(problems)
    outcome = RunOutcome(
        run_id=run_id,
        result=(
            "cancelled"
            if effect_result.cancelled or interruption is not None
            else "failed"
            if failed or certainty == "indeterminate"
            else "succeeded"
        ),
        certainty="indeterminate" if certainty == "indeterminate" else "known",
        problems=tuple(problems),
    )
    instrument_state = (
        None if host is None else build_instrument_state_evidence(run_id, effect_result)
    )
    contents = build_terminal_contents(
        outcome=outcome,
        measurement_count=(recorded_measurement_count if seal_receipt else 0),
        dataset_content_hash=(
            None if seal_receipt is None else seal_receipt.dataset_content_hash
        ),
        dataset_schema=dataset_schema,
        expected_record_count=(
            len(point_state.points) if projection.has_dataset else None
        ),
        instrument_state=instrument_state,
    )
    models: list[RunModelWrite] = []
    if instrument_state is not None:
        models.append(
            RunModelWrite(
                ref=instrument_state_evidence_ref(),
                value=instrument_state,
            )
        )
    manifest = session.commit_terminal(
        TerminalRunCommit(
            run_id=run_id,
            outcome=outcome,
            contents=contents,
            models=tuple(models),
        )
    )
    committed_outcome = manifest.outcome
    if committed_outcome is None:
        raise AssertionError("terminal commit returned a non-terminal manifest")
    if interruption is not None:
        interruption.add_note(f"Scopecat run_id: {run_id}")
        raise interruption
    if committed_outcome.result != "succeeded":
        _raise_terminal_run_error(run_id, committed_outcome)
    return manifest


def _initialize_point_plan(state: _ExecutionPointState, *, enabled: bool) -> None:
    if enabled and state.proposal_writer is not None:
        state.proposal_writer.initialize()


def _advance_unrecorded_coverage(
    session: ExecutionSession,
    points: tuple[AcceptedRunPoint, ...],
    *,
    completed_point_count: int,
) -> int:
    point_indices = tuple(point.ordinal for point in points)
    next_completed_count = completed_point_count + len(points)
    if point_indices != tuple(range(completed_point_count, next_completed_count)):
        raise AssertionError("completed coverage must be one contiguous prefix")
    if session.coverage is not None:
        session.coverage.advance(
            start_index=completed_point_count,
            point_count=len(points),
        )
    return next_completed_count


def _flush_execution_progress(
    session: ExecutionSession,
    *,
    has_dataset: bool,
) -> tuple[MeasurementDatasetReceipt, ...]:
    if session.coverage is not None:
        session.coverage.flush()
    return session.measurements.flush() if has_dataset else ()


def _raise_terminal_run_error(run_id: str, outcome: RunOutcome) -> None:
    if outcome.certainty == "indeterminate":
        raise RunIndeterminate(run_id=run_id, outcome=outcome)
    if outcome.result == "cancelled":
        raise RunCancelled(run_id=run_id, outcome=outcome)
    raise RunFailed(run_id=run_id, outcome=outcome)


def _validate_measurement_completion(
    buffer: CanonicalMeasurementBuffer,
    *,
    successful: bool,
) -> None:
    if successful and buffer.pending_indices:
        raise AssertionError(
            "successful coverage left non-contiguous measurement records"
        )


def _initialize_dataset_header(
    program: RunProgram,
    session: ExecutionSession,
) -> tuple[MeasurementDatasetHeader | None, MeasurementRecordingError | None]:
    schema = program.measurements.schema
    if schema is None:
        return None, None
    header = MeasurementDatasetHeader(
        run_id=session.run_id,
        recording_contract_fingerprint=program.measurements.contract_fingerprint,
        dataset_schema=schema,
        expected_record_count=program.points.contract.point_count,
        record_count_limit=program.points.contract.point_limit,
    )
    try:
        initialize_measurement_dataset(
            header,
            session.measurements,
            session.journal,
        )
    except MeasurementRecordingError as error:
        return header, error
    return header, None


def _prepare_execution_start(
    program: RunProgram,
    session: ExecutionSession,
) -> tuple[MeasurementDatasetHeader | None, MeasurementRecordingError | None, bool]:
    if session.cancellation_requested():
        return None, None, not session.effects_ready()
    header, failure = _initialize_dataset_header(program, session)
    return header, failure, False


def _execute_or_cancel_effects(
    *,
    program: RunProgram,
    session: ExecutionSession,
    coverage_observer: CoverageMeasurementObserver,
    header_failure: MeasurementRecordingError | None,
    cancelled_without_effects: bool,
    point_state: _ExecutionPointState,
) -> RunEffectResult:
    if cancelled_without_effects:
        return RunEffectResult(
            problems=(
                runtime_problem(
                    "run_cancellation_requested",
                    "run stopped before hardware provisioning after cancellation "
                    "was requested",
                    run_id=session.run_id,
                    operation_id="execution-plan.cancel",
                ),
            ),
            observed_state=(),
            baseline_state=(),
            final_state=(),
            cancelled=True,
        )
    if header_failure is not None:
        return RunEffectResult(
            problems=(),
            observed_state=(),
            baseline_state=(),
            final_state=(),
        )
    return _execute_instrument_effects(
        program=program,
        session=session,
        coverage_observer=coverage_observer,
        point_state=point_state,
    )


def _header_failure_problems(
    error: MeasurementRecordingError | None,
    *,
    run_id: str,
) -> tuple[list[Problem], bool]:
    if error is None:
        return [], False
    return (
        [
            *contextualize_problems(
                error.problems,
                run_id=run_id,
                operation_id=error.operation_id,
            ),
            measurement_recording_terminal_problem(error, run_id=run_id),
        ],
        error.write_may_have_completed,
    )


def _execute_instrument_effects(
    *,
    program: RunProgram,
    session: ExecutionSession,
    coverage_observer: CoverageMeasurementObserver,
    point_state: _ExecutionPointState,
) -> RunEffectResult:
    instruments = session.instruments
    setup_problems = list(instruments.setup_problems)
    if not instruments.ready:
        return RunEffectResult(
            problems=tuple(setup_problems),
            observed_state=(),
            baseline_state=(),
            final_state=(),
        )

    if setup_problems:
        try:
            finished = instruments.finish(
                operation_id="hardware.reject-setup",
                failed=True,
            )
            release_problems = list(finished.problems)
            release_unknown = finished.indeterminate
        except Exception as error:
            release_problems = [
                problem_from_exception(
                    "instrument_setup_release_failed",
                    "instrument setup could not be released",
                    run_id=session.run_id,
                    operation_id="hardware.reject-setup",
                    error=error,
                )
            ]
            release_unknown = True
        return RunEffectResult(
            problems=(*setup_problems, *release_problems),
            observed_state=(),
            baseline_state=(),
            final_state=(),
            indeterminate=release_unknown,
        )

    engine = RunEffectInterpreter(
        run_id=session.run_id,
        coordinate_ids=program.points.coordinate_ids,
        instruments=instruments,
        journal=session.journal,
        coverage_observer=coverage_observer,
        recorded_value_ids=program.runtime_value_ids,
        payload_codecs=(
            EMPTY_PAYLOAD_CODECS
            if program.host is None
            else program.host.payload_codecs
        ),
        cancellation_requested=session.cancellation_requested,
    )

    def commit_durable_progress() -> None:
        _flush_execution_progress(
            session,
            has_dataset=program.measurements.has_dataset,
        )

    result = engine.run(
        _execution_coverage(
            program,
            point_state,
            durable_progress=commit_durable_progress,
        ),
        points=point_state.points,
        success_state=program.success_state,
    )
    return replace(result, proposal_ledger=point_state.ledger)


@dataclass(slots=True)
class _ExecutionPointState:
    points: list[AcceptedRunPoint]
    observations: list[CompletedPointObservation]
    ledger: PointProposalLedger | None
    inspections: list[RunPointInspection]
    proposal_writer: RunPointProposalWriter | None

    @classmethod
    def create(
        cls,
        program: RunProgram,
        *,
        proposal_writer: RunPointProposalWriter | None,
    ) -> _ExecutionPointState:
        adaptive = program.adaptive_point_plan
        points = list(program.points.points)
        return cls(
            points=points,
            observations=[],
            ledger=(
                None
                if adaptive is None
                else adaptive.ledger(initial_point_count=len(points))
            ),
            inspections=[],
            proposal_writer=proposal_writer,
        )


def _execution_coverage(
    program: RunProgram,
    state: _ExecutionPointState,
    *,
    durable_progress: Callable[[], None],
) -> Iterator[RunCoveredOperation]:
    yield from program.coverage
    adaptive = program.adaptive_point_plan
    if adaptive is None:
        return
    durable_progress()
    ledger = state.ledger
    if ledger is None:
        raise AssertionError("adaptive execution requires a proposal ledger")
    while len(state.points) < adaptive.max_points:
        if len(ledger.entries) >= adaptive.proposal_limit:
            raise RuntimeError("optimizer exceeded the adaptive proposal limit")
        proposal = adaptive.optimizer.propose(
            PointOptimizerContext(
                observations=tuple(state.observations),
                ledger=ledger,
                point_limit=adaptive.max_points,
            )
        )
        if isinstance(proposal, OptimizationComplete):
            if state.proposal_writer is not None:
                state.proposal_writer.close(
                    completed_point_count=len(state.observations),
                    reason=proposal.reason,
                )
            break
        if proposal.based_on_completed_point_count is None:
            proposal = PointCandidate(
                coordinates=proposal.coordinates,
                source=proposal.source,
                based_on_completed_point_count=len(state.observations),
            )
        rejection = _proposal_rejection(proposal, state)
        if rejection is not None:
            ledger = ledger.reject(proposal, reason=rejection)
            state.ledger = ledger
            if state.proposal_writer is not None:
                state.proposal_writer.append(ledger.entries[-1], None)
            continue
        try:
            accepted = program.coverage.accept(proposal)
        except CheckFailed as error:
            ledger = ledger.reject(proposal, reason=str(error))
            state.ledger = ledger
            if state.proposal_writer is not None:
                state.proposal_writer.append(ledger.entries[-1], None)
            continue
        state.points.append(accepted.point)
        state.inspections.append(accepted.inspection)
        ledger = ledger.accept(proposal, accepted.point)
        state.ledger = ledger
        if state.proposal_writer is not None:
            state.proposal_writer.append(ledger.entries[-1], accepted.inspection)
        yield from accepted.operations
        durable_progress()
    else:
        if state.proposal_writer is not None:
            state.proposal_writer.close(
                completed_point_count=len(state.observations),
                reason="point budget exhausted",
            )


def _proposal_rejection(
    proposal: PointCandidate,
    state: _ExecutionPointState,
) -> str | None:
    based_on = proposal.based_on_completed_point_count
    if based_on is not None and based_on != len(state.observations):
        return (
            f"proposal was based on {based_on} completed points; "
            f"the run has {len(state.observations)}"
        )
    return None


def _effect_problems(
    *,
    result: RunEffectResult,
    run_id: str,
) -> list[Problem]:
    return list(
        contextualize_problems(
            result.problems,
            run_id=run_id,
            operation_id="execution-plan.effects",
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
        uncertain = error.certainty == "indeterminate"
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
                details={"exception_type": type(error).__qualname__},
            )
        ],
        True,
        error,
    )
