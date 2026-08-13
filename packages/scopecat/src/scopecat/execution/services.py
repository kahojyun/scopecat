"""Ports bundled for one execution environment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.execution.program import RunPointInspection
from scopecat.measurements.points import PointCandidate
from scopecat.optimization import PointProposalDecision
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments.execution import RunInstrumentHost
from scopecat.sdk.journal import ExecutionJournal


def _never_cancel() -> bool:
    return False


def _effects_are_ready() -> bool:
    return True


class RunCoverageWriter(Protocol):
    """Commit bounded contiguous logical-point progress."""

    def advance(self, *, start_index: int, point_count: int) -> None: ...

    def flush(self) -> None: ...


@dataclass(frozen=True, slots=True)
class QueuedRunPointCandidate:
    operation_id: str
    candidate: PointCandidate


class RunPointProposalWriter(Protocol):
    """Commit point-plan facts and publish bounded live inspections."""

    def initialize(self) -> None: ...

    def next_queued(self) -> QueuedRunPointCandidate | None: ...

    def append(
        self,
        decision: PointProposalDecision,
        inspection: RunPointInspection | None,
        *,
        queue_operation_id: str | None = None,
    ) -> None: ...

    def close(self, *, completed_point_count: int, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionSession:
    """Bind one run's effect ports so execution cannot mix storage scopes."""

    accepted: RunManifest
    begin: Callable[[], None]
    commit_terminal: Callable[[TerminalRunCommit], RunManifest]
    journal: ExecutionJournal
    measurements: MeasurementDatasetWriter
    instruments: RunInstrumentHost
    coverage: RunCoverageWriter | None = None
    point_proposals: RunPointProposalWriter | None = None
    cancellation_requested: Callable[[], bool] = _never_cancel
    effects_ready: Callable[[], bool] = _effects_are_ready

    @property
    def run_id(self) -> str:
        return self.accepted.run_id
