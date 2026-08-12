"""Canonicalize physically reordered point records before durable append."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.records.measurement import MeasurementArray, MeasurementRecord

MEASUREMENT_CHUNK_RECORD_LIMIT = 256
MEASUREMENT_CHUNK_VALUE_BYTE_LIMIT = 8 * 1024 * 1024


@dataclass(slots=True)
class CanonicalMeasurementBuffer:
    """Release only the longest contiguous prefix of canonical point records."""

    next_index: int = 0
    _pending: dict[int, MeasurementRecord] = field(default_factory=dict)

    def add(
        self,
        records: tuple[MeasurementRecord, ...],
    ) -> tuple[MeasurementRecord, ...]:
        for record in records:
            point_index = record.point_index
            if point_index < self.next_index or point_index in self._pending:
                raise ValueError(
                    f"measurement point index {point_index} was already buffered"
                )
            self._pending[point_index] = record

        ready: list[MeasurementRecord] = []
        while (record := self._pending.pop(self.next_index, None)) is not None:
            ready.append(record)
            self.next_index += 1
        return tuple(ready)

    @property
    def pending_indices(self) -> tuple[int, ...]:
        return tuple(sorted(self._pending))


@dataclass(slots=True)
class MeasurementChunkBuffer:
    """Group a canonical record stream into memory-bounded durable appends."""

    record_limit: int = MEASUREMENT_CHUNK_RECORD_LIMIT
    value_byte_limit: int = MEASUREMENT_CHUNK_VALUE_BYTE_LIMIT
    _pending: list[MeasurementRecord] = field(default_factory=list)
    _pending_value_bytes: int = 0

    def __post_init__(self) -> None:
        if self.record_limit <= 0:
            raise ValueError("measurement chunk record limit must be positive")
        if self.value_byte_limit <= 0:
            raise ValueError("measurement chunk value byte limit must be positive")

    def add(
        self,
        records: tuple[MeasurementRecord, ...],
    ) -> tuple[tuple[MeasurementRecord, ...], ...]:
        chunks: list[tuple[MeasurementRecord, ...]] = []
        for record in records:
            value_bytes = _measurement_record_value_bytes(record)
            if self._pending and (
                self._pending_value_bytes + value_bytes > self.value_byte_limit
            ):
                chunks.append(self._release_pending())
            self._pending.append(record)
            self._pending_value_bytes += value_bytes
            if (
                len(self._pending) >= self.record_limit
                or self._pending_value_bytes >= self.value_byte_limit
            ):
                chunks.append(self._release_pending())
        return tuple(chunks)

    def finish(self) -> tuple[tuple[MeasurementRecord, ...], ...]:
        return (self._release_pending(),) if self._pending else ()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def pending_value_bytes(self) -> int:
        return self._pending_value_bytes

    def _release_pending(self) -> tuple[MeasurementRecord, ...]:
        chunk = tuple(self._pending)
        self._pending.clear()
        self._pending_value_bytes = 0
        return chunk


def _measurement_record_value_bytes(record: MeasurementRecord) -> int:
    return sum(
        value.values.nbytes
        for values in (record.coordinates, record.observables)
        for value in values.values()
        if isinstance(value, MeasurementArray)
    )


__all__ = [
    "MEASUREMENT_CHUNK_RECORD_LIMIT",
    "MEASUREMENT_CHUNK_VALUE_BYTE_LIMIT",
    "CanonicalMeasurementBuffer",
    "MeasurementChunkBuffer",
]
