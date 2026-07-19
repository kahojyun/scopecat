"""Verified dependency and point-variation facts for residual lowering.

``ComputePlan`` closes demand, ownership, transitive provenance, and evaluation
scope once so every lowering consumer uses the same graph facts.
``VariationAnalysis`` identifies the point axes that may change each semantic
object, enabling safe structural reuse across a scan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from scopecat.compiler.relations.analysis import PlanReferenceKind
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    OperationId,
    ValueId,
)
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.program import (
    ComputeEdge,
    CoreProgram,
    RouteInput,
    TypedComputeNode,
    core_actions,
    core_state,
)
from scopecat.compiler.typed.state import (
    ForEachStateSpec,
    LogicalStateResourceTarget,
    SetStateSpec,
    StateSpecVariant,
)


@dataclass(frozen=True, slots=True)
class PointVariationSupport:
    """Point columns whose values can change one lowered semantic object."""

    point_columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "point_columns", tuple(sorted(set(self.point_columns)))
        )

    def merged(self, other: PointVariationSupport) -> PointVariationSupport:
        return PointVariationSupport((*self.point_columns, *other.point_columns))


@dataclass(frozen=True, slots=True)
class VariationAnalysis:
    """One verified projection of structural variation across semantic owners.

    The supports describe which point axes can change a value, allowing the
    iteration layout to derive exact contiguous reuse coverage.
    """

    parameters: PointVariationSupport
    routes: Mapping[str, PointVariationSupport]
    compute: Mapping[OperationId, PointVariationSupport]
    state: tuple[PointVariationSupport, ...]


class ComputeScope(StrEnum):
    """The only two evaluation scopes of residual pure compute."""

    RUN = "run"
    POINT = "point"


@dataclass(frozen=True, slots=True)
class ComputeDependencies:
    point_columns: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    upstream_compute: tuple[str, ...] = ()

    @property
    def scope(self) -> ComputeScope:
        return (
            ComputeScope.POINT
            if self.point_columns or self.routes
            else ComputeScope.RUN
        )

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


@dataclass(frozen=True, slots=True)
class ComputePlan:
    """Verified residual compute facts consumed by every target materializer.

    Scope follows transitive point and route dependence. Finer reuse remains
    separate because it depends on structural variation within point scope.
    """

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
    demanded.update(
        field.value_use.value_id
        for action in core_actions(program)
        for field in action.fields
        if isinstance(field.value_use, ComputeResultRef)
    )
    return ComputePlan(
        nodes=program.compute_nodes,
        scopes=MappingProxyType(scopes),
        dependencies=MappingProxyType(dependencies),
        output_owners=MappingProxyType(output_owners),
        demanded_payload_results=frozenset(demanded),
    )


def _state_compute_results(spec: StateSpecVariant) -> tuple[ValueId, ...]:
    if isinstance(spec, SetStateSpec):
        return (
            (spec.value_use.value_id,)
            if isinstance(spec.value_use, ComputeResultRef)
            else ()
        )
    return tuple(
        value_id for child in spec.state for value_id in _state_compute_results(child)
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


def _parameter_overlay_variation_support(
    overlays: Sequence[PointParameterOverlay],
) -> PointVariationSupport:
    """Return structural point support that can change effective parameters."""

    return PointVariationSupport(
        _merge_many(
            tuple(
                use.value.plan.references.ids(PlanReferenceKind.POINT_COLUMN)
                for overlay in overlays
                for use in (*overlay.key_uses.values(), overlay.value_use)
            )
        )
    )


def _route_variation_support(
    program: CoreProgram,
    *,
    parameter_support: PointVariationSupport,
) -> Mapping[str, PointVariationSupport]:
    """Return structural point support that can change each resource route."""

    overlaid_tables = {overlay.table_id for overlay in program.parameter_overlays}
    selected: dict[str, PointVariationSupport] = {}
    for route in program.route_intents:
        columns: set[str] = set()
        for use in route.entity_uses:
            dependencies = _value_dependencies(use.value)
            columns.update(dependencies.point_columns)
            if set(dependencies.parameters) & overlaid_tables:
                columns.update(parameter_support.point_columns)
        selected[route.port_id.qualified_name] = PointVariationSupport(tuple(columns))
    return MappingProxyType(selected)


def analyze_variation_support(
    program: CoreProgram,
    compute_plan: ComputePlan,
) -> VariationAnalysis:
    """Project every target-facing support from canonical dependencies once."""

    parameter_support = _parameter_overlay_variation_support(program.parameter_overlays)
    route_support = _route_variation_support(
        program,
        parameter_support=parameter_support,
    )
    overlaid_tables = {overlay.table_id for overlay in program.parameter_overlays}
    compute_support = MappingProxyType(
        {
            operation_id: PointVariationSupport(
                (
                    *dependency.point_columns,
                    *(
                        parameter_support.point_columns
                        if set(dependency.parameters) & overlaid_tables
                        else ()
                    ),
                    *(
                        column_id
                        for route_id in dependency.routes
                        for column_id in route_support[route_id].point_columns
                    ),
                )
            )
            for operation_id, dependency in compute_plan.dependencies.items()
        }
    )

    def value_support(value: ValueExpr) -> PointVariationSupport:
        dependencies = _value_dependencies(value)
        return PointVariationSupport(
            (
                *dependencies.point_columns,
                *(
                    parameter_support.point_columns
                    if set(dependencies.parameters) & overlaid_tables
                    else ()
                ),
            )
        )

    def spec_support(spec: StateSpecVariant) -> PointVariationSupport:
        if isinstance(spec, ForEachStateSpec):
            selected = value_support(spec.relation_use.value)
            for child in spec.state:
                selected = selected.merged(spec_support(child))
            return selected
        selected = PointVariationSupport()
        target = spec.resource_target
        if isinstance(target, LogicalStateResourceTarget):
            selected = selected.merged(route_support[target.port_id.qualified_name])
        else:
            selected = selected.merged(value_support(target.use.value))
        for use in spec.route_entity_uses:
            selected = selected.merged(value_support(use.value))
        if isinstance(spec.value_use, ComputeResultRef):
            owner = compute_plan.output_owners[spec.value_use.value_id]
            selected = selected.merged(compute_support[owner])
        else:
            selected = selected.merged(value_support(spec.value_use.value))
        return selected

    return VariationAnalysis(
        parameters=parameter_support,
        routes=route_support,
        compute=compute_support,
        state=tuple(spec_support(spec) for spec in core_state(program)),
    )


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


def _merge_many(values: Sequence[tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(sorted({item for value in values for item in value}))
