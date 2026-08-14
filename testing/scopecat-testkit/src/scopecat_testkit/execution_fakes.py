"""Small execution fakes for repository tests."""

from __future__ import annotations

from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)


class FakeMeasurementDatasetRepository:
    """Record measurement writes and return stable receipts."""

    def __init__(self) -> None:
        self._header: MeasurementDatasetHeader | None = None
        self._appends: dict[str, MeasurementDatasetAppend] = {}
        self._seals: dict[str, MeasurementDatasetSeal] = {}
        self._receipts: dict[str, MeasurementDatasetReceipt] = {}

    @property
    def appends(self) -> tuple[MeasurementDatasetAppend, ...]:
        return tuple(self._appends.values())

    @property
    def receipts(self) -> tuple[MeasurementDatasetReceipt, ...]:
        return tuple(self._receipts.values())

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        return tuple(
            record for append in self._appends.values() for record in append.records
        )

    @property
    def header(self) -> MeasurementDatasetHeader | None:
        return self._header

    def initialize(
        self,
        header: MeasurementDatasetHeader,
    ) -> MeasurementDatasetReceipt:
        durable = header
        if (
            self._header is not None
            and self._header.content_hash != durable.content_hash
        ):
            raise RuntimeError("measurement dataset header changed content")
        if self._header is None:
            self._header = durable
            self._receipts[durable.operation_id] = MeasurementDatasetReceipt(
                operation_id=durable.operation_id,
                dataset_content_hash=durable.content_hash,
            )
        return self._receipts[durable.operation_id]

    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt:
        durable = append
        if (
            self._header is None
            or self._header.content_hash != durable.header_content_hash
        ):
            raise RuntimeError("measurement dataset append header is missing")
        existing = self._appends.get(durable.operation_id)
        if existing is not None and existing.content_hash != durable.content_hash:
            raise RuntimeError(
                f"measurement operation {durable.operation_id} changed content"
            )
        if existing is None:
            self._appends[durable.operation_id] = durable
            self._receipts[durable.operation_id] = MeasurementDatasetReceipt(
                operation_id=durable.operation_id,
                dataset_content_hash=durable.content_hash,
            )
        return self._receipts[durable.operation_id]

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        durable = seal
        if (
            self._header is None
            or self._header.content_hash != durable.header_content_hash
        ):
            raise RuntimeError("measurement dataset seal header is missing")
        existing = self._seals.get(durable.operation_id)
        if existing is not None and existing.content_hash != durable.content_hash:
            raise RuntimeError(
                f"measurement seal {durable.operation_id} changed content"
            )
        if existing is None:
            self._seals[durable.operation_id] = durable
            self._receipts[durable.operation_id] = MeasurementDatasetReceipt(
                operation_id=durable.operation_id,
                dataset_content_hash=durable.dataset_content_hash,
            )
        return self._receipts[durable.operation_id]
