"""Ports bundled for one execution environment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from scopecat.execution.ports.journal import (
    CollectionRepository,
    ExecutionJournal,
    PayloadEvidenceCommitter,
)
from scopecat.execution.ports.measurement import MeasurementRecordCommitter
from scopecat.execution.ports.resources import ResourceLeaseManager
from scopecat.measurements.results import MeasurementRecord
from scopecat.records.execution_journal import (
    CollectionChunkReceipt,
    ExecutionTransition,
)
from scopecat.runs.repository import RunRepository


class ExecutionJournalStore(ExecutionJournal, Protocol):
    """Journal writer with the recovery view required by local execution."""

    def entries(self) -> tuple[ExecutionTransition, ...]: ...


class MeasurementRecordRepository(MeasurementRecordCommitter, Protocol):
    """Measurement committer with its canonical recovery view."""

    def measurements(self) -> tuple[MeasurementRecord, ...]: ...


class CollectionRecordRepository(CollectionRepository, Protocol):
    """Readback repository with its canonical recovery view."""

    def receipts(self) -> tuple[CollectionChunkReceipt, ...]: ...


@dataclass(frozen=True, slots=True)
class ExecutionServices:
    """All effect boundaries needed to execute and publish a durable run."""

    runs: RunRepository
    resources: ResourceLeaseManager
    journal_for: Callable[[str], ExecutionJournalStore]
    measurements_for: Callable[[str], MeasurementRecordRepository]
    collections_for: Callable[[str], CollectionRecordRepository]
    payloads_for: Callable[[str], PayloadEvidenceCommitter]


__all__ = [
    "CollectionRecordRepository",
    "ExecutionJournalStore",
    "ExecutionServices",
    "MeasurementRecordRepository",
]
