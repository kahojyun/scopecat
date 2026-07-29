"""Interpret the closed RunProgram through its durable effect ledger."""

from __future__ import annotations

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
from scopecat.execution.measurement_postprocessors import (
    execute_measurement_postprocessors,
)
from scopecat.execution.measurement_recording import (
    append_measurement_dataset,
    seal_measurement_dataset,
)
from scopecat.execution.persistence import (
    validate_run_measurements,
)
from scopecat.execution.program import RunDomainJob, RunProgram
from scopecat.execution.services import (
    ExecutionSession,
)
from scopecat.kernel.errors import (
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    MeasurementRecordingError,
    ProblemFailure,
    RunFailed,
    RunIndeterminate,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
)
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.measurements.points import RunPoint
from scopecat.measurements.projection import project_measurement_records
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    seal_measurement_values,
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
    point_count = len(program.points.points)
    run_id = session.run_id
    journal = session.journal
    measurements = session.measurements
    committed_measurement_count = 0
    append_content_hashes: list[str] = []

    def commit_coverage(
        points: tuple[RunPoint, ...],
        candidates: tuple[MeasurementValueCandidate, ...],
    ) -> None:
        nonlocal committed_measurement_count
        completed_candidates = execute_measurement_postprocessors(
            program.measurement_postprocessors,
            candidates,
            points=points,
            catalog=program.measurements.catalog,
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
        )
        block_problems = (
            *validate_run_measurements(
                measurements=projected.records,
                expected_indices={point.ordinal for point in points},
            ),
        )
        if block_problems:
            raise ProblemFailure(block_problems)
        receipt = append_measurement_dataset(
            projected,
            measurements,
            journal,
        )
        if receipt is not None:
            committed_measurement_count += len(projected.records)
            append_content_hashes.append(receipt.dataset_content_hash)

    effect_result = _execute_instrument_effects(
        program=program,
        session=session,
        coverage_observer=commit_coverage,
    )

    problems = _effect_problems(
        result=effect_result,
        run_id=run_id,
    )
    certainty = "indeterminate" if effect_result.indeterminate else "known"
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
        if coverage_failure is not None:
            raise coverage_failure
        schema = program.measurements.schema_for(effect_result.admitted_points)
        if schema is not None:
            seal_receipt = seal_measurement_dataset(
                run_id=run_id,
                recording_contract_fingerprint=(
                    program.measurements.contract_fingerprint
                ),
                point_count=committed_measurement_count,
                append_content_hashes=tuple(append_content_hashes),
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

    admitted_points = effect_result.admitted_points
    dataset_schema = projection.schema_for(admitted_points)

    failed = bool(problems)
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
        problems=tuple(problems),
    )
    instrument_state = (
        None if host is None else build_instrument_state_evidence(run_id, effect_result)
    )
    contents = build_terminal_contents(
        outcome=outcome,
        measurement_count=(committed_measurement_count if seal_receipt else 0),
        dataset_content_hash=(
            None if seal_receipt is None else seal_receipt.dataset_content_hash
        ),
        dataset_schema=dataset_schema,
        expected_record_count=(point_count if projection.records else None),
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
    if interruption is not None:
        interruption.add_note(f"Scopecat run_id: {run_id}")
        raise interruption
    if outcome.result != "succeeded":
        if outcome.certainty == "indeterminate":
            raise RunIndeterminate(run_id=run_id, outcome=outcome)
        raise RunFailed(run_id=run_id, outcome=outcome)
    return manifest


def _execute_instrument_effects(
    *,
    program: RunProgram,
    session: ExecutionSession,
    coverage_observer: CoverageMeasurementObserver,
) -> RunEffectResult:
    instruments = session.instruments
    setup_problems = list(instruments.setup_problems)
    if not instruments.ready:
        return RunEffectResult(
            problems=tuple(setup_problems),
            observed_state=(),
            prepared_state=(),
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
            prepared_state=(),
            final_state=(),
            indeterminate=release_unknown,
        )

    engine = RunEffectInterpreter(
        run_id=session.run_id,
        coordinate_ids=program.points.coordinate_ids,
        instruments=instruments,
        journal=session.journal,
        coverage_observer=coverage_observer,
        payload_codecs=(
            EMPTY_PAYLOAD_CODECS
            if program.host is None
            else program.host.payload_codecs
        ),
    )
    return engine.run(
        program.coverage,
        points=program.points.points,
    )


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
