"""Specialize linked host semantics into final local operations.

Preparation selects implementations and run-invariant compute once. Bounded
materialization selects logical entities and binds state, actions, compute, and
collection to the static resource manifests prepared for the local target.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import Protocol, cast

from pydantic import JsonValue

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.linking.implementations import (
    SelectedLocalImplementations,
    select_local_implementations,
)
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
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
from scopecat.compiler.typed.products import ProductAxisDef, ProductDef
from scopecat.compiler.typed.program import (
    AcquireSpec,
    CoreProgram,
    TypedDomainExecution,
)
from scopecat.compiler.typed.records import (
    point_coordinate_ids,
)
from scopecat.compiler.typed.state import (
    SetStateSpec,
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
from scopecat.kernel.content_identity import stable_content_hash
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
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.measurements.results import MeasurementDType
from scopecat.planning.local_compute import (
    bind_compute_operations as _bind_compute_operations,
)
from scopecat.planning.local_effects import (
    ComputeBindingSeed,
    LocalTargetPlan,
    MaterializedLocalEffects,
)
from scopecat.planning.local_values import evaluate_value_expr
from scopecat.planning.routing import (
    ResourceBinding,
    ResourceBindingError,
    ResourcePortManifest,
    RoutingView,
)
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


@dataclass(frozen=True, slots=True)
class _ResourceEntitySelection:
    """Point-local logical entity ids paired with one static manifest."""

    manifest: ResourcePortManifest
    entity_ids: tuple[str, ...] = ()

    def select_one(self) -> ResourceBinding:
        return self.manifest.select_one(self.entity_ids)


def _normalize_entity_ids(values: Sequence[object]) -> tuple[str, ...]:
    entity_ids: list[str] = []
    for value in values:
        if isinstance(value, EntityRef):
            if not value.id:
                raise ResourceBindingError(
                    "module_resource_entity_invalid",
                    "resource entity id must be non-empty",
                )
            entity_ids.append(value.id)
        elif isinstance(value, str) and value:
            entity_ids.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            if not value:
                raise ResourceBindingError(
                    "module_resource_entity_invalid",
                    "resource entity series must not be empty",
                )
            entity_ids.extend(_normalize_entity_ids(value))
        else:
            raise ResourceBindingError(
                "module_resource_entity_invalid",
                f"resource entity must resolve to an entity reference, got {value!r}",
            )
    return tuple(dict.fromkeys(entity_ids))


def _empty_metadata() -> dict[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class _PendingStateField:
    field_path: str
    value: StateValue
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingResourceState:
    instrument_id: str
    capability_id: str
    fields: tuple[_PendingStateField, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingCollectionRequest:
    product_use_ids: tuple[ProductUseId, ...]
    product_id: ProductId
    provider_key: str
    capability: str
    unit: str | None
    dtype: MeasurementDType
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()
    axes: tuple[ProductAxisDef, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class _PendingCollect:
    instrument_id: str
    requests: tuple[_PendingCollectionRequest, ...]


def _collection_channel_bindings(
    bindings: Sequence[CommandChannelBinding],
    *,
    capability: str,
) -> tuple[CommandChannelBinding, ...]:
    return tuple(binding for binding in bindings if binding.capability == capability)


class _InstrumentOperation(Protocol):
    @property
    def instrument_id(self) -> str: ...


def materialize_local_execution(
    linked_points: MaterializedLinkedPoints,
    *,
    target: LocalTargetPlan,
    point_count: int,
) -> MaterializedLocalEffects:
    """Lower one bounded point coverage into final ordered local effects.

    Structural variation selects representative points for safe reuse while
    exact coverage preserves logical ownership of every resulting operation.
    """

    linked = linked_points.linked_plan
    program = target.program
    if linked.program.id != program.id:
        raise ValueError("local target plan belongs to a different program")
    environment = linked.environment
    problems = list(environment.problems)
    verified_program = linked_points.verified_program
    implementations = target.implementations
    selected_compute_plan = verified_program.compute_plan
    variation = verified_program.variation_analysis
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
    resources_by_ordinal = _select_coverage_resources(
        program,
        target.resource_ports,
        planner_points,
        params_by_ordinal,
        problems,
        verified_program=verified_program,
        variation_support=variation.resource_entities,
    )
    payload_ids_by_ordinal: dict[int, dict[ValueId, str]] = {
        ordinal: dict(compute_seed.payload_ids) for ordinal in ordinals
    }
    signatures_by_ordinal = {
        ordinal: dict(compute_seed.signatures) for ordinal in ordinals
    }
    compute_effects: list[RunCoverageEffect] = []
    for node in selected_compute_plan.point_nodes:
        support = variation.compute[node.id]
        for compute_coverage in layout.partition(
            support.point_columns,
            ordinals,
            rows=rows,
        ):
            representative = point_by_ordinal[compute_coverage[0]]
            representative_params = params_by_ordinal[compute_coverage[0]]
            compute_operations, point_payload_ids, signatures = (
                _bind_compute_operations(
                    (node,),
                    operation_prefix=representative.logical_id.value,
                    ctx=EvalContext(
                        params=representative_params,
                        point_row=representative.row,
                    ),
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
    state_support_by_effect: dict[int, PointVariationSupport] = {}
    state_index = 0
    for effect_index, effect in enumerate(program.effects):
        if isinstance(effect, TypedDomainExecution | ActionSpec | AcquireSpec):
            continue
        state_support_by_effect[effect_index] = variation.state[state_index]
        state_index += 1
    known_compute_results = {node.result.id for node in program.compute_nodes}
    for effect_index, effect in enumerate(program.effects):
        if isinstance(effect, TypedDomainExecution):
            continue
        if isinstance(effect, AcquireSpec):
            for ordinal in ordinals:
                point = point_by_ordinal[ordinal]
                resources = resources_by_ordinal[ordinal]
                collect = _bind_collect(
                    program.product_defs,
                    program.product_uses,
                    effect,
                    resources,
                    point_index=ordinal,
                    problems=problems,
                )
                if collect is not None:
                    operation = _collect_operation(
                        point.logical_id.value,
                        acquisition_id=effect.id.qualified_name,
                        point_index=ordinal,
                        point_count=point_count,
                        collect=collect,
                    )
                    effect_operations[effect_index].append(
                        RunCoverageEffect.at_point(ordinal, operation)
                    )
            continue
        if isinstance(effect, ActionSpec):
            for ordinal in ordinals:
                point = point_by_ordinal[ordinal]
                params = params_by_ordinal[ordinal]
                resources = resources_by_ordinal[ordinal]
                actions = _bind_actions(
                    _evaluate_action_records(
                        effect,
                        effect_index,
                        point,
                        params,
                        verified_program=verified_program,
                        problems=problems,
                    ),
                    resources=resources,
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
            TypedDomainExecution | ActionSpec | AcquireSpec,
        ):
            continue
        state_end = effect_index + 1
        while state_end < len(program.effects) and not isinstance(
            program.effects[state_end],
            TypedDomainExecution | ActionSpec | AcquireSpec,
        ):
            state_end += 1
        state_group: list[tuple[int, StateSpecVariant]] = []
        for index in range(effect_index, state_end):
            state = program.effects[index]
            if isinstance(state, TypedDomainExecution | ActionSpec | AcquireSpec):
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
            resources = resources_by_ordinal[representative.logical_ordinal]
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
                resources=resources,
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
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return MaterializedLocalEffects(
        compute_operations=tuple(compute_effects),
        effect_operations=tuple(tuple(items) for items in effect_operations),
    )


def prepare_local_target(
    linked: LinkedPlan,
    *,
    product_use_ids: AbstractSet[ProductUseId],
    instrument_order: Sequence[str] = (),
) -> LocalTargetPlan:
    """Select the complete local target once for all bounded coverage.

    Product demand is closed before physical binding so an acquisition with no
    live product cannot create a spurious missing or ambiguous hardware error.
    Only surviving local effects receive static manifests.
    """

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
    if implementations is None or has_blocking_problems(problems):
        raise CheckFailed(problems)
    active_resource_ports = _active_resource_port_ids(program)
    resource_ports: dict[LogicalResourcePortId, ResourcePortManifest] = {}
    if active_resource_ports:
        physical_resources = RoutingView.from_config(linked.environment.config)
        resource_ports = {
            requirement.port_id: physical_resources.bind_port(
                port_id=requirement.port_id,
                capabilities=requirement.capabilities,
            )
            for requirement in program.resource_requirements
            if requirement.port_id in active_resource_ports
        }
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
        instrument_order=_validate_instrument_order(instrument_order),
        resource_ports=resource_ports,
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


def _select_coverage_resources(
    program: CoreProgram,
    resource_ports: Mapping[LogicalResourcePortId, ResourcePortManifest],
    points: Sequence[MaterializedPoint],
    params_by_ordinal: Mapping[int, ParameterRelationData],
    problems: list[Problem],
    *,
    verified_program: VerifiedCoreProgram,
    variation_support: Mapping[str, PointVariationSupport],
) -> dict[int, Mapping[LogicalResourcePortId, _ResourceEntitySelection]]:
    """Evaluate point-local entities over the target's static port manifests.

    Variation keys reuse identical logical selections. Physical endpoint
    candidates were already frozen while preparing the local target.
    """

    cache: dict[tuple[str, str], _ResourceEntitySelection | None] = {}
    return {
        point.logical_ordinal: _select_point_resources(
            program,
            resource_ports,
            point,
            params_by_ordinal[point.logical_ordinal],
            problems,
            verified_program=verified_program,
            variation_support=variation_support,
            cache=cache,
        )
        for point in points
    }


def _select_point_resources(
    program: CoreProgram,
    resource_ports: Mapping[LogicalResourcePortId, ResourcePortManifest],
    point: MaterializedPoint,
    params: ParameterRelationData,
    problems: list[Problem],
    *,
    verified_program: VerifiedCoreProgram,
    variation_support: Mapping[str, PointVariationSupport],
    cache: dict[tuple[str, str], _ResourceEntitySelection | None],
) -> Mapping[LogicalResourcePortId, _ResourceEntitySelection]:
    selected: dict[LogicalResourcePortId, _ResourceEntitySelection] = {}
    for requirement in program.resource_requirements:
        manifest = resource_ports.get(requirement.port_id)
        if manifest is None:
            continue
        port_id = requirement.port_id.qualified_name
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
                selected[cached.manifest.port_id] = cached
            continue
        ctx = EvalContext(params=params, point_row=point.row)
        entity_values: list[object] = []
        failed = False
        for use in requirement.entity_uses:
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
                        "experiment_resource_entity_evaluation_failed",
                        f"resource {requirement.port_id.qualified_name} entity "
                        "expression failed for "
                        f"point {point.logical_ordinal}: {error}",
                        model_location(
                            "resources",
                            requirement.port_id.qualified_name,
                        ),
                    )
                )
        if failed:
            cache[key] = None
            continue
        try:
            resource = _ResourceEntitySelection(
                manifest=manifest,
                entity_ids=_normalize_entity_ids(entity_values),
            )
        except ResourceBindingError as error:
            problems.append(
                _problem(
                    error.code,
                    str(error),
                    model_location(
                        "resources",
                        requirement.port_id.qualified_name,
                    ),
                    category=(
                        ProblemCategory.CONFLICT
                        if error.code.endswith("_ambiguous")
                        else ProblemCategory.UNAVAILABLE
                    ),
                )
            )
            cache[key] = None
            continue
        cache[key] = resource
        selected[resource.manifest.port_id] = resource
    return selected


def _active_resource_port_ids(
    program: CoreProgram,
) -> frozenset[LogicalResourcePortId]:
    """Return ports consumed by effects that survive product demand closure.

    Physical binding must happen after this cut; otherwise an unused
    acquisition could still make unavailable or ambiguous hardware block a run.
    """

    demanded_products = {use.product_id for use in program.product_uses}
    selected: set[LogicalResourcePortId] = set()
    for effect in program.effects:
        if isinstance(effect, AcquireSpec):
            if any(
                product_id in demanded_products for product_id in effect.product_ids
            ):
                selected.add(effect.resource_port_id)
        elif isinstance(effect, ActionSpec):
            selected.add(effect.resource_port_id)
        elif not isinstance(effect, TypedDomainExecution):
            selected.update(_state_resource_port_ids(effect))
    return frozenset(selected)


def _state_resource_port_ids(
    state: StateSpecVariant,
) -> tuple[LogicalResourcePortId, ...]:
    if isinstance(state, SetStateSpec):
        return (state.resource_target.port_id,)
    return tuple(
        port_id for child in state.state for port_id in _state_resource_port_ids(child)
    )


def _bind_actions(
    records: Sequence[ActionRecord],
    *,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
    payload_ids: Mapping[ValueId, str],
    known_compute_results: set[ValueId],
    point_index: int,
    point_uid: str,
    problems: list[Problem],
) -> tuple[InstrumentActionOperation, ...]:
    bound: list[InstrumentActionOperation] = []
    for record in records:
        try:
            binding = _bind_single_resource(
                record.resource_port_id,
                resources=resources,
                missing_code="action_resource_port_unbound",
            )
            entity_ids, channel_bindings, _unbound = _logical_state_target(
                binding=binding,
                capability_id=record.capability_id,
                target_entities=(),
            )
        except ResourceBindingError as error:
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
                    category=(
                        ProblemCategory.CONFLICT
                        if error.code.endswith("ambiguous")
                        else ProblemCategory.NOT_FOUND
                        if error.code.endswith("not_found")
                        or error.code.endswith("unbound")
                        else ProblemCategory.UNAVAILABLE
                    ),
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
                    channel_bindings=channel_bindings,
                )
            )
        bound.append(
            InstrumentActionOperation(
                operation_id=f"{point_uid}.action.{record.id.qualified_name}",
                instrument_id=binding.instrument_id,
                capability_id=record.capability_id,
                fields=tuple(fields),
            )
        )
    return tuple(bound)


def _bind_desired_state(
    records: Sequence[StateRecord],
    *,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
    payload_ids: Mapping[ValueId, str],
    known_compute_results: set[ValueId],
    point_index: int,
    problems: list[Problem],
) -> tuple[_PendingResourceState, ...]:
    grouped: dict[
        tuple[str, str],
        dict[tuple[str, tuple[str, ...], _ChannelSignature], _PendingStateField],
    ] = {}
    signatures: dict[
        tuple[str, str, str, tuple[str, ...], _ChannelSignature],
        set[str],
    ] = {}
    owners: dict[
        tuple[str, str, str, tuple[str, ...], _ChannelSignature],
        set[LogicalResourcePortId],
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
            bound_targets = _bind_state_resources(
                record.resource_target,
                capability_id=capability_id,
                target_entities=record.target_entities,
                resources=resources,
            )
        except ResourceBindingError as error:
            problems.append(
                _problem(
                    error.code,
                    str(error),
                    model_location(
                        "desired_state",
                        "resource_port_id",
                    ),
                    category=(
                        ProblemCategory.CONFLICT
                        if error.code.endswith("ambiguous")
                        else ProblemCategory.NOT_FOUND
                        if error.code.endswith("not_found")
                        or error.code.endswith("unbound")
                        else ProblemCategory.UNAVAILABLE
                    ),
                )
            )
            continue
        for binding in bound_targets:
            channel_key = channel_signature(binding.channel_bindings)
            group = grouped.setdefault((binding.instrument_id, capability_id), {})
            key = (field_path, binding.entity_ids, channel_key)
            signature_key = (
                binding.instrument_id,
                capability_id,
                field_path,
                binding.entity_ids,
                channel_key,
            )
            signatures.setdefault(signature_key, set()).add(
                state_value.model_dump_json()
            )
            owners.setdefault(signature_key, set()).add(record.resource_target)
            group.setdefault(
                key,
                _PendingStateField(
                    field_path=field_path,
                    value=state_value,
                    entity_ids=binding.entity_ids,
                    channel_bindings=binding.channel_bindings,
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
        _PendingResourceState(
            instrument_id=resource,
            capability_id=capability,
            fields=tuple(fields.values()),
        )
        for (resource, capability), fields in grouped.items()
    )


def _state_operations(
    point_uid: str,
    states: Sequence[_PendingResourceState],
) -> tuple[ApplyStateOperation, ...]:
    grouped: dict[str, list[_PendingResourceState]] = {}
    for state in states:
        grouped.setdefault(state.instrument_id, []).append(state)
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
                    channel_bindings=field.channel_bindings,
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


def _bind_single_resource(
    target: LogicalResourcePortId,
    *,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
    missing_code: str,
) -> ResourceBinding:
    resource = resources.get(target)
    if resource is None:
        raise ResourceBindingError(
            missing_code,
            f"logical resource port {target.qualified_name!r} is not bound",
        )
    return resource.select_one()


def _bind_state_resources(
    target: LogicalResourcePortId,
    *,
    capability_id: str,
    target_entities: Sequence[object],
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
) -> tuple[ResourceBinding, ...]:
    resource = resources.get(target)
    if resource is None:
        raise ResourceBindingError(
            "state_resource_port_unbound",
            f"logical state resource port {target.qualified_name!r} is not bound",
        )
    requested_entity_ids = _normalize_entity_ids(target_entities)

    if not resource.entity_ids:
        binding = _bind_single_resource(
            target,
            resources=resources,
            missing_code="state_resource_port_unbound",
        )
        entity_ids, channel_bindings, unbound = _logical_state_target(
            binding=binding,
            capability_id=capability_id,
            target_entities=requested_entity_ids,
        )
        if unbound:
            raise ResourceBindingError(
                "state_target_entity_unbound",
                "state target entities are not bound: " + ", ".join(unbound),
            )
        return (
            replace(
                binding,
                entity_ids=entity_ids,
                channel_bindings=channel_bindings,
            ),
        )

    selected_entity_ids = requested_entity_ids or resource.entity_ids
    unbound = tuple(
        entity_id
        for entity_id in selected_entity_ids
        if entity_id not in resource.entity_ids
    )
    if unbound:
        raise ResourceBindingError(
            "state_target_entity_unbound",
            "state target entities are outside the declared resource scope: "
            + ", ".join(unbound),
        )
    shards = resource.manifest.select_shards(selected_entity_ids)
    selected: list[ResourceBinding] = []
    for shard in shards:
        entity_ids, channel_bindings, _unbound = _logical_state_target(
            binding=shard,
            capability_id=capability_id,
            target_entities=(),
        )
        selected.append(
            replace(
                shard,
                entity_ids=entity_ids,
                channel_bindings=channel_bindings,
            )
        )
    return tuple(selected)


def _logical_state_target(
    *,
    binding: ResourceBinding,
    capability_id: str,
    target_entities: Sequence[object],
) -> tuple[
    tuple[str, ...],
    tuple[CommandChannelBinding, ...],
    tuple[str, ...],
]:
    requested_entity_ids = tuple(
        dict.fromkeys(
            value.id if isinstance(value, EntityRef) else str(value)
            for value in target_entities
        )
    )
    selected_entity_ids = requested_entity_ids or binding.entity_ids
    if requested_entity_ids and binding.entity_ids:
        unbound = tuple(
            entity_id
            for entity_id in requested_entity_ids
            if entity_id not in binding.entity_ids
        )
        if unbound:
            return requested_entity_ids, (), unbound
    channel_bindings = tuple(
        channel_binding
        for channel_binding in binding.channel_bindings
        if (not selected_entity_ids or channel_binding.entity_id in selected_entity_ids)
        and (
            channel_binding.capability is None
            or channel_binding.capability == capability_id
        )
    )
    return (
        selected_entity_ids
        or tuple(
            dict.fromkeys(
                channel_binding.entity_id for channel_binding in channel_bindings
            )
        ),
        channel_bindings,
        (),
    )


def _channel_binding_identity(
    binding: CommandChannelBinding,
) -> _ChannelBindingIdentity:
    return (
        binding.entity_id,
        binding.channel_id,
        binding.line_id,
        binding.capability,
        tuple(sorted(binding.group_ids)),
    )


def channel_signature(
    bindings: Sequence[CommandChannelBinding],
) -> _ChannelSignature:
    return tuple(_channel_binding_identity(binding) for binding in bindings)


def _bind_collect(
    products: Sequence[ProductDef],
    product_uses: Sequence[ProductUse],
    acquire: AcquireSpec,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
    *,
    point_index: int,
    problems: list[Problem],
) -> _PendingCollect | None:
    products_by_id = {product.id: product for product in products}
    uses_by_product: dict[ProductId, list[ProductUse]] = {}
    for use in product_uses:
        uses_by_product.setdefault(use.product_id, []).append(use)
    requested = tuple(
        acquired
        for acquired in acquire.products
        if acquired.product_id in uses_by_product
    )
    if not requested:
        return None
    try:
        instrument_id, entity_ids, channel_bindings = _bind_record_target(
            acquire.resource_port_id,
            capability=acquire.capability_id,
            resources=resources,
        )
    except ResourceBindingError as error:
        problems.append(
            _problem(
                error.code,
                str(error),
                model_location(
                    "points",
                    point_index,
                    "acquisitions",
                    acquire.id.qualified_name,
                    "resource_port_id",
                ),
                category=(
                    ProblemCategory.CONFLICT
                    if error.code.endswith("ambiguous")
                    else ProblemCategory.NOT_FOUND
                    if error.code.endswith("not_found")
                    or error.code.endswith("unbound")
                    else ProblemCategory.UNAVAILABLE
                ),
            )
        )
        return None
    requests = tuple(
        _PendingCollectionRequest(
            product_use_ids=tuple(
                use.id for use in uses_by_product[acquired.product_id]
            ),
            product_id=product.id,
            provider_key=acquired.provider_key,
            capability=acquire.capability_id,
            unit=product.unit,
            dtype=product.dtype,
            entity_ids=entity_ids,
            channel_bindings=channel_bindings,
            axes=product.axes,
            metadata=dict(acquired.metadata),
        )
        for acquired in requested
        for product in (products_by_id[acquired.product_id],)
    )
    return _PendingCollect(instrument_id=instrument_id, requests=requests)


def _collect_operation(
    point_uid: str,
    *,
    acquisition_id: str,
    point_index: int,
    point_count: int,
    collect: _PendingCollect,
) -> CollectOperation:
    instrument_id = collect.instrument_id
    operation_id = "collect-" + stable_content_hash(
        {
            "kind": "scopecat.collect_operation.v1",
            "point_id": point_uid,
            "acquisition_id": acquisition_id,
            "instrument_id": instrument_id,
        }
    )
    return CollectOperation(
        operation_id=operation_id,
        instrument_id=instrument_id,
        result_bindings=tuple(
            CollectionResultBinding(
                provider_key=request.provider_key,
                product_use_ids=request.product_use_ids,
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
                    channel_bindings=list(request.channel_bindings),
                    metadata=cast(
                        "dict[str, JsonValue]",
                        thaw_json_value(request.metadata),
                    ),
                )
                for request in collect.requests
            ],
        ),
    )


def _bind_record_target(
    target: LogicalResourcePortId,
    *,
    capability: str,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
) -> tuple[
    str,
    tuple[str, ...],
    tuple[CommandChannelBinding, ...],
]:
    binding = _bind_single_resource(
        target,
        resources=resources,
        missing_code="record_resource_port_unbound",
    )
    channel_bindings = _collection_channel_bindings(
        binding.channel_bindings,
        capability=capability,
    )
    return (
        binding.instrument_id,
        tuple(
            dict.fromkeys(
                (
                    *binding.entity_ids,
                    *(
                        channel_binding.entity_id
                        for channel_binding in channel_bindings
                    ),
                )
            )
        ),
        channel_bindings,
    )


def _problem(
    code: str,
    message: str,
    location: ModelLocation,
    *,
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
) -> Problem:
    return compiler_problem(code, message, location, category=category)
