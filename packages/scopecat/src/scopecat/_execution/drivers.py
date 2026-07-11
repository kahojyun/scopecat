"""Driver discovery and lifecycle helpers outside the program interpreter."""

from __future__ import annotations

from typing import cast

from scopecat._execution.journal import ExecutionJournal, ExecutionJournalEntry
from scopecat.diagnostics import Diagnostic
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentDriver,
    InstrumentStateSnapshot,
)
from scopecat.models.config import ConfigProfileSnapshot


def validate_instruments(
    *,
    config: ConfigProfileSnapshot,
    instruments: list[InstrumentDriver],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    configured_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    seen: set[str] = set()
    for instrument in instruments:
        instrument_id = instrument.instrument_id
        if not instrument_id:
            diagnostics.append(
                _diagnostic(
                    "instrument_missing_id",
                    "instrument_id must be non-empty",
                    "instrument.instrument_id",
                )
            )
            continue
        if instrument_id in seen:
            diagnostics.append(
                _diagnostic(
                    "instrument_duplicate_id",
                    f"duplicate instrument id {instrument_id}",
                    "instrument.instrument_id",
                )
            )
        seen.add(instrument_id)
        if instrument_id not in configured_ids:
            diagnostics.append(
                _diagnostic(
                    "instrument_not_in_config",
                    f"instrument {instrument_id} is not in config",
                    "instrument.instrument_id",
                )
            )
        if not instrument.implementation_id:
            diagnostics.append(
                _diagnostic(
                    "instrument_missing_implementation_id",
                    "implementation_id must be non-empty",
                    "instrument.implementation_id",
                )
            )
        if not instrument.implementation_version:
            diagnostics.append(
                _diagnostic(
                    "instrument_missing_implementation_version",
                    "implementation_version must be non-empty",
                    "instrument.implementation_version",
                )
            )
    return diagnostics


def describe_instruments(
    instruments: list[InstrumentDriver],
) -> tuple[list[InstrumentDescription], list[Diagnostic]]:
    descriptions: list[InstrumentDescription] = []
    diagnostics: list[Diagnostic] = []
    for instrument in instruments:
        try:
            description = instrument.describe()
        except Exception as error:
            diagnostics.append(
                diagnostic_from_exception(
                    "instrument_describe_failed",
                    f"instrument describe failed for {instrument.instrument_id}",
                    instrument.instrument_id,
                    error,
                )
            )
            continue
        if description.instrument_id != instrument.instrument_id:
            diagnostics.append(
                _diagnostic(
                    "instrument_description_id_mismatch",
                    f"driver {instrument.instrument_id} described "
                    f"{description.instrument_id}",
                    instrument.instrument_id,
                )
            )
            continue
        if (
            description.implementation_id != instrument.implementation_id
            or description.implementation_version != instrument.implementation_version
        ):
            diagnostics.append(
                _diagnostic(
                    "instrument_description_implementation_mismatch",
                    f"instrument {instrument.instrument_id} description does not "
                    "match its implementation identity",
                    instrument.instrument_id,
                )
            )
            continue
        descriptions.append(description)
    return descriptions, diagnostics


def cleanup_after_setup_failure(
    instruments: list[InstrumentDriver],
    diagnostics: list[Diagnostic],
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
            fallback=f"provider-driver-{instrument_index}",
            diagnostics=diagnostics,
        )
        interruption = _first_interruption(interruption, identity_interruption)
        managed.append((instrument_id, identity_known, instrument))

    for cleanup_index, (instrument_id, _, instrument) in enumerate(reversed(managed)):
        entry = ExecutionJournalEntry(
            run_id=run_id,
            operation_id=(f"lifecycle.setup-cleanup.{cleanup_index}.{instrument_id}"),
            stage="setup_cleanup",
            effect="lifecycle",
            state="started",
            instrument_id=instrument_id,
        )
        interruption = _first_interruption(
            interruption,
            _append_setup_transition(journal, entry, diagnostics),
        )
        try:
            instrument.cleanup()
        except Exception as error:
            diagnostic = diagnostic_from_exception(
                "instrument_cleanup_failed",
                f"instrument cleanup failed for {instrument_id}",
                instrument_id,
                error,
            )
            diagnostics.append(diagnostic)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    ),
                    diagnostics,
                ),
            )
            continue
        except BaseException as error:
            interruption = _first_interruption(interruption, error)
            diagnostic = _interruption_diagnostic(error, instrument_id)
            diagnostics.append(diagnostic)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    ),
                    diagnostics,
                ),
            )
            continue
        interruption = _first_interruption(
            interruption,
            _append_setup_transition(
                journal,
                entry.model_copy(update={"state": "completed"}),
                diagnostics,
            ),
        )
    states: list[InstrumentStateSnapshot] = []
    for read_index, (instrument_id, identity_known, instrument) in enumerate(managed):
        entry = ExecutionJournalEntry(
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
            _append_setup_transition(journal, entry, diagnostics),
        )
        try:
            state = instrument.read_state().model_copy(deep=True)
            if identity_known and state.instrument_id != instrument_id:
                raise ValueError("read state belongs to a different instrument")
        except Exception as error:
            diagnostic = diagnostic_from_exception(
                "instrument_readback_failed",
                f"instrument terminal readback failed for {instrument_id}",
                instrument_id,
                error,
            )
            diagnostics.append(diagnostic)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    ),
                    diagnostics,
                ),
            )
            continue
        except BaseException as error:
            interruption = _first_interruption(interruption, error)
            diagnostic = _interruption_diagnostic(error, instrument_id)
            diagnostics.append(diagnostic)
            interruption = _first_interruption(
                interruption,
                _append_setup_transition(
                    journal,
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    ),
                    diagnostics,
                ),
            )
            continue
        states.append(state)
        interruption = _first_interruption(
            interruption,
            _append_setup_transition(
                journal,
                entry.model_copy(update={"state": "completed"}),
                diagnostics,
            ),
        )
    return states, interruption


def _append_setup_transition(
    journal: ExecutionJournal,
    entry: ExecutionJournalEntry,
    diagnostics: list[Diagnostic],
) -> BaseException | None:
    try:
        journal.append(entry)
    except Exception as error:
        diagnostics.append(
            diagnostic_from_exception(
                "execution_journal_commit_failed",
                f"failed to journal {entry.operation_id}",
                "execution.journal",
                error,
            )
        )
    except BaseException as error:
        diagnostics.append(_interruption_diagnostic(error, "execution.journal"))
        return error
    return None


def _safe_instrument_id(
    instrument: InstrumentDriver,
    *,
    fallback: str,
    diagnostics: list[Diagnostic],
) -> tuple[str, bool, BaseException | None]:
    try:
        instrument_id = cast("object", instrument.instrument_id)
    except Exception as error:
        diagnostics.append(
            diagnostic_from_exception(
                "instrument_identity_failed",
                "instrument identity lookup failed during setup finalization",
                fallback,
                error,
            )
        )
        return fallback, False, None
    except BaseException as error:
        diagnostics.append(_interruption_diagnostic(error, fallback))
        return fallback, False, error
    if type(instrument_id) is not str or not instrument_id:
        diagnostics.append(
            _diagnostic(
                "instrument_identity_invalid",
                "instrument identity must be a non-empty string during setup "
                "finalization",
                fallback,
            )
        )
        return fallback, False, None
    return instrument_id, True, None


def _first_interruption(
    current: BaseException | None,
    candidate: BaseException | None,
) -> BaseException | None:
    return current if current is not None else candidate


def diagnostic_from_exception(
    code: str,
    message: str,
    path: str,
    error: Exception,
) -> Diagnostic:
    to_diagnostic = getattr(error, "to_diagnostic", None)
    if callable(to_diagnostic):
        converted = to_diagnostic()
        if isinstance(converted, Diagnostic):
            return converted
    return _diagnostic(
        code,
        f"{message}: {type(error).__name__}: {error}",
        path,
    )


def _interruption_diagnostic(error: BaseException, path: str) -> Diagnostic:
    return _diagnostic(
        "execution_interrupted",
        f"execution interrupted by {type(error).__name__}: {error}",
        path,
    )


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = [
    "cleanup_after_setup_failure",
    "describe_instruments",
    "diagnostic_from_exception",
    "validate_instruments",
]
