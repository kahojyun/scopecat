"""Runtime lowering helpers for transient experiment execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from inspect import Parameter, signature
from typing import Any, Protocol, cast

from scopecat._planning.diagnostics import planning_diagnostic
from scopecat._planning.planner import PlannerPoint, PlannerSnapshot
from scopecat._planning.records import RecordPlan
from scopecat._planning.state import StateRecord
from scopecat.experiments import (
    CollectInstructionPlan,
    ComputeNodeContext,
    ComputeNodeFunction,
    ComputeNodeSpec,
    PointRouteBinding,
    ProductBinding,
    ProgramResourceState,
    ProgramStateField,
    ScalarValueExpr,
    SeriesValueExpr,
    ValueExpr,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.config import ConfigProfileSnapshot, RoutingChannelBinding
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef, StateValue
from scopecat.models.value import ComputeResultRef, PayloadValue
from scopecat.relations import EvalContext, ParameterRelationData
from scopecat.routing import RoutingError, RoutingView


def compile_compute_node_payloads(
    plan: PlannerSnapshot,
    *,
    route_bindings: dict[int, list[PointRouteBinding]],
    compute_payload_schema_ids: dict[str, str],
) -> tuple[
    dict[tuple[int, str], object],
    dict[str, CommandPayload],
    list[dict[str, Any]],
]:
    if not plan.compute_nodes:
        return {}, {}, []
    compute_results: dict[tuple[int, str], object] = {}
    payloads: dict[str, CommandPayload] = {}
    diagnostics: list[dict[str, Any]] = []
    points_by_index = {point.point_index: point for point in plan.points}
    for point_index, point_params in plan.point_parameters.items():
        point = points_by_index.get(point_index)
        if point is None:
            continue
        point_results, point_payloads, point_diagnostics = (
            evaluate_compute_nodes_for_point(
                point=point,
                params=point_params,
                compute_nodes=plan.compute_nodes,
                route_bindings=tuple(route_bindings.get(point_index, ())),
                compute_payload_schema_ids=compute_payload_schema_ids,
                initial_compute_results=compute_results,
            )
        )
        compute_results.update(point_results)
        payloads.update(point_payloads)
        diagnostics.extend(point_diagnostics)
    return compute_results, payloads, diagnostics


def evaluate_compute_nodes_for_point(
    *,
    point: PlannerPoint,
    params: ParameterRelationData,
    compute_nodes: Sequence[ComputeNodeSpec],
    route_bindings: Sequence[PointRouteBinding],
    compute_payload_schema_ids: dict[str, str],
    initial_compute_results: dict[tuple[int, str], object] | None = None,
) -> tuple[
    dict[tuple[int, str], object],
    dict[str, CommandPayload],
    list[dict[str, Any]],
]:
    compute_results: dict[tuple[int, str], object] = dict(initial_compute_results or {})
    point_results: dict[tuple[int, str], object] = {}
    payloads: dict[str, CommandPayload] = {}
    diagnostics: list[dict[str, Any]] = []
    point_routes = tuple(route_bindings)
    for node in compute_nodes:
        try:
            node_inputs = _compute_node_inputs(
                node,
                point=point,
                params=params,
                compute_results=compute_results,
                route_bindings=point_routes,
            )
            if node.fn is None:
                msg = (
                    f"compute node {node.id} has no in-memory function; "
                    "rebuild it from module/template source before execution"
                )
                raise ValueError(msg)
            context = ComputeNodeContext(
                node_id=node.id,
                point_index=point.point_index,
                point_uid=point.point_uid,
                row=point.row,
                params=params,
                inputs=node_inputs,
                routes=tuple(
                    route
                    for route in point_routes
                    if not node.route_ports or route.port_id in node.route_ports
                ),
                payloads=payloads,
            )
            result = _call_compute_node_fn(node.fn, context, node_inputs)
            if result is None:
                msg = f"compute node {node.id} returned None"
                raise ValueError(msg)
            result_key = (point.point_index, node.id)
            compute_results[result_key] = result
            point_results[result_key] = result
            schema_id = compute_payload_schema_ids.get(node.id)
            if schema_id is not None:
                payload = CommandPayload(
                    id=_compute_result_payload_id(node, point.point_index),
                    schema_id=schema_id,
                    metadata={
                        "compute_node_id": node.id,
                        "point_index": point.point_index,
                    },
                    payload=result,
                )
                payloads[payload.id] = payload
        except Exception as error:
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "compute_node_evaluation_failed",
                    (
                        f"compute node {node.id} failed for point "
                        f"{point.point_index}: {type(error).__name__}: {error}"
                    ),
                    f"compute_nodes.{node.id}",
                )
            )
    return point_results, payloads, diagnostics


def _compute_node_inputs(
    node: ComputeNodeSpec,
    *,
    point: PlannerPoint,
    params: ParameterRelationData,
    compute_results: dict[tuple[int, str], object],
    route_bindings: tuple[PointRouteBinding, ...],
) -> dict[str, object]:
    ctx = EvalContext(params=params, row=point.row)
    values: dict[str, object] = {}
    for name, input_spec in node.inputs.items():
        if input_spec.kind == "value":
            values[name] = _evaluate_value_expr(
                _required_value_expr(
                    input_spec.value,
                    f"compute_nodes.{node.id}.inputs.{name}.value",
                ),
                ctx,
            )
            continue
        if input_spec.kind == "compute_result":
            values[name] = compute_results[
                (
                    point.point_index,
                    _required_name(
                        input_spec.node_id,
                        f"compute_nodes.{node.id}.inputs.{name}.node_id",
                    ),
                )
            ]
            continue
        if input_spec.kind == "route":
            values[name] = _required_route_binding(
                route_bindings,
                _required_name(
                    input_spec.port_id,
                    f"compute_nodes.{node.id}.inputs.{name}.port_id",
                ),
            )
            continue
        msg = f"unsupported compute node input kind: {input_spec.kind}"
        raise ValueError(msg)
    return values


def _call_compute_node_fn(
    fn: ComputeNodeFunction,
    context: ComputeNodeContext,
    inputs: dict[str, object],
) -> object:
    if _compute_node_uses_context(fn):
        return fn(context)
    return fn(**inputs)


def _compute_node_uses_context(fn: ComputeNodeFunction) -> bool:
    try:
        parameters = list(signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False
    if len(parameters) != 1:
        return False
    parameter = parameters[0]
    return parameter.name in {"ctx", "context"} and parameter.kind in {
        Parameter.POSITIONAL_ONLY,
        Parameter.POSITIONAL_OR_KEYWORD,
        Parameter.KEYWORD_ONLY,
    }


def _required_route_binding(
    route_bindings: tuple[PointRouteBinding, ...],
    port_id: str,
) -> PointRouteBinding:
    for binding in route_bindings:
        if binding.port_id == port_id:
            return binding
    msg = f"compute node route input references unknown port {port_id!r}"
    raise ValueError(msg)


def runtime_product_binding(record: RecordPlan) -> ProductBinding:
    return ProductBinding(
        record_id=record.id,
        instrument_id=record.resource,
        product_key=_record_product_key(record),
        kind=record.kind,
        capability=record.capability,
        unit=record.unit,
        dtype=record.dtype,
        axes=list(record.axes),
        metadata=dict(record.metadata),
    )


def _record_product_key(record: RecordPlan) -> str:
    if record.product_key:
        return record.product_key
    if record.capability:
        return record.capability
    return record.id


def compile_point_routes(
    plan: PlannerSnapshot,
    *,
    config: ConfigProfileSnapshot | None,
) -> tuple[dict[int, list[PointRouteBinding]], list[dict[str, Any]]]:
    if not plan.route_intents:
        return {}, []
    if config is None:
        return {}, [
            planning_diagnostic(
                "error",
                "runtime_graph_routing_config_required",
                "runtime graph routing requires a config profile snapshot",
                "route_intents",
            )
        ]
    routing = RoutingView.from_config(config)
    bindings: dict[int, list[PointRouteBinding]] = {}
    diagnostics: list[dict[str, Any]] = []
    for point in plan.points:
        point_params = plan.point_parameters.get(
            point.point_index,
            ParameterRelationData(),
        )
        for intent in plan.route_intents:
            entity_values: list[object] = []
            entity_expression_failed = False
            for expression in intent.entity_exprs:
                try:
                    entity_values.append(
                        _evaluate_value_expr(
                            expression,
                            EvalContext(params=point_params, row=point.row),
                        )
                    )
                except Exception as error:
                    entity_expression_failed = True
                    diagnostics.append(
                        planning_diagnostic(
                            "error",
                            "runtime_graph_route_entity_invalid",
                            (
                                f"route {intent.port_id} entity expression failed "
                                f"for point {point.point_index}: {error}"
                            ),
                            f"route_intents.{intent.port_id}",
                        )
                    )
            if entity_expression_failed:
                continue
            try:
                binding = routing.route_point(
                    port_id=intent.port_id,
                    capabilities=intent.capabilities,
                    entity_values=entity_values,
                    resource_id=intent.resource_id,
                )
            except RoutingError as error:
                diagnostics.append(
                    planning_diagnostic(
                        "error",
                        error.code,
                        str(error),
                        f"route_intents.{intent.port_id}",
                    )
                )
                continue
            bindings.setdefault(point.point_index, []).append(
                PointRouteBinding(
                    port_id=binding.port_id,
                    resource_id=binding.resource_id,
                    capabilities=list(binding.capabilities),
                    entity_ids=list(binding.entity_ids),
                    product_axis_order=list(binding.product_axis_order),
                    channel_bindings=list(binding.channel_bindings),
                )
            )
    return bindings, diagnostics


def compile_desired_state_points(
    state_records: list[StateRecord],
    *,
    command_payload_ids: set[str],
    unavailable_compute_payload_node_ids: frozenset[str],
    route_bindings: dict[int, list[PointRouteBinding]],
) -> tuple[dict[int, list[ProgramResourceState]], list[dict[str, Any]]]:
    grouped: dict[tuple[int, str, str], list[ProgramStateField]] = {}
    diagnostics: list[dict[str, Any]] = []
    missing_compute_payload_node_ids: set[str] = set()
    for record in state_records:
        capability_id, separator, field_path = record.field.partition(".")
        if not separator or not capability_id or not field_path:
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "state_field_requires_capability",
                    "state fields must use capability.field syntax",
                    "desired_state.field",
                )
            )
            continue
        value = _state_value(
            record.value,
            point_index=record.point_index,
            command_payload_ids=command_payload_ids,
        )
        if value is None:
            if isinstance(record.value, ComputeResultRef):
                node_id = record.value.node_id
                if node_id in unavailable_compute_payload_node_ids:
                    continue
                if node_id not in missing_compute_payload_node_ids:
                    missing_compute_payload_node_ids.add(node_id)
                    diagnostics.append(
                        planning_diagnostic(
                            "error",
                            "compute_payload_not_materialized",
                            (
                                f"compute payload for node {node_id!r} has no "
                                "command payload"
                            ),
                            "desired_state.value",
                        )
                    )
                continue
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "state_value_unsupported",
                    (
                        "state values must be quantities, numbers, or "
                        "compute-result payload references"
                    ),
                    "desired_state.value",
                )
            )
            continue
        channel_bindings, unbound_entity_ids = _state_field_channel_bindings(
            resource_id=record.resource,
            capability_id=capability_id,
            route_entities=record.route_entities,
            route_bindings=route_bindings.get(record.point_index, []),
        )
        if unbound_entity_ids:
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "state_route_entity_unbound",
                    (
                        f"state route entities are not bound to {record.resource!r} "
                        f"for capability {capability_id!r}: "
                        + ", ".join(unbound_entity_ids)
                    ),
                    "desired_state.route_entities",
                )
            )
            continue
        grouped.setdefault(
            (record.point_index, record.resource, capability_id),
            [],
        ).append(
            ProgramStateField(
                field_path=field_path,
                value=value,
                channel_bindings=channel_bindings,
            )
        )

    desired: dict[int, list[ProgramResourceState]] = {}
    for (point_index, resource_id, capability_id), fields in grouped.items():
        desired.setdefault(point_index, []).append(
            ProgramResourceState(
                resource_id=resource_id,
                capability_id=capability_id,
                fields=fields,
            )
        )
    return desired, diagnostics


def _state_field_channel_bindings(
    *,
    resource_id: str,
    capability_id: str,
    route_entities: Sequence[object],
    route_bindings: Sequence[PointRouteBinding],
) -> tuple[list[RoutingChannelBinding], tuple[str, ...]]:
    if not route_entities:
        return [], ()
    entity_ids = _state_route_entity_ids(route_entities)
    if not entity_ids:
        return [], ()
    selected: dict[str, RoutingChannelBinding] = {}
    for route in route_bindings:
        if route.port_id != resource_id and route.resource_id != resource_id:
            continue
        if capability_id not in route.capabilities:
            continue
        for binding in route.channel_bindings:
            if binding.entity_id in entity_ids:
                selected.setdefault(binding.entity_id, binding)
    return (
        [selected[entity_id] for entity_id in entity_ids if entity_id in selected],
        tuple(entity_id for entity_id in entity_ids if entity_id not in selected),
    )


def _state_route_entity_ids(values: Sequence[object]) -> tuple[str, ...]:
    entity_ids: list[str] = []
    for value in values:
        if isinstance(value, EntityRef):
            if not value.id:
                msg = "state route entity id must be non-empty"
                raise ValueError(msg)
            entity_ids.append(value.id)
        elif isinstance(value, str) and value:
            entity_ids.append(value)
        else:
            msg = f"state route entity must be an entity reference, got {value!r}"
            raise TypeError(msg)
    return tuple(dict.fromkeys(entity_ids))


def compile_collect_instructions(
    *,
    point_indices: list[int],
    product_bindings: list[ProductBinding],
    route_bindings: dict[int, list[PointRouteBinding]],
) -> dict[int, list[CollectInstructionPlan]]:
    instructions: dict[int, list[CollectInstructionPlan]] = {}
    for point_index in point_indices:
        grouped: dict[str | None, list[ProductBinding]] = {}
        for binding in product_bindings:
            resolved = resolve_product_binding_resource(
                binding,
                route_bindings.get(point_index, []),
            )
            grouped.setdefault(resolved.instrument_id, []).append(resolved)
        instructions[point_index] = [
            CollectInstructionPlan(
                point_index=point_index,
                instrument_id=instrument_id,
                products=list(bindings),
            )
            for instrument_id, bindings in grouped.items()
        ]
    return instructions


def normalize_desired_state(
    states: Sequence[ProgramResourceState],
    *,
    point_index: int,
) -> tuple[list[ProgramResourceState], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], dict[str, ProgramStateField]] = {}
    value_signatures: dict[tuple[str, str, str, str], set[str]] = {}
    diagnostics: list[dict[str, Any]] = []
    for state in states:
        group_key = (state.resource_id, state.capability_id)
        fields = grouped.setdefault(group_key, {})
        for field in state.fields:
            channel_signature = _state_channel_signature(field.channel_bindings)
            field_key = (*group_key, field.field_path, channel_signature)
            signature = _state_value_signature(field.value)
            value_signatures.setdefault(field_key, set()).add(signature)
            fields.setdefault(f"{field.field_path}\0{channel_signature}", field)

    for (
        resource_id,
        capability_id,
        field_path,
        _channel_signature,
    ), signatures in sorted(value_signatures.items()):
        if len(signatures) <= 1:
            continue
        diagnostics.append(
            planning_diagnostic(
                "error",
                "runtime_state_field_conflict",
                (
                    f"{resource_id}.{capability_id}.{field_path} receives "
                    f"multiple values at point {point_index}"
                ),
                f"points.{point_index}.desired_state",
            )
        )

    normalized = [
        ProgramResourceState(
            resource_id=resource_id,
            capability_id=capability_id,
            fields=list(fields.values()),
        )
        for (resource_id, capability_id), fields in grouped.items()
    ]
    return normalized, diagnostics


def _state_value_signature(value: StateValue) -> str:
    return value.model_dump_json(round_trip=True)


def _state_channel_signature(bindings: Sequence[RoutingChannelBinding]) -> str:
    return "|".join(
        ":".join(
            (
                binding.entity_id,
                binding.channel_id,
                binding.line_id or "",
                binding.capability or "",
                ",".join(binding.group_ids),
            )
        )
        for binding in bindings
    )


class _RouteConstraintPoint(Protocol):
    point_index: int
    route_bindings: Sequence[PointRouteBinding]


def route_constraint_diagnostics(
    points: Sequence[_RouteConstraintPoint],
    *,
    group_resource_limits: Mapping[str, int | None] | None = None,
    channel_route_port_limits: Mapping[str, int | None] | None = None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    selected_group_resource_limits = group_resource_limits or {}
    selected_channel_route_port_limits = channel_route_port_limits or {}
    for point in points:
        diagnostics.extend(_duplicate_route_port_diagnostics(point))
        diagnostics.extend(
            _shared_group_resource_diagnostics(
                point,
                group_resource_limits=selected_group_resource_limits,
            )
        )
        diagnostics.extend(
            _channel_shared_by_port_diagnostics(
                point,
                channel_route_port_limits=selected_channel_route_port_limits,
            )
        )
    return diagnostics


def _duplicate_route_port_diagnostics(
    point: _RouteConstraintPoint,
) -> list[dict[str, Any]]:
    by_port: dict[str, list[PointRouteBinding]] = {}
    for route in point.route_bindings:
        by_port.setdefault(route.port_id, []).append(route)
    diagnostics: list[dict[str, Any]] = []
    for port_id, bindings in by_port.items():
        signatures = {
            (
                binding.resource_id,
                tuple(binding.capabilities),
                tuple(binding.entity_ids),
                tuple(binding.product_axis_order),
            )
            for binding in bindings
        }
        if len(signatures) <= 1:
            continue
        diagnostics.append(
            planning_diagnostic(
                "error",
                "routing_port_resolved_multiple_bindings",
                (
                    f"route port {port_id} resolved to multiple bindings for "
                    f"point {point.point_index}"
                ),
                f"points.{point.point_index}.route_bindings.{port_id}",
            )
        )
    return diagnostics


def _shared_group_resource_diagnostics(
    point: _RouteConstraintPoint,
    *,
    group_resource_limits: Mapping[str, int | None],
) -> list[dict[str, Any]]:
    by_group: dict[str, set[str]] = {}
    for route in point.route_bindings:
        for binding in route.channel_bindings:
            for group_id in binding.group_ids:
                by_group.setdefault(group_id, set()).add(route.resource_id)
    diagnostics: list[dict[str, Any]] = []
    for group_id, resource_ids in sorted(by_group.items()):
        max_resources = group_resource_limits.get(group_id, 1)
        if max_resources is None or len(resource_ids) <= max_resources:
            continue
        diagnostics.append(
            planning_diagnostic(
                "error",
                "routing_shared_group_resource_conflict",
                (
                    f"shared group {group_id} is used by {len(resource_ids)} "
                    f"resources at point {point.point_index}, above its limit "
                    f"of {max_resources}: {', '.join(sorted(resource_ids))}"
                ),
                f"points.{point.point_index}.route_bindings",
            )
        )
    return diagnostics


def _channel_shared_by_port_diagnostics(
    point: _RouteConstraintPoint,
    *,
    channel_route_port_limits: Mapping[str, int | None],
) -> list[dict[str, Any]]:
    by_channel: dict[str, set[str]] = {}
    for route in point.route_bindings:
        for binding in route.channel_bindings:
            by_channel.setdefault(binding.channel_id, set()).add(route.port_id)
    diagnostics: list[dict[str, Any]] = []
    for channel_id, port_ids in sorted(by_channel.items()):
        max_ports = channel_route_port_limits.get(channel_id, 1)
        if max_ports is None or len(port_ids) <= max_ports:
            continue
        diagnostics.append(
            planning_diagnostic(
                "error",
                "routing_channel_shared_by_ports",
                (
                    f"channel {channel_id} is selected by {len(port_ids)} route "
                    f"ports at point {point.point_index}, above its limit of "
                    f"{max_ports}: {', '.join(sorted(port_ids))}"
                ),
                f"points.{point.point_index}.route_bindings",
            )
        )
    return diagnostics


def resolve_program_state_resources(
    states: list[ProgramResourceState],
    route_bindings: list[PointRouteBinding],
) -> list[ProgramResourceState]:
    return [
        state.model_copy(
            update={
                "resource_id": _resolve_routed_resource(
                    state.resource_id,
                    route_bindings,
                )
            }
        )
        for state in states
    ]


def resolve_product_binding_resource(
    binding: ProductBinding,
    route_bindings: list[PointRouteBinding],
) -> ProductBinding:
    if binding.instrument_id is None:
        return binding
    return binding.model_copy(
        update={
            "instrument_id": _resolve_routed_resource(
                binding.instrument_id,
                route_bindings,
            )
        }
    )


def _resolve_routed_resource(
    resource_id: str,
    route_bindings: list[PointRouteBinding],
) -> str:
    for binding in route_bindings:
        if binding.port_id == resource_id:
            return binding.resource_id
    return resource_id


def _state_value(
    value: object,
    *,
    point_index: int,
    command_payload_ids: set[str],
) -> StateValue | None:
    if isinstance(value, Quantity):
        if not math.isfinite(value.value):
            return None
        return StateValue(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            numeric_value = float(value)
        except OverflowError:
            return None
        if not math.isfinite(numeric_value):
            return None
        return StateValue(numeric_value)
    if isinstance(value, ComputeResultRef):
        payload_id = compute_result_payload_id(value.node_id, point_index)
        if payload_id in command_payload_ids:
            return StateValue(PayloadRef(payload_id=payload_id))
    return None


def _compute_result_payload_id(node: ComputeNodeSpec, point_index: int) -> str:
    return compute_result_payload_id(node.id, point_index)


def compute_result_payload_id(node_id: str, point_index: int) -> str:
    return f"{node_id}.payload.point-{point_index}"


def _evaluate_value_expr(
    value: ValueExpr,
    ctx: EvalContext,
) -> object:
    if isinstance(value, ScalarValueExpr):
        return _unwrap_payload_values(value.expr.eval(ctx))
    if isinstance(value, SeriesValueExpr):
        return _unwrap_payload_values(value.expr.evaluate(ctx))
    return _unwrap_payload_values(value.expr.evaluate_in_context(ctx))


def _unwrap_payload_values(value: object) -> object:
    if isinstance(value, PayloadValue):
        return value.payload
    if isinstance(value, list):
        items = cast("list[object]", value)
        return [_unwrap_payload_values(item) for item in items]
    if isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        return tuple(_unwrap_payload_values(item) for item in items)
    if isinstance(value, dict):
        mapping = cast("Mapping[object, object]", value)
        return {name: _unwrap_payload_values(item) for name, item in mapping.items()}
    return value


def _required_value_expr(value: ValueExpr | None, path: str) -> ValueExpr:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_name(value: str | None, path: str) -> str:
    if not value:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


__all__ = [
    "compile_collect_instructions",
    "compile_compute_node_payloads",
    "compile_desired_state_points",
    "compile_point_routes",
    "compute_result_payload_id",
    "evaluate_compute_nodes_for_point",
    "normalize_desired_state",
    "resolve_program_state_resources",
    "route_constraint_diagnostics",
    "runtime_product_binding",
]
