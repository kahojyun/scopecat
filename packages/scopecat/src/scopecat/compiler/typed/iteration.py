"""Compiler-owned symbolic iteration layout for verified point domains.

The layout is the single structural account of point variation used by local
lowering, parameter overlays, resource selections, and the domain SDK projection.
Sharing that account keeps reuse and target lowering consistent. Proven axes
and nesting enable structural specialization; opaque regions preserve safety
when the compiler lacks enough information.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from math import prod
from typing import cast

from scopecat.compiler.relations.evaluation import EvalContext
from scopecat.compiler.relations.evaluator import evaluate_series_expression
from scopecat.compiler.relations.model import (
    GridRelationExpr,
    LinspaceSeriesExpr,
    LiteralRowsRelationExpr,
    LiteralScalarExpr,
    RangeSeriesExpr,
    ScalarGridColumn,
    SeriesGridColumn,
    ValuesGridColumn,
    ValuesSeriesExpr,
)
from scopecat.compiler.relations.point_domain import (
    PointDependentProduct,
    PointDomainPath,
    PointRelationRows,
    PointUnit,
    PointZip,
)
from scopecat.compiler.relations.scalar_eval import read_path
from scopecat.compiler.typed.point_domain import (
    CompilerPointDomainExpr,
    VerifiedPointDomain,
)
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash


@dataclass(frozen=True, slots=True)
class PointIterationAxis:
    id: str
    values: tuple[object, ...]
    repeat_each: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", deepcopy(tuple(self.values)))

    def values_at(self, ordinals: Sequence[int]) -> tuple[object, ...]:
        return tuple(
            self.values[(ordinal // self.repeat_each) % len(self.values)]
            for ordinal in ordinals
        )


@dataclass(frozen=True, slots=True)
class PointIterationUnit:
    @property
    def extent(self) -> int:
        return 1


@dataclass(frozen=True, slots=True)
class PointIterationLeaf:
    axis_ids: tuple[str, ...]
    extent: int | None


@dataclass(frozen=True, slots=True)
class PointIterationOpaque:
    extent: int | None


@dataclass(frozen=True, slots=True)
class PointIterationDependent:
    """Ordered product whose right layout is evaluated per left point."""

    left: PointIterationNode
    right: PointIterationNode
    extent: int | None


@dataclass(frozen=True, slots=True)
class PointIterationProduct:
    factors: tuple[PointIterationNode, ...]

    @property
    def extent(self) -> int | None:
        extents = tuple(factor.extent for factor in self.factors)
        if any(extent is None for extent in extents):
            return None
        return prod(cast("tuple[int, ...]", extents))


@dataclass(frozen=True, slots=True)
class PointIterationZip:
    sources: tuple[PointIterationNode, ...]
    extent: int | None


type PointIterationNode = (
    PointIterationUnit
    | PointIterationLeaf
    | PointIterationOpaque
    | PointIterationDependent
    | PointIterationProduct
    | PointIterationZip
)


@dataclass(frozen=True, slots=True)
class PointIterationLayout:
    root: PointIterationNode
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
            exact_axes = cast("tuple[PointIterationAxis, ...]", axes)
            values = {
                axis.id: content_fingerprint(axis.values_at((ordinal,))[0])
                for axis in exact_axes
            }
        elif fallback_row is not None:
            values = {
                axis_id: content_fingerprint(read_path(fallback_row, axis_id))
                for axis_id in requested
            }
        else:
            raise KeyError("iteration support crosses an opaque axis")
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
    """Project the one compiler-owned exact/opaque iteration structure."""

    coordinate_ids = tuple(column.id for column in point_domain.coordinate_columns)

    def exact_count(path: PointDomainPath) -> int | None:
        cardinality = point_domain.analysis.facts[path].cardinality
        return (
            cardinality.minimum if cardinality.maximum == cardinality.minimum else None
        )

    def project(
        node: CompilerPointDomainExpr,
        path: PointDomainPath,
        *,
        repeat_each: int,
    ) -> tuple[PointIterationNode, tuple[PointIterationAxis, ...]]:
        count = exact_count(path)
        if isinstance(node, PointUnit):
            return PointIterationUnit(), ()
        if isinstance(node, PointDependentProduct):
            right_count = exact_count((*path, "right"))
            if right_count is None:
                left_layout: PointIterationNode = PointIterationOpaque(
                    exact_count((*path, "left"))
                )
                left_axes: tuple[PointIterationAxis, ...] = ()
            else:
                left_layout, left_axes = project(
                    node.left,
                    (*path, "left"),
                    repeat_each=repeat_each * right_count,
                )
            right_layout, right_axes = project(
                node.right,
                (*path, "right"),
                repeat_each=repeat_each,
            )
            return (
                PointIterationDependent(left_layout, right_layout, count),
                (*left_axes, *right_axes),
            )
        if isinstance(node, PointRelationRows):
            relation = node.rows.plan.root
            projected = _finite_relation_layout(
                relation,
                coordinate_ids=tuple(
                    column.id
                    for column in node.rows.value_type.columns
                    if column.id in coordinate_ids
                ),
                repeat_each=repeat_each,
                extent=count,
            )
            if projected is None:
                return PointIterationOpaque(count), ()
            return projected
        if isinstance(node, PointZip):
            projected = tuple(
                project(
                    source,
                    (*path, "sources", index),
                    repeat_each=repeat_each,
                )
                for index, source in enumerate(node.sources)
            )
            return (
                PointIterationZip(
                    tuple(child for child, _axes in projected),
                    count,
                ),
                tuple(axis for _child, axes in projected for axis in axes),
            )
        projected_factors: list[
            tuple[PointIterationNode, tuple[PointIterationAxis, ...]]
        ] = []
        for index, factor in enumerate(node.factors):
            suffix_counts = tuple(
                exact_count((*path, "factors", suffix_index))
                for suffix_index in range(index + 1, len(node.factors))
            )
            if any(suffix_count is None for suffix_count in suffix_counts):
                projected_factors.append(
                    (
                        PointIterationOpaque(exact_count((*path, "factors", index))),
                        (),
                    )
                )
                continue
            projected_factors.append(
                project(
                    factor,
                    (*path, "factors", index),
                    repeat_each=repeat_each
                    * prod(cast("tuple[int, ...]", suffix_counts)),
                )
            )
        return (
            PointIterationProduct(tuple(child for child, _axes in projected_factors)),
            tuple(axis for _child, axes in projected_factors for axis in axes),
        )

    root, axes = project(point_domain.root, (), repeat_each=1)
    return PointIterationLayout(root, axes)


def _finite_relation_layout(
    relation: object,
    *,
    coordinate_ids: Sequence[str],
    repeat_each: int,
    extent: int | None,
) -> tuple[PointIterationNode, tuple[PointIterationAxis, ...]] | None:
    if isinstance(relation, LiteralRowsRelationExpr):
        axes = tuple(
            PointIterationAxis(
                column_id,
                tuple(read_path(row, column_id) for row in relation.rows),
                repeat_each=repeat_each,
            )
            for column_id in (
                column_id
                for column_id in coordinate_ids
                if all(column_id in row for row in relation.rows)
            )
        )
        return PointIterationLeaf(
            tuple(axis.id for axis in axes), len(relation.rows)
        ), axes
    if not isinstance(relation, GridRelationExpr):
        return None
    columns: list[tuple[str, tuple[object, ...] | None, int | None]] = []
    for column_id, column in relation.columns.items():
        values, length = _finite_grid_column(column)
        columns.append((column_id, values, length))
    lengths = tuple(length for _column_id, _values, length in columns)
    selected_extent = extent
    if selected_extent is None and all(length is not None for length in lengths):
        selected_extent = prod(cast("tuple[int, ...]", lengths))
    projected_axes: list[PointIterationAxis] = []
    for index, (column_id, values, _length) in enumerate(columns):
        if values is None or column_id not in coordinate_ids:
            continue
        trailing = lengths[index + 1 :]
        stride: int | None = None
        if all(length is not None for length in trailing):
            stride = prod(cast("tuple[int, ...]", trailing))
        else:
            prefix = lengths[: index + 1]
            if selected_extent is not None and all(
                length is not None for length in prefix
            ):
                prefix_extent = prod(cast("tuple[int, ...]", prefix))
                if prefix_extent and selected_extent % prefix_extent == 0:
                    stride = selected_extent // prefix_extent
        if stride is not None:
            projected_axes.append(
                PointIterationAxis(
                    column_id,
                    values,
                    repeat_each=repeat_each * stride,
                )
            )
    if selected_extent is None and not projected_axes:
        return None
    selected_axes = tuple(projected_axes)
    return (
        PointIterationLeaf(
            tuple(axis.id for axis in selected_axes),
            selected_extent,
        ),
        selected_axes,
    )


def _finite_grid_column(
    column: object,
) -> tuple[tuple[object, ...] | None, int | None]:
    if isinstance(column, ValuesGridColumn):
        values = tuple(column.values)
        return values, len(values)
    if isinstance(column, ScalarGridColumn):
        return (
            ((column.scalar.value,), 1)
            if isinstance(column.scalar, LiteralScalarExpr)
            else (None, 1)
        )
    if not isinstance(column, SeriesGridColumn):
        return None, None
    series = column.series
    if isinstance(series, ValuesSeriesExpr):
        values = tuple(series.items)
        return values, len(values)
    if isinstance(series, LinspaceSeriesExpr) and all(
        isinstance(value, LiteralScalarExpr) for value in (series.start, series.stop)
    ):
        values = tuple(evaluate_series_expression(series, EvalContext()))
        return values, len(values)
    if isinstance(series, LinspaceSeriesExpr):
        return None, series.count
    if isinstance(series, RangeSeriesExpr) and all(
        isinstance(value, LiteralScalarExpr)
        for value in (series.start, series.stop, series.step)
    ):
        values = tuple(evaluate_series_expression(series, EvalContext()))
        return values, len(values)
    return None, None


__all__ = [
    "PointIterationAxis",
    "PointIterationDependent",
    "PointIterationLayout",
    "PointIterationLeaf",
    "PointIterationNode",
    "PointIterationOpaque",
    "PointIterationProduct",
    "PointIterationUnit",
    "PointIterationZip",
    "analyze_point_iteration_layout",
]
