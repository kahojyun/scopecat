"""Initial readback, safety finalization, and terminal-state capture."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.ports.instruments import RunInstrumentHost
from scopecat.records.instrument import InstrumentStateSnapshot


class InstrumentLifecycle:
    """Manage deterministic readback and reverse-order daemon finalization."""

    def __init__(
        self,
        *,
        resource_order: Sequence[str],
        instruments: RunInstrumentHost,
        journal: JournaledEffectBoundary,
    ) -> None:
        self.resource_order = tuple(resource_order)
        self.instruments = instruments
        self.journal = journal

    def read_states(
        self,
        *,
        phase: Literal["initial", "terminal"],
    ) -> list[InstrumentStateSnapshot]:
        states: list[InstrumentStateSnapshot] = []
        for instrument_id in self.resource_order:
            operation_id = f"lifecycle.{phase}-read-state.{instrument_id}"
            try:
                state = self.instruments.read_state(
                    instrument_id,
                    operation_id=operation_id,
                ).model_copy(deep=True)
                if state.instrument_id != instrument_id:
                    raise ValueError("read state belongs to a different instrument")
            except Exception as error:
                problem = self.journal.problem_from_exception(
                    "instrument_readback_failed",
                    f"instrument {phase} readback failed for {instrument_id}",
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self.journal.problems.append(problem)
                continue
            except BaseException as error:
                problem = self.journal.record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                continue
            states.append(state)
        return states

    def finalize(self) -> None:
        action = "abort" if bool(self.journal.problems) else "cleanup"
        self._run_finalizer(action)

    def close(self) -> None:
        """Release driver connections after terminal state has been captured."""

        self._run_finalizer("close")

    def _run_finalizer(
        self,
        action: Literal["abort", "cleanup", "close"],
    ) -> None:
        for instrument_id in reversed(self.resource_order):
            operation_id = f"lifecycle.{action}.{instrument_id}"
            entry = self.journal.entry(
                operation_id=operation_id,
                stage=action,
                effect="lifecycle",
                state="started",
                instrument_id=instrument_id,
            )
            # Safety finalization proceeds even if the journal itself is damaged.
            self.journal.commit_best_effort(entry)

            try:
                self.instruments.lifecycle(
                    instrument_id,
                    operation_id=operation_id,
                    action=action,
                )
            except Exception as error:
                problem = self.journal.problem_from_exception(
                    f"instrument_{action}_failed",
                    f"instrument {action} failed for {instrument_id}",
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self.journal.problems.append(problem)
                self.journal.commit_best_effort(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            except BaseException as error:
                problem = self.journal.record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self.journal.commit_best_effort(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            self.journal.commit_best_effort(
                entry.model_copy(update={"state": "completed"})
            )
