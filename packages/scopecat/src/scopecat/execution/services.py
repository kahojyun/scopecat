"""Ports bundled for one execution environment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from scopecat.execution.observation import RuntimeEventSink
from scopecat.execution.ports.journal import (
    CollectionRepository,
    ExecutionJournal,
    PayloadEvidenceCommitter,
)
from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.execution.ports.resources import ResourceLeaseManager
from scopecat.measurements.results import MeasurementRecord
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution_journal import (
    CollectionChunkReceipt,
    ExecutionTransition,
)
from scopecat.records.measurement_recording import MeasurementDatasetAppendIndex
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit


class ExecutionRunStore(Protocol):
    """Run state used while interpreting an already-admitted program."""

    def read_manifest(self, run_id: str) -> RunManifest: ...

    def write_manifest(self, manifest: RunManifest) -> None: ...

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot: ...

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest: ...


class ExecutionJournalStore(ExecutionJournal, Protocol):
    """Journal writer with the recovery view required by local execution."""

    def entries(self) -> tuple[ExecutionTransition, ...]: ...


class MeasurementDatasetRepository(MeasurementDatasetWriter, Protocol):
    """Dataset writer with its canonical recovery view."""

    def measurements(self) -> tuple[MeasurementRecord, ...]: ...

    def append_indices(self) -> tuple[MeasurementDatasetAppendIndex, ...]: ...


class CollectionRecordRepository(CollectionRepository, Protocol):
    """Readback repository with its canonical recovery view."""

    def receipts(self) -> tuple[CollectionChunkReceipt, ...]: ...


@dataclass(frozen=True, slots=True)
class ExecutionServices:
    """All effect boundaries needed to execute and publish a durable run."""

    runs: ExecutionRunStore
    resources: ResourceLeaseManager
    journal_for: Callable[[str], ExecutionJournalStore]
    measurements_for: Callable[[str], MeasurementDatasetRepository]
    collections_for: Callable[[str], CollectionRecordRepository]
    payloads_for: Callable[[str], PayloadEvidenceCommitter]
    runtime_event_sink: RuntimeEventSink | None = None
