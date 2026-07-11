"""Bind a typed program to one validated configuration environment."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

from scopecat._compiler.bound import (
    BoundAxis,
    BoundCollect,
    BoundComputeCall,
    BoundComputeOutput,
    BoundPlan,
    BoundPoint,
    BoundProduct,
    BoundRecord,
    BoundResourceState,
    BoundRoute,
    BoundStateField,
    BoundValue,
    PlannedStateChange,
)
from scopecat._compiler.dependencies import (
    ComputeDependencies,
    analyze_compute_dependencies,
)
from scopecat._compiler.diagnostics import CompilerDiagnosticError
from scopecat._compiler.environment import ValidatedConfigEnvironment
from scopecat._compiler.ids import NodeId
from scopecat._compiler.parameter_overlays import apply_point_parameter_overlay
from scopecat._compiler.program import (
    ComputeEdge,
    TypedComputeNode,
    TypedProgram,
    ValueInput,
)
from scopecat._compiler.records import (
    RecordAxisPlan,
    RecordPlan,
    expected_dataset_schema,
    plan_records,
    point_coordinate_ids,
    validate_record_plan,
)
from scopecat._compiler.route_constraints import validate_route_constraints
from scopecat._compiler.state import StateRecord
from scopecat._compute_result import ComputeResultRef
from scopecat._content_identity import content_fingerprint, stable_content_hash
from scopecat._relations import EvalContext, ParameterRelationData, Row
from scopecat._value_expressions import ScalarValueExpr, SeriesValueExpr, ValueExpr
from scopecat.compute_values import ResolvedRoute
from scopecat.diagnostics import Diagnostic
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef, StateValue
from scopecat.models.value import PayloadValue
from scopecat.value_types import Scalar
from scopecat.value_validation import (
    ValueValidationError,
    coerce_literal,
)

type _ChannelBindingIdentity = tuple[
    str,
    str,
    str | None,
    str | None,
    tuple[str, ...],
]
type _ChannelSignature = tuple[_ChannelBindingIdentity, ...]


def bind_program(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
) -> BoundPlan:
    """Produce the single config-bound plan used by preview and execution."""

    diagnostics = list(environment.diagnostics)
    if not environment.valid or environment.routing is None:
        return _empty_plan(program, diagnostics)

    rows = _materialize_point_rows(program, environment, diagnostics)
    planner_points = [_Point(index, row) for index, row in enumerate(rows)]
    coordinate_schema_valid = True
    try:
        coordinate_ids = tuple(point_coordinate_ids(planner_points))
    except ValueError as error:
        coordinate_schema_valid = False
        coordinate_ids = ()
        diagnostics.append(
            _diagnostic(
                "experiment_point_schema_invalid",
                f"experiment point schema is invalid: {error}",
                "points",
            )
        )
    record_plans = plan_records(program.records, point_count=len(planner_points))
    record_diagnostics = _as_diagnostics(
        validate_record_plan(record_plans, coordinate_ids=coordinate_ids)
    )
    diagnostics.extend(record_diagnostics)

    state_records: list[StateRecord] = []
    point_parameters: dict[int, ParameterRelationData] = {}
    compute_dependencies = analyze_compute_dependencies(program.compute_nodes)

    for point in planner_points:
        params = _point_parameters(
            environment.parameters,
            program=program,
            point=point,
            diagnostics=diagnostics,
        )
        if params is None:
            continue
        point_parameters[point.point_index] = params
        ctx = EvalContext(params=params, row=point.row)
        for state_index, state in enumerate(program.state):
            try:
                state_records.extend(
                    state.evaluate(point_index=point.point_index, ctx=ctx)
                )
            except Exception as error:
                diagnostics.append(
                    _diagnostic(
                        "experiment_state_evaluation_failed",
                        f"state binding failed for point {point.point_index}: {error}",
                        f"state.{state_index}",
                    )
                )
    if len(point_parameters) != len(planner_points):
        return _empty_plan(program, diagnostics)
    routes_by_point = _bind_routes(
        program,
        environment,
        planner_points,
        point_parameters,
        diagnostics,
    )
    diagnostics.extend(
        validate_route_constraints(routes_by_point, config=environment.config)
    )
    state_by_point: dict[int, list[StateRecord]] = {}
    for record in state_records:
        state_by_point.setdefault(record.point_index, []).append(record)

    schema = None
    if coordinate_schema_valid and not any(
        diagnostic.severity in {"error", "blocker"} for diagnostic in record_diagnostics
    ):
        try:
            schema = expected_dataset_schema(
                experiment_id=program.id,
                points=planner_points,
                records=record_plans,
            )
        except ValueError as error:
            diagnostics.append(
                _diagnostic(
                    "experiment_dataset_schema_invalid",
                    f"experiment output schema is invalid: {error}",
                    "records",
                )
            )
    bound_records = tuple(_bound_record(record) for record in record_plans)
    occurrences: dict[str, int] = {}
    bound_points: list[BoundPoint] = []
    previous_state: dict[tuple[str, str, _ChannelSignature], object] = {}
    state_changes: list[PlannedStateChange] = []

    for point in planner_points:
        params = point_parameters.get(point.point_index)
        if params is None:
            continue
        routes = tuple(routes_by_point.get(point.point_index, ()))
        point_state_records = tuple(state_by_point.get(point.point_index, ()))
        demanded_payload_nodes = {
            value.node_id
            for state in point_state_records
            if isinstance((value := state.value), ComputeResultRef)
        }
        compute, payload_ids = _bind_compute_calls(
            program.compute_nodes,
            point=point,
            params=params,
            routes=routes,
            dependencies=compute_dependencies,
            demanded_payload_nodes=demanded_payload_nodes,
            diagnostics=diagnostics,
        )
        desired = _bind_desired_state(
            point_state_records,
            routes=routes,
            payload_ids=payload_ids,
            known_compute_nodes={node.id for node in program.compute_nodes},
            point_index=point.point_index,
            diagnostics=diagnostics,
        )
        collect = _bind_collect(record_plans, routes)
        _validate_collect_products(
            collect,
            records=record_plans,
            point_index=point.point_index,
            diagnostics=diagnostics,
        )
        for resource in desired:
            for field in resource.fields:
                field_name = f"{resource.capability_id}.{field.field_path}"
                key = (
                    resource.resource_id,
                    field_name,
                    _channel_signature(field.channel_bindings),
                )
                before = previous_state.get(key)
                if before != field.value:
                    state_changes.append(
                        PlannedStateChange(
                            point_index=point.point_index,
                            resource=resource.resource_id,
                            field=field_name,
                            before=before,
                            after=field.value,
                        )
                    )
                previous_state[key] = field.value
        try:
            point_key = stable_content_hash(content_fingerprint(point.row))
        except Exception as error:
            diagnostics.append(
                _diagnostic(
                    "experiment_point_identity_failed",
                    f"point {point.point_index} has no stable identity: {error}",
                    f"points.{point.point_index}",
                )
            )
            return _empty_plan(program, diagnostics)
        occurrence = occurrences.get(point_key, 0)
        occurrences[point_key] = occurrence + 1
        point_uid = stable_content_hash(
            {"point_key": point_key, "occurrence": occurrence}
        )
        bound_points.append(
            BoundPoint(
                point_index=point.point_index,
                point_key=point_key,
                point_uid=point_uid,
                occurrence=occurrence,
                row=dict(point.row),
                parameters=params,
                coordinates=cast(
                    "dict[str, Any]",
                    {
                        name: value
                        for name, value in point.row.items()
                        if name in coordinate_ids
                    },
                ),
                compute=compute,
                routes=routes,
                desired_state=desired,
                collect=collect,
            )
        )

    return BoundPlan(
        experiment_id=program.id,
        experiment_kind=program.kind,
        point_coordinate_ids=coordinate_ids,
        points=tuple(bound_points),
        records=bound_records,
        route_intents=program.route_intents,
        state_changes=tuple(state_changes),
        expected_dataset_schema=schema,
        diagnostics=tuple(diagnostics),
    )


class _Point:
    def __init__(self, point_index: int, row: Row) -> None:
        self.point_index = point_index
        self.row = row


def _empty_plan(program: TypedProgram, diagnostics: Sequence[Diagnostic]) -> BoundPlan:
    return BoundPlan(
        experiment_id=program.id,
        experiment_kind=program.kind,
        point_coordinate_ids=(),
        points=(),
        records=(),
        route_intents=program.route_intents,
        state_changes=(),
        expected_dataset_schema=None,
        diagnostics=tuple(diagnostics),
    )


def _materialize_point_rows(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
    diagnostics: list[Diagnostic],
) -> list[Row]:
    try:
        rows = program.point_source.expr.evaluate(environment.parameters)
    except Exception as error:
        diagnostics.append(
            _diagnostic(
                "experiment_points_evaluation_failed",
                f"experiment point relation failed: {error}",
                "points",
            )
        )
        return []

    try:
        typed_rows = cast(
            "tuple[dict[str, object], ...]",
            coerce_literal(
                program.point_source.value_type,
                rows,
                path="points",
            ),
        )
    except ValueValidationError as error:
        diagnostics.append(
            _diagnostic(
                "module_point_value_type_mismatch",
                str(error),
                error.path,
            )
        )
        return []

    entity_columns = set(program.point_source.entity_column_ids)
    materialized: list[Row] = []
    for row in typed_rows:
        selected = cast("Row", dict(row))
        for column_id in entity_columns:
            value = selected.get(column_id)
            if value is None:
                continue
            entity = _resolve_entity(value, environment, diagnostics)
            if entity is not None:
                selected[column_id] = entity
        materialized.append(selected)
    try:
        normalized_rows = cast(
            "tuple[dict[str, object], ...]",
            coerce_literal(
                program.point_source.value_type,
                materialized,
                path="points",
            ),
        )
    except ValueValidationError as error:
        diagnostics.append(
            _diagnostic(
                "module_point_value_type_mismatch",
                str(error),
                error.path,
            )
        )
        return []
    return [cast("Row", dict(row)) for row in normalized_rows]


def _resolve_entity(
    value: object,
    environment: ValidatedConfigEnvironment,
    diagnostics: list[Diagnostic],
) -> EntityRef | None:
    selected = value if isinstance(value, EntityRef) else EntityRef(id=str(value))
    known = environment.config.topology.entity(selected.id)
    if known is None:
        diagnostics.append(
            _diagnostic(
                "unknown_authoring_entity",
                f"experiment references unknown entity {selected.id}",
                "entity",
            )
        )
        return None
    if (
        selected.kind is not None
        and known.kind is not None
        and selected.kind != known.kind
    ):
        diagnostics.append(
            _diagnostic(
                "authoring_entity_kind_mismatch",
                f"entity {selected.id} has kind {known.kind}, not {selected.kind}",
                "entity",
            )
        )
        return None
    return EntityRef(
        id=selected.id,
        kind=selected.kind or known.kind,
        metadata={**known.metadata, **selected.metadata},
    )


def _point_parameters(
    base: ParameterRelationData,
    *,
    program: TypedProgram,
    point: _Point,
    diagnostics: list[Diagnostic],
) -> ParameterRelationData | None:
    if not program.parameter_overlays:
        return base
    touched_tables = {overlay.table_id for overlay in program.parameter_overlays}
    params = ParameterRelationData.model_construct(
        scalars=base.scalars,
        series=base.series,
        tables={
            table_id: (
                [dict(row) for row in rows] if table_id in touched_tables else rows
            )
            for table_id, rows in base.tables.items()
        },
    )
    ctx = EvalContext(params=params, row=point.row)
    failed = False
    for index, overlay in enumerate(program.parameter_overlays):
        try:
            apply_point_parameter_overlay(overlay, ctx=ctx, params=params)
        except CompilerDiagnosticError as error:
            failed = True
            diagnostics.append(_diagnostic(error.code, str(error), f"overlays.{index}"))
        except Exception as error:
            failed = True
            diagnostics.append(
                _diagnostic(
                    "experiment_parameter_overlay_failed",
                    f"parameter overlay failed for point {point.point_index}: {error}",
                    f"overlays.{index}",
                )
            )
    return None if failed else params


def _bind_routes(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
    points: Sequence[_Point],
    point_parameters: Mapping[int, ParameterRelationData],
    diagnostics: list[Diagnostic],
) -> dict[int, tuple[BoundRoute, ...]]:
    routing = environment.routing
    if routing is None:
        return {}
    routes: dict[int, tuple[BoundRoute, ...]] = {}
    for point in points:
        params = point_parameters.get(point.point_index)
        if params is None:
            continue
        selected: list[BoundRoute] = []
        for intent in program.route_intents:
            ctx = EvalContext(params=params, row=point.row)
            entity_values: list[object] = []
            failed = False
            for expression in intent.entity_exprs:
                try:
                    entity_values.append(_evaluate_value_expr(expression, ctx))
                except Exception as error:
                    failed = True
                    diagnostics.append(
                        _diagnostic(
                            "experiment_route_entity_evaluation_failed",
                            f"route {intent.port_id} entity expression failed for "
                            f"point {point.point_index}: {error}",
                            f"routes.{intent.port_id}",
                        )
                    )
            if failed:
                continue
            try:
                binding = routing.route_point(
                    port_id=intent.port_id,
                    capabilities=list(intent.capabilities),
                    entity_values=entity_values,
                    resource_id=intent.resource_id,
                )
            except Exception as error:
                diagnostics.append(
                    _diagnostic(
                        getattr(error, "code", "routing_failed"),
                        str(error),
                        f"routes.{intent.port_id}",
                    )
                )
                continue
            selected.append(
                BoundRoute(
                    port_id=binding.port_id,
                    resource_id=binding.resource_id,
                    capabilities=tuple(binding.capabilities),
                    entity_ids=tuple(binding.entity_ids),
                    product_axis_order=tuple(binding.product_axis_order),
                    channel_bindings=tuple(binding.channel_bindings),
                )
            )
        routes[point.point_index] = tuple(selected)
    return routes


def _bind_compute_calls(
    nodes: Sequence[TypedComputeNode],
    *,
    point: _Point,
    params: ParameterRelationData,
    routes: Sequence[BoundRoute],
    dependencies: Mapping[NodeId, ComputeDependencies],
    demanded_payload_nodes: set[NodeId],
    diagnostics: list[Diagnostic],
) -> tuple[tuple[BoundComputeCall, ...], dict[NodeId, str]]:
    calls: list[BoundComputeCall] = []
    signatures: dict[NodeId, str] = {}
    payload_ids: dict[NodeId, str] = {}
    ctx = EvalContext(params=params, row=point.row)
    for node in nodes:
        inputs: dict[str, BoundValue | BoundComputeOutput] = {}
        signature_inputs: dict[str, object] = {}
        failed = False
        for name, input_spec in node.inputs.items():
            try:
                if isinstance(input_spec, ValueInput):
                    value = _unwrap_payload_values(
                        coerce_literal(
                            input_spec.value_type,
                            _evaluate_value_expr(input_spec.value, ctx),
                            path=f"compute.{node.id}.{name}",
                        )
                    )
                    inputs[name] = BoundValue(value)
                    signature_inputs[name] = content_fingerprint(value)
                elif isinstance(input_spec, ComputeEdge):
                    upstream_signature = signatures.get(input_spec.producer)
                    if upstream_signature is None:
                        msg = f"producer {input_spec.producer} is not available"
                        raise ValueError(msg)
                    inputs[name] = BoundComputeOutput(input_spec.producer)
                    signature_inputs[name] = {"compute": upstream_signature}
                else:
                    route = next(
                        (
                            route
                            for route in routes
                            if route.port_id == input_spec.port_id
                        ),
                        None,
                    )
                    if route is None:
                        msg = f"route port {input_spec.port_id!r} is not bound"
                        raise ValueError(msg)
                    missing = set(input_spec.value_type.capabilities) - set(
                        route.capabilities
                    )
                    if missing:
                        msg = "route is missing capabilities: " + ", ".join(
                            sorted(missing)
                        )
                        raise ValueError(msg)
                    resolved = ResolvedRoute(
                        port_id=route.port_id,
                        resource_id=route.resource_id,
                        capabilities=route.capabilities,
                        entity_ids=route.entity_ids,
                        product_axis_order=route.product_axis_order,
                    )
                    inputs[name] = BoundValue(resolved)
                    signature_inputs[name] = content_fingerprint(resolved)
            except Exception as error:
                failed = True
                diagnostics.append(
                    _diagnostic(
                        "compute_node_input_binding_failed",
                        f"compute node {node.id} input {name!r} failed: {error}",
                        f"compute.{node.id}.{name}",
                    )
                )
        if failed:
            continue
        if node.fn is None:
            diagnostics.append(
                _diagnostic(
                    "compute_node_function_missing",
                    f"compute node {node.id} has no in-memory function",
                    f"compute.{node.id}",
                )
            )
            continue
        signature = stable_content_hash(
            {
                "node": node.id.qualified_name,
                "inputs": signature_inputs,
            }
        )
        signatures[node.id] = signature
        schema_id = (
            _payload_schema(node.output_type)
            if node.id in demanded_payload_nodes
            else None
        )
        payload_id = (
            f"{node.id.qualified_name}.payload.{signature}"
            if schema_id is not None
            else None
        )
        if payload_id is not None:
            payload_ids[node.id] = payload_id
        calls.append(
            BoundComputeCall(
                node_id=node.id,
                fn=node.fn,
                inputs=inputs,
                output_type=node.output_type,
                cache_key=signature,
                dependencies=dict(dependencies[node.id].as_mapping()),
                payload_id=payload_id,
                payload_schema_id=schema_id,
            )
        )
    return tuple(calls), payload_ids


def _payload_schema(value_type: object) -> str | None:
    from scopecat.value_types import Payload

    if isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload):
        return value_type.atom.schema_id
    return None


def _bind_desired_state(
    records: Sequence[StateRecord],
    *,
    routes: Sequence[BoundRoute],
    payload_ids: Mapping[NodeId, str],
    known_compute_nodes: set[NodeId],
    point_index: int,
    diagnostics: list[Diagnostic],
) -> tuple[BoundResourceState, ...]:
    grouped: dict[
        tuple[str, str],
        dict[tuple[str, _ChannelSignature], BoundStateField],
    ] = {}
    signatures: dict[tuple[str, str, str, _ChannelSignature], set[str]] = {}
    for record in records:
        capability_id, separator, field_path = record.field.partition(".")
        if not separator or not capability_id or not field_path:
            diagnostics.append(
                _diagnostic(
                    "state_field_requires_capability",
                    "state fields must use capability.field syntax",
                    "desired_state.field",
                )
            )
            continue
        if isinstance(record.value, ComputeResultRef):
            if record.value.node_id not in known_compute_nodes:
                diagnostics.append(
                    _diagnostic(
                        "compute_payload_unknown_node",
                        "state references unknown compute node "
                        f"{record.value.node_id.qualified_name!r}",
                        "desired_state.value",
                    )
                )
                continue
            if record.value.node_id not in payload_ids:
                diagnostics.append(
                    _diagnostic(
                        "compute_payload_unavailable",
                        "state compute output is not an available payload: "
                        f"{record.value.node_id.qualified_name!r}",
                        "desired_state.value",
                    )
                )
                continue
        state_value = _state_value(record.value, payload_ids=payload_ids)
        if state_value is None:
            diagnostics.append(
                _diagnostic(
                    "state_value_unsupported",
                    "state values must be finite numbers, quantities, "
                    "or payload outputs",
                    "desired_state.value",
                )
            )
            continue
        resource_id = _resolved_resource(record.resource, routes)
        channel_bindings, unbound = _state_channel_bindings(
            resource_id=resource_id,
            port_id=record.resource,
            capability_id=capability_id,
            route_entities=record.route_entities,
            routes=routes,
        )
        if unbound:
            diagnostics.append(
                _diagnostic(
                    "state_route_entity_unbound",
                    "state route entities are not bound: " + ", ".join(unbound),
                    "desired_state.route_entities",
                )
            )
            continue
        channel_key = _channel_signature(channel_bindings)
        group = grouped.setdefault((resource_id, capability_id), {})
        key = (field_path, channel_key)
        signature_key = (resource_id, capability_id, field_path, channel_key)
        signatures.setdefault(signature_key, set()).add(state_value.model_dump_json())
        group.setdefault(
            key,
            BoundStateField(
                field_path=field_path,
                value=state_value,
                channel_bindings=channel_bindings,
            ),
        )
    for (resource, capability, field_path, _channel), values in signatures.items():
        if len(values) > 1:
            diagnostics.append(
                _diagnostic(
                    "experiment_conflicting_desired_state",
                    f"{resource}.{capability}.{field_path} receives multiple values "
                    f"at point {point_index}",
                    f"points.{point_index}.desired_state",
                )
            )
    return tuple(
        BoundResourceState(
            resource_id=resource,
            capability_id=capability,
            fields=tuple(fields.values()),
        )
        for (resource, capability), fields in grouped.items()
    )


def _state_value(
    value: object,
    *,
    payload_ids: Mapping[NodeId, str],
) -> StateValue | None:
    if isinstance(value, ComputeResultRef):
        payload_id = payload_ids.get(value.node_id)
        return StateValue(PayloadRef(payload_id=payload_id)) if payload_id else None
    if isinstance(value, Quantity):
        return StateValue(value) if math.isfinite(value.value) else None
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return StateValue(float(value))
        except (OverflowError, ValueError):
            return None
    return None


def _resolved_resource(resource_or_port: str, routes: Sequence[BoundRoute]) -> str:
    for route in routes:
        if route.port_id == resource_or_port:
            return route.resource_id
    return resource_or_port


def _state_channel_bindings(
    *,
    resource_id: str,
    port_id: str,
    capability_id: str,
    route_entities: Sequence[object],
    routes: Sequence[BoundRoute],
) -> tuple[tuple[RoutingChannelBinding, ...], tuple[str, ...]]:
    if not route_entities:
        unscoped_bindings: list[RoutingChannelBinding] = []
        seen_unscoped: set[_ChannelBindingIdentity] = set()
        for route in routes:
            if route.port_id != port_id:
                continue
            if capability_id not in route.capabilities:
                continue
            for binding in route.channel_bindings:
                if (
                    binding.capability is not None
                    and binding.capability != capability_id
                ):
                    continue
                key = (
                    binding.entity_id,
                    binding.channel_id,
                    binding.line_id,
                    binding.capability,
                    tuple(binding.group_ids),
                )
                if key in seen_unscoped:
                    continue
                seen_unscoped.add(key)
                unscoped_bindings.append(binding)
        return tuple(unscoped_bindings), ()
    entity_ids = tuple(
        dict.fromkeys(
            value.id if isinstance(value, EntityRef) else str(value)
            for value in route_entities
        )
    )
    selected: dict[str, list[RoutingChannelBinding]] = {}
    seen_scoped: set[_ChannelBindingIdentity] = set()
    for route in routes:
        if route.port_id != port_id and route.resource_id != resource_id:
            continue
        if capability_id not in route.capabilities:
            continue
        for binding in route.channel_bindings:
            if binding.entity_id not in entity_ids:
                continue
            if binding.capability is not None and binding.capability != capability_id:
                continue
            identity = _channel_binding_identity(binding)
            if identity in seen_scoped:
                continue
            seen_scoped.add(identity)
            selected.setdefault(binding.entity_id, []).append(binding)
    return (
        tuple(
            binding
            for entity_id in entity_ids
            for binding in selected.get(entity_id, ())
        ),
        tuple(entity_id for entity_id in entity_ids if entity_id not in selected),
    )


def _channel_binding_identity(
    binding: RoutingChannelBinding,
) -> _ChannelBindingIdentity:
    return (
        binding.entity_id,
        binding.channel_id,
        binding.line_id,
        binding.capability,
        tuple(binding.group_ids),
    )


def _channel_signature(
    bindings: Sequence[RoutingChannelBinding],
) -> _ChannelSignature:
    return tuple(_channel_binding_identity(binding) for binding in bindings)


def _bind_collect(
    records: Sequence[RecordPlan],
    routes: Sequence[BoundRoute],
) -> tuple[BoundCollect, ...]:
    grouped: dict[str | None, list[BoundProduct]] = {}
    for record in records:
        if record.source != "instrument":
            continue
        instrument_id = (
            _resolved_resource(record.resource, routes)
            if record.resource is not None
            else None
        )
        product = BoundProduct(
            record_id=record.id,
            instrument_id=instrument_id,
            product_key=record.product_key or record.capability or record.id,
            kind=record.kind,
            capability=record.capability,
            unit=record.unit,
            dtype=record.dtype,
            axes=tuple(_bound_axis(axis) for axis in record.axes),
            metadata=dict(record.metadata),
        )
        grouped.setdefault(instrument_id, []).append(product)
    return tuple(
        BoundCollect(instrument_id=instrument_id, products=tuple(products))
        for instrument_id, products in grouped.items()
    )


def _validate_collect_products(
    collects: Sequence[BoundCollect],
    *,
    records: Sequence[RecordPlan],
    point_index: int,
    diagnostics: list[Diagnostic],
) -> None:
    for collect in collects:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for product in collect.products:
            if product.product_key in seen:
                duplicates.add(product.product_key)
            seen.add(product.product_key)
        for product_key in sorted(duplicates):
            duplicate_record_ids = {
                product.record_id
                for product in collect.products
                if product.product_key == product_key
            }
            symbolic_resources = {
                record.resource
                for record in records
                if record.id in duplicate_record_ids
            }
            if len(symbolic_resources) <= 1:
                # The symbolic record pass already reports duplicates that do
                # not arise specifically from route resolution.
                continue
            instrument = collect.instrument_id or "broadcast instruments"
            diagnostics.append(
                _diagnostic(
                    "experiment_record_product_duplicate",
                    f"instrument {instrument!r} receives product {product_key!r} "
                    f"more than once at point {point_index}",
                    f"points.{point_index}.records",
                )
            )
    broadcast_keys = {
        product.product_key
        for collect in collects
        if collect.instrument_id is None
        for product in collect.products
    }
    for collect in collects:
        if collect.instrument_id is None:
            continue
        explicit_keys = {product.product_key for product in collect.products}
        for product_key in sorted(broadcast_keys & explicit_keys):
            diagnostics.append(
                _diagnostic(
                    "experiment_record_product_duplicate",
                    f"instrument {collect.instrument_id!r} receives broadcast and "
                    f"explicit product {product_key!r} at point {point_index}",
                    f"points.{point_index}.records",
                )
            )


def _bound_record(record: RecordPlan) -> BoundRecord:
    return BoundRecord(
        id=record.id,
        kind=record.kind,
        source=record.source,
        resource=record.resource,
        capability=record.capability,
        product_key=record.product_key,
        unit=record.unit,
        dtype=record.dtype,
        axes=tuple(_bound_axis(axis) for axis in record.axes),
        dims=tuple(record.dims),
        shape=tuple(record.shape),
        metadata=dict(record.metadata),
    )


def _bound_axis(axis: RecordAxisPlan) -> BoundAxis:
    return BoundAxis(
        id=axis.id,
        kind=axis.kind,
        size=axis.size,
        unit=axis.unit,
        metadata=dict(axis.metadata),
    )


def _evaluate_value_expr(value: ValueExpr | object, ctx: EvalContext) -> object:
    if isinstance(value, ScalarValueExpr):
        return value.expr.eval(ctx)
    if isinstance(value, SeriesValueExpr):
        return value.expr.evaluate(ctx)
    expr = getattr(value, "expr", None)
    if expr is not None:
        return expr.evaluate_in_context(ctx)
    msg = f"unsupported typed value expression: {value!r}"
    raise TypeError(msg)


def _unwrap_payload_values(value: object) -> object:
    if isinstance(value, PayloadValue):
        return value.payload
    if isinstance(value, list):
        return [_unwrap_payload_values(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(
            _unwrap_payload_values(item) for item in cast("tuple[object, ...]", value)
        )
    if isinstance(value, dict):
        return {
            name: _unwrap_payload_values(item)
            for name, item in cast("Mapping[object, object]", value).items()
        }
    return value


def _as_diagnostics(values: Sequence[dict[str, Any]]) -> list[Diagnostic]:
    return [Diagnostic.model_validate(value) for value in values]


def _diagnostic(code: str, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = ["bind_program"]
