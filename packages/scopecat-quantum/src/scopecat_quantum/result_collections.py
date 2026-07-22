"""Recursive address collections shared by quantum result-lowering stages."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class ResultCollection[LeafT]:
    """An ordered result-address axis whose items may contain nested axes."""

    axis_id: str
    items: tuple[LeafT | ResultCollection[LeafT], ...]

    def __post_init__(self) -> None:
        if not self.axis_id.strip():
            raise ValueError("result collection axis_id must be non-empty")
        if not self.items:
            raise ValueError("result collections require at least one item")
        child_shapes = tuple(_result_collection_axes(item) for item in self.items)
        if any(shape != child_shapes[0] for shape in child_shapes[1:]):
            raise ValueError("result collection items must have one rectangular shape")
        if self.axis_id in {axis_id for axis_id, _size in child_shapes[0]}:
            raise ValueError(
                "result collection axis ids must be unique along each path"
            )


def _result_collection_axes(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, ResultCollection):
        return ()
    child_axes = _result_collection_axes(value.items[0])
    return ((value.axis_id, len(value.items)), *child_axes)


def result_collection_axes[LeafT](
    value: LeafT | ResultCollection[LeafT],
) -> tuple[tuple[str, int], ...]:
    """Return ordered axis ids and sizes for one rectangular result tree."""

    return _result_collection_axes(value)


def _iter_result_leaves(value: object) -> Iterator[object]:
    if not isinstance(value, ResultCollection):
        yield value
        return
    for item in value.items:
        yield from _iter_result_leaves(item)


def iter_result_leaves[LeafT](
    value: LeafT | ResultCollection[LeafT],
) -> Iterator[LeafT]:
    """Yield leaves in stable recursive axis order."""

    return cast("Iterator[LeafT]", _iter_result_leaves(value))


__all__ = [
    "ResultCollection",
    "iter_result_leaves",
    "result_collection_axes",
]
