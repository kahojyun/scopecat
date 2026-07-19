"""Specialize one linked program into final point-local execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from typing import Protocol, cast

from pydantic import JsonValue

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.linking.implementations import (
    SelectedLocalImplementations,
    select_local_implementations,
)
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.linking.product_realizations import (
    SelectedLocalProductRealizations,
    select_local_product_realizations,
)
from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
    evaluate_relation_in_context,
    evaluate_scalar,
    evaluate_series,
)
from scopecat.compiler.relations.model import (
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.availability import ValueRate
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    OperationId,
    ValueId,
)
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
    ValueExpr,
)
from scopecat.compiler.typed.action import ActionRecord, evaluate_action_spec
from scopecat.compiler.typed.dependencies import (
    ComputeDependencies,
    analyze_compute_dependencies,
)
from scopecat.compiler.typed.point_domain import (
    MaterializedPoint,
)
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    ComputeEdge,
    CoreProgram,
    TypedComputeNode,
    ValueInput,
    core_actions,
    core_state,
)
from scopecat.compiler.typed.records import (
    point_coordinate_ids,
)
from scopecat.compiler.typed.state import StateRecord, evaluate_state_spec
from scopecat.compiler.typed.verification import (
    VerifiedCoreProgram,
)
from scopecat.execution.local.program import (
    ActionField,
    ActionStage,
    ApplyStateOperation,
    ApplyStateStage,
    BoundInput,
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    ComputeOperation,
    ComputeResultSlot,
    ComputeStage,
    InstrumentActionOperation,
    OutputInput,
    PayloadSlot,
    PointProgram,
    StateTarget,
)
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
    model_location,
)
from scopecat.kernel.product_identity import ProductUse, ProductUseId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
    ResourceClaim,
    ResourceTarget,
)
from scopecat.kernel.routes import ResolvedRoute
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_validation import coerce_literal
from scopecat.planning.local_route_constraints import (
    PendingCollect,
    PendingCollectionRequest,
    PendingResourceState,
    PendingRoute,
    PendingStateField,
    validate_point_resource_constraints,
)
from scopecat.planning.routing import RoutingError, RoutingView
from scopecat.records.config import RoutingChannelBinding
from scopecat.records.entity import EntityRef
from scopecat.records.instrument import CommandChannelBinding
from scopecat.records.measurement import CoordinateValue
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments.contracts import (
    CollectAxisRequest,
    CollectCommand,
    CollectProductRequest,
)

type _ChannelBindingIdentity = tuple[
    str,
    str,
    str | None,
    str | None,
    tuple[str, ...],
]
type _ChannelSignature = tuple[_ChannelBindingIdentity, ...]


def _normalize_collection_channel_bindings(
    bindings: Sequence[RoutingChannelBinding],
    *,
    capability: str | None,
) -> tuple[RoutingChannelBinding, ...]:
    selected = tuple(
        binding
        for binding in bindings
        if binding.capability is None
        or capability is None
        or binding.capability == capability
    )
    if capability is not None:
        return selected
    normalized: list[RoutingChannelBinding] = []
    seen: set[tuple[str, str, str | None, tuple[str, ...]]] = set()
    for binding in selected:
        identity = (
            binding.entity_id,
            binding.channel_id,
            binding.line_id,
            tuple(sorted(binding.group_ids)),
        )
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(binding.model_copy(update={"capability": None}))
    return tuple(normalized)


class _InstrumentOperation(Protocol):
    @property
    def instrument_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class MaterializedLocalEffects:
    """Transient planning result used to close final run operations."""

    experiment_id: str
    points: tuple[PointProgram, ...]
    product_uses: tuple[ProductUse, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]
    run_compute_operations: tuple[ComputeOperation, ...] = ()

    @property
    def point_count(self) -> int:
        return len(self.points)


def materialize_local_execution(
    linked: LinkedPlan,
    *,
    product_use_ids: AbstractSet[ProductUseId] | None = None,
    instrument_order: Sequence[str] = (),
) -> MaterializedLocalEffects:
    """Materialize final point-local operations and selected products."""

    return _materialize_local_execution(
        linked,
        linked_points=None,
        product_use_ids=product_use_ids,
        instrument_order=instrument_order,
    )


def materialize_local_execution_from_points(
    linked_points: MaterializedLinkedPoints,
    *,
    product_use_ids: AbstractSet[ProductUseId] | None = None,
    instrument_order: Sequence[str] = (),
) -> MaterializedLocalEffects:
    """Plan local execution from an already-materialized logical point domain."""

    return _materialize_local_execution(
        linked_points.linked_plan,
        linked_points=linked_points,
        product_use_ids=product_use_ids,
        instrument_order=instrument_order,
    )


def _materialize_local_execution(
    linked: LinkedPlan,
    *,
    linked_points: MaterializedLinkedPoints | None,
    product_use_ids: AbstractSet[ProductUseId] | None,
    instrument_order: Sequence[str],
) -> MaterializedLocalEffects:
    """Bind one selected semantic task into final local execution."""

    program = linked.program
    if product_use_ids is not None:
        requested = frozenset(product_use_ids)
        available = {use.id for use in program.product_uses}
        unknown = sorted(
            (use_id.value for use_id in requested - available),
        )
        if unknown:
            msg = "local product selection contains unknown uses: " + ", ".join(unknown)
            raise ValueError(msg)
        selected_uses = tuple(
            use for use in program.product_uses if use.id in requested
        )
        selected_record_uses = tuple(
            record
            for record in program.record_uses
            if record.product_use_id in requested
        )
        program = replace(
            program,
            product_uses=selected_uses,
            record_uses=selected_record_uses,
        )
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
    if (
        implementation_problems
        or implementations is None
        or product_realization_problems
        or product_realizations is None
        or not environment.valid
        or environment.routing is None
    ):
        raise CheckFailed(problems)
    if linked_points is None:
        try:
            linked_points = materialize_linked_points(linked)
        except CheckFailed as error:
            problems.extend(error.problems)
            raise CheckFailed(problems) from error
    verified_program = linked_points.verified_program
    materialized_domain = linked_points.point_domain
    planner_points = materialized_domain.points
    try:
        coordinate_ids = tuple(point_coordinate_ids(planner_points))
    except ValueError as error:
        coordinate_ids = ()
        problems.append(
            _problem(
                "experiment_point_schema_invalid",
                f"experiment point schema is invalid: {error}",
                model_location("points"),
            )
        )
    state_records: list[StateRecord] = []
    action_records: list[ActionRecord] = []
    point_parameters = {
        point.logical_ordinal: parameters
        for point, parameters in zip(
            planner_points,
            linked_points.point_parameters,
            strict=True,
        )
    }
    compute_dependencies = analyze_compute_dependencies(program.compute_nodes)

    for point, params in zip(
        planner_points,
        linked_points.point_parameters,
        strict=True,
    ):
        ctx = EvalContext(params=params, point_row=point.row)
        for state_index, state in enumerate(core_state(program)):
            try:
                state_records.extend(
                    evaluate_state_spec(
                        state,
                        point_index=point.logical_ordinal,
                        ctx=ctx,
                        relation_plan=verified_program.relation_plan,
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
        for action_index, action in enumerate(core_actions(program)):
            try:
                action_records.append(
                    evaluate_action_spec(
                        action,
                        point_index=point.logical_ordinal,
                        ctx=ctx,
                        relation_plan=verified_program.relation_plan,
                    )
                )
            except (ArithmeticError, KeyError, TypeError, ValueError) as error:
                problems.append(
                    _problem(
                        "experiment_action_evaluation_failed",
                        "action binding failed for point "
                        f"{point.logical_ordinal}: {error}",
                        model_location("actions", action_index),
                    )
                )
    routes_by_point = _bind_routes(
        program,
        environment,
        planner_points,
        point_parameters,
        problems,
        verified_program=verified_program,
    )
    selected_instrument_order = _explicit_instrument_order(
        instrument_order,
        routes_by_point=routes_by_point,
    )
    state_by_point: dict[int, list[StateRecord]] = {}
    for record in state_records:
        state_by_point.setdefault(record.point_index, []).append(record)
    actions_by_point: dict[int, list[ActionRecord]] = {}
    for record in action_records:
        actions_by_point.setdefault(record.point_index, []).append(record)

    point_programs: list[PointProgram] = []
    run_compute_operations: tuple[ComputeOperation, ...] = ()
    compute_rate_by_result = {
        node.result.id: node.result.availability.rate for node in program.compute_nodes
    }

    for point in planner_points:
        params = point_parameters.get(point.logical_ordinal)
        if params is None:
            continue
        routes = tuple(routes_by_point.get(point.logical_ordinal, ()))
        point_state_records = tuple(state_by_point.get(point.logical_ordinal, ()))
        point_action_records = tuple(actions_by_point.get(point.logical_ordinal, ()))
        demanded_payload_results = {
            value.value_id
            for state in point_state_records
            if isinstance((value := state.value), ComputeResultRef)
        } | {
            field.value.value_id
            for action in point_action_records
            for field in action.fields
            if isinstance(field.value, ComputeResultRef)
        }
        bound_compute_operations, payload_ids = _bind_compute_operations(
            program.compute_nodes,
            point=point,
            params=params,
            routes=routes,
            dependencies=compute_dependencies,
            implementations=implementations,
            demanded_payload_results=demanded_payload_results,
            problems=problems,
            verified_program=verified_program,
        )
        if not run_compute_operations:
            run_compute_operations = tuple(
                replace(
                    operation,
                    operation_id=f"run.compute.{operation.semantic_operation_id}",
                )
                for operation in bound_compute_operations
                if compute_rate_by_result[operation.result.id] is ValueRate.RUN
            )
            for operation in run_compute_operations:
                if operation.payload_slot is not None:
                    problems.append(
                        _problem(
                            "run_compute_payload_unsupported",
                            "run-rate compute cannot produce a point-scoped payload",
                            model_location(
                                "compute",
                                operation.semantic_operation_id,
                                "result",
                            ),
                        )
                    )
        compute_operations = tuple(
            operation
            for operation in bound_compute_operations
            if compute_rate_by_result[operation.result.id] is ValueRate.POINT
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
        actions = _bind_actions(
            point_action_records,
            routes=routes,
            routing=environment.routing,
            payload_ids=payload_ids,
            known_compute_results={node.result.id for node in program.compute_nodes},
            point_index=point.logical_ordinal,
            point_uid=point.logical_id.value,
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
        valid_collect = _validate_collection_requests(
            collect,
            point_index=point.logical_ordinal,
            problems=problems,
        )
        state_operations = _state_operations(point.logical_id.value, desired)
        collect_operations = (
            _collect_operations(
                point.logical_id.value,
                point_index=point.logical_ordinal,
                point_count=len(planner_points),
                collects=collect,
            )
            if valid_collect
            else ()
        )
        stages = (
            ComputeStage(compute_operations),
            ApplyStateStage(
                _order_instrument_operations(
                    state_operations,
                    instrument_order=selected_instrument_order,
                )
            ),
            ActionStage(actions),
            CollectStage(
                _order_instrument_operations(
                    collect_operations,
                    instrument_order=selected_instrument_order,
                )
            ),
        )
        point_programs.append(
            PointProgram(
                point_index=point.logical_ordinal,
                logical_id=point.logical_id,
                coordinates={
                    name: cast("CoordinateValue", value)
                    for name, value in point.row.items()
                    if name in coordinate_ids
                },
                stages=tuple(stage for stage in stages if stage.operations),
            )
        )

    resource_order = _resource_order(
        point_programs,
        instrument_order=selected_instrument_order,
    )
    claims = _resource_claims(point_programs, routes_by_point=routes_by_point)
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return MaterializedLocalEffects(
        experiment_id=program.id,
        points=tuple(point_programs),
        product_uses=program.product_uses,
        resource_order=resource_order,
        resource_claims=(
            *(ResourceClaim(instrument_id) for instrument_id in resource_order),
            *(claim for claim in claims if claim.kind != "instrument"),
        ),
        run_compute_operations=run_compute_operations,
    )


def _resource_claims(
    points: Sequence[PointProgram],
    *,
    routes_by_point: Mapping[int, Sequence[PendingRoute]],
) -> tuple[ResourceClaim, ...]:
    claims: list[ResourceClaim] = []
    seen: set[tuple[str, str]] = set()

    def append(claim: ResourceClaim) -> None:
        key = (claim.kind, claim.id)
        if key not in seen:
            seen.add(key)
            claims.append(claim)

    for point in points:
        for operation in point.state_operations:
            append(ResourceClaim(operation.instrument_id))
        for action in point.actions:
            append(ResourceClaim(action.instrument_id))
        for operation in point.collect_operations:
            append(ResourceClaim(operation.instrument_id))

        bindings = (
            *(
                binding
                for route in routes_by_point.get(point.point_index, ())
                for binding in route.channel_bindings
            ),
            *(
                binding
                for operation in point.state_operations
                for target in operation.targets
                for binding in target.channel_bindings
            ),
            *(
                binding
                for action in point.actions
                for field in action.fields
                for binding in field.channel_bindings
            ),
            *(
                binding
                for operation in point.collect_operations
                for request in operation.command.requests
                for binding in request.channel_bindings
            ),
        )
        for binding in bindings:
            append(ResourceClaim(binding.channel_id, "channel"))
            for group_id in binding.group_ids:
                append(ResourceClaim(group_id, "group"))
    return tuple(claims)


def _explicit_instrument_order(
    instrument_order: Sequence[str],
    *,
    routes_by_point: Mapping[int, Sequence[PendingRoute]],
) -> tuple[str, ...]:
    selected = tuple(instrument_order)
    if len(selected) != len(set(selected)) or any(not item for item in selected):
        msg = "instrument_order must contain unique non-empty ids"
        raise ValueError(msg)
    routed = {
        route.resource_id.value
        for routes in routes_by_point.values()
        for route in routes
    }
    return (*selected, *sorted(routed - set(selected)))


def _order_instrument_operations[T: _InstrumentOperation](
    operations: Sequence[T],
    *,
    instrument_order: Sequence[str],
) -> tuple[T, ...]:
    by_instrument = {operation.instrument_id: operation for operation in operations}
    selected = tuple(
        by_instrument[instrument_id]
        for instrument_id in instrument_order
        if instrument_id in by_instrument
    )
    selected_ids = {operation.instrument_id for operation in selected}
    return (
        *selected,
        *sorted(
            (
                operation
                for operation in operations
                if operation.instrument_id not in selected_ids
            ),
            key=lambda operation: operation.instrument_id,
        ),
    )


def _resource_order(
    points: Sequence[PointProgram],
    *,
    instrument_order: Sequence[str],
) -> tuple[str, ...]:
    used = {
        operation.instrument_id
        for point in points
        for operation in (
            *point.state_operations,
            *point.actions,
            *point.collect_operations,
        )
    }
    selected = tuple(
        instrument_id for instrument_id in instrument_order if instrument_id in used
    )
    return (*selected, *sorted(used - set(selected)))


def _bind_routes(
    program: CoreProgram,
    environment: ValidatedConfigEnvironment,
    points: Sequence[MaterializedPoint],
    point_parameters: Mapping[int, ParameterRelationData],
    problems: list[Problem],
    *,
    verified_program: VerifiedCoreProgram,
) -> dict[int, tuple[PendingRoute, ...]]:
    routing = environment.routing
    if routing is None:
        return {}
    routes: dict[int, tuple[PendingRoute, ...]] = {}
    for point in points:
        params = point_parameters.get(point.logical_ordinal)
        if params is None:
            continue
        selected: list[PendingRoute] = []
        for intent in program.route_intents:
            ctx = EvalContext(params=params, point_row=point.row)
            entity_values: list[object] = []
            failed = False
            for use in intent.entity_uses:
                try:
                    entity_values.append(
                        _evaluate_value_expr(
                            use.value,
                            verified_program.relation_plan(use.id),
                            ctx,
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
                PendingRoute(
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


def _bind_compute_operations(
    nodes: Sequence[TypedComputeNode],
    *,
    point: MaterializedPoint,
    params: ParameterRelationData,
    routes: Sequence[PendingRoute],
    dependencies: Mapping[OperationId, ComputeDependencies],
    implementations: SelectedLocalImplementations,
    demanded_payload_results: set[ValueId],
    problems: list[Problem],
    verified_program: VerifiedCoreProgram,
) -> tuple[tuple[ComputeOperation, ...], dict[ValueId, str]]:
    operations: list[ComputeOperation] = []
    output_owners = {node.result.id: node.id for node in nodes}
    if len(output_owners) != len(nodes):
        msg = "typed compute graph contains duplicate result identities"
        raise ValueError(msg)
    signatures: dict[ValueId, str] = {}
    payload_ids: dict[ValueId, str] = {}
    ctx = EvalContext(params=params, point_row=point.row)
    for node in nodes:
        inputs: dict[str, BoundInput | OutputInput] = {}
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
                                verified_program.relation_plan(
                                    input_spec.relation_use_id
                                ),
                                ctx,
                            ),
                            path=("compute", *node.id.scope, node.id.local_id, name),
                        )
                    )
                    inputs[name] = BoundInput(value)
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
                    inputs[name] = OutputInput(input_spec.value_id)
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
                    inputs[name] = BoundInput(resolved)
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
        operations.append(
            ComputeOperation(
                operation_id=(
                    f"{point.logical_id.value}.compute.{node.id.qualified_name}"
                ),
                semantic_operation_id=node.id.qualified_name,
                implementation_id=implementation.implementation_id.value,
                contract=node.contract,
                kernel=implementation.kernel,
                inputs=inputs,
                result=ComputeResultSlot(
                    id=node.result.id,
                    value_type=node.result.value_type,
                ),
                dependencies=dict(dependencies[node.id].as_mapping()),
                payload_slot=(
                    PayloadSlot(id=payload_id, schema_id=schema_id)
                    if payload_id is not None and schema_id is not None
                    else None
                ),
            )
        )
    return tuple(operations), payload_ids


def _payload_schema(value_type: object) -> str | None:
    from scopecat.kernel.value_types import Payload

    if isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload):
        return value_type.atom.schema_id
    return None


def _bind_actions(
    records: Sequence[ActionRecord],
    *,
    routes: Sequence[PendingRoute],
    routing: RoutingView,
    payload_ids: Mapping[ValueId, str],
    known_compute_results: set[ValueId],
    point_index: int,
    point_uid: str,
    problems: list[Problem],
) -> tuple[InstrumentActionOperation, ...]:
    bound: list[InstrumentActionOperation] = []
    for record in records:
        try:
            resource_id, entity_ids, channel_bindings, unbound = _bind_state_resource(
                record.resource_port_id,
                capability_id=record.capability_id,
                route_entities=(),
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
                        "actions",
                        record.id.qualified_name,
                        "resource",
                    ),
                    category=ProblemCategory.UNAVAILABLE,
                )
            )
            continue
        if unbound:
            problems.append(
                _problem(
                    "action_route_entity_unbound",
                    "action route entities are not bound: " + ", ".join(unbound),
                    model_location(
                        "points",
                        point_index,
                        "actions",
                        record.id.qualified_name,
                        "resource",
                    ),
                    category=ProblemCategory.UNAVAILABLE,
                )
            )
            continue
        fields: list[ActionField] = []
        for field in record.fields:
            if isinstance(field.value, ComputeResultRef):
                if field.value.value_id not in known_compute_results:
                    problems.append(
                        _problem(
                            "compute_payload_unknown_output",
                            "action references unknown compute result "
                            f"{field.value.value_id.qualified_name!r}",
                            model_location(
                                "actions",
                                record.id.qualified_name,
                                "fields",
                                field.id,
                            ),
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
                    continue
                if field.value.value_id not in payload_ids:
                    problems.append(
                        _problem(
                            "compute_payload_unavailable",
                            "action compute output is not an available payload: "
                            f"{field.value.value_id.qualified_name!r}",
                            model_location(
                                "actions",
                                record.id.qualified_name,
                                "fields",
                                field.id,
                            ),
                        )
                    )
                    continue
            value = _state_value(field.value, payload_ids=payload_ids)
            if value is None:
                problems.append(
                    _problem(
                        "action_value_unsupported",
                        "action values must be primitive scalars, finite quantities, "
                        "or payload outputs",
                        model_location(
                            "actions",
                            record.id.qualified_name,
                            "fields",
                            field.id,
                        ),
                    )
                )
                continue
            fields.append(
                ActionField(
                    id=field.id,
                    value=value,
                    entity_ids=entity_ids,
                    channel_bindings=tuple(
                        _command_channel_binding(binding)
                        for binding in channel_bindings
                    ),
                )
            )
        bound.append(
            InstrumentActionOperation(
                operation_id=f"{point_uid}.action.{record.id.qualified_name}",
                instrument_id=resource_id.value,
                capability_id=record.capability_id,
                fields=tuple(fields),
            )
        )
    return tuple(bound)


def _command_channel_binding(
    binding: RoutingChannelBinding,
) -> CommandChannelBinding:
    return CommandChannelBinding(
        entity_id=binding.entity_id,
        channel_id=binding.channel_id,
        line_id=binding.line_id,
        capability=binding.capability,
        group_ids=list(binding.group_ids),
        metadata=dict(binding.metadata),
    )


def _bind_desired_state(
    records: Sequence[StateRecord],
    *,
    routes: Sequence[PendingRoute],
    routing: RoutingView,
    payload_ids: Mapping[ValueId, str],
    known_compute_results: set[ValueId],
    point_index: int,
    problems: list[Problem],
) -> tuple[PendingResourceState, ...]:
    grouped: dict[
        tuple[PhysicalResourceId, str],
        dict[tuple[str, tuple[str, ...], _ChannelSignature], PendingStateField],
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
        channel_key = channel_signature(channel_bindings)
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
            PendingStateField(
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
        PendingResourceState(
            resource_id=resource,
            capability_id=capability,
            fields=tuple(fields.values()),
        )
        for (resource, capability), fields in grouped.items()
    )


def _state_operations(
    point_uid: str,
    states: Sequence[PendingResourceState],
) -> tuple[ApplyStateOperation, ...]:
    grouped: dict[str, list[PendingResourceState]] = {}
    for state in states:
        grouped.setdefault(state.resource_id.value, []).append(state)
    return tuple(
        ApplyStateOperation(
            operation_id=f"{point_uid}.state.{instrument_id}",
            instrument_id=instrument_id,
            targets=tuple(
                StateTarget(
                    capability_id=state.capability_id,
                    field_path=field.field_path,
                    value=field.value,
                    entity_ids=field.entity_ids,
                    channel_bindings=tuple(
                        _command_channel_binding(binding)
                        for binding in field.channel_bindings
                    ),
                )
                for state in instrument_states
                for field in state.fields
            ),
        )
        for instrument_id, instrument_states in grouped.items()
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
    if isinstance(value, bool | int | str):
        return StateValue(value)
    if isinstance(value, float):
        return StateValue(value) if math.isfinite(value) else None
    return None


def _bind_state_resource(
    target: ResourceTarget,
    *,
    capability_id: str,
    route_entities: Sequence[object],
    routes: Sequence[PendingRoute],
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
    route: PendingRoute,
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


def channel_signature(
    bindings: Sequence[RoutingChannelBinding],
) -> _ChannelSignature:
    return tuple(_channel_binding_identity(binding) for binding in bindings)


def _bind_collect(
    products: Sequence[ProductDef],
    producers: Sequence[InstrumentProductProducer],
    realizations: SelectedLocalProductRealizations,
    routes: Sequence[PendingRoute],
    *,
    routing: RoutingView,
    point_index: int,
    problems: list[Problem],
) -> tuple[PendingCollect, ...]:
    products_by_id = {product.id: product for product in products}
    producers_by_id = {producer.id: producer for producer in producers}
    grouped: dict[PhysicalResourceId, list[PendingCollectionRequest]] = {}
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
        request = PendingCollectionRequest(
            product_use_id=realization.product_use_id,
            product_id=product.id,
            provider_key=producer.provider_key,
            capability=producer.capability,
            unit=product.unit,
            dtype=product.dtype,
            resource_port_id=resource_port_id,
            entity_ids=entity_ids,
            channel_bindings=channel_bindings,
            axes=product.axes,
            metadata=dict(producer.metadata),
        )
        grouped.setdefault(resource_id, []).append(request)
    return tuple(
        PendingCollect(resource_id=resource_id, requests=tuple(requests))
        for resource_id, requests in grouped.items()
    )


def _collect_operations(
    point_uid: str,
    *,
    point_index: int,
    point_count: int,
    collects: Sequence[PendingCollect],
) -> tuple[CollectOperation, ...]:
    operations: list[CollectOperation] = []
    for collect in collects:
        instrument_id = collect.resource_id.value
        operation_id = f"{point_uid}.collect.{instrument_id}"
        operations.append(
            CollectOperation(
                operation_id=operation_id,
                instrument_id=instrument_id,
                result_bindings=tuple(
                    CollectionResultBinding(
                        provider_key=request.provider_key,
                        product_use_id=request.product_use_id,
                        product_id=request.product_id,
                    )
                    for request in collect.requests
                ),
                command=CollectCommand(
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                    point_index=point_index,
                    point_count=point_count,
                    requests=[
                        CollectProductRequest(
                            id=request.provider_key,
                            capability_id=request.capability,
                            unit=request.unit,
                            dtype=request.dtype,
                            dimensions=[
                                CollectAxisRequest(
                                    id=axis.id,
                                    kind=axis.kind,
                                    size=axis.size,
                                    unit=axis.unit,
                                    metadata=cast(
                                        "dict[str, JsonValue]",
                                        thaw_json_value(axis.metadata),
                                    ),
                                )
                                for axis in request.axes
                            ],
                            entity_ids=list(request.entity_ids),
                            channel_bindings=[
                                _command_channel_binding(binding)
                                for binding in request.channel_bindings
                            ],
                            metadata=cast(
                                "dict[str, JsonValue]",
                                thaw_json_value(request.metadata),
                            ),
                        )
                        for request in collect.requests
                    ],
                ),
            )
        )
    return tuple(operations)


def _bind_record_target(
    target: ResourceTarget | None,
    *,
    implicit_resource_id: PhysicalResourceId | None,
    capability: str | None,
    routes: Sequence[PendingRoute],
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
            _normalize_collection_channel_bindings(
                binding.channel_bindings,
                capability=capability,
            ),
        )
    channel_bindings = _normalize_collection_channel_bindings(
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
    collects: Sequence[PendingCollect],
    *,
    point_index: int,
    problems: list[Problem],
) -> bool:
    valid = True
    for collect in collects:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for request in collect.requests:
            if request.provider_key in seen:
                duplicates.add(request.provider_key)
            seen.add(request.provider_key)
        for provider_key in sorted(duplicates):
            valid = False
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
    return valid


def _evaluate_value_expr(
    value: ValueExpr | object,
    relation_plan: VerifiedRelationPlan[PlanNode],
    ctx: EvalContext,
) -> object:
    if isinstance(value, ScalarValueExpr):
        return evaluate_scalar(
            cast("VerifiedRelationPlan[ScalarExpr]", relation_plan),
            ctx,
        )
    if isinstance(value, SeriesValueExpr):
        return evaluate_series(
            cast("VerifiedRelationPlan[SeriesExpr]", relation_plan),
            ctx,
        )
    if isinstance(value, TableValueExpr):
        return evaluate_relation_in_context(
            cast("VerifiedRelationPlan[RelationExpr]", relation_plan),
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
