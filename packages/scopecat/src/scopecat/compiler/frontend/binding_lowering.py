"""Lower source resource bindings into typed compiler route intents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.authoring._binding_intents import (
    BindingIntent,
    ResourcePort,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_availability,
)
from scopecat.compiler.frontend.context import ExperimentAuthoringContext
from scopecat.compiler.frontend.value_binding import bind_value_input_refs
from scopecat.compiler.relations.model import (
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
)
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.availability import ValueStage
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.value_expressions import (
    ScalarOrSeriesValueExpr,
    verify_scalar_value_expr,
    verify_series_value_expr,
)
from scopecat.compiler.typed.program import ResourceRouteIntent
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.value_types import Entity, Scalar, Series
from scopecat.records.entity import EntityRef


@dataclass(frozen=True)
class BindingSpec:
    """Private compiler-ready desired-state binding."""

    resource_port_id: LogicalResourcePortId
    capability_id: str
    field_path: str
    value: ScalarExpr | ComputeResultRef
    value_type: Scalar | None


def lower_binding_intent(
    intent: BindingIntent,
    ctx: ExperimentAuthoringContext,
    resource_ports: Mapping[LogicalResourcePortId, ResourcePort],
) -> BindingSpec:
    """Lower one source binding after config-dependent port validation."""

    resource_port = resource_ports.get(intent.port_id)
    if resource_port is None:
        ctx.raise_problem(
            "module_unknown_resource_port",
            f"binding references unknown resource port {intent.port_id}",
            "bindings",
        )
    require_port_capability(ctx, resource_port, intent.capability_id)
    value = intent.value
    value_type: Scalar | None = None
    if isinstance(value, ValueRef):
        declared_type = value.value_type
        value = internal_lower_value_ref(value)
        if not isinstance(value, ScalarExpr | ComputeResultRef):
            msg = "state binding value must be scalar-shaped"
            raise TypeError(msg)
        if isinstance(value, ScalarExpr):
            if not isinstance(declared_type, Scalar):
                msg = "state binding scalar expression must declare a scalar type"
                raise TypeError(msg)
            value_type = declared_type
    return BindingSpec(
        resource_port_id=intent.port_id,
        capability_id=intent.capability_id,
        field_path=intent.field_path,
        value=value if isinstance(value, ComputeResultRef) else as_scalar_expr(value),
        value_type=value_type,
    )


def build_route_intents(
    ctx: ExperimentAuthoringContext,
    ports: Sequence[ResourcePort],
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> list[ResourceRouteIntent]:
    route_intents: list[ResourceRouteIntent] = []
    for port in ports:
        route_intents.append(
            ResourceRouteIntent(
                port_id=port.symbol_id,
                capabilities=tuple(port.selector.capabilities),
                entity_uses=tuple(
                    relation_use(
                        _route_entity_expr(
                            ctx,
                            input_id,
                            inputs,
                            type_bindings=type_bindings,
                        )
                    )
                    for input_id in port.selector.entity_inputs
                ),
                fixed_resource_id=None,
            )
        )
    return route_intents


def ports_by_id(
    ctx: ExperimentAuthoringContext,
    ports: Sequence[ResourcePort],
) -> dict[LogicalResourcePortId, ResourcePort]:
    result: dict[LogicalResourcePortId, ResourcePort] = {}
    for port in ports:
        port_id = port.symbol_id
        if port_id in result:
            ctx.raise_problem(
                "module_resource_port_duplicate",
                f"duplicate resource port {port_id.qualified_name}",
                "resources",
                path=(*port_id.scope, port_id.local_id),
            )
        result[port_id] = port
    return result


def _route_entity_expr(
    ctx: ExperimentAuthoringContext,
    source: ValueRef,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
) -> ScalarOrSeriesValueExpr:
    value_type = source.value_type
    is_entity_value = (
        isinstance(value_type, Scalar) and isinstance(value_type.atom, Entity)
    ) or (
        isinstance(value_type, Series) and isinstance(value_type.item_type.atom, Entity)
    )
    if (
        not is_entity_value
        or internal_value_ref_availability(source).stage != ValueStage.PLAN
    ):
        ctx.raise_problem(
            "module_resource_entity_input_invalid",
            "resource entity source must be a plan-stage entity value",
            "resources",
        )
    lowered = internal_lower_value_ref(source)
    if not isinstance(lowered, ScalarExpr | SeriesExpr):
        ctx.raise_problem(
            "module_resource_entity_input_invalid",
            "resource entity source must be scalar or series-shaped",
            "resources",
        )
    bound = bind_value_input_refs(lowered, inputs)
    if not isinstance(bound, ScalarExpr | SeriesExpr):
        ctx.raise_problem(
            "module_resource_entity_input_invalid",
            "resource entity source must be scalar or series-shaped",
            "resources",
        )
    if isinstance(bound, ScalarExpr) and bound.kind == "literal":
        bound = bound.model_copy(
            update={"value": ctx.require_entity(cast("EntityRef | str", bound.value))}
        )
    if isinstance(bound, SeriesExpr) and bound.kind == "values":
        bound = bound.model_copy(
            update={
                "items": list(
                    ctx.require_entities(
                        cast("Sequence[EntityRef | str]", bound.items or ())
                    )
                )
            }
        )
    if isinstance(bound, ScalarExpr) and isinstance(value_type, Scalar):
        return verify_scalar_value_expr(
            bound,
            bindings=type_bindings,
            expected_type=value_type,
        )
    if isinstance(bound, SeriesExpr) and isinstance(value_type, Series):
        return verify_series_value_expr(
            bound,
            bindings=type_bindings,
            expected_type=value_type,
        )
    msg = "resource entity source expression does not match its declared shape"
    raise TypeError(msg)


def require_port_capability(
    ctx: ExperimentAuthoringContext,
    port: ResourcePort,
    capability_id: str,
) -> None:
    if capability_id not in port.selector.capabilities:
        ctx.raise_problem(
            "module_resource_port_capability_missing",
            "resource port "
            f"{port.qualified_id} does not declare capability {capability_id}",
            "resources",
            path=(*port.scope, port.id),
        )


__all__ = [
    "BindingSpec",
    "build_route_intents",
    "lower_binding_intent",
    "ports_by_id",
    "require_port_capability",
]
