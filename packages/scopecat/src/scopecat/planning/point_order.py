"""Derive physical point traversal without changing logical point identity."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from scopecat.compiler.point_domain import MaterializedPointDomain
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.value_data import CellValue
from scopecat.program.scans import (
    PointSchedule,
    PointTraversal,
    RepeatMode,
)


@dataclass(frozen=True, slots=True)
class PointExecutionGroup:
    """One named recovery group in preferred physical traversal order."""

    id: str
    key: Mapping[str, CellValue] = field(repr=False)
    ordinals: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("point execution group id must be non-empty")
        if not self.ordinals or len(self.ordinals) != len(set(self.ordinals)):
            raise ValueError(
                "point execution group ordinals must be non-empty and unique"
            )
        object.__setattr__(self, "key", MappingProxyType(dict(self.key)))


@dataclass(frozen=True, slots=True)
class PointExecutionPlan:
    """Preferred row order with author-declared recovery group boundaries.

    Groups guide traversal but remain splittable by physical batching. Durable
    coverage is deliberately stricter: a resume cut is legal only when a group
    prefix covers exactly one canonical point prefix.
    """

    groups: tuple[PointExecutionGroup, ...]
    point_count: int
    _durable_group_offsets: Mapping[int, int] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.point_count) is not int or self.point_count < 0:
            raise ValueError("point execution count must be a non-negative integer")
        selected = self.ordinals
        if len(selected) != self.point_count or set(selected) != set(
            range(self.point_count)
        ):
            raise ValueError("point execution groups must partition every point once")
        cuts = {0: 0}
        completed = 0
        maximum = -1
        for group_offset, group in enumerate(self.groups, start=1):
            completed += len(group.ordinals)
            maximum = max(maximum, *group.ordinals)
            if maximum == completed - 1:
                cuts[completed] = group_offset
        object.__setattr__(
            self,
            "_durable_group_offsets",
            MappingProxyType(cuts),
        )

    @property
    def ordinals(self) -> tuple[int, ...]:
        return tuple(ordinal for group in self.groups for ordinal in group.ordinals)

    @property
    def group_count(self) -> int:
        return len(self.groups)

    def group(self, index: int) -> PointExecutionGroup:
        if not 0 <= index < self.group_count:
            raise IndexError(index)
        return self.groups[index]

    def group_containing(self, point_ordinal: int) -> PointExecutionGroup:
        if not 0 <= point_ordinal < self.point_count:
            raise IndexError(point_ordinal)
        for group in self.groups:
            if point_ordinal in group.ordinals:
                return group
        raise AssertionError("point execution plan lost a canonical point")

    def remaining_groups(
        self,
        *,
        durable_start: int = 0,
    ) -> Iterator[PointExecutionGroup]:
        """Yield groups after one canonical durable coverage watermark."""

        try:
            first_group = self._durable_group_offsets[durable_start]
        except KeyError as error:
            raise ValueError(
                "durable point coverage ends inside a point group"
            ) from error
        yield from self.groups[first_group:]

    def is_durable_cut(self, canonical_point_count: int) -> bool:
        return canonical_point_count in self._durable_group_offsets


def resolve_point_schedule(
    domain: MaterializedPointDomain,
    *,
    repeat: int,
    repeat_mode: RepeatMode,
    schedule: PointSchedule,
) -> PointExecutionPlan:
    """Compose base traversal with stable grouped traversal.

    Groups follow the first appearance of their key on the base path. Members
    retain their relative order on that path. This makes grouping and traversal
    one deterministic scheduling policy without turning groups into batches.
    """

    ordinals = point_execution_ordinals(
        domain,
        repeat=repeat,
        repeat_mode=repeat_mode,
        traversal=schedule.traversal,
    )
    grouping = schedule.grouping
    if grouping is None:
        return PointExecutionPlan(
            tuple(
                PointExecutionGroup(
                    id="point",
                    key={},
                    ordinals=(ordinal,),
                )
                for ordinal in ordinals
            ),
            point_count=len(domain.points),
        )
    varying = frozenset(grouping.varying_coordinate_ids)
    key_ids = tuple(axis.id for axis in domain.axes if axis.id not in varying)
    grouped: dict[str, tuple[dict[str, CellValue], list[int]]] = {}
    for ordinal in ordinals:
        row = domain.points[ordinal].row
        key = {coordinate_id: row[coordinate_id] for coordinate_id in key_ids}
        fingerprint = stable_content_hash(content_fingerprint(key))
        selected = grouped.get(fingerprint)
        if selected is None:
            selected_ordinals: list[int] = []
            selected = (key, selected_ordinals)
            grouped[fingerprint] = selected
        elif selected[0] != key:
            raise AssertionError("point grouping coordinate fingerprint collided")
        selected[1].append(ordinal)
    return PointExecutionPlan(
        tuple(
            PointExecutionGroup(
                id=f"{grouping.id}:{fingerprint}",
                key=key,
                ordinals=tuple(selected),
            )
            for fingerprint, (key, selected) in grouped.items()
        ),
        point_count=len(domain.points),
    )


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
