"""Canonicalize physically reordered point records before durable append."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.records.measurement import MeasurementRecord


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
