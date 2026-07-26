"""Complete, bounded domain compilation requests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, cast

from scopecat.measurements.points import RunPoint
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainPointRef,
    DomainProductUseRef,
)

if TYPE_CHECKING:
    from scopecat.sdk.domain.execution import PreparedDomainExecution
    from scopecat.sdk.domain.preparation import DomainPreparationBuilder


@dataclass(frozen=True, slots=True)
class DomainResolvedInputs:
    """Complete input columns for one bounded logical-point batch."""

    ordinals: tuple[int, ...]
    columns: tuple[tuple[str, tuple[object, ...]], ...]

    def __post_init__(self) -> None:
        ordinals = tuple(self.ordinals)
        columns = tuple((name, tuple(values)) for name, values in self.columns)
        names = tuple(name for name, _values in columns)
        if len(names) != len(set(names)):
            raise ValueError("resolved domain input ids must be unique")
        if any(len(values) != len(ordinals) for _name, values in columns):
            raise ValueError("resolved domain input columns must match point count")
        object.__setattr__(self, "ordinals", ordinals)
        object.__setattr__(self, "columns", columns)

    def input(self, name: str) -> tuple[object, ...]:
        """Return one input column in selected ordinal order."""

        for input_name, values in self.columns:
            if input_name == name:
                return values
        raise KeyError(name)

    def decode_collection[ItemT, CollectionT](
        self,
        name: str,
        decode: Callable[[Sequence[ItemT]], CollectionT],
    ) -> tuple[CollectionT, ...]:
        """Decode one collection-valued input independently at every point.

        Core carries domain-owned collection items as ``object``; the adapter's
        decoder restores their concrete type.
        """

        return tuple(
            decode(cast("Sequence[ItemT]", value)) for value in self.input(name)
        )


@dataclass(frozen=True, slots=True)
class DomainBatchInputs:
    """Complete program and compiler inputs for one bounded batch."""

    program: DomainResolvedInputs
    compiler: DomainResolvedInputs

    def __post_init__(self) -> None:
        if self.program.ordinals != self.compiler.ordinals:
            raise ValueError("domain batch input point coverage must match")

    @property
    def ordinals(self) -> tuple[int, ...]:
        return self.program.ordinals


@dataclass(frozen=True, slots=True)
class DomainBatchRequest:
    """One complete bounded input to domain compilation and preparation."""

    batch_ordinal: int
    call: DomainCallView
    inputs: DomainBatchInputs
    points: tuple[DomainPointRef, ...]
    measurement_catalog: MeasurementValueCatalog = field(repr=False)
    run_points: tuple[RunPoint, ...] = field(repr=False)

    def __post_init__(self) -> None:
        points = tuple(self.points)
        run_points = tuple(self.run_points)
        point_ordinals = tuple(point.ordinal for point in points)
        if self.inputs.ordinals != point_ordinals:
            raise ValueError("domain batch inputs must match its logical points")
        if tuple(point.ordinal for point in run_points) != point_ordinals:
            raise ValueError("domain batch run points must match its logical points")
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "run_points", run_points)

    @property
    def point_ordinals(self) -> tuple[int, ...]:
        return self.inputs.ordinals

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self.call.product_uses

    def new_preparation(self) -> DomainPreparationBuilder:
        """Create a builder that closes this batch for execution."""

        from scopecat.sdk.domain.preparation import DomainPreparationBuilder

        return DomainPreparationBuilder(self)


class DomainCompiler(Protocol):
    """Compile complete bounded batches for one configured domain target."""

    @property
    def target_id(self) -> str: ...

    @property
    def target_kind(self) -> str: ...

    @property
    def max_points_per_batch(self) -> int: ...

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution: ...


__all__ = [
    "DomainBatchInputs",
    "DomainBatchRequest",
    "DomainCompiler",
    "DomainResolvedInputs",
]
