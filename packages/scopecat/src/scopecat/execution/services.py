"""Ports bundled for one execution environment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments.execution import RunInstrumentHost
from scopecat.sdk.journal import ExecutionJournal


def _never_cancel() -> bool:
    return False


def _effects_are_ready() -> bool:
    return True


@dataclass(frozen=True, slots=True)
class ExecutionSession:
    """Bind one run's effect ports so execution cannot mix storage scopes."""

    accepted: RunManifest
    begin: Callable[[], None]
    commit_terminal: Callable[[TerminalRunCommit], RunManifest]
    journal: ExecutionJournal
    measurements: MeasurementDatasetWriter
    instruments: RunInstrumentHost
    cancellation_requested: Callable[[], bool] = _never_cancel
    effects_ready: Callable[[], bool] = _effects_are_ready

    @property
    def run_id(self) -> str:
        return self.accepted.run_id
