"""Durable local orchestration for config-bound execution programs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import cast

from pydantic import JsonValue

from scopecat.execution.effect_interpreter import RunEffectInterpreter
from scopecat.execution.effect_result import (
    CoverageMeasurementObserver,
    RunEffectResult,
)
from scopecat.execution.local.drivers import (
    cleanup_after_setup_failure,
    describe_instruments,
    validate_instruments,
)
from scopecat.execution.program import RunProgram
from scopecat.kernel.errors import (
    ProviderContractError,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderResult,
)
from scopecat.sdk.journal import ExecutionJournal, commit_transition
from scopecat.sdk.runtime_problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)


def execute_run_operations(
    *,
    config: ConfigProfileSnapshot,
    program: RunProgram,
    run_id: str,
    journal: ExecutionJournal,
    instrument_provider: InstrumentProvider | None = None,
    coverage_observer: CoverageMeasurementObserver | None = None,
) -> RunEffectResult:
    """Provision optional host drivers and interpret one operation sequence."""

    host = program.host
    point_catalog = program.points
    if host is None:
        engine = RunEffectInterpreter(
            run_id=run_id,
            coordinate_ids=point_catalog.coordinate_ids,
            resource_order=program.resource_order,
            drivers={},
            journal=journal,
            coverage_observer=coverage_observer,
        )
        return engine.run(
            program.coverage,
            points=program.points.points,
        )

    return _execute_run_host_operations(
        config=config,
        program=program,
        instrument_provider=instrument_provider,
        run_id=run_id,
        journal=journal,
        coverage_observer=coverage_observer,
    )


def _execute_run_host_operations(
    *,
    config: ConfigProfileSnapshot,
    program: RunProgram,
    instrument_provider: InstrumentProvider | None,
    run_id: str,
    journal: ExecutionJournal,
    coverage_observer: CoverageMeasurementObserver | None,
) -> RunEffectResult:
    """Provision host resources and interpret the complete operation sequence."""

    host = program.host
    if host is None:
        raise AssertionError("host execution requires a host binding")
    if instrument_provider is None:
        raise ProviderContractError(
            (
                problem(
                    "instrument_provider_missing",
                    "host execution requires its experiment-system provider",
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("execution", "provider"),
                ),
            )
        )
    setup_problems: list[Problem] = []
    result = _provision_and_execute(
        run_id=run_id,
        config=config,
        provider=instrument_provider,
        program=program,
        setup_problems=setup_problems,
        journal=journal,
        coverage_observer=coverage_observer,
    )
    if not setup_problems:
        return result
    return replace(
        result,
        problems=(
            *setup_problems,
            *(problem for problem in result.problems if problem not in setup_problems),
        ),
    )


def _provision_and_execute(
    *,
    run_id: str,
    config: ConfigProfileSnapshot,
    provider: InstrumentProvider,
    program: RunProgram,
    setup_problems: list[Problem],
    journal: ExecutionJournal,
    coverage_observer: CoverageMeasurementObserver | None,
) -> RunEffectResult:
    """Provision, verify, execute, and finalize the admitted run."""

    host = program.host
    if host is None:
        raise AssertionError("provider provisioning requires a host binding")
    provider_entry = ExecutionTransition(
        run_id=run_id,
        operation_id="lifecycle.provide-instruments",
        stage="provide_instruments",
        effect="lifecycle",
        state="started",
        evidence={
            "provider_id": host.provider_id,
            "advertised_instrument_ids": list(host.advertised_descriptions),
        },
    )
    provider_intent_committed, journal_interruption = _commit_provider_transition(
        journal,
        provider_entry,
        setup_problems,
    )
    if not provider_intent_committed:
        return _setup_result(
            problems=setup_problems,
            interruption=journal_interruption,
        )

    try:
        provider_result = provider.provide(
            InstrumentProviderContext(
                config=config,
                instrument_ids=host.resource_order,
            )
        )
    except Exception as error:
        problem = problem_from_exception(
            "instrument_provider_failed",
            f"instrument provider {host.provider_id} failed",
            run_id=run_id,
            operation_id=provider_entry.operation_id,
            error=error,
        )
        setup_problems.append(problem)
        _, journal_interruption = _commit_provider_transition(
            journal,
            provider_entry.model_copy(
                update={"state": "unknown", "problems": (problem,)}
            ),
            setup_problems,
        )
        return _setup_result(
            problems=setup_problems,
            indeterminate=True,
            interruption=journal_interruption,
        )
    except BaseException as error:
        problem = _interruption_problem(
            error,
            run_id=run_id,
            operation_id=provider_entry.operation_id,
        )
        setup_problems.append(problem)
        _, journal_interruption = _commit_provider_transition(
            journal,
            provider_entry.model_copy(
                update={"state": "unknown", "problems": (problem,)}
            ),
            setup_problems,
        )
        return _setup_result(
            problems=setup_problems,
            indeterminate=True,
            interruption=error,
        )

    return _execute_provider_result(
        run_id=run_id,
        config=config,
        provider_result=provider_result,
        provider_entry=provider_entry,
        program=program,
        setup_problems=setup_problems,
        journal=journal,
        coverage_observer=coverage_observer,
    )


def _execute_provider_result(
    *,
    run_id: str,
    config: ConfigProfileSnapshot,
    provider_result: InstrumentProviderResult,
    provider_entry: ExecutionTransition,
    program: RunProgram,
    setup_problems: list[Problem],
    journal: ExecutionJournal,
    coverage_observer: CoverageMeasurementObserver | None,
) -> RunEffectResult:
    """Own every returned driver until a fully constructed engine takes over."""

    host = program.host
    if host is None:
        raise AssertionError("provided drivers require a host binding")
    instruments = list(provider_result.drivers)
    provider_transition_attempted = False
    engine: RunEffectInterpreter | None = None
    indeterminate = False
    interruption: BaseException | None = None
    try:
        provider_problems = list(
            contextualize_problems(
                provider_result.problems,
                run_id=run_id,
                operation_id=provider_entry.operation_id,
            )
        )
        setup_problems.extend(provider_problems)
        provider_evidence = {
            **provider_entry.evidence,
            **_provider_result_evidence(
                provider_id=host.provider_id,
                provider_result=provider_result,
                instruments=instruments,
                problems=provider_problems,
            ),
        }
        provider_transition_attempted = True
        transition_committed, journal_interruption = _commit_provider_transition(
            journal,
            provider_entry.model_copy(
                update={
                    "state": ("failed" if bool(provider_problems) else "completed"),
                    "problems": tuple(provider_problems),
                    "evidence": provider_evidence,
                }
            ),
            setup_problems,
        )
        if not transition_committed or journal_interruption is not None:
            indeterminate = True
            interruption = journal_interruption
        else:
            actual_descriptions: list[InstrumentDescription] = []
            if instruments and not bool(setup_problems):
                setup_problems.extend(
                    validate_instruments(config=config, instruments=instruments)
                )
                actual_descriptions, description_problems = describe_instruments(
                    instruments
                )
                setup_problems.extend(description_problems)
            setup_problems.extend(
                _validate_provided_descriptions(
                    run_id=run_id,
                    advertised={
                        instrument_id: host.advertised_descriptions[instrument_id]
                        for instrument_id in host.resource_order
                    },
                    actual=actual_descriptions,
                )
            )
            if not bool(setup_problems):
                engine = RunEffectInterpreter(
                    run_id=run_id,
                    coordinate_ids=program.points.coordinate_ids,
                    resource_order=program.resource_order,
                    drivers={
                        instrument.instrument_id: instrument
                        for instrument in instruments
                    },
                    journal=journal,
                    coverage_observer=coverage_observer,
                )
    except Exception as error:
        problem = problem_from_exception(
            "instrument_provider_result_invalid",
            f"instrument provider {host.provider_id} returned an invalid result",
            run_id=run_id,
            operation_id=provider_entry.operation_id,
            error=error,
        )
        setup_problems.append(problem)
        if not provider_transition_attempted:
            _commit_provider_transition(
                journal,
                provider_entry.model_copy(
                    update={"state": "failed", "problems": (problem,)}
                ),
                setup_problems,
            )
    except BaseException as error:
        problem = _interruption_problem(
            error,
            run_id=run_id,
            operation_id=provider_entry.operation_id,
        )
        setup_problems.append(problem)
        if not provider_transition_attempted:
            _commit_provider_transition(
                journal,
                provider_entry.model_copy(
                    update={"state": "unknown", "problems": (problem,)}
                ),
                setup_problems,
            )
        indeterminate = True
        interruption = error

    if engine is not None:
        # Engine construction is the ownership hand-off.  Its run boundary is
        # responsible for abort/cleanup and terminal state capture after effects.
        return engine.run(
            program.coverage,
            points=program.points.points,
        )
    return _finalize_owned_setup(
        run_id=run_id,
        instruments=instruments,
        problems=setup_problems,
        journal=journal,
        indeterminate=indeterminate,
        interruption=interruption,
    )


def _finalize_owned_setup(
    *,
    run_id: str,
    instruments: list[InstrumentDriver],
    problems: list[Problem],
    journal: ExecutionJournal,
    indeterminate: bool = False,
    interruption: BaseException | None = None,
) -> RunEffectResult:
    final_state, cleanup_interruption = cleanup_after_setup_failure(
        instruments,
        problems,
        run_id=run_id,
        journal=journal,
    )
    return _setup_result(
        problems=problems,
        final_state=final_state,
        indeterminate=indeterminate,
        interruption=(
            interruption if interruption is not None else cleanup_interruption
        ),
    )


def _setup_result(
    *,
    problems: list[Problem],
    final_state: Sequence[InstrumentStateSnapshot] = (),
    indeterminate: bool = False,
    interruption: BaseException | None = None,
) -> RunEffectResult:
    return RunEffectResult(
        problems=tuple(problems),
        initial_state=(),
        final_state=tuple(final_state),
        indeterminate=indeterminate,
        interruption=interruption,
    )


def _validate_provided_descriptions(
    *,
    run_id: str,
    advertised: dict[str, InstrumentDescription],
    actual: list[InstrumentDescription],
) -> list[Problem]:
    actual_by_id = {item.instrument_id: item for item in actual}
    problems: list[Problem] = []
    for instrument_id in sorted(set(advertised) - set(actual_by_id)):
        problems.append(
            runtime_problem(
                "instrument_provider_missing_advertised_instrument",
                f"provider did not create advertised instrument {instrument_id}",
                run_id=run_id,
                operation_id="lifecycle.provide-instruments",
                instrument_id=instrument_id,
            )
        )
    for instrument_id in sorted(set(actual_by_id) - set(advertised)):
        problems.append(
            runtime_problem(
                "instrument_provider_unadvertised_instrument",
                f"provider created unadvertised instrument {instrument_id}",
                run_id=run_id,
                operation_id="lifecycle.provide-instruments",
                instrument_id=instrument_id,
            )
        )
    for instrument_id in sorted(set(advertised) & set(actual_by_id)):
        if advertised[instrument_id] != actual_by_id[instrument_id]:
            problems.append(
                runtime_problem(
                    "instrument_description_changed_after_provision",
                    f"instrument {instrument_id} differs from its advertised contract",
                    run_id=run_id,
                    operation_id="lifecycle.provide-instruments",
                    instrument_id=instrument_id,
                )
            )
    return problems


def _interruption_problem(
    error: BaseException,
    *,
    run_id: str,
    operation_id: str,
) -> Problem:
    return runtime_problem(
        "execution_interrupted",
        f"execution interrupted by {type(error).__name__}",
        run_id=run_id,
        operation_id=operation_id,
        details={
            "exception_type": f"{type(error).__module__}.{type(error).__qualname__}"
        },
    )


def _commit_provider_transition(
    journal: ExecutionJournal,
    entry: ExecutionTransition,
    problems: list[Problem],
) -> tuple[bool, BaseException | None]:
    try:
        commit_transition(journal, entry)
    except Exception as error:
        problems.append(
            problem_from_exception(
                "execution_journal_commit_failed",
                f"failed to journal {entry.operation_id}",
                run_id=entry.run_id,
                operation_id=entry.operation_id,
                error=error,
                phase=ProblemPhase.PERSISTENCE,
            )
        )
        return False, None
    except BaseException as error:
        problems.append(
            _interruption_problem(
                error,
                run_id=entry.run_id,
                operation_id=entry.operation_id,
            )
        )
        return False, error
    return True, None


def _provider_result_evidence(
    *,
    provider_id: str,
    provider_result: InstrumentProviderResult,
    instruments: list[InstrumentDriver],
    problems: list[Problem],
) -> dict[str, JsonValue]:
    instrument_ids = sorted(instrument.instrument_id for instrument in instruments)
    receipt = {
        "provider_id": provider_id,
        "instrument_ids": instrument_ids,
        "problems": [item.model_dump(mode="json") for item in problems],
        "metadata": provider_result.metadata,
    }
    evidence = {
        "instrument_ids": instrument_ids,
        "provisioning_receipt": receipt,
    }
    return cast("dict[str, JsonValue]", evidence)
