"""Specialize one linked program into final point-local execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import replace
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
)
from scopecat.compiler.linking.product_realizations import (
    SelectedLocalProductRealizations,
    select_local_product_realizations,
)
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.typed.action import (
    ActionRecord,
    ActionSpec,
    evaluate_action_spec,
)
from scopecat.compiler.typed.dependencies import (
    ComputePlan,
    PointVariationSupport,
)
from scopecat.compiler.typed.point_domain import (
    MaterializedPoint,
)
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
)
from scopecat.compiler.typed.records import (
    point_coordinate_ids,
)
from scopecat.compiler.typed.state import (
    StateRecord,
    StateSpecVariant,
    evaluate_state_spec,
)
from scopecat.compiler.typed.verification import (
    VerifiedCoreProgram,
)
from scopecat.execution.local.program import (
    ActionField,
    ApplyStateOperation,
    CollectionResultBinding,
    CollectOperation,
    ComputeOperation,
    InstrumentActionOperation,
    StateTarget,
)
from scopecat.execution.program import RunCoverageEffect
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
    model_location,
)
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
    ResourceTarget,
)
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.planning.local_compute import (
    bind_compute_operations as _bind_compute_operations,
)
from scopecat.planning.local_effects import (
    ComputeBindingSeed,
    LocalTargetPlan,
    MaterializedLocalEffects,
)
from scopecat.planning.local_route_constraints import (
    PendingCollect,
    PendingCollectionRequest,
    PendingResourceState,
    PendingRoute,
    PendingStateField,
    validate_point_resource_constraints,
)
from scopecat.planning.local_values import evaluate_value_expr
from scopecat.planning.routing import RoutingError, RoutingView
from scopecat.records.config import RoutingChannelBinding
from scopecat.records.entity import EntityRef
from scopecat.records.instrument import CommandChannelBinding
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


def materialize_local_execution(
    linked_points: MaterializedLinkedPoints,
    *,
    target: LocalTargetPlan,
    point_count: int,
) -> MaterializedLocalEffects:
    """Lower local work without discarding the ordered Core effect sequence."""

    linked = linked_points.linked_plan
    program = target.program
    if linked.program.id != program.id:
        raise ValueError("local target plan belongs to a different program")
    environment = linked.environment
    routing = environment.routing
    if routing is None:
        raise AssertionError("linked plan lost its validated routing view")
    problems = list(environment.problems)
    verified_program = linked_points.verified_program
    implementations = target.implementations
    product_realizations = target.product_realizations
    selected_compute_plan = verified_program.compute_plan
    selected_instrument_order = target.instrument_order
    compute_seed = target.compute_seed
    materialized_domain = linked_points.point_domain
    planner_points = materialized_domain.points
    try:
        point_coordinate_ids(planner_points)
    except ValueError as error:
        problems.append(
            _problem(
                "experiment_point_schema_invalid",
                f"experiment point schema is invalid: {error}",
                model_location("points"),
            )
        )
    point_by_ordinal = {point.logical_ordinal: point for point in planner_points}
    params_by_ordinal = {
        point.logical_ordinal: params
        for point, params in zip(
            planner_points,
            linked_points.point_parameters,
            strict=True,
        )
    }
    rows = {ordinal: point.row for ordinal, point in point_by_ordinal.items()}
    ordinals = tuple(point.logical_ordinal for point in planner_points)
    layout = linked_points.verified_program.iteration_layout
    route_cache: dict[tuple[str, str], PendingRoute | None] = {}
    payload_ids_by_ordinal: dict[int, dict[ValueId, str]] = {
        ordinal: dict(compute_seed.payload_ids) for ordinal in ordinals
    }
    signatures_by_ordinal = {
        ordinal: dict(compute_seed.signatures) for ordinal in ordinals
    }
    compute_effects: list[RunCoverageEffect] = []
    for node in selected_compute_plan.point_nodes:
        support = target.variation.compute[node.id]
        for compute_coverage in layout.partition(
            support.point_columns,
            ordinals,
            rows=rows,
        ):
            representative = point_by_ordinal[compute_coverage[0]]
            representative_params = params_by_ordinal[compute_coverage[0]]
            routes = _bind_point_routes(
                program,
                environment,
                representative,
                representative_params,
                problems,
                verified_program=verified_program,
                variation_support=target.variation.routes,
                cache=route_cache,
            )
            compute_operations, point_payload_ids, signatures = (
                _bind_compute_operations(
                    (node,),
                    operation_prefix=representative.logical_id.value,
                    ctx=EvalContext(
                        params=representative_params,
                        point_row=representative.row,
                    ),
                    routes=routes,
                    compute_plan=selected_compute_plan,
                    implementations=implementations,
                    demanded_payload_results=set(
                        selected_compute_plan.demanded_payload_results
                    ),
                    problems=problems,
                    verified_program=verified_program,
                    initial_signatures=signatures_by_ordinal[
                        representative.logical_ordinal
                    ],
                )
            )
            for ordinal in compute_coverage:
                signatures_by_ordinal[ordinal] = dict(signatures)
                payload_ids_by_ordinal[ordinal].update(point_payload_ids)
            compute_effects.extend(
                RunCoverageEffect(compute_coverage, operation)
                for operation in compute_operations
            )

    effect_operations: list[list[RunCoverageEffect]] = [
        [] for _effect in program.effects
    ]
    desired_by_ordinal: dict[int, list[PendingResourceState]] = {
        ordinal: [] for ordinal in ordinals
    }
    state_support_by_effect: dict[int, PointVariationSupport] = {}
    state_index = 0
    for effect_index, effect in enumerate(program.effects):
        if isinstance(effect, TypedDomainExecution | ActionSpec):
            continue
        state_support_by_effect[effect_index] = target.variation.state[state_index]
        state_index += 1
    known_compute_results = {node.result.id for node in program.compute_nodes}
    for effect_index, effect in enumerate(program.effects):
        if isinstance(effect, TypedDomainExecution):
            continue
        if isinstance(effect, ActionSpec):
            for ordinal in ordinals:
                point = point_by_ordinal[ordinal]
                params = params_by_ordinal[ordinal]
                routes = _bind_point_routes(
                    program,
                    environment,
                    point,
                    params,
                    problems,
                    verified_program=verified_program,
                    variation_support=target.variation.routes,
                    cache=route_cache,
                )
                actions = _bind_actions(
                    _evaluate_action_records(
                        effect,
                        effect_index,
                        point,
                        params,
                        verified_program=verified_program,
                        problems=problems,
                    ),
                    routes=routes,
                    routing=routing,
                    payload_ids=payload_ids_by_ordinal[ordinal],
                    known_compute_results=known_compute_results,
                    point_index=ordinal,
                    point_uid=point.logical_id.value,
                    problems=problems,
                )
                ordered = _order_instrument_operations(
                    actions,
                    instrument_order=selected_instrument_order,
                )
                effect_operations[effect_index].extend(
                    RunCoverageEffect.at_point(ordinal, operation)
                    for operation in ordered
                )
            continue

        if effect_index and not isinstance(
            program.effects[effect_index - 1],
            TypedDomainExecution | ActionSpec,
        ):
            continue
        state_end = effect_index + 1
        while state_end < len(program.effects) and not isinstance(
            program.effects[state_end],
            TypedDomainExecution | ActionSpec,
        ):
            state_end += 1
        state_group: list[tuple[int, StateSpecVariant]] = []
        for index in range(effect_index, state_end):
            state = program.effects[index]
            if isinstance(state, TypedDomainExecution | ActionSpec):
                raise AssertionError("state region contains a non-state effect")
            state_group.append((index, state))
        support = PointVariationSupport()
        for index, _state in state_group:
            support = support.merged(state_support_by_effect[index])
        for state_coverage in layout.partition(
            support.point_columns,
            ordinals,
            rows=rows,
        ):
            representative = point_by_ordinal[state_coverage[0]]
            representative_params = params_by_ordinal[state_coverage[0]]
            routes = _bind_point_routes(
                program,
                environment,
                representative,
                representative_params,
                problems,
                verified_program=verified_program,
                variation_support=target.variation.routes,
                cache=route_cache,
            )
            desired = _bind_desired_state(
                tuple(
                    record
                    for index, state in state_group
                    for record in _evaluate_state_records(
                        state,
                        index,
                        representative,
                        representative_params,
                        verified_program=verified_program,
                        problems=problems,
                    )
                ),
                routes=routes,
                routing=routing,
                payload_ids=payload_ids_by_ordinal[representative.logical_ordinal],
                known_compute_results=known_compute_results,
                point_index=representative.logical_ordinal,
                problems=problems,
            )
            ordered = _order_instrument_operations(
                _state_operations(representative.logical_id.value, desired),
                instrument_order=selected_instrument_order,
            )
            effect_operations[state_end - 1].extend(
                RunCoverageEffect(state_coverage, operation) for operation in ordered
            )
            for ordinal in state_coverage:
                desired_by_ordinal[ordinal].extend(desired)

    collect_effects: list[RunCoverageEffect] = []
    for ordinal in ordinals:
        point = point_by_ordinal[ordinal]
        params = params_by_ordinal[ordinal]
        routes = _bind_point_routes(
            program,
            environment,
            point,
            params,
            problems,
            verified_program=verified_program,
            variation_support=target.variation.routes,
            cache=route_cache,
        )
        collect = _bind_collect(
            program.product_defs,
            program.instrument_product_producers,
            product_realizations,
            routes,
            routing=routing,
            point_index=ordinal,
            problems=problems,
        )
        problems.extend(
            validate_point_resource_constraints(
                ordinal,
                routes,
                desired_by_ordinal[ordinal],
                collect,
                config=environment.config,
            )
        )
        valid_collect = _validate_collection_requests(
            collect,
            point_index=ordinal,
            problems=problems,
        )
        collect_operations = (
            _order_instrument_operations(
                _collect_operations(
                    point.logical_id.value,
                    point_index=ordinal,
                    point_count=point_count,
                    collects=collect,
                ),
                instrument_order=selected_instrument_order,
            )
            if valid_collect
            else ()
        )
        collect_effects.extend(
            RunCoverageEffect.at_point(ordinal, operation)
            for operation in collect_operations
        )
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return MaterializedLocalEffects(
        compute_operations=tuple(compute_effects),
        effect_operations=tuple(tuple(items) for items in effect_operations),
        collect_operations=tuple(collect_effects),
    )


def prepare_local_target(
    linked: LinkedPlan,
    *,
    product_use_ids: AbstractSet[ProductUseId],
    instrument_order: Sequence[str] = (),
) -> LocalTargetPlan:
    """Select and bind the complete local target once for all coverage blocks."""

    requested = frozenset(product_use_ids)
    available = {use.id for use in linked.program.product_uses}
    unknown = sorted(use_id.value for use_id in requested - available)
    if unknown:
        msg = "local product selection contains unknown uses: " + ", ".join(unknown)
        raise ValueError(msg)
    program = replace(
        linked.program,
        product_uses=tuple(
            use for use in linked.program.product_uses if use.id in requested
        ),
        record_uses=tuple(
            record
            for record in linked.program.record_uses
            if record.product_use_id in requested
        ),
    )
    problems = list(linked.environment.problems)
    implementations, implementation_problems = select_local_implementations(
        program.compute_nodes,
        program.implementation_catalog,
        phase=ProblemPhase.PLANNING,
    )
    problems.extend(implementation_problems)
    routing = linked.environment.routing
    if routing is None:
        raise AssertionError("linked plan lost its validated routing view")
    product_realizations, product_problems = select_local_product_realizations(
        program.product_defs,
        program.instrument_product_producers,
        program.product_uses,
        routing=routing,
        phase=ProblemPhase.PLANNING,
    )
    problems.extend(product_problems)
    if (
        implementations is None
        or product_realizations is None
        or has_blocking_problems(problems)
    ):
        raise CheckFailed(problems)
    compute_plan = linked.verified_program.compute_plan
    run_operations, compute_seed = _bind_run_compute(
        linked,
        compute_plan,
        implementations=implementations,
        problems=problems,
    )
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return LocalTargetPlan(
        program=program,
        implementations=implementations,
        product_realizations=product_realizations,
        instrument_order=_validate_instrument_order(instrument_order),
        variation=linked.verified_program.variation_analysis,
        run_operations=run_operations,
        compute_seed=compute_seed,
    )


def _evaluate_state_records(
    state: StateSpecVariant,
    effect_index: int,
    point: MaterializedPoint,
    params: ParameterRelationData,
    *,
    verified_program: VerifiedCoreProgram,
    problems: list[Problem],
) -> tuple[StateRecord, ...]:
    ctx = EvalContext(params=params, point_row=point.row)
    try:
        return tuple(
            evaluate_state_spec(
                state,
                point_index=point.logical_ordinal,
                ctx=ctx,
                relation_plan=verified_program.relation_plan,
                location=model_location("effects", effect_index),
            )
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        problems.append(
            _problem(
                "experiment_state_evaluation_failed",
                f"state binding failed for point {point.logical_ordinal}: {error}",
                model_location("effects", effect_index),
            )
        )
        return ()


def _evaluate_action_records(
    action: ActionSpec,
    effect_index: int,
    point: MaterializedPoint,
    params: ParameterRelationData,
    *,
    verified_program: VerifiedCoreProgram,
    problems: list[Problem],
) -> tuple[ActionRecord, ...]:
    ctx = EvalContext(params=params, point_row=point.row)
    try:
        return (
            evaluate_action_spec(
                action,
                point_index=point.logical_ordinal,
                ctx=ctx,
                relation_plan=verified_program.relation_plan,
            ),
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        problems.append(
            _problem(
                "experiment_action_evaluation_failed",
                f"action binding failed for point {point.logical_ordinal}: {error}",
                model_location("effects", effect_index),
            )
        )
        return ()


def _bind_run_compute(
    linked: LinkedPlan,
    compute_plan: ComputePlan,
    *,
    implementations: SelectedLocalImplementations,
    problems: list[Problem],
) -> tuple[tuple[ComputeOperation, ...], ComputeBindingSeed]:
    operations, payload_ids, signatures = _bind_compute_operations(
        compute_plan.run_nodes,
        operation_prefix="run",
        ctx=EvalContext(params=linked.environment.parameters),
        routes=(),
        compute_plan=compute_plan,
        implementations=implementations,
        demanded_payload_results=set(compute_plan.demanded_payload_results),
        problems=problems,
        verified_program=linked.verified_program,
    )
    return operations, ComputeBindingSeed(
        signatures=signatures,
        payload_ids=payload_ids,
    )


def _validate_instrument_order(
    instrument_order: Sequence[str],
) -> tuple[str, ...]:
    selected = tuple(instrument_order)
    if len(selected) != len(set(selected)) or any(not item for item in selected):
        msg = "instrument_order must contain unique non-empty ids"
        raise ValueError(msg)
    return selected


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


def _bind_point_routes(
    program: CoreProgram,
    environment: ValidatedConfigEnvironment,
    point: MaterializedPoint,
    params: ParameterRelationData,
    problems: list[Problem],
    *,
    verified_program: VerifiedCoreProgram,
    variation_support: Mapping[str, PointVariationSupport],
    cache: dict[tuple[str, str], PendingRoute | None],
) -> tuple[PendingRoute, ...]:
    routing = environment.routing
    if routing is None:
        return ()
    selected: list[PendingRoute] = []
    for intent in program.route_intents:
        port_id = intent.port_id.qualified_name
        key = (
            port_id,
            verified_program.iteration_layout.projection_key(
                variation_support[port_id].point_columns,
                point.logical_ordinal,
                fallback_row=point.row,
            ),
        )
        if key in cache:
            cached = cache[key]
            if cached is not None:
                selected.append(cached)
            continue
        ctx = EvalContext(params=params, point_row=point.row)
        entity_values: list[object] = []
        failed = False
        for use in intent.entity_uses:
            try:
                entity_values.append(
                    evaluate_value_expr(
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
            cache[key] = None
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
            cache[key] = None
            continue
        route = PendingRoute(
            port_id=binding.port_id,
            resource_id=binding.resource_id,
            resource_kind=binding.resource_kind,
            capabilities=tuple(binding.capabilities),
            entity_ids=tuple(binding.entity_ids),
            served_entity_ids=tuple(binding.served_entity_ids),
            product_axis_order=tuple(binding.product_axis_order),
            channel_bindings=tuple(binding.channel_bindings),
        )
        cache[key] = route
        selected.append(route)
    return tuple(selected)


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


def _problem(
    code: str,
    message: str,
    location: ModelLocation,
    *,
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
) -> Problem:
    return compiler_problem(code, message, location, category=category)
