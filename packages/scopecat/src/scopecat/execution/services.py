"""Ports bundled for one execution environment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.journal import ExecutionJournal


@dataclass(frozen=True, slots=True)
class ExecutionSession:
    """Bind one run's effect ports so execution cannot mix storage scopes."""

    accepted: RunManifest
    config: ConfigProfileSnapshot
    begin: Callable[[], None]
    commit_terminal: Callable[[TerminalRunCommit], RunManifest]
    journal: ExecutionJournal
    measurements: MeasurementDatasetWriter

    @property
    def run_id(self) -> str:
        return self.accepted.run_id
