"""Compiler-owned exact iteration layout for verified point domains."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import prod

from scopecat.compiler.relations.model import LiteralScalarExpr
from scopecat.compiler.relations.point_domain import (
    PointAxis,
    PointAxisValues,
    PointDependentProduct,
    PointDomainPath,
    PointProduct,
    PointRows,
    PointUnit,
    PointZip,
    point_axis_linear_value,
)
from scopecat.compiler.relations.scalar_eval import read_path
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import (
    CompilerPointDomainExpr,
    VerifiedPointDomain,
)
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.records.parameter import Quantity


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
    preferred_tile_size: int | None = None

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
    """Project iteration directly from the exact point algebra."""

    coordinate_ids = {column.id for column in point_domain.coordinate_columns}

    def count(path: PointDomainPath) -> int:
        return point_domain.analysis.facts[path].cardinality

    def project(
        node: CompilerPointDomainExpr,
        path: PointDomainPath,
        *,
        repeat_each: int,
    ) -> tuple[PointIterationAxis, ...]:
        if isinstance(node, PointUnit):
            return ()
        if isinstance(node, PointRows):
            column_ids = tuple(column.id for column in node.columns)
            return tuple(
                PointIterationAxis(
                    column_id,
                    tuple(row[index] for row in node.rows),
                    repeat_each=repeat_each,
                )
                for index, column_id in enumerate(column_ids)
                if column_id in coordinate_ids
            )
        if isinstance(node, PointAxis):
            values = _known_axis_values(node)
            return (
                (
                    PointIterationAxis(
                        node.id,
                        values,
                        repeat_each=repeat_each,
                    ),
                )
                if values is not None and node.id in coordinate_ids
                else ()
            )
        if isinstance(node, PointZip):
            return tuple(
                axis
                for index, source in enumerate(node.sources)
                for axis in project(
                    source,
                    (*path, "sources", index),
                    repeat_each=repeat_each,
                )
            )
        if isinstance(node, PointProduct):
            return tuple(
                axis
                for index, factor in enumerate(node.factors)
                for axis in project(
                    factor,
                    (*path, "factors", index),
                    repeat_each=repeat_each
                    * prod(
                        count((*path, "factors", suffix_index))
                        for suffix_index in range(index + 1, len(node.factors))
                    ),
                )
            )
        right_count = count((*path, "right"))
        return (
            *project(
                node.left,
                (*path, "left"),
                repeat_each=repeat_each * right_count,
            ),
            *project(
                node.right,
                (*path, "right"),
                repeat_each=repeat_each,
            ),
        )

    root = point_domain.root
    preferred_path = (
        ("factors", len(root.factors) - 1)
        if isinstance(root, PointProduct)
        else ("right",)
        if isinstance(root, PointDependentProduct)
        else ()
    )
    preferred_tile_size = count(preferred_path) or None
    return PointIterationLayout(
        axes=project(root, (), repeat_each=1),
        preferred_tile_size=preferred_tile_size,
    )


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
