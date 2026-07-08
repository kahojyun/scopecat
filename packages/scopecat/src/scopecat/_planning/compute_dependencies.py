"""Internal compute dependency summaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import cast

from scopecat.experiments import ComputeNodeInput, ComputeNodeSpec
from scopecat.relations import ScalarExpr


@dataclass(frozen=True)
class ComputeDependencySummary:
    point_columns: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    scalar_params: tuple[str, ...] = ()
    parameter_tables: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    upstream_compute: tuple[str, ...] = ()

    def merged(self, other: ComputeDependencySummary) -> ComputeDependencySummary:
        return ComputeDependencySummary(
            point_columns=_merge(self.point_columns, other.point_columns),
            input_refs=_merge(self.input_refs, other.input_refs),
            scalar_params=_merge(self.scalar_params, other.scalar_params),
            parameter_tables=_merge(self.parameter_tables, other.parameter_tables),
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
    if node.route_ports:
        summary = summary.merged(
            ComputeDependencySummary(routes=tuple(sorted(node.route_ports)))
        )
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
    return source_dependencies.merged(_expr_dependencies(input_spec.value))


def _expr_dependencies(expr: ScalarExpr) -> ComputeDependencySummary:
    if expr.kind == "column":
        return ComputeDependencySummary(point_columns=(expr.name,) if expr.name else ())
    if expr.kind == "input":
        return ComputeDependencySummary(input_refs=(expr.name,) if expr.name else ())
    if expr.kind == "param_scalar":
        return ComputeDependencySummary(scalar_params=(expr.name,) if expr.name else ())
    if expr.kind == "param_lookup":
        summary = ComputeDependencySummary(
            parameter_tables=(expr.table_id,) if expr.table_id else ()
        )
        for key_expr in (expr.key or {}).values():
            summary = summary.merged(_expr_dependencies(key_expr))
        return summary
    if expr.kind == "binary":
        summary = ComputeDependencySummary()
        if expr.left is not None:
            summary = summary.merged(_expr_dependencies(expr.left))
        if expr.right is not None:
            summary = summary.merged(_expr_dependencies(expr.right))
        return summary
    if expr.kind == "case":
        summary = ComputeDependencySummary()
        for branch in expr.cases or ():
            summary = summary.merged(_expr_dependencies(branch.condition))
            summary = summary.merged(_expr_dependencies(branch.value))
        if expr.fallback is not None:
            summary = summary.merged(_expr_dependencies(expr.fallback))
        return summary
    return ComputeDependencySummary()


def _payload_dependency_summary(
    payload: object | None,
) -> ComputeDependencySummary | None:
    if payload is None:
        return None
    parameter_tables = getattr(payload, "parameter_tables", None)
    if parameter_tables is None:
        return None
    if isinstance(parameter_tables, str):
        values = (parameter_tables,)
    elif isinstance(parameter_tables, Sequence):
        values = tuple(
            str(value) for value in cast("Sequence[object]", parameter_tables)
        )
    else:
        return None
    return ComputeDependencySummary(parameter_tables=tuple(sorted(set(values))))


def _merge(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({*left, *right}))


__all__ = [
    "ComputeDependencySummary",
    "summarize_compute_dependencies",
    "summarize_compute_node_dependencies",
]
