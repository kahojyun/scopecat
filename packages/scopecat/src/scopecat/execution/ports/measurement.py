"""Measurement-record persistence port."""

from typing import Protocol

from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)


class MeasurementDatasetWriter(Protocol):
    """Idempotently append and seal one canonical dataset."""

    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt: ...

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt: ...
