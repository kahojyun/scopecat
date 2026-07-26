"""Initial readback, safety finalization, and terminal-state capture."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.records.execution_journal import ExecutionStage
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import InstrumentDriver


class DriverLifecycle:
    """Manage deterministic readback and reverse-order driver finalization."""

    def __init__(
        self,
        *,
        resource_order: Sequence[str],
        drivers: Mapping[str, InstrumentDriver],
        journal: JournaledEffectBoundary,
    ) -> None:
        self.resource_order = tuple(resource_order)
        self.drivers = drivers
        self.journal = journal

    def read_states(
        self,
        *,
        phase: Literal["initial", "terminal"],
    ) -> list[InstrumentStateSnapshot]:
        states: list[InstrumentStateSnapshot] = []
        for instrument_id in self.resource_order:
            operation_id = f"lifecycle.{phase}-read-state.{instrument_id}"
            transition_stage: ExecutionStage = (
                "terminal_readback" if phase == "terminal" else "initial_readback"
            )
            entry = self.journal.entry(
                operation_id=operation_id,
                stage=transition_stage,
                effect="read",
                state="started",
                instrument_id=instrument_id,
            )
            self.journal.observe(entry)
            try:
                state = self.drivers[instrument_id].read_state().model_copy(deep=True)
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
                self.journal.observe(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            except BaseException as error:
                problem = self.journal.record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self.journal.observe(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            states.append(state)
            self.journal.observe(entry.model_copy(update={"state": "completed"}))
        return states

    def finalize(self) -> None:
        action = "abort" if bool(self.journal.problems) else "cleanup"
        used = set(self.resource_order)
        extras = tuple(sorted(set(self.drivers) - used))
        managed_order = (
            *extras,
            *(
                instrument_id
                for instrument_id in self.resource_order
                if instrument_id in self.drivers
            ),
        )
        for instrument_id in reversed(managed_order):
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
                getattr(self.drivers[instrument_id], action)()
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
