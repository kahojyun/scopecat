"""Bind a typed program to one validated configuration environment."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

from scopecat._compiler.bound import (
    BoundAxis,
    BoundCollect,
    BoundComputeCall,
    BoundComputeDefinition,
    BoundComputeOutput,
    BoundComputeResult,
    BoundPlan,
    BoundPoint,
    BoundRecord,
    BoundResourceState,
    BoundRoute,
    BoundStateField,
    BoundValue,
    CollectionRequest,
    PlannedStateChange,
    normalize_collection_channel_bindings,
)
from scopecat._compiler.dependencies import (
    ComputeDependencies,
    analyze_compute_dependencies,
)
from scopecat._compiler.environment import ValidatedConfigEnvironment
from scopecat._compiler.implementations import (
    SelectedLocalImplementations,
    select_local_implementations,
)
from scopecat._compiler.linked import (
    LinkedPlan,
    link_program,
    materialize_selected_linked_points,
    select_linked_program,
)
from scopecat._compiler.parameter_overlays import apply_point_parameter_overlay
from scopecat._compiler.point_domain import (
    MaterializedPoint,
)
from scopecat._compiler.problems import CompilerProblemError, compiler_problem
from scopecat._compiler.product_realizations import (
    SelectedLocalProductRealizations,
    select_local_product_realizations,
)
from scopecat._compiler.products import (
    InstrumentProductProducer,
    ProductAxisDef,
    ProductDef,
)
from scopecat._compiler.program import (
    ComputeEdge,
    TypedComputeNode,
    TypedComputeOutput,
    TypedProgram,
    ValueInput,
)
from scopecat._compiler.records import (
    RecordAxisPlan,
    RecordPlan,
    expected_dataset_schema,
    plan_records,
    point_coordinate_ids,
    validate_product_graph,
    validate_record_plan,
)
from scopecat._compiler.route_constraints import validate_point_resource_constraints
from scopecat._compiler.state import StateRecord, evaluate_state_spec
from scopecat._compiler.verification import (
    SelectedTypedProgram,
)
from scopecat._compute_result import ComputeResultRef
from scopecat._content_identity import content_fingerprint, stable_content_hash
from scopecat._relation_analysis import PlanNode
from scopecat._relation_backend import (
    REFERENCE_RELATION_BACKEND,
    EvalContext,
    ParameterRelationData,
    RelationBackend,
    SelectedRelationPlan,
    evaluate_relation_in_context,
    evaluate_scalar,
    evaluate_series,
)
from scopecat._relations import RelationExpr, ScalarExpr, SeriesExpr
from scopecat._resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
    ResourceTarget,
)
from scopecat._semantic_graph import OperationId, ValueId
from scopecat._value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
    ValueExpr,
)
from scopecat.compute_values import ResolvedRoute
from scopecat.errors import CheckFailed
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef, StateValue
from scopecat.models.value import PayloadValue
from scopecat.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
    model_location,
)
from scopecat.routing import RoutingError, RoutingView
from scopecat.value_types import Scalar
from scopecat.value_validation import coerce_literal

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
    *,
    relation_backend: RelationBackend = REFERENCE_RELATION_BACKEND,
) -> BoundPlan:
    """Link and locally materialize one typed program.

    This compatibility-sized orchestration entry point deliberately composes
    two independently callable compiler passes.  Target-domain lowerings can
    consume :class:`LinkedPlan` directly without first constructing local
    points.
    """

    try:
        linked = link_program(program, environment)
    except CheckFailed as error:
        return _empty_plan(
            program,
            error.problems,
            relation_backend=relation_backend,
        )
    return materialize_local_plan(
        linked,
        relation_backend=relation_backend,
    )


def materialize_local_plan(
    linked: LinkedPlan,
    *,
    relation_backend: RelationBackend = REFERENCE_RELATION_BACKEND,
) -> BoundPlan:
    """Lower a linked symbolic plan to the current local per-point plan."""

    program = linked.program
    environment = linked.environment
    routing = environment.routing
    if routing is None:
        raise AssertionError("linked plan lost its validated routing view")
    problems = list(environment.problems)
    implementations, implementation_problems = select_local_implementations(
        program.compute_nodes,
        program.implementation_catalog,
        phase=ProblemPhase.PLANNING,
    )
    problems.extend(implementation_problems)
    product_realizations, product_realization_problems = (
        select_local_product_realizations(
            program.product_defs,
            program.instrument_product_producers,
            program.product_uses,
            routing=routing,
            phase=ProblemPhase.PLANNING,
        )
    )
    problems.extend(product_realization_problems)
    try:
        selected_program = select_linked_program(linked, relation_backend)
    except CheckFailed as error:
        problems.extend(error.problems)
        selected_program = None
    if (
        implementation_problems
        or implementations is None
        or product_realization_problems
        or product_realizations is None
        or selected_program is None
        or not environment.valid
        or environment.routing is None
    ):
        return _empty_plan(
            program,
            problems,
            relation_backend=relation_backend,
            local_implementations=implementations,
            local_product_realizations=product_realizations,
        )
    try:
        linked_points = materialize_selected_linked_points(
            linked,
            selected_program,
            relation_backend,
        )
    except CheckFailed as error:
        problems.extend(error.problems)
        return _empty_plan(
            program,
            problems,
            relation_backend=relation_backend,
            local_implementations=implementations,
            local_product_realizations=product_realizations,
        )
    selected_program = linked_points.selected_program
    materialized_domain = linked_points.point_domain
    planner_points = materialized_domain.points
    coordinate_schema_valid = True
    try:
        coordinate_ids = tuple(point_coordinate_ids(planner_points))
    except ValueError as error:
        coordinate_schema_valid = False
        coordinate_ids = ()
        problems.append(
            _problem(
                "experiment_point_schema_invalid",
                f"experiment point schema is invalid: {error}",
                model_location("points"),
            )
        )
    record_plans = plan_records(
        program.product_defs,
        program.product_uses,
        program.record_uses,
        point_count=len(planner_points),
    )
    record_problems = validate_record_plan(
        record_plans,
        coordinate_ids=coordinate_ids,
    )
    problems.extend(record_problems)

    state_records: list[StateRecord] = []
    point_parameters: dict[int, ParameterRelationData] = {}
    compute_dependencies = analyze_compute_dependencies(program.compute_nodes)

    for point in planner_points:
        params = _point_parameters(
            environment.parameters,
            program=program,
            point=point,
            problems=problems,
            selected_program=selected_program,
            relation_backend=relation_backend,
        )
        if params is None:
            continue
        point_parameters[point.logical_ordinal] = params
        ctx = EvalContext(params=params, point_row=point.row)
        for state_index, state in enumerate(program.state):
            try:
                state_records.extend(
                    evaluate_state_spec(
                        state,
                        point_index=point.logical_ordinal,
                        ctx=ctx,
                        backend=relation_backend,
                        selected_plan=selected_program.selected_plan,
                        location=model_location("state", state_index),
                    )
                )
            except (ArithmeticError, KeyError, TypeError, ValueError) as error:
                problems.append(
                    _problem(
                        "experiment_state_evaluation_failed",
                        "state binding failed for point "
                        f"{point.logical_ordinal}: {error}",
                        model_location("state", state_index),
                    )
                )
    if len(point_parameters) != len(planner_points):
        return _empty_plan(
            program,
            problems,
            relation_backend=relation_backend,
            local_implementations=implementations,
            local_product_realizations=product_realizations,
        )
    routes_by_point = _bind_routes(
        program,
        environment,
        planner_points,
        point_parameters,
        problems,
        selected_program=selected_program,
        relation_backend=relation_backend,
    )
    state_by_point: dict[int, list[StateRecord]] = {}
    for record in state_records:
        state_by_point.setdefault(record.point_index, []).append(record)

    schema = None
    if coordinate_schema_valid and not has_blocking_problems(record_problems):
        try:
            schema = expected_dataset_schema(
                experiment_id=program.id,
                points=planner_points,
                records=record_plans,
            )
        except ValueError as error:
            problems.append(
                _problem(
                    "experiment_dataset_schema_invalid",
                    f"experiment output schema is invalid: {error}",
                    model_location("records"),
                )
            )
    bound_records = tuple(_bound_record(record) for record in record_plans)
    bound_points: list[BoundPoint] = []
    previous_state: dict[
        tuple[PhysicalResourceId, str, str, tuple[str, ...], _ChannelSignature],
        object,
    ] = {}
    state_changes: list[PlannedStateChange] = []

    for point in planner_points:
        params = point_parameters.get(point.logical_ordinal)
        if params is None:
            continue
        routes = tuple(routes_by_point.get(point.logical_ordinal, ()))
        point_state_records = tuple(state_by_point.get(point.logical_ordinal, ()))
        demanded_payload_results = {
            value.value_id
            for state in point_state_records
            if isinstance((value := state.value), ComputeResultRef)
        }
        compute, payload_ids = _bind_compute_calls(
            program.compute_nodes,
            point=point,
            params=params,
            routes=routes,
            dependencies=compute_dependencies,
            implementations=implementations,
            demanded_payload_results=demanded_payload_results,
            problems=problems,
            selected_program=selected_program,
            relation_backend=relation_backend,
        )
        desired = _bind_desired_state(
            point_state_records,
            routes=routes,
            routing=environment.routing,
            payload_ids=payload_ids,
            known_compute_results={node.result.id for node in program.compute_nodes},
            point_index=point.logical_ordinal,
            problems=problems,
        )
        collect = _bind_collect(
            program.product_defs,
            program.instrument_product_producers,
            product_realizations,
            routes,
            routing=environment.routing,
            point_index=point.logical_ordinal,
            problems=problems,
        )
        problems.extend(
            validate_point_resource_constraints(
                point.logical_ordinal,
                routes,
                desired,
                collect,
                config=environment.config,
            )
        )
        _validate_collection_requests(
            collect,
            point_index=point.logical_ordinal,
            problems=problems,
        )
        for resource in desired:
            for field in resource.fields:
                key = (
                    resource.resource_id,
                    resource.capability_id,
                    field.field_path,
                    field.entity_ids,
                    _channel_signature(field.channel_bindings),
                )
                before = previous_state.get(key)
                if before != field.value:
                    state_changes.append(
                        PlannedStateChange(
                            point_index=point.logical_ordinal,
                            resource_id=resource.resource_id,
                            capability_id=resource.capability_id,
                            field_path=field.field_path,
                            before=before,
                            after=field.value,
                            resource_port_id=field.resource_port_id,
                            entity_ids=field.entity_ids,
                            channel_bindings=field.channel_bindings,
                        )
                    )
                previous_state[key] = field.value
        bound_points.append(
            BoundPoint(
                point_index=point.logical_ordinal,
                logical_id=point.logical_id,
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
        product_defs=program.product_defs,
        instrument_product_producers=program.instrument_product_producers,
        product_uses=program.product_uses,
        record_uses=program.record_uses,
        records=bound_records,
        route_intents=program.route_intents,
        state_changes=tuple(state_changes),
        expected_dataset_schema=schema,
        local_implementations=implementations,
        local_product_realizations=product_realizations,
        relation_backend_id=relation_backend.backend_id,
        compute_definitions=tuple(
            _bound_compute_definition(node) for node in program.compute_nodes
        ),
        problems=tuple(problems),
    )


def _empty_plan(
    program: TypedProgram,
    problems: Sequence[Problem],
    *,
    relation_backend: RelationBackend,
    local_implementations: SelectedLocalImplementations | None = None,
    local_product_realizations: SelectedLocalProductRealizations | None = None,
) -> BoundPlan:
    product_problems = validate_product_graph(
        program.product_defs,
        program.instrument_product_producers,
        program.product_uses,
        program.record_uses,
    )
    records = (
        tuple(
            _bound_record(record)
            for record in plan_records(
                program.product_defs,
                program.product_uses,
                program.record_uses,
                point_count=0,
            )
        )
        if not product_problems
        else ()
    )
    return BoundPlan(
        experiment_id=program.id,
        experiment_kind=program.kind,
        point_coordinate_ids=(),
        points=(),
        product_defs=program.product_defs,
        instrument_product_producers=program.instrument_product_producers,
        product_uses=program.product_uses,
        record_uses=program.record_uses,
        records=records,
        route_intents=program.route_intents,
        state_changes=(),
        expected_dataset_schema=None,
        local_implementations=local_implementations,
        local_product_realizations=local_product_realizations,
        relation_backend_id=relation_backend.backend_id,
        compute_definitions=tuple(
            _bound_compute_definition(node) for node in program.compute_nodes
        ),
        problems=tuple(problems),
    )


def _point_parameters(
    base: ParameterRelationData,
    *,
    program: TypedProgram,
    point: MaterializedPoint,
    problems: list[Problem],
    selected_program: SelectedTypedProgram,
    relation_backend: RelationBackend,
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
    ctx = EvalContext(params=params, point_row=point.row)
    failed = False
    for overlay in program.parameter_overlays:
        try:
            apply_point_parameter_overlay(
                overlay,
                ctx=ctx,
                params=params,
                backend=relation_backend,
                selected_plan=selected_program.selected_plan,
            )
        except CompilerProblemError as error:
            failed = True
            problems.append(error.problem)
    return None if failed else params


def _bind_routes(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
    points: Sequence[MaterializedPoint],
    point_parameters: Mapping[int, ParameterRelationData],
    problems: list[Problem],
    *,
    selected_program: SelectedTypedProgram,
    relation_backend: RelationBackend,
) -> dict[int, tuple[BoundRoute, ...]]:
    routing = environment.routing
    if routing is None:
        return {}
    routes: dict[int, tuple[BoundRoute, ...]] = {}
    for point in points:
        params = point_parameters.get(point.logical_ordinal)
        if params is None:
            continue
        selected: list[BoundRoute] = []
        for intent in program.route_intents:
            ctx = EvalContext(params=params, point_row=point.row)
            entity_values: list[object] = []
            failed = False
            for use in intent.entity_uses:
                try:
                    entity_values.append(
                        _evaluate_value_expr(
                            use.value,
                            selected_program.selected_plan(use.id),
                            ctx,
                            relation_backend=relation_backend,
                        )
                    )
                except (ArithmeticError, KeyError, TypeError, ValueError) as error:
                    failed = True
                    problems.append(
                        _problem(
                            "experiment_route_entity_evaluation_failed",
                            f"route {intent.port_id.qualified_name} entity "
                            "expression failed for "
                            f"point {point.logical_ordinal}: {error}",
                            model_location("routes", intent.port_id.qualified_name),
                        )
                    )
            if failed:
                continue
            try:
                binding = routing.route_point(
                    port_id=intent.port_id,
                    capabilities=list(intent.capabilities),
                    entity_values=entity_values,
                    fixed_resource_id=intent.fixed_resource_id,
                )
            except RoutingError as error:
                problems.append(
                    _problem(
                        error.code,
                        str(error),
                        model_location("routes", intent.port_id.qualified_name),
                        category=(
                            ProblemCategory.CONFLICT
                            if error.code.endswith("_ambiguous")
                            else ProblemCategory.UNAVAILABLE
                        ),
                    )
                )
                continue
            selected.append(
                BoundRoute(
                    port_id=binding.port_id,
                    resource_id=binding.resource_id,
                    resource_kind=binding.resource_kind,
                    capabilities=tuple(binding.capabilities),
                    entity_ids=tuple(binding.entity_ids),
                    served_entity_ids=tuple(binding.served_entity_ids),
                    product_axis_order=tuple(binding.product_axis_order),
                    channel_bindings=tuple(binding.channel_bindings),
                )
            )
        routes[point.logical_ordinal] = tuple(selected)
    return routes


def _bind_compute_calls(
    nodes: Sequence[TypedComputeNode],
    *,
    point: MaterializedPoint,
    params: ParameterRelationData,
    routes: Sequence[BoundRoute],
    dependencies: Mapping[OperationId, ComputeDependencies],
    implementations: SelectedLocalImplementations,
    demanded_payload_results: set[ValueId],
    problems: list[Problem],
    selected_program: SelectedTypedProgram,
    relation_backend: RelationBackend,
) -> tuple[tuple[BoundComputeCall, ...], dict[ValueId, str]]:
    calls: list[BoundComputeCall] = []
    output_owners = {node.result.id: node.id for node in nodes}
    if len(output_owners) != len(nodes):
        msg = "typed compute graph contains duplicate result identities"
        raise ValueError(msg)
    signatures: dict[ValueId, str] = {}
    payload_ids: dict[ValueId, str] = {}
    ctx = EvalContext(params=params, point_row=point.row)
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
                            _evaluate_value_expr(
                                input_spec.value,
                                selected_program.selected_plan(
                                    input_spec.relation_use_id
                                ),
                                ctx,
                                relation_backend=relation_backend,
                            ),
                            path=("compute", *node.id.scope, node.id.local_id, name),
                        )
                    )
                    inputs[name] = BoundValue(value)
                    signature_inputs[name] = content_fingerprint(value)
                elif isinstance(input_spec, ComputeEdge):
                    owner = output_owners.get(input_spec.value_id)
                    if owner is None:
                        msg = (
                            "compute result "
                            f"{input_spec.value_id.qualified_name!r} has no owner"
                        )
                        raise ValueError(msg)
                    upstream_signature = signatures.get(input_spec.value_id)
                    if upstream_signature is None:
                        msg = (
                            f"producer {owner.qualified_name!r} result "
                            f"{input_spec.value_id.qualified_name!r} is not available"
                        )
                        raise ValueError(msg)
                    inputs[name] = BoundComputeOutput(input_spec.value_id)
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
                        port_id=route.port_id.qualified_name,
                        resource_id=route.resource_id.value,
                        resource_kind=route.resource_kind,
                        capabilities=route.capabilities,
                        entity_ids=route.entity_ids,
                        served_entity_ids=route.served_entity_ids,
                        product_axis_order=route.product_axis_order,
                    )
                    inputs[name] = BoundValue(resolved)
                    signature_inputs[name] = content_fingerprint(resolved)
            except (ArithmeticError, KeyError, TypeError, ValueError) as error:
                failed = True
                problems.append(
                    _problem(
                        "compute_node_input_binding_failed",
                        f"compute node {node.id} input {name!r} failed: {error}",
                        model_location(
                            "compute",
                            *node.id.scope,
                            node.id.local_id,
                            name,
                        ),
                    )
                )
        if failed:
            continue
        implementation = implementations.selected_for(node.id)
        signature = stable_content_hash(
            {
                "operation": node.id.qualified_name,
                "contract": content_fingerprint(node.contract),
                "interface": content_fingerprint(implementation.interface),
                "implementation": implementation.implementation_id.value,
                "inputs": signature_inputs,
            }
        )
        signatures[node.result.id] = signature
        schema_id = (
            _payload_schema(node.result.value_type)
            if node.result.id in demanded_payload_results
            else None
        )
        payload_id = (
            f"{node.result.id.qualified_name}.payload.{signature}"
            if schema_id is not None
            else None
        )
        if payload_id is not None:
            payload_ids[node.result.id] = payload_id
        calls.append(
            BoundComputeCall(
                operation_id=node.id,
                implementation=implementation,
                contract=node.contract,
                inputs=inputs,
                result=_bound_compute_result(node.result),
                cache_key=signature,
                dependencies=dict(dependencies[node.id].as_mapping()),
                payload_id=payload_id,
                payload_schema_id=schema_id,
            )
        )
    return tuple(calls), payload_ids


def _bound_compute_definition(node: TypedComputeNode) -> BoundComputeDefinition:
    return BoundComputeDefinition(
        operation_id=node.id,
        result=_bound_compute_result(node.result),
    )


def _bound_compute_result(result: TypedComputeOutput) -> BoundComputeResult:
    return BoundComputeResult(
        id=result.id,
        value_type=result.value_type,
        availability=result.availability,
    )


def _payload_schema(value_type: object) -> str | None:
    from scopecat.value_types import Payload

    if isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload):
        return value_type.atom.schema_id
    return None


def _bind_desired_state(
    records: Sequence[StateRecord],
    *,
    routes: Sequence[BoundRoute],
    routing: RoutingView,
    payload_ids: Mapping[ValueId, str],
    known_compute_results: set[ValueId],
    point_index: int,
    problems: list[Problem],
) -> tuple[BoundResourceState, ...]:
    grouped: dict[
        tuple[PhysicalResourceId, str],
        dict[tuple[str, tuple[str, ...], _ChannelSignature], BoundStateField],
    ] = {}
    signatures: dict[
        tuple[PhysicalResourceId, str, str, tuple[str, ...], _ChannelSignature],
        set[str],
    ] = {}
    owners: dict[
        tuple[PhysicalResourceId, str, str, tuple[str, ...], _ChannelSignature],
        set[ResourceTarget],
    ] = {}
    for record in records:
        capability_id = record.capability_id
        field_path = record.field_path
        if isinstance(record.value, ComputeResultRef):
            if record.value.value_id not in known_compute_results:
                problems.append(
                    _problem(
                        "compute_payload_unknown_output",
                        "state references unknown compute result "
                        f"{record.value.value_id.qualified_name!r}",
                        model_location("desired_state", "value"),
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
                continue
            if record.value.value_id not in payload_ids:
                problems.append(
                    _problem(
                        "compute_payload_unavailable",
                        "state compute output is not an available payload: "
                        f"{record.value.value_id.qualified_name!r}",
                        model_location("desired_state", "value"),
                    )
                )
                continue
        state_value = _state_value(record.value, payload_ids=payload_ids)
        if state_value is None:
            problems.append(
                _problem(
                    "state_value_unsupported",
                    "state values must be finite numbers, quantities, "
                    "or payload outputs",
                    model_location("desired_state", "value"),
                )
            )
            continue
        try:
            resource_id, entity_ids, channel_bindings, unbound = _bind_state_resource(
                record.resource_target,
                capability_id=capability_id,
                route_entities=record.route_entities,
                routes=routes,
                routing=routing,
            )
        except RoutingError as error:
            problems.append(
                _problem(
                    error.code,
                    str(error),
                    model_location(
                        "desired_state",
                        _resource_target_location_field(record.resource_target),
                    ),
                    category=(
                        ProblemCategory.NOT_FOUND
                        if error.code.endswith("not_found")
                        or error.code.endswith("unbound")
                        else ProblemCategory.UNAVAILABLE
                    ),
                )
            )
            continue
        if unbound:
            problems.append(
                _problem(
                    "state_route_entity_unbound",
                    "state route entities are not bound: " + ", ".join(unbound),
                    model_location("desired_state", "route_entities"),
                    category=ProblemCategory.UNAVAILABLE,
                )
            )
            continue
        channel_key = _channel_signature(channel_bindings)
        group = grouped.setdefault((resource_id, capability_id), {})
        key = (field_path, entity_ids, channel_key)
        signature_key = (
            resource_id,
            capability_id,
            field_path,
            entity_ids,
            channel_key,
        )
        signatures.setdefault(signature_key, set()).add(state_value.model_dump_json())
        owners.setdefault(signature_key, set()).add(record.resource_target)
        group.setdefault(
            key,
            BoundStateField(
                field_path=field_path,
                value=state_value,
                resource_port_id=(
                    record.resource_target
                    if isinstance(record.resource_target, LogicalResourcePortId)
                    else None
                ),
                entity_ids=entity_ids,
                channel_bindings=channel_bindings,
            ),
        )
    for (
        resource,
        capability,
        field_path,
        _entities,
        _channel,
    ), values in signatures.items():
        if len(values) > 1:
            problems.append(
                _problem(
                    "experiment_conflicting_desired_state",
                    f"{resource}.{capability}.{field_path} receives multiple values "
                    f"at point {point_index}",
                    model_location("points", point_index, "desired_state"),
                    category=ProblemCategory.CONFLICT,
                )
            )
    for (
        resource,
        capability,
        field_path,
        _entities,
        _channel,
    ), target_owners in owners.items():
        if len(target_owners) > 1:
            problems.append(
                _problem(
                    "experiment_aliased_desired_state_target",
                    f"{resource}.{capability}.{field_path} is owned by multiple "
                    f"resource targets at point {point_index}",
                    model_location("points", point_index, "desired_state"),
                    category=ProblemCategory.CONFLICT,
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
    payload_ids: Mapping[ValueId, str],
) -> StateValue | None:
    if isinstance(value, ComputeResultRef):
        payload_id = payload_ids.get(value.value_id)
        return StateValue(PayloadRef(payload_id=payload_id)) if payload_id else None
    if isinstance(value, Quantity):
        return StateValue(value) if math.isfinite(value.value) else None
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return StateValue(float(value))
        except (OverflowError, ValueError):
            return None
    return None


def _bind_state_resource(
    target: ResourceTarget,
    *,
    capability_id: str,
    route_entities: Sequence[object],
    routes: Sequence[BoundRoute],
    routing: RoutingView,
) -> tuple[
    PhysicalResourceId,
    tuple[str, ...],
    tuple[RoutingChannelBinding, ...],
    tuple[str, ...],
]:
    if isinstance(target, PhysicalResourceId):
        binding = routing.bind_physical(
            resource_id=target,
            capabilities=(capability_id,),
            entity_values=route_entities,
        )
        _require_instrument_resource(
            binding.resource_id,
            resource_kind=binding.resource_kind,
        )
        return (
            binding.resource_id,
            binding.entity_ids,
            binding.channel_bindings,
            (),
        )

    port_id = target
    route = next((route for route in routes if route.port_id == port_id), None)
    if route is None:
        raise RoutingError(
            "state_resource_port_unbound",
            f"logical state resource port {port_id.qualified_name!r} is not bound",
        )
    _require_instrument_resource(
        route.resource_id,
        resource_kind=route.resource_kind,
    )
    if capability_id not in route.capabilities:
        raise RoutingError(
            "state_resource_port_capability_missing",
            f"logical state resource port {port_id.qualified_name!r} does not "
            f"provide capability {capability_id!r}",
        )
    entity_ids, channel_bindings, unbound = _logical_state_target(
        route=route,
        capability_id=capability_id,
        route_entities=route_entities,
        routing=routing,
    )
    return route.resource_id, entity_ids, channel_bindings, unbound


def _logical_state_target(
    *,
    route: BoundRoute,
    capability_id: str,
    route_entities: Sequence[object],
    routing: RoutingView,
) -> tuple[
    tuple[str, ...],
    tuple[RoutingChannelBinding, ...],
    tuple[str, ...],
]:
    requested_entity_ids = tuple(
        dict.fromkeys(
            value.id if isinstance(value, EntityRef) else str(value)
            for value in route_entities
        )
    )
    selected_entity_ids = requested_entity_ids or route.entity_ids
    if requested_entity_ids and route.entity_ids:
        unbound = tuple(
            entity_id
            for entity_id in requested_entity_ids
            if entity_id not in route.entity_ids
        )
        if unbound:
            return requested_entity_ids, (), unbound
    if selected_entity_ids:
        binding = routing.bind_physical(
            resource_id=route.resource_id,
            capabilities=(capability_id,),
            entity_values=selected_entity_ids,
        )
        return binding.entity_ids, binding.channel_bindings, ()
    channel_bindings = tuple(
        binding
        for binding in route.channel_bindings
        if binding.capability is None or binding.capability == capability_id
    )
    return (
        tuple(dict.fromkeys(binding.entity_id for binding in channel_bindings)),
        channel_bindings,
        (),
    )


def _channel_binding_identity(
    binding: RoutingChannelBinding,
) -> _ChannelBindingIdentity:
    return (
        binding.entity_id,
        binding.channel_id,
        binding.line_id,
        binding.capability,
        tuple(sorted(binding.group_ids)),
    )


def _channel_signature(
    bindings: Sequence[RoutingChannelBinding],
) -> _ChannelSignature:
    return tuple(_channel_binding_identity(binding) for binding in bindings)


def _bind_collect(
    products: Sequence[ProductDef],
    producers: Sequence[InstrumentProductProducer],
    realizations: SelectedLocalProductRealizations,
    routes: Sequence[BoundRoute],
    *,
    routing: RoutingView,
    point_index: int,
    problems: list[Problem],
) -> tuple[BoundCollect, ...]:
    products_by_id = {product.id: product for product in products}
    producers_by_id = {producer.id: producer for producer in producers}
    grouped: dict[PhysicalResourceId, list[CollectionRequest]] = {}
    for realization in realizations.entries:
        product = products_by_id[realization.product_id]
        producer = producers_by_id[realization.producer_id]
        if product != realization.product:
            msg = "local product realization contract changed after selection"
            raise ValueError(msg)
        if producer != realization.producer:
            msg = "local product producer contract changed after selection"
            raise ValueError(msg)
        try:
            (
                resource_id,
                resource_port_id,
                entity_ids,
                channel_bindings,
            ) = _bind_record_target(
                producer.resource_target,
                implicit_resource_id=realization.implicit_resource_id,
                capability=producer.capability,
                routes=routes,
                routing=routing,
            )
        except RoutingError as error:
            problems.append(
                _problem(
                    error.code,
                    str(error),
                    model_location(
                        "points",
                        point_index,
                        "product_uses",
                        realization.product_use_id.value,
                        _resource_target_location_field(producer.resource_target),
                    ),
                    category=(
                        ProblemCategory.NOT_FOUND
                        if error.code.endswith("not_found")
                        or error.code.endswith("unbound")
                        else ProblemCategory.UNAVAILABLE
                    ),
                )
            )
            continue
        request = CollectionRequest(
            product_use_id=realization.product_use_id,
            product_id=product.id,
            provider_key=producer.provider_key,
            capability=producer.capability,
            unit=product.unit,
            dtype=product.dtype,
            resource_port_id=resource_port_id,
            entity_ids=entity_ids,
            channel_bindings=channel_bindings,
            axes=tuple(_bound_axis(axis) for axis in product.axes),
            metadata=dict(producer.metadata),
        )
        grouped.setdefault(resource_id, []).append(request)
    return tuple(
        BoundCollect(resource_id=resource_id, requests=tuple(requests))
        for resource_id, requests in grouped.items()
    )


def _bind_record_target(
    target: ResourceTarget | None,
    *,
    implicit_resource_id: PhysicalResourceId | None,
    capability: str | None,
    routes: Sequence[BoundRoute],
    routing: RoutingView,
) -> tuple[
    PhysicalResourceId,
    LogicalResourcePortId | None,
    tuple[str, ...],
    tuple[RoutingChannelBinding, ...],
]:
    if target is None:
        if implicit_resource_id is None:
            msg = "implicit product target requires a selected physical resource"
            raise ValueError(msg)
        binding = routing.bind_physical(
            resource_id=implicit_resource_id,
            capabilities=(() if capability is None else (capability,)),
        )
        return binding.resource_id, None, binding.entity_ids, binding.channel_bindings
    if isinstance(target, PhysicalResourceId):
        binding = routing.bind_physical(
            resource_id=target,
            capabilities=(() if capability is None else (capability,)),
        )
        _require_instrument_resource(
            binding.resource_id,
            resource_kind=binding.resource_kind,
        )
        return binding.resource_id, None, binding.entity_ids, binding.channel_bindings
    route = next((route for route in routes if route.port_id == target), None)
    if route is None:
        raise RoutingError(
            "record_resource_port_unbound",
            f"logical record resource port {target.qualified_name!r} is not bound",
        )
    _require_instrument_resource(
        route.resource_id,
        resource_kind=route.resource_kind,
    )
    if capability is not None and capability not in route.capabilities:
        raise RoutingError(
            "record_resource_port_capability_missing",
            f"logical record resource port {target.qualified_name!r} does not "
            f"provide capability {capability!r}",
        )
    if route.entity_ids:
        binding = routing.bind_physical(
            resource_id=route.resource_id,
            capabilities=(route.capabilities if capability is None else (capability,)),
            entity_values=route.entity_ids,
        )
        return (
            binding.resource_id,
            target,
            binding.entity_ids,
            normalize_collection_channel_bindings(
                binding.channel_bindings,
                capability=capability,
            ),
        )
    channel_bindings = normalize_collection_channel_bindings(
        route.channel_bindings,
        capability=capability,
    )
    return (
        route.resource_id,
        target,
        tuple(
            dict.fromkeys(
                (
                    *route.entity_ids,
                    *(binding.entity_id for binding in channel_bindings),
                )
            )
        ),
        channel_bindings,
    )


def _resource_target_location_field(target: ResourceTarget | None) -> str:
    if isinstance(target, LogicalResourcePortId):
        return "resource_port_id"
    if isinstance(target, PhysicalResourceId):
        return "physical_resource_id"
    return "resource_target"


def _require_instrument_resource(
    resource_id: PhysicalResourceId,
    *,
    resource_kind: str,
) -> None:
    if resource_kind != "instrument":
        raise RoutingError(
            "physical_resource_kind_unsupported",
            f"physical resource {resource_id.value!r} has kind "
            f"{resource_kind!r}; local state and collection require an instrument",
        )


def _validate_collection_requests(
    collects: Sequence[BoundCollect],
    *,
    point_index: int,
    problems: list[Problem],
) -> None:
    for collect in collects:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for request in collect.requests:
            if request.provider_key in seen:
                duplicates.add(request.provider_key)
            seen.add(request.provider_key)
        for provider_key in sorted(duplicates):
            problems.append(
                _problem(
                    "collection_provider_key_duplicate",
                    f"instrument {collect.resource_id.value!r} receives provider "
                    "product "
                    f"{provider_key!r} "
                    f"more than once at point {point_index}",
                    model_location("points", point_index, "collection"),
                    category=ProblemCategory.CONFLICT,
                )
            )


def _bound_record(record: RecordPlan) -> BoundRecord:
    return BoundRecord(
        id=record.id,
        product_use_id=record.product_use_id,
        product_id=record.product_id,
        kind=record.kind,
        unit=record.unit,
        dtype=record.dtype,
        axes=tuple(_bound_axis(axis) for axis in record.axes),
        dims=tuple(record.dims),
        shape=tuple(record.shape),
        metadata=dict(record.metadata),
    )


def _bound_axis(axis: RecordAxisPlan | ProductAxisDef) -> BoundAxis:
    return BoundAxis(
        id=axis.id,
        kind=axis.kind,
        size=axis.size,
        unit=axis.unit,
        metadata=dict(axis.metadata),
    )


def _evaluate_value_expr(
    value: ValueExpr | object,
    selected_plan: SelectedRelationPlan[PlanNode],
    ctx: EvalContext,
    *,
    relation_backend: RelationBackend,
) -> object:
    if isinstance(value, ScalarValueExpr):
        return evaluate_scalar(
            relation_backend,
            cast("SelectedRelationPlan[ScalarExpr]", selected_plan),
            ctx,
        )
    if isinstance(value, SeriesValueExpr):
        return evaluate_series(
            relation_backend,
            cast("SelectedRelationPlan[SeriesExpr]", selected_plan),
            ctx,
        )
    if isinstance(value, TableValueExpr):
        return evaluate_relation_in_context(
            relation_backend,
            cast("SelectedRelationPlan[RelationExpr]", selected_plan),
            ctx,
        )
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


def _problem(
    code: str,
    message: str,
    location: ModelLocation,
    *,
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
) -> Problem:
    return compiler_problem(code, message, location, category=category)


__all__ = ["bind_program", "materialize_local_plan"]
