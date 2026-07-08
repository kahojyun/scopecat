from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.authoring.context import ExperimentAuthoringContext
from scopecat.authoring.expressions import (
    BindingSpec,
    Expression,
)
from scopecat.authoring.expressions import (
    bind as spec_bind,
)
from scopecat.experiments import ResourceRouteIntent
from scopecat.models.entity import EntityArray, EntityRef, entity_array
from scopecat.models.parameter import Quantity
from scopecat.relations import ScalarExpr, col


@dataclass(frozen=True)
class ResourceSelector:
    capabilities: tuple[str, ...] = ()
    entity_inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourcePort:
    id: str
    selector: ResourceSelector


@dataclass(frozen=True)
class BindingIntent:
    port_path: str
    value: Expression | ScalarExpr | Quantity | float

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        resource_ports: Mapping[str, ResourcePort],
    ) -> BindingSpec:
        port_id, capability_id, field_path = _parse_port_path(ctx, self.port_path)
        resource_port = resource_ports.get(port_id)
        if resource_port is None:
            ctx.raise_diagnostic(
                "module_unknown_resource_port",
                f"binding references unknown resource port {port_id}",
                "bindings",
            )
        _require_port_capability(ctx, resource_port, capability_id)
        return spec_bind(
            port_id,
            capability_id,
            field_path,
            self.value,
        )


ExperimentBindingIntent = BindingIntent


def requires(
    *capabilities: str,
    for_entities: Sequence[str] = (),
) -> ResourceSelector:
    return ResourceSelector(
        capabilities=tuple(capabilities),
        entity_inputs=tuple(for_entities),
    )


def resource_port(
    id: str,  # noqa: A002
    selector: ResourceSelector,
) -> ResourcePort:
    return ResourcePort(id=id, selector=selector)


def bind(
    port_path: str,
    value: Expression | ScalarExpr | Quantity | float,
) -> BindingIntent:
    return BindingIntent(port_path=port_path, value=value)


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
                    _route_entity_expr(ctx, input_id, inputs)
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
    input_id: str,
    inputs: Mapping[str, object],
) -> ScalarExpr:
    if input_id not in inputs:
        return col(input_id)
    value = inputs[input_id]
    if isinstance(value, str) and value:
        return ScalarExpr(kind="literal", value=ctx.require_entity(value))
    if isinstance(value, EntityRef):
        return ScalarExpr(kind="literal", value=ctx.require_entity(value))
    if isinstance(value, EntityArray):
        return ScalarExpr(kind="literal", value=ctx.require_entity_array(value))
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        selected = entity_array(cast("Sequence[EntityRef | str]", value))
        return ScalarExpr(
            kind="literal",
            value=ctx.require_entity_array(selected),
        )
    ctx.raise_diagnostic(
        "module_resource_entity_input_invalid",
        f"resource entity input {input_id} must be an entity or entity array",
        f"inputs.{input_id}",
    )


def _require_port_capability(
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
