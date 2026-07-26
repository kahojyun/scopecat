"""Compiler-owned exact iteration layout for verified point domains."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import prod

from scopecat.compiler.relations.scalar_eval import read_path
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import VerifiedPointDomain
from scopecat.graph.relations.model import LiteralScalarExpr
from scopecat.graph.relations.point_domain import (
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointProduct,
    PointUnit,
    point_axis_linear_value,
)
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.quantity import Quantity


@dataclass(frozen=True, slots=True)
class PointIterationLinearValues:
    """A constant-space exact linear sequence for one known axis center."""

    center: Quantity
    span: Quantity
    count: int

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> Quantity:
        return point_axis_linear_value(self.center, self.span, self.count, index)


@dataclass(frozen=True, slots=True)
class PointIterationAxis:
    id: str
    values: tuple[object, ...] | PointIterationLinearValues
    repeat_each: int = 1

    def values_at(self, ordinals: Sequence[int]) -> tuple[object, ...]:
        return tuple(
            self.values[(ordinal // self.repeat_each) % len(self.values)]
            for ordinal in ordinals
        )


@dataclass(frozen=True, slots=True)
class PointIterationLayout:
    axes: tuple[PointIterationAxis, ...] = ()

    def axis(self, axis_id: str) -> PointIterationAxis | None:
        return next((axis for axis in self.axes if axis.id == axis_id), None)

    def projection_key(
        self,
        axis_ids: Sequence[str],
        ordinal: int,
        *,
        fallback_row: Mapping[str, object] | None = None,
    ) -> str:
        requested = tuple(axis_ids)
        axes = tuple(self.axis(axis_id) for axis_id in requested)
        if all(axis is not None for axis in axes):
            values = {
                axis.id: content_fingerprint(axis.values_at((ordinal,))[0])
                for axis in axes
                if axis is not None
            }
        elif fallback_row is not None:
            values = {
                axis_id: content_fingerprint(read_path(fallback_row, axis_id))
                for axis_id in requested
            }
        else:
            raise KeyError("iteration support requires a materialized axis value")
        return stable_content_hash(values)

    def partition(
        self,
        axis_ids: Sequence[str],
        ordinals: Sequence[int],
        *,
        rows: Mapping[int, Mapping[str, object]] | None = None,
    ) -> tuple[tuple[int, ...], ...]:
        selected = tuple(ordinals)
        if not selected:
            return ()
        keys = tuple(
            self.projection_key(
                axis_ids,
                ordinal,
                fallback_row=None if rows is None else rows[ordinal],
            )
            for ordinal in selected
        )
        partitions: list[tuple[int, ...]] = []
        start = 0
        for offset in range(1, len(selected)):
            if keys[offset] != keys[start]:
                partitions.append(selected[start:offset])
                start = offset
        partitions.append(selected[start:])
        return tuple(partitions)


def analyze_point_iteration_layout(
    point_domain: VerifiedPointDomain,
) -> PointIterationLayout:
    """Project iteration strides from a flat Cartesian point domain."""

    coordinate_ids = {column.id for column in point_domain.coordinate_columns}
    root = point_domain.root
    if isinstance(root, PointUnit):
        return PointIterationLayout()
    axes = root.factors if isinstance(root, PointProduct) else (root,)
    projected = tuple(
        projected_axis
        for index, axis in enumerate(axes)
        if axis.id in coordinate_ids
        for values in (_known_axis_values(axis),)
        if values is not None
        for projected_axis in (
            PointIterationAxis(
                axis.id,
                values,
                repeat_each=prod(_axis_count(suffix) for suffix in axes[index + 1 :]),
            ),
        )
    )
    return PointIterationLayout(axes=projected)


def _axis_count(axis: PointAxis[RelationUse[ScalarValueExpr]]) -> int:
    source = axis.source
    return source.count if isinstance(source, PointAxisLinear) else len(source.values)


def _known_axis_values(
    axis: PointAxis[RelationUse[ScalarValueExpr]],
) -> tuple[object, ...] | PointIterationLinearValues | None:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return source.values
    center = source.center.value.plan.root
    if not isinstance(center, LiteralScalarExpr) or not isinstance(
        center.value, Quantity
    ):
        return None
    return PointIterationLinearValues(center.value, source.span, source.count)


__all__ = [
    "PointIterationAxis",
    "PointIterationLayout",
    "PointIterationLinearValues",
    "analyze_point_iteration_layout",
]
