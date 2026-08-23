"""Canonicalize physically reordered point records before durable append."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from scopecat.records.measurement import MeasurementRecord


def _every_cut(_point_count: int) -> bool:
    return True


@dataclass(slots=True)
class CanonicalPointBuffer:
    """Release completed indices only through canonical durable cut points."""

    next_index: int = 0
    is_durable_cut: Callable[[int], bool] = field(
        default=_every_cut,
        repr=False,
        compare=False,
    )
    _pending: set[int] = field(default_factory=set)

    def add(self, point_indices: tuple[int, ...]) -> tuple[int, ...]:
        for point_index in point_indices:
            if point_index < self.next_index or point_index in self._pending:
                raise ValueError(f"point index {point_index} was already buffered")
            self._pending.add(point_index)

        contiguous_end = self.next_index
        while contiguous_end in self._pending:
            contiguous_end += 1
        durable_end = next(
            (
                candidate
                for candidate in range(contiguous_end, self.next_index, -1)
                if self.is_durable_cut(candidate)
            ),
            self.next_index,
        )
        ready = tuple(range(self.next_index, durable_end))
        self._pending.difference_update(ready)
        self.next_index = durable_end
        return ready

    @property
    def pending_indices(self) -> tuple[int, ...]:
        return tuple(sorted(self._pending))


@dataclass(slots=True)
class CanonicalMeasurementBuffer:
    """Release only the longest contiguous prefix of canonical point records."""

    next_index: int = 0
    is_durable_cut: Callable[[int], bool] = field(
        default=_every_cut,
        repr=False,
        compare=False,
    )
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

        contiguous_end = self.next_index
        while contiguous_end in self._pending:
            contiguous_end += 1
        durable_end = next(
            (
                candidate
                for candidate in range(contiguous_end, self.next_index, -1)
                if self.is_durable_cut(candidate)
            ),
            self.next_index,
        )
        ready = tuple(
            self._pending.pop(point_index)
            for point_index in range(self.next_index, durable_end)
        )
        self.next_index = durable_end
        return ready

    @property
    def pending_indices(self) -> tuple[int, ...]:
        return tuple(sorted(self._pending))


__all__ = ["CanonicalMeasurementBuffer", "CanonicalPointBuffer"]
