"""Small execution fakes for repository tests."""

from __future__ import annotations

from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetBatch,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
    measurement_fragment_content_hash,
    measurement_record_content_hash,
)


class FakeMeasurementDatasetRepository:
    """Record measurement writes and return stable receipts."""

    def __init__(self) -> None:
        self._header: MeasurementDatasetHeader | None = None
        self._prior_records: tuple[MeasurementRecord, ...] = ()
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
        return self._prior_records + tuple(
            record for append in self._appends.values() for record in append.records
        )

    def seed_prior_records(self, records: tuple[MeasurementRecord, ...]) -> None:
        """Seed acquisition records owned by an earlier execution segment."""

        if self._appends or self._seals:
            raise RuntimeError("prior records must be seeded before current writes")
        self._prior_records = records

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
                acquisition_record_count=len(self.measurements()),
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
                acquisition_record_count=(
                    durable.acquisition_start + len(durable.records)
                ),
            )
        return self._receipts[durable.operation_id]

    def ingest(
        self,
        batch: MeasurementDatasetBatch,
    ) -> tuple[MeasurementDatasetReceipt, ...]:
        return (
            self.append(
                MeasurementDatasetAppend(
                    run_id=batch.run_id,
                    header_content_hash=batch.header_content_hash,
                    acquisition_start=len(self.measurements()),
                    records=batch.records,
                )
            ),
        )

    def flush(self) -> tuple[MeasurementDatasetReceipt, ...]:
        return ()

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
            appends = tuple(
                sorted(
                    self._appends.values(),
                    key=lambda append: append.acquisition_start,
                )
            )
            fragment_records = tuple(
                record for append in appends for record in append.records
            )
            records = self._prior_records + fragment_records
            record_hashes = tuple(
                measurement_record_content_hash(record)
                for record in sorted(records, key=lambda record: record.point_index)
            )
            fragment_record_hashes = tuple(
                measurement_record_content_hash(record) for record in fragment_records
            )
            if len(records) != durable.record_count:
                raise RuntimeError("measurement dataset seal point count is incomplete")
            if len(fragment_record_hashes) != durable.fragment_record_count:
                raise RuntimeError("measurement fragment record count is incomplete")
            if durable.fragment_content_hash != measurement_fragment_content_hash(
                header_content_hash=durable.header_content_hash,
                record_content_hashes=fragment_record_hashes,
            ):
                raise RuntimeError("measurement fragment seal changed content")
            self._seals[durable.operation_id] = durable
            self._receipts[durable.operation_id] = MeasurementDatasetReceipt(
                operation_id=durable.operation_id,
                dataset_content_hash=measurement_dataset_content_hash(
                    header_content_hash=durable.header_content_hash,
                    record_content_hashes=record_hashes,
                ),
                acquisition_record_count=len(records),
            )
        return self._receipts[durable.operation_id]
