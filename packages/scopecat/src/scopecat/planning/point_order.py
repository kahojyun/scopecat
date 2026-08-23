"""Derive physical point traversal without changing logical point identity."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from scopecat.compiler.point_domain import MaterializedPointDomain
from scopecat.program.scans import PointTraversal, RepeatMode


@dataclass(frozen=True, slots=True)
class PointExecutionPlan:
    """Physical row order grouped by author-declared logical block boundaries.

    Every block is indivisible for physical batching. ``is_durable_cut`` is
    deliberately stricter: durable coverage is a canonical point prefix, so a
    resume cut is legal only when a physical block prefix covers exactly that
    canonical prefix.
    """

    ordinals: Sequence[int] = field(repr=False)
    block_size: int
    _durable_cuts: frozenset[int] | None = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        point_count = len(self.ordinals)
        if type(self.block_size) is not int or self.block_size <= 0:
            raise ValueError("point execution block size must be positive")
        if point_count % self.block_size:
            raise ValueError(
                "point count must be divisible by the execution block size"
            )
        if isinstance(self.ordinals, range) and self.ordinals == range(point_count):
            object.__setattr__(self, "_durable_cuts", None)
            return
        selected = tuple(self.ordinals)
        if len(set(selected)) != point_count or set(selected) != set(
            range(point_count)
        ):
            raise ValueError("point execution order must be a complete permutation")
        cuts = {0}
        maximum = -1
        for offset in range(0, point_count, self.block_size):
            block = selected[offset : offset + self.block_size]
            maximum = max(maximum, *block)
            prefix_count = offset + self.block_size
            if maximum == prefix_count - 1:
                cuts.add(prefix_count)
        object.__setattr__(self, "_durable_cuts", frozenset(cuts))

    @property
    def point_count(self) -> int:
        return len(self.ordinals)

    @property
    def block_count(self) -> int:
        return self.point_count // self.block_size

    def block(self, index: int) -> tuple[int, ...]:
        if not 0 <= index < self.block_count:
            raise IndexError(index)
        start = index * self.block_size
        return tuple(self.ordinals[start : start + self.block_size])

    def block_containing(self, point_ordinal: int) -> tuple[int, ...]:
        if not 0 <= point_ordinal < self.point_count:
            raise IndexError(point_ordinal)
        for index in range(self.block_count):
            block = self.block(index)
            if point_ordinal in block:
                return block
        raise AssertionError("point execution plan lost a canonical point")

    def blocks(self, *, durable_start: int = 0) -> Iterator[tuple[int, ...]]:
        """Yield whole remaining blocks after one canonical durable watermark."""

        if not self.is_durable_cut(durable_start):
            raise ValueError("durable point coverage ends inside an execution block")
        first_block = durable_start // self.block_size
        for index in range(first_block, self.block_count):
            yield self.block(index)

    def is_durable_cut(self, canonical_point_count: int) -> bool:
        if not 0 <= canonical_point_count <= self.point_count:
            return False
        cuts = self._durable_cuts
        if cuts is None:
            return canonical_point_count % self.block_size == 0
        return canonical_point_count in cuts


def point_execution_ordinals(
    domain: MaterializedPointDomain,
    *,
    repeat: int,
    repeat_mode: RepeatMode,
    traversal: PointTraversal,
) -> Sequence[int]:
    """Return canonical point ordinals in their requested execution order."""

    canonical: Sequence[int] = range(len(domain.points))
    if traversal == "forward":
        return canonical
    if domain.layout != "product_grid":
        raise AssertionError("snake traversal requires a product-grid point domain")

    base_axis_sizes = domain.axis_sizes
    if repeat > 1:
        repeat_index = -1 if repeat_mode == "point" else 0
        repeat_axis = base_axis_sizes[repeat_index]
        if repeat_axis != ("repeat", repeat):
            raise AssertionError("expanded repeat axis does not match point policy")
        base_axis_sizes = (
            base_axis_sizes[:-1] if repeat_mode == "point" else base_axis_sizes[1:]
        )

    base_ordinals = _snake_ordinals(tuple(size for _axis_id, size in base_axis_sizes))
    if repeat == 1:
        selected = base_ordinals
    elif repeat_mode == "point":
        selected = tuple(
            base_ordinal * repeat + repeat_index
            for base_ordinal in base_ordinals
            for repeat_index in range(repeat)
        )
    else:
        selected = tuple(
            repeat_index * len(base_ordinals) + base_ordinal
            for repeat_index in range(repeat)
            for base_ordinal in (
                base_ordinals
                if repeat_index % 2 == 0
                else tuple(reversed(base_ordinals))
            )
        )

    if len(selected) != len(canonical) or set(selected) != set(canonical):
        raise AssertionError("point traversal must permute every canonical point once")
    return selected


def _snake_ordinals(axis_sizes: tuple[int, ...]) -> tuple[int, ...]:
    coordinates = _snake_coordinates(axis_sizes)
    return tuple(
        _flatten_coordinate(coordinate, axis_sizes) for coordinate in coordinates
    )


def _snake_coordinates(axis_sizes: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    if not axis_sizes:
        return ((),)
    head, *tail = axis_sizes
    tail_path = _snake_coordinates(tuple(tail))
    return tuple(
        (index, *coordinate)
        for index in range(head)
        for coordinate in (tail_path if index % 2 == 0 else tuple(reversed(tail_path)))
    )


def _flatten_coordinate(
    coordinate: tuple[int, ...],
    axis_sizes: tuple[int, ...],
) -> int:
    ordinal = 0
    for index, size in zip(coordinate, axis_sizes, strict=True):
        ordinal = ordinal * size + index
    return ordinal
