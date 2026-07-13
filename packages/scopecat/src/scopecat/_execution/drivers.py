"""Driver discovery and lifecycle helpers outside the program interpreter."""

from __future__ import annotations

import logging
from typing import cast

from scopecat._execution.journal import ExecutionJournal, ExecutionTransition
from scopecat._execution.problems import problem_from_exception, runtime_problem
from scopecat.instruments.sdk import (
    DriverFault,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentStateSnapshot,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)

logger = logging.getLogger(__name__)


def validate_instruments(
    *,
    config: ConfigProfileSnapshot,
    instruments: list[InstrumentDriver],
) -> list[Problem]:
    problems: list[Problem] = []
    configured_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    seen: set[str] = set()
    for instrument_index, instrument in enumerate(instruments):
        instrument_id = instrument.instrument_id
        if not instrument_id:
            problems.append(
                _preflight_problem(
                    "instrument_missing_id",
                    "instrument_id must be non-empty",
                    "instruments",
                    instrument_index,
                    "instrument_id",
                )
            )
            continue
        if instrument_id in seen:
            problems.append(
                _preflight_problem(
                    "instrument_duplicate_id",
                    f"duplicate instrument id {instrument_id}",
                    "instruments",
                    instrument_index,
                    "instrument_id",
                )
            )
        seen.add(instrument_id)
        if instrument_id not in configured_ids:
            problems.append(
                _preflight_problem(
                    "instrument_not_in_config",
                    f"instrument {instrument_id} is not in config",
                    "instruments",
                    instrument_index,
                    "instrument_id",
                )
            )
        if not instrument.implementation_id:
            problems.append(
                _preflight_problem(
                    "instrument_missing_implementation_id",
                    "implementation_id must be non-empty",
                    "instruments",
                    instrument_index,
                    "implementation_id",
                )
            )
        if not instrument.implementation_version:
            problems.append(
                _preflight_problem(
                    "instrument_missing_implementation_version",
                    "implementation_version must be non-empty",
                    "instruments",
                    instrument_index,
                    "implementation_version",
                )
            )
    return problems


def describe_instruments(
    instruments: list[InstrumentDriver],
) -> tuple[list[InstrumentDescription], list[Problem]]:
    descriptions: list[InstrumentDescription] = []
    problems: list[Problem] = []
    for instrument in instruments:
        try:
            description = instrument.describe()
        except Exception as error:
            problems.append(
                preflight_problem_from_exception(
                    "instrument_describe_failed",
                    f"instrument describe failed for {instrument.instrument_id}",
                    ("instruments", instrument.instrument_id, "description"),
                    error,
                )
            )
            continue
        if description.instrument_id != instrument.instrument_id:
            problems.append(
                _preflight_problem(
                    "instrument_description_id_mismatch",
                    f"driver {instrument.instrument_id} described "
                    f"{description.instrument_id}",
                    "instruments",
                    instrument.instrument_id,
                    "description",
                    "instrument_id",
                )
            )
            continue
        if (
            description.implementation_id != instrument.implementation_id
            or description.implementation_version != instrument.implementation_version
        ):
            problems.append(
                _preflight_problem(
                    "instrument_description_implementation_mismatch",
                    f"instrument {instrument.instrument_id} description does not "
                    "match its implementation identity",
                    "instruments",
                    instrument.instrument_id,
                    "description",
                    "implementation",
                )
            )
            continue
        descriptions.append(description)
    return descriptions, problems


def cleanup_after_setup_failure(
    instruments: list[InstrumentDriver],
    problems: list[Problem],
    *,
    run_id: str,
    journal: ExecutionJournal,
) -> tuple[list[InstrumentStateSnapshot], BaseException | None]:
    """Journal, release provisioned drivers, and capture their terminal state."""

    interruption: BaseException | None = None
    managed: list[tuple[str, bool, InstrumentDriver]] = []
    for instrument_index, instrument in enumerate(instruments):
        instrument_id, identity_known, identity_interruption = _safe_instrument_id(
            instrument,
            run_id=run_id,
            fallback=f"provider-driver-{instrument_index}",
            problems=problems,
        )
        interruption = _first_interruption(interruption, identity_interruption)
        managed.append((instrument_id, identity_known, instrument))

    for cleanup_index, (instrument_id, _, instrument) in enumerate(reversed(managed)):
        entry = ExecutionTransition(
            run_id=run_id,
            operation_id=(f"lifecycle.setup-cleanup.{cleanup_index}.{instrument_id}"),
            stage="setup_cleanup",
            effect="lifecycle",
            state="started",
            instrument_id=instrument_id,
        )
        interruption = _first_interruption(
            interruption,
            _append_setup_transition(journal, entry, problems),
        )
        try:
            instrument.cleanup()
        except Exception as error:
            problem = problem_from_exception(
                "instrument_cleanup_failed",
                f"instrument cleanup failed for {instrument_id}",
                run_id=run_id,
                operation_id=entry.operation_id,
                instrument_id=instrument_id,
                error=error,
            )
            problems.append(problem)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "problems": (problem,)}
                    ),
                    problems,
                ),
            )
            continue
        except BaseException as error:
            interruption = _first_interruption(interruption, error)
            problem = _interruption_problem(
                error,
                run_id=run_id,
                operation_id=entry.operation_id,
                instrument_id=instrument_id,
            )
            problems.append(problem)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "problems": (problem,)}
                    ),
                    problems,
                ),
            )
            continue
        interruption = _first_interruption(
            interruption,
            _append_setup_transition(
                journal,
                entry.model_copy(update={"state": "completed"}),
                problems,
            ),
        )
    states: list[InstrumentStateSnapshot] = []
    for read_index, (instrument_id, identity_known, instrument) in enumerate(managed):
        entry = ExecutionTransition(
            run_id=run_id,
            operation_id=(
                f"lifecycle.setup-terminal-read-state.{read_index}.{instrument_id}"
            ),
            stage="setup_terminal_readback",
            effect="read",
            state="started",
            instrument_id=instrument_id,
        )
        interruption = _first_interruption(
            interruption,
            _append_setup_transition(journal, entry, problems),
        )
        try:
            state = instrument.read_state().model_copy(deep=True)
            if identity_known and state.instrument_id != instrument_id:
                raise ValueError("read state belongs to a different instrument")
        except Exception as error:
            problem = problem_from_exception(
                "instrument_readback_failed",
                f"instrument terminal readback failed for {instrument_id}",
                run_id=run_id,
                operation_id=entry.operation_id,
                instrument_id=instrument_id,
                error=error,
            )
            problems.append(problem)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "problems": (problem,)}
                    ),
                    problems,
                ),
            )
            continue
        except BaseException as error:
            interruption = _first_interruption(interruption, error)
            problem = _interruption_problem(
                error,
                run_id=run_id,
                operation_id=entry.operation_id,
                instrument_id=instrument_id,
            )
            problems.append(problem)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "problems": (problem,)}
                    ),
                    problems,
                ),
            )
            continue
        states.append(state)
        interruption = _first_interruption(
            interruption,
            _append_setup_transition(
                journal,
                entry.model_copy(update={"state": "completed"}),
                problems,
            ),
        )
    return states, interruption


def _append_setup_transition(
    journal: ExecutionJournal,
    entry: ExecutionTransition,
    problems: list[Problem],
) -> BaseException | None:
    try:
        journal.append(entry)
    except Exception as error:
        problems.append(
            problem_from_exception(
                "execution_journal_commit_failed",
                f"failed to journal {entry.operation_id}",
                run_id=entry.run_id,
                operation_id=entry.operation_id,
                error=error,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
            )
        )
    except BaseException as error:
        problems.append(
            _interruption_problem(
                error,
                run_id=entry.run_id,
                operation_id=entry.operation_id,
            )
        )
        return error
    return None


def _safe_instrument_id(
    instrument: InstrumentDriver,
    *,
    run_id: str,
    fallback: str,
    problems: list[Problem],
) -> tuple[str, bool, BaseException | None]:
    try:
        instrument_id = cast("object", instrument.instrument_id)
    except Exception as error:
        problems.append(
            problem_from_exception(
                "instrument_identity_failed",
                "instrument identity lookup failed during setup finalization",
                run_id=run_id,
                instrument_id=fallback,
                error=error,
            )
        )
        return fallback, False, None
    except BaseException as error:
        problems.append(
            _interruption_problem(
                error,
                run_id=run_id,
                instrument_id=fallback,
            )
        )
        return fallback, False, error
    if type(instrument_id) is not str or not instrument_id:
        problems.append(
            runtime_problem(
                "instrument_identity_invalid",
                "instrument identity must be a non-empty string during setup "
                "finalization",
                run_id=run_id,
                instrument_id=fallback,
                category=ProblemCategory.PROVIDER_CONTRACT,
            )
        )
        return fallback, False, None
    return instrument_id, True, None


def _first_interruption(
    current: BaseException | None,
    candidate: BaseException | None,
) -> BaseException | None:
    return current if current is not None else candidate


def preflight_problem_from_exception(
    code: str,
    message: str,
    path: tuple[LocationPathItem, ...],
    error: Exception,
) -> Problem:
    if isinstance(error, DriverFault):
        source = error.problem
        related_locations = source.related_locations
        if source.location is not None:
            related_locations = (source.location, *related_locations)
        return source.model_copy(
            update={
                "phase": ProblemPhase.PROVIDER_PREFLIGHT,
                "location": model_location("instrument_provider", *path),
                "related_locations": related_locations,
            }
        )
    logger.error(
        "instrument provider preflight raised an exception",
        extra={"problem_code": code},
        exc_info=(type(error), error, error.__traceback__),
    )
    return blocking_problem(
        code,
        f"{message} ({type(error).__name__})",
        category=ProblemCategory.EXTERNAL_FAILURE,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", *path),
        details={
            "exception_type": f"{type(error).__module__}.{type(error).__qualname__}"
        },
    )


def _interruption_problem(
    error: BaseException,
    *,
    run_id: str,
    operation_id: str | None = None,
    instrument_id: str | None = None,
) -> Problem:
    return runtime_problem(
        "execution_interrupted",
        f"execution interrupted by {type(error).__name__}",
        run_id=run_id,
        operation_id=operation_id,
        instrument_id=instrument_id,
        category=ProblemCategory.INTERRUPTED,
        details={
            "exception_type": f"{type(error).__module__}.{type(error).__qualname__}"
        },
    )


def _preflight_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("instrument_provider", *path),
    )


__all__ = [
    "cleanup_after_setup_failure",
    "describe_instruments",
    "preflight_problem_from_exception",
    "validate_instruments",
]
