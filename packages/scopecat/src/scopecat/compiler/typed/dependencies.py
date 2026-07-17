"""Dependency provenance attached to config-bound compute calls.

This is a compiler analysis, not an execution-time graph walk.  The result is
carried by ``BoundComputeCall`` so preview and observability code never need to
reconstruct dependencies from authoring expressions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.compiler.relations.analysis import PlanReferenceKind
from scopecat.compiler.semantic.model import (
    OperationId,
    ValueId,
)
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.program import ComputeEdge, RouteInput, TypedComputeNode


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
) -> dict[OperationId, ComputeDependencies]:
    """Return transitive dependency provenance for a verified compute DAG."""

    output_owners = {node.result.id: node.id for node in nodes}
    direct = {
        node.id: _node_dependencies(node, output_owners=output_owners) for node in nodes
    }
    resolved: dict[OperationId, ComputeDependencies] = {}
    for node in nodes:
        summary = direct[node.id]
        for input_value in node.inputs.values():
            if not isinstance(input_value, ComputeEdge):
                continue
            producer_id = output_owners[input_value.value_id]
            summary = summary.merged(resolved.get(producer_id, direct[producer_id]))
        resolved[node.id] = summary
    return resolved


def _node_dependencies(
    node: TypedComputeNode,
    *,
    output_owners: Mapping[ValueId, OperationId],
) -> ComputeDependencies:
    summary = ComputeDependencies()
    for input_value in node.inputs.values():
        if isinstance(input_value, ComputeEdge):
            producer_id = output_owners[input_value.value_id]
            current = ComputeDependencies(
                upstream_compute=(producer_id.qualified_name,)
            )
        elif isinstance(input_value, RouteInput):
            current = ComputeDependencies(routes=(input_value.port_id.qualified_name,))
        else:
            current = _value_dependencies(input_value.value)
            if input_value.origin_input_ids:
                current = current.merged(
                    ComputeDependencies(input_refs=input_value.origin_input_ids)
                )
        summary = summary.merged(current)
    return summary


def _value_dependencies(value: ValueExpr) -> ComputeDependencies:
    references = value.plan.references
    return ComputeDependencies(
        point_columns=references.ids(PlanReferenceKind.POINT_COLUMN),
        input_refs=references.ids(
            PlanReferenceKind.INPUT_SCALAR,
            PlanReferenceKind.INPUT_SERIES,
            PlanReferenceKind.INPUT_TABLE,
        ),
        parameters=references.ids(
            PlanReferenceKind.PARAMETER_SCALAR,
            PlanReferenceKind.PARAMETER_SERIES,
            PlanReferenceKind.PARAMETER_TABLE,
        ),
    )


def _merge(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({*left, *right}))
