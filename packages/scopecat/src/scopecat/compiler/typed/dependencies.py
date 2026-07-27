"""Verified dependency facts for residual compute lowering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from scopecat.compiler.relations.verification import PlanImportNamespace
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.program import (
    ComputeEdge,
    CoreProgram,
    TypedComputeNode,
    core_state,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.graph.values import (
    ComputeResultRef,
    OperationId,
    ValueId,
)


class ComputeScope(StrEnum):
    """The only two evaluation scopes of residual pure compute."""

    RUN = "run"
    POINT = "point"


@dataclass(frozen=True, slots=True)
class ComputeDependencies:
    point_columns: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    upstream_compute: tuple[str, ...] = ()

    @property
    def scope(self) -> ComputeScope:
        return ComputeScope.POINT if self.point_columns else ComputeScope.RUN

    def merged(self, other: ComputeDependencies) -> ComputeDependencies:
        return ComputeDependencies(
            point_columns=_merge(self.point_columns, other.point_columns),
            input_refs=_merge(self.input_refs, other.input_refs),
            parameters=_merge(self.parameters, other.parameters),
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
            "upstream_compute": self.upstream_compute,
        }
        return {name: value for name, value in values.items() if value}


@dataclass(frozen=True, slots=True)
class ComputePlan:
    """Verified residual compute facts consumed by every target materializer."""

    nodes: tuple[TypedComputeNode, ...]
    scopes: Mapping[OperationId, ComputeScope]
    dependencies: Mapping[OperationId, ComputeDependencies]
    output_owners: Mapping[ValueId, OperationId]
    demanded_payload_results: frozenset[ValueId]

    @property
    def run_nodes(self) -> tuple[TypedComputeNode, ...]:
        return tuple(
            node for node in self.nodes if self.scopes[node.id] is ComputeScope.RUN
        )

    @property
    def point_nodes(self) -> tuple[TypedComputeNode, ...]:
        return tuple(
            node for node in self.nodes if self.scopes[node.id] is ComputeScope.POINT
        )


def analyze_compute_plan(program: CoreProgram) -> ComputePlan:
    """Close compute scope, provenance, ownership, and effect demand once."""

    dependencies = analyze_compute_dependencies(program.compute_nodes)
    output_owners = {node.result.id: node.id for node in program.compute_nodes}
    overlaid_parameter_tables = {
        overlay.table_id for overlay in program.parameter_overlays
    }
    scopes = {
        node.id: (
            ComputeScope.POINT
            if dependencies[node.id].scope is ComputeScope.POINT
            or bool(set(dependencies[node.id].parameters) & overlaid_parameter_tables)
            else ComputeScope.RUN
        )
        for node in program.compute_nodes
    }
    demanded = {
        value_id
        for spec in core_state(program)
        for value_id in _state_compute_results(spec)
    }
    return ComputePlan(
        nodes=program.compute_nodes,
        scopes=MappingProxyType(scopes),
        dependencies=MappingProxyType(dependencies),
        output_owners=MappingProxyType(output_owners),
        demanded_payload_results=frozenset(demanded),
    )


def _state_compute_results(spec: SetStateSpec) -> tuple[ValueId, ...]:
    return (
        (spec.value_use.value_id,)
        if isinstance(spec.value_use, ComputeResultRef)
        else ()
    )


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
        else:
            current = _value_dependencies(input_value.value)
            if input_value.origin_input_ids:
                current = current.merged(
                    ComputeDependencies(input_refs=input_value.origin_input_ids)
                )
        summary = summary.merged(current)
    return summary


def _value_dependencies(value: ValueExpr) -> ComputeDependencies:
    plan = value.plan
    point_requirement = plan.external_point_requirement
    return ComputeDependencies(
        point_columns=(
            point_requirement.column_references if point_requirement is not None else ()
        ),
        input_refs=plan.import_ids(PlanImportNamespace.INPUT),
        parameters=plan.import_ids(PlanImportNamespace.PARAMETER),
    )


def _merge(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({*left, *right}))
