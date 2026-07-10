"""Internal compute dependency summaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import cast

from scopecat._compiler.program import ComputeNodeInput, ComputeNodeSpec
from scopecat._relations import GridColumn, RelationExpr, ScalarExpr, SeriesExpr
from scopecat._value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    ValueExpr,
)


@dataclass(frozen=True)
class ComputeDependencySummary:
    point_columns: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    upstream_compute: tuple[str, ...] = ()

    def merged(self, other: ComputeDependencySummary) -> ComputeDependencySummary:
        return ComputeDependencySummary(
            point_columns=_merge(self.point_columns, other.point_columns),
            input_refs=_merge(self.input_refs, other.input_refs),
            parameters=_merge(self.parameters, other.parameters),
            routes=_merge(self.routes, other.routes),
            upstream_compute=_merge(self.upstream_compute, other.upstream_compute),
        )

    def as_dict(self) -> dict[str, list[str]]:
        return {key: list(value) for key, value in asdict(self).items() if value}


def summarize_compute_node_dependencies(
    node: ComputeNodeSpec,
    *,
    payload: object | None = None,
) -> ComputeDependencySummary:
    summary = ComputeDependencySummary()
    for input_spec in node.inputs.values():
        summary = summary.merged(_input_dependencies(input_spec))
    payload_dependencies = _payload_dependency_summary(payload)
    if payload_dependencies is not None:
        summary = summary.merged(payload_dependencies)
    return summary


def summarize_compute_dependencies(
    nodes: Sequence[ComputeNodeSpec],
) -> dict[str, ComputeDependencySummary]:
    direct = {node.id: summarize_compute_node_dependencies(node) for node in nodes}
    resolved: dict[str, ComputeDependencySummary] = {}
    resolving: set[str] = set()

    def resolve(node_id: str) -> ComputeDependencySummary:
        if node_id in resolved:
            return resolved[node_id]
        summary = direct.get(node_id, ComputeDependencySummary())
        if node_id in resolving:
            return summary
        resolving.add(node_id)
        for upstream_id in summary.upstream_compute:
            summary = summary.merged(resolve(upstream_id))
        resolving.remove(node_id)
        resolved[node_id] = summary
        return summary

    return {node.id: resolve(node.id) for node in nodes}


def _input_dependencies(input_spec: ComputeNodeInput) -> ComputeDependencySummary:
    source_dependencies = ComputeDependencySummary(
        input_refs=tuple(sorted(input_spec.source_inputs))
    )
    if input_spec.kind == "compute_result":
        return source_dependencies.merged(
            ComputeDependencySummary(
                upstream_compute=(input_spec.node_id,) if input_spec.node_id else ()
            )
        )
    if input_spec.kind == "route":
        return source_dependencies.merged(
            ComputeDependencySummary(
                routes=(input_spec.port_id,) if input_spec.port_id else ()
            )
        )
    if input_spec.value is None:
        return source_dependencies
    # ``source_inputs`` is authoring provenance from before binding.  Once a
    # value has been linked, its executable expression is authoritative: it
    # already retains every input that remains unbound and exposes parameters
    # or point columns that replaced the original input edge.
    return _value_expr_dependencies(input_spec.value)


def _value_expr_dependencies(expr: ValueExpr) -> ComputeDependencySummary:
    if isinstance(expr, ScalarValueExpr):
        return _scalar_expr_dependencies(expr.expr)
    if isinstance(expr, SeriesValueExpr):
        return _series_expr_dependencies(expr.expr)
    return _relation_expr_dependencies(expr.expr)


def _scalar_expr_dependencies(expr: ScalarExpr) -> ComputeDependencySummary:
    if expr.kind in {"column", "outer_column"}:
        return ComputeDependencySummary(point_columns=(expr.name,) if expr.name else ())
    if expr.kind == "input":
        return ComputeDependencySummary(input_refs=(expr.name,) if expr.name else ())
    if expr.kind == "param_scalar":
        return ComputeDependencySummary(parameters=(expr.name,) if expr.name else ())
    if expr.kind == "param_lookup":
        summary = ComputeDependencySummary(
            parameters=(expr.table_id,) if expr.table_id else ()
        )
        for key_expr in (expr.key or {}).values():
            summary = summary.merged(_scalar_expr_dependencies(key_expr))
        return summary
    if expr.kind == "binary":
        summary = ComputeDependencySummary()
        if expr.left is not None:
            summary = summary.merged(_scalar_expr_dependencies(expr.left))
        if expr.right is not None:
            summary = summary.merged(_scalar_expr_dependencies(expr.right))
        return summary
    if expr.kind == "case":
        summary = ComputeDependencySummary()
        for branch in expr.cases or ():
            summary = summary.merged(_scalar_expr_dependencies(branch.condition))
            summary = summary.merged(_scalar_expr_dependencies(branch.value))
        if expr.fallback is not None:
            summary = summary.merged(_scalar_expr_dependencies(expr.fallback))
        return summary
    return ComputeDependencySummary()


def _series_expr_dependencies(expr: SeriesExpr) -> ComputeDependencySummary:
    if expr.kind == "param_series":
        return ComputeDependencySummary(parameters=(expr.name,) if expr.name else ())
    if expr.kind == "input":
        return ComputeDependencySummary(input_refs=(expr.name,) if expr.name else ())
    if expr.kind in {"linspace", "range"}:
        summary = ComputeDependencySummary()
        for bound in (expr.start, expr.stop, expr.step):
            if bound is not None:
                summary = summary.merged(_scalar_expr_dependencies(bound))
        return summary
    if expr.kind in {"relation_column", "relation_entities"} and expr.source:
        return _relation_expr_dependencies(expr.source)
    return ComputeDependencySummary()


def _relation_expr_dependencies(expr: RelationExpr) -> ComputeDependencySummary:
    if expr.kind == "table":
        return ComputeDependencySummary(
            parameters=(expr.table_id,) if expr.table_id else ()
        )
    if expr.kind == "input":
        return ComputeDependencySummary(input_refs=(expr.name,) if expr.name else ())
    if expr.kind == "grid":
        summary = ComputeDependencySummary()
        for column in (expr.columns or {}).values():
            summary = summary.merged(_grid_column_dependencies(column))
        return summary
    if expr.kind in {"select", "sort", "limit"}:
        return (
            _relation_expr_dependencies(expr.source)
            if expr.source is not None
            else ComputeDependencySummary()
        )
    if expr.kind == "filter":
        summary = (
            _relation_expr_dependencies(expr.source)
            if expr.source is not None
            else ComputeDependencySummary()
        )
        if expr.condition is not None:
            summary = summary.merged(_scalar_expr_dependencies(expr.condition))
        return summary
    if expr.kind in {"join", "cross"}:
        summary = ComputeDependencySummary()
        for source in (expr.left, expr.right):
            if source is not None:
                summary = summary.merged(_relation_expr_dependencies(source))
        return summary
    if expr.kind == "with_columns":
        summary = (
            _relation_expr_dependencies(expr.source)
            if expr.source is not None
            else ComputeDependencySummary()
        )
        for column in (expr.new_columns or {}).values():
            summary = summary.merged(_scalar_expr_dependencies(column))
        return summary
    return ComputeDependencySummary()


def _grid_column_dependencies(column: GridColumn) -> ComputeDependencySummary:
    if column.kind == "scalar" and column.scalar is not None:
        return _scalar_expr_dependencies(column.scalar)
    if column.kind == "series" and column.series is not None:
        return _series_expr_dependencies(column.series)
    if column.kind == "relation" and column.relation is not None:
        return _relation_expr_dependencies(column.relation)
    return ComputeDependencySummary()


def _payload_dependency_summary(
    payload: object | None,
) -> ComputeDependencySummary | None:
    if payload is None:
        return None
    parameters = getattr(payload, "parameters", None)
    if parameters is None:
        return None
    if isinstance(parameters, str):
        values = (parameters,)
    elif isinstance(parameters, Sequence):
        values = tuple(str(value) for value in cast("Sequence[object]", parameters))
    else:
        return None
    return ComputeDependencySummary(parameters=tuple(sorted(set(values))))


def _merge(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({*left, *right}))


__all__ = [
    "ComputeDependencySummary",
    "summarize_compute_dependencies",
    "summarize_compute_node_dependencies",
]
