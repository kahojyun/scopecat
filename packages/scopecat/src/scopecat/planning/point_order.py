"""Derive physical point traversal without changing logical point identity."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.compiler.point_domain import MaterializedPointDomain
from scopecat.program.scans import PointTraversal, RepeatMode


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
