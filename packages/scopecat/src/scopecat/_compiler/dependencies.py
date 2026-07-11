"""Dependency provenance attached to config-bound compute calls.

This is a compiler analysis, not an execution-time graph walk.  The result is
carried by ``BoundComputeCall`` so preview and observability code never need to
reconstruct dependencies from authoring expressions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import ComputeEdge, RouteInput, TypedComputeNode
from scopecat._relations import GridColumn, RelationExpr, ScalarExpr, SeriesExpr
from scopecat._value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    ValueExpr,
)


@dataclass(frozen=True, slots=True)
class ComputeDependencies:
    point_columns: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    upstream_compute: tuple[str, ...] = ()

    def merged(self, other: ComputeDependencies) -> ComputeDependencies:
        return ComputeDependencies(
            point_columns=_merge(self.point_columns, other.point_columns),
            input_refs=_merge(self.input_refs, other.input_refs),
            parameters=_merge(self.parameters, other.parameters),
            routes=_merge(self.routes, other.routes),
            upstream_compute=_merge(
                self.upstream_compute,
                other.upstream_compute,
            ),
        )

    def as_mapping(self) -> Mapping[str, tuple[str, ...]]:
        values = {
            "point_columns": self.point_columns,
            "input_refs": self.input_refs,
            "parameters": self.parameters,
            "routes": self.routes,
            "upstream_compute": self.upstream_compute,
        }
        return {name: value for name, value in values.items() if value}


def analyze_compute_dependencies(
    nodes: Sequence[TypedComputeNode],
) -> dict[NodeId, ComputeDependencies]:
    """Return transitive dependency provenance for a verified compute DAG."""

    direct = {node.id: _node_dependencies(node) for node in nodes}
    resolved: dict[NodeId, ComputeDependencies] = {}
    for node in nodes:
        summary = direct[node.id]
        for input_value in node.inputs.values():
            if not isinstance(input_value, ComputeEdge):
                continue
            summary = summary.merged(
                resolved.get(input_value.producer, direct[input_value.producer])
            )
        resolved[node.id] = summary
    return resolved


def _node_dependencies(node: TypedComputeNode) -> ComputeDependencies:
    summary = ComputeDependencies()
    for input_value in node.inputs.values():
        if isinstance(input_value, ComputeEdge):
            current = ComputeDependencies(
                upstream_compute=(input_value.producer.qualified_name,)
            )
        elif isinstance(input_value, RouteInput):
            current = ComputeDependencies(routes=(input_value.port_id,))
        else:
            current = _value_dependencies(input_value.value)
            if input_value.source_inputs:
                current = current.merged(
                    ComputeDependencies(input_refs=input_value.source_inputs)
                )
        summary = summary.merged(current)
    return summary


def _value_dependencies(value: ValueExpr) -> ComputeDependencies:
    if isinstance(value, ScalarValueExpr):
        return _scalar_dependencies(value.expr)
    if isinstance(value, SeriesValueExpr):
        return _series_dependencies(value.expr)
    return _relation_dependencies(value.expr)


def _scalar_dependencies(expr: ScalarExpr) -> ComputeDependencies:
    if expr.kind in {"column", "outer_column"}:
        return ComputeDependencies(point_columns=(expr.name,) if expr.name else ())
    if expr.kind == "input":
        return ComputeDependencies(input_refs=(expr.name,) if expr.name else ())
    if expr.kind == "param_scalar":
        return ComputeDependencies(parameters=(expr.name,) if expr.name else ())
    if expr.kind == "param_lookup":
        summary = ComputeDependencies(
            parameters=(expr.table_id,) if expr.table_id else ()
        )
        for key_expr in (expr.key or {}).values():
            summary = summary.merged(_scalar_dependencies(key_expr))
        return summary
    if expr.kind == "binary":
        summary = ComputeDependencies()
        if expr.left is not None:
            summary = summary.merged(_scalar_dependencies(expr.left))
        if expr.right is not None:
            summary = summary.merged(_scalar_dependencies(expr.right))
        return summary
    if expr.kind == "case":
        summary = ComputeDependencies()
        for branch in expr.cases or ():
            summary = summary.merged(_scalar_dependencies(branch.condition))
            summary = summary.merged(_scalar_dependencies(branch.value))
        if expr.fallback is not None:
            summary = summary.merged(_scalar_dependencies(expr.fallback))
        return summary
    return ComputeDependencies()


def _series_dependencies(expr: SeriesExpr) -> ComputeDependencies:
    if expr.kind == "param_series":
        return ComputeDependencies(parameters=(expr.name,) if expr.name else ())
    if expr.kind == "input":
        return ComputeDependencies(input_refs=(expr.name,) if expr.name else ())
    if expr.kind in {"linspace", "range"}:
        summary = ComputeDependencies()
        for bound in (expr.start, expr.stop, expr.step):
            if bound is not None:
                summary = summary.merged(_scalar_dependencies(bound))
        return summary
    if expr.kind in {"relation_column", "relation_entities"} and expr.source:
        return _relation_dependencies(expr.source)
    return ComputeDependencies()


def _relation_dependencies(expr: RelationExpr) -> ComputeDependencies:
    if expr.kind == "table":
        return ComputeDependencies(parameters=(expr.table_id,) if expr.table_id else ())
    if expr.kind == "input":
        return ComputeDependencies(input_refs=(expr.name,) if expr.name else ())
    if expr.kind == "grid":
        summary = ComputeDependencies()
        for column in (expr.columns or {}).values():
            summary = summary.merged(_grid_column_dependencies(column))
        return summary
    if expr.kind in {"select", "sort", "limit"}:
        return (
            _relation_dependencies(expr.source)
            if expr.source is not None
            else ComputeDependencies()
        )
    if expr.kind == "filter":
        summary = (
            _relation_dependencies(expr.source)
            if expr.source is not None
            else ComputeDependencies()
        )
        if expr.condition is not None:
            summary = summary.merged(_scalar_dependencies(expr.condition))
        return summary
    if expr.kind in {"join", "cross"}:
        summary = ComputeDependencies()
        for source in (expr.left, expr.right):
            if source is not None:
                summary = summary.merged(_relation_dependencies(source))
        return summary
    if expr.kind == "zip":
        summary = ComputeDependencies()
        for source in expr.sources or ():
            summary = summary.merged(_relation_dependencies(source))
        return summary
    if expr.kind == "with_columns":
        summary = (
            _relation_dependencies(expr.source)
            if expr.source is not None
            else ComputeDependencies()
        )
        for column in (expr.new_columns or {}).values():
            summary = summary.merged(_scalar_dependencies(column))
        return summary
    return ComputeDependencies()


def _grid_column_dependencies(column: GridColumn) -> ComputeDependencies:
    if column.kind == "scalar" and column.scalar is not None:
        return _scalar_dependencies(column.scalar)
    if column.kind == "series" and column.series is not None:
        return _series_dependencies(column.series)
    if column.kind == "relation" and column.relation is not None:
        return _relation_dependencies(column.relation)
    return ComputeDependencies()


def _merge(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({*left, *right}))


__all__ = ["ComputeDependencies", "analyze_compute_dependencies"]
