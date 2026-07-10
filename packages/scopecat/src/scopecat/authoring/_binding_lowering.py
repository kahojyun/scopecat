from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat._compiler.program import ResourceRouteIntent
from scopecat._compute_result import ComputeResultRef
from scopecat._relations import (
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
)
from scopecat._value_expressions import as_scalar_or_series_value_expr
from scopecat.authoring._binding_intents import (
    BindingIntent,
    ResourcePort,
)
from scopecat.authoring._context import ExperimentAuthoringContext
from scopecat.authoring._value_binding import bind_value_input_refs
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_source_kind,
)
from scopecat.models.entity import EntityRef
from scopecat.value_types import Entity, Scalar, Series


@dataclass(frozen=True)
class BindingSpec:
    """Private compiler-ready desired-state binding."""

    resource_id: str
    capability_id: str
    field_path: str
    value: ScalarExpr | ComputeResultRef


def lower_binding_intent(
    intent: BindingIntent,
    ctx: ExperimentAuthoringContext,
    resource_ports: Mapping[str, ResourcePort],
) -> BindingSpec:
    """Lower one source binding after config-dependent port validation."""

    port_id, capability_id, field_path = _parse_port_path(ctx, intent.port_path)
    resource_port = resource_ports.get(port_id)
    if resource_port is None:
        ctx.raise_diagnostic(
            "module_unknown_resource_port",
            f"binding references unknown resource port {port_id}",
            "bindings",
        )
    require_port_capability(ctx, resource_port, capability_id)
    value = intent.value
    if isinstance(value, ValueRef):
        value = internal_lower_value_ref(value)
        if not isinstance(value, ScalarExpr | ComputeResultRef):
            msg = "state binding value must be scalar-shaped"
            raise TypeError(msg)
    return BindingSpec(
        resource_id=port_id,
        capability_id=capability_id,
        field_path=field_path,
        value=value if isinstance(value, ComputeResultRef) else as_scalar_expr(value),
    )


def build_route_intents(
    ctx: ExperimentAuthoringContext,
    ports: Sequence[ResourcePort],
    *,
    inputs: Mapping[str, object],
) -> list[ResourceRouteIntent]:
    route_intents: list[ResourceRouteIntent] = []
    for port in ports:
        route_intents.append(
            ResourceRouteIntent(
                port_id=port.id,
                capabilities=list(port.selector.capabilities),
                entity_exprs=[
                    as_scalar_or_series_value_expr(
                        _route_entity_expr(ctx, input_id, inputs)
                    )
                    for input_id in port.selector.entity_inputs
                ],
                resource_id=None,
            )
        )
    return route_intents


def ports_by_id(
    ctx: ExperimentAuthoringContext,
    ports: Sequence[ResourcePort],
) -> dict[str, ResourcePort]:
    result: dict[str, ResourcePort] = {}
    for port in ports:
        if port.id in result:
            ctx.raise_diagnostic(
                "module_resource_port_duplicate",
                f"duplicate resource port {port.id}",
                f"resources.{port.id}",
            )
        result[port.id] = port
    return result


def _route_entity_expr(
    ctx: ExperimentAuthoringContext,
    source: ValueRef,
    inputs: Mapping[str, object],
) -> ScalarExpr | SeriesExpr:
    value_type = source.value_type
    is_entity_value = (
        isinstance(value_type, Scalar) and isinstance(value_type.atom, Entity)
    ) or (
        isinstance(value_type, Series) and isinstance(value_type.item_type.atom, Entity)
    )
    if not is_entity_value or internal_value_ref_source_kind(source) == "compute":
        ctx.raise_diagnostic(
            "module_resource_entity_input_invalid",
            "resource entity source must be a non-compute entity value",
            "resources",
        )
    lowered = internal_lower_value_ref(source)
    if not isinstance(lowered, ScalarExpr | SeriesExpr):
        ctx.raise_diagnostic(
            "module_resource_entity_input_invalid",
            "resource entity source must be scalar or series-shaped",
            "resources",
        )
    bound = bind_value_input_refs(lowered, inputs)
    if not isinstance(bound, ScalarExpr | SeriesExpr):
        ctx.raise_diagnostic(
            "module_resource_entity_input_invalid",
            "resource entity source must be scalar or series-shaped",
            "resources",
        )
    if isinstance(bound, ScalarExpr) and bound.kind == "literal":
        return bound.model_copy(
            update={"value": ctx.require_entity(cast("EntityRef | str", bound.value))}
        )
    if isinstance(bound, SeriesExpr) and bound.kind == "values":
        return bound.model_copy(
            update={
                "items": list(
                    ctx.require_entities(
                        cast("Sequence[EntityRef | str]", bound.items or ())
                    )
                )
            }
        )
    return bound


def require_port_capability(
    ctx: ExperimentAuthoringContext,
    port: ResourcePort,
    capability_id: str,
) -> None:
    if port.selector.capabilities and capability_id not in port.selector.capabilities:
        ctx.raise_diagnostic(
            "module_resource_port_capability_missing",
            f"resource port {port.id} does not declare capability {capability_id}",
            f"resources.{port.id}",
        )


def _parse_port_path(
    ctx: ExperimentAuthoringContext,
    port_path: str,
) -> tuple[str, str, str]:
    parts = port_path.split(".")
    if len(parts) < 3:
        ctx.raise_diagnostic(
            "module_binding_path_invalid",
            "binding path must be '<port>.<capability>.<field>'",
            "bindings",
        )
    return parts[0], parts[1], ".".join(parts[2:])


__all__ = [
    "BindingSpec",
    "build_route_intents",
    "lower_binding_intent",
    "ports_by_id",
    "require_port_capability",
]
