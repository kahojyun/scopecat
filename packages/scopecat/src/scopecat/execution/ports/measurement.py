"""Measurement-record persistence port."""

from typing import Protocol

from scopecat.records.measurement_recording import (
    MeasurementRecordChunk,
    MeasurementRecordReceipt,
)


class MeasurementRecordCommitter(Protocol):
    """Idempotently commit one chunk by deterministic operation identity."""

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt: ...


__all__ = ["MeasurementRecordCommitter"]
