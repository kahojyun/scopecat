"""Resolved inputs and point coverage for one domain compilation batch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainPointRef,
    DomainProductUseRef,
)


@dataclass(frozen=True, slots=True)
class DomainBatchInputs:
    """Resolved program and compiler input columns for one bounded batch."""

    program: tuple[tuple[str, tuple[object, ...]], ...]
    compiler: tuple[tuple[str, tuple[object, ...]], ...]

    def program_input(self, name: str) -> tuple[object, ...]:
        """Return one program input column in request point order."""

        return _input_column(self.program, name)

    def compiler_input(self, name: str) -> tuple[object, ...]:
        """Return one compiler input column in request point order."""

        return _input_column(self.compiler, name)

    def decode_compiler_collection[ItemT, CollectionT](
        self,
        name: str,
        decode: Callable[[Sequence[ItemT]], CollectionT],
    ) -> tuple[CollectionT, ...]:
        """Decode a collection-valued compiler input at every point."""

        return tuple(
            decode(cast("Sequence[ItemT]", value))
            for value in self.compiler_input(name)
        )


@dataclass(frozen=True, slots=True)
class DomainCompileRequest:
    """One host-effect-bounded call region presented before partitioning."""

    call: DomainCallView
    inputs: DomainBatchInputs
    points: tuple[DomainPointRef, ...]
    measurement_catalog: MeasurementValueCatalog = field(repr=False)

    @property
    def point_ordinals(self) -> tuple[int, ...]:
        return tuple(point.ordinal for point in self.points)

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self.call.product_uses


@dataclass(frozen=True, slots=True)
class DomainBatchRequest(DomainCompileRequest):
    """One compiler-selected contiguous batch ready for preparation."""

    batch_ordinal: int


@dataclass(frozen=True, slots=True)
class DomainBatchPartition:
    """Ordered batch sizes covering one bounded call region exactly once."""

    batch_sizes: tuple[int, ...]

    def __post_init__(self) -> None:
        if any(type(size) is not int or size <= 0 for size in self.batch_sizes):
            raise ValueError("domain batch sizes must be positive integers")

    @classmethod
    def with_maximum_size(
        cls,
        point_count: int,
        maximum_size: int,
    ) -> DomainBatchPartition:
        if type(maximum_size) is not int or maximum_size <= 0:
            raise ValueError("domain maximum batch size must be a positive integer")
        full_batches, remainder = divmod(point_count, maximum_size)
        return cls((maximum_size,) * full_batches + ((remainder,) if remainder else ()))


def _input_column(
    columns: tuple[tuple[str, tuple[object, ...]], ...],
    name: str,
) -> tuple[object, ...]:
    for input_name, values in columns:
        if input_name == name:
            return values
    raise KeyError(name)


__all__ = [
    "DomainBatchInputs",
    "DomainBatchPartition",
    "DomainBatchRequest",
    "DomainCompileRequest",
]
