"""Measurement-record persistence port."""

from typing import Protocol

from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetBatch,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)


class MeasurementDatasetLifecycleWriter(Protocol):
    """Initialize and seal one canonical measurement dataset."""

    def initialize(
        self, header: MeasurementDatasetHeader
    ) -> MeasurementDatasetReceipt: ...

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt: ...


class MeasurementDatasetWriter(MeasurementDatasetLifecycleWriter, Protocol):
    """Ingest live records and durably flush one canonical dataset."""

    def ingest(
        self,
        batch: MeasurementDatasetBatch,
    ) -> tuple[MeasurementDatasetReceipt, ...]: ...

    def flush(self) -> tuple[MeasurementDatasetReceipt, ...]: ...


class DurableMeasurementDatasetWriter(MeasurementDatasetLifecycleWriter, Protocol):
    """Direct durable writer used by storage adapters and focused tests."""

    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt: ...
