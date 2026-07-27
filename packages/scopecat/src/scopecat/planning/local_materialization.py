"""Specialize linked host semantics into final local operations.

Preparation binds run-invariant compute once. Bounded materialization selects
logical entities and binds state, compute, and collection to the static
resource manifests prepared for the local target.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from typing import Protocol, cast

from pydantic import JsonValue

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
)
from scopecat.compiler.relations.context import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.typed.dependencies import ComputePlan
from scopecat.compiler.typed.point_domain import (
    MaterializedPoint,
)
from scopecat.compiler.typed.program import CoreProgram, TypedDomainExecution
from scopecat.compiler.typed.state import (
    SetStateSpec,
    StateRecord,
    evaluate_state_spec,
)
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectionResultBinding,
    CollectOperation,
    ComputeOperation,
    StateTarget,
)
from scopecat.execution.program import RunCoverageEffect
from scopecat.graph.values import ComputeResultRef, ValueId
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.measurements.products import ProductDef
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
from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments.contracts import (
    CollectAxisRequest,
    CollectCommand,
    CollectProductRequest,
)

type _ChannelBindingIdentity = tuple[
    str,
    str,
    str | None,
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
        else:
            raise ResourceBindingError(
                "module_resource_entity_invalid",
                f"resource entity must resolve to an entity reference, got {value!r}",
            )
    return tuple(dict.fromkeys(entity_ids))


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
) -> MaterializedLocalEffects:
    """Lower one bounded point coverage into final ordered local effects."""

    program = target.program
    problems: list[Problem] = []
    verified_program = linked_points.linked_plan.verified_program
    selected_compute_plan = verified_program.compute_plan
    selected_instrument_order = target.instrument_order
    compute_seed = target.compute_seed
    materialized_domain = linked_points.point_domain
    planner_points = materialized_domain.points
    point_count = len(planner_points)
    point_by_ordinal = {point.logical_ordinal: point for point in planner_points}
    params_by_ordinal = {
        point.logical_ordinal: params
        for point, params in zip(
            planner_points,
            linked_points.point_parameters,
            strict=True,
        )
    }
    ordinals = tuple(point.logical_ordinal for point in planner_points)
    resources_by_ordinal = _select_coverage_resources(
        program,
        target.resource_ports,
        planner_points,
        params_by_ordinal,
        problems,
    )
    payload_ids_by_ordinal: dict[int, dict[ValueId, str]] = {
        ordinal: dict(compute_seed.payload_ids) for ordinal in ordinals
    }
    signatures_by_ordinal = {
        ordinal: dict(compute_seed.signatures) for ordinal in ordinals
    }
    compute_effects: list[RunCoverageEffect] = []
    for node in selected_compute_plan.point_nodes:
        for ordinal in ordinals:
            point = point_by_ordinal[ordinal]
            point_params = params_by_ordinal[ordinal]
            compute_operations, point_payload_ids, signatures = (
                _bind_compute_operations(
                    (node,),
                    operation_prefix=point.logical_id.value,
                    ctx=EvalContext(
                        params=point_params,
                        point_row=point.row,
                    ),
                    compute_plan=selected_compute_plan,
                    demanded_payload_results=set(
                        selected_compute_plan.demanded_payload_results
                    ),
                    problems=problems,
                    initial_signatures=signatures_by_ordinal[ordinal],
                )
            )
            signatures_by_ordinal[ordinal] = dict(signatures)
            payload_ids_by_ordinal[ordinal].update(point_payload_ids)
            compute_effects.extend(
                RunCoverageEffect.at_point(ordinal, operation)
                for operation in compute_operations
            )

    effect_operations: list[list[RunCoverageEffect]] = [
        [] for _effect in program.effects
    ]
    known_compute_results = {node.result.id for node in program.compute_nodes}
    for effect_index, effect in enumerate(program.effects):
        if isinstance(effect, TypedDomainExecution):
            continue
        if isinstance(effect, AcquireEffect):
            for ordinal in ordinals:
                point = point_by_ordinal[ordinal]
                resources = resources_by_ordinal[ordinal]
                collect = _bind_collect(
                    program.product_defs,
                    target.product_uses,
                    effect,
                    resources,
                    point_uid=point.logical_id.value,
                    point_index=ordinal,
                    point_count=point_count,
                    problems=problems,
                )
                if collect is not None:
                    effect_operations[effect_index].append(
                        RunCoverageEffect.at_point(ordinal, collect)
                    )
            continue
        if effect_index and not isinstance(
            program.effects[effect_index - 1],
            TypedDomainExecution | AcquireEffect,
        ):
            continue
        state_end = effect_index + 1
        while state_end < len(program.effects) and not isinstance(
            program.effects[state_end],
            TypedDomainExecution | AcquireEffect,
        ):
            state_end += 1
        state_group: list[tuple[int, SetStateSpec]] = []
        for index in range(effect_index, state_end):
            state = program.effects[index]
            if isinstance(state, TypedDomainExecution | AcquireEffect):
                raise AssertionError("state group contains a non-state effect")
            state_group.append((index, state))
        for ordinal in ordinals:
            point = point_by_ordinal[ordinal]
            point_params = params_by_ordinal[ordinal]
            resources = resources_by_ordinal[ordinal]
            desired = _bind_desired_state(
                tuple(
                    record
                    for index, state in state_group
                    for record in _evaluate_state_records(
                        state,
                        index,
                        point,
                        point_params,
                        problems=problems,
                    )
                ),
                point_uid=point.logical_id.value,
                resources=resources,
                payload_ids=payload_ids_by_ordinal[ordinal],
                known_compute_results=known_compute_results,
                point_index=ordinal,
                problems=problems,
            )
            ordered = _order_instrument_operations(
                desired,
                instrument_order=selected_instrument_order,
            )
            effect_operations[state_end - 1].extend(
                RunCoverageEffect.at_point(ordinal, operation) for operation in ordered
            )
    if bool(problems):
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
    product_uses = tuple(
        use for use in linked.program.product_uses if use.id in requested
    )
    problems: list[Problem] = []
    active_resource_ports = _active_resource_port_ids(
        linked.program,
        product_uses=product_uses,
    )
    resource_ports: dict[LogicalResourcePortId, ResourcePortManifest] = {}
    if active_resource_ports:
        physical_resources = RoutingView.from_config(linked.environment.config)
        resource_ports = {
            requirement.port_id: physical_resources.bind_port(
                port_id=requirement.port_id,
                capabilities=requirement.capabilities,
            )
            for requirement in linked.program.resource_requirements
            if requirement.port_id in active_resource_ports
        }
    compute_plan = linked.verified_program.compute_plan
    run_operations, compute_seed = _bind_run_compute(
        linked,
        compute_plan,
        problems=problems,
    )
    if bool(problems):
        raise CheckFailed(problems)
    return LocalTargetPlan(
        program=linked.program,
        product_uses=product_uses,
        instrument_order=_validate_instrument_order(instrument_order),
        resource_ports=resource_ports,
        run_operations=run_operations,
        compute_seed=compute_seed,
    )


def _evaluate_state_records(
    state: SetStateSpec,
    effect_index: int,
    point: MaterializedPoint,
    params: ParameterRelationData,
    *,
    problems: list[Problem],
) -> tuple[StateRecord, ...]:
    ctx = EvalContext(params=params, point_row=point.row)
    try:
        return tuple(
            evaluate_state_spec(
                state,
                point_index=point.logical_ordinal,
                ctx=ctx,
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


def _bind_run_compute(
    linked: LinkedPlan,
    compute_plan: ComputePlan,
    *,
    problems: list[Problem],
) -> tuple[tuple[ComputeOperation, ...], ComputeBindingSeed]:
    operations, payload_ids, signatures = _bind_compute_operations(
        compute_plan.run_nodes,
        operation_prefix="run",
        ctx=EvalContext(params=linked.environment.parameters),
        compute_plan=compute_plan,
        demanded_payload_results=set(compute_plan.demanded_payload_results),
        problems=problems,
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
) -> dict[int, Mapping[LogicalResourcePortId, _ResourceEntitySelection]]:
    """Evaluate point-local entities over the target's static port manifests."""

    return {
        point.logical_ordinal: _select_point_resources(
            program,
            resource_ports,
            point,
            params_by_ordinal[point.logical_ordinal],
            problems,
        )
        for point in points
    }


def _select_point_resources(
    program: CoreProgram,
    resource_ports: Mapping[LogicalResourcePortId, ResourcePortManifest],
    point: MaterializedPoint,
    params: ParameterRelationData,
    problems: list[Problem],
) -> Mapping[LogicalResourcePortId, _ResourceEntitySelection]:
    selected: dict[LogicalResourcePortId, _ResourceEntitySelection] = {}
    for requirement in program.resource_requirements:
        manifest = resource_ports.get(requirement.port_id)
        if manifest is None:
            continue
        ctx = EvalContext(params=params, point_row=point.row)
        entity_values: list[object] = []
        failed = False
        for use in requirement.entity_uses:
            try:
                entity_values.append(
                    evaluate_value_expr(
                        use.value,
                        use.value.plan,
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
                )
            )
            continue
        selected[resource.manifest.port_id] = resource
    return selected


def _active_resource_port_ids(
    program: CoreProgram,
    *,
    product_uses: Sequence[ProductUse],
) -> frozenset[LogicalResourcePortId]:
    """Return ports consumed by effects that survive product demand closure.

    Physical binding must happen after this cut; otherwise an unused
    acquisition could still make unavailable or ambiguous hardware block a run.
    """

    demanded_products = {use.product_id for use in product_uses}
    selected: set[LogicalResourcePortId] = set()
    for effect in program.effects:
        if isinstance(effect, AcquireEffect):
            if any(
                product_id in demanded_products for product_id in effect.product_ids
            ):
                selected.add(effect.resource_port_id)
        elif not isinstance(effect, TypedDomainExecution):
            selected.update(_state_resource_port_ids(effect))
    return frozenset(selected)


def _state_resource_port_ids(
    state: SetStateSpec,
) -> tuple[LogicalResourcePortId, ...]:
    return (state.resource_target.port_id,)


def _bind_desired_state(
    records: Sequence[StateRecord],
    *,
    point_uid: str,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
    payload_ids: Mapping[ValueId, str],
    known_compute_results: set[ValueId],
    point_index: int,
    problems: list[Problem],
) -> tuple[ApplyStateOperation, ...]:
    grouped: dict[
        str,
        dict[
            tuple[str, str, tuple[str, ...], _ChannelSignature],
            StateTarget,
        ],
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
            binding = _bind_state_resource(
                record.resource_target,
                capability_id=capability_id,
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
                )
            )
            continue
        channel_key = channel_signature(binding.channel_bindings)
        group = grouped.setdefault(binding.instrument_id, {})
        key = (capability_id, field_path, binding.entity_ids, channel_key)
        signature_key = (
            binding.instrument_id,
            capability_id,
            field_path,
            binding.entity_ids,
            channel_key,
        )
        signatures.setdefault(signature_key, set()).add(state_value.model_dump_json())
        owners.setdefault(signature_key, set()).add(record.resource_target)
        group.setdefault(
            key,
            StateTarget(
                capability_id=capability_id,
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
                )
            )
    return tuple(
        ApplyStateOperation(
            operation_id=f"{point_uid}.state.{instrument_id}",
            instrument_id=instrument_id,
            targets=tuple(targets.values()),
        )
        for instrument_id, targets in grouped.items()
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


def _bind_state_resource(
    target: LogicalResourcePortId,
    *,
    capability_id: str,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
) -> ResourceBinding:
    resource = resources.get(target)
    if resource is None:
        raise ResourceBindingError(
            "state_resource_port_unbound",
            f"logical state resource port {target.qualified_name!r} is not bound",
        )
    binding = resource.select_one()
    channel_bindings = tuple(
        channel_binding
        for channel_binding in binding.channel_bindings
        if (
            channel_binding.capability is None
            or channel_binding.capability == capability_id
        )
    )
    entity_ids = binding.entity_ids or tuple(
        dict.fromkeys(channel_binding.entity_id for channel_binding in channel_bindings)
    )
    return replace(
        binding,
        entity_ids=entity_ids,
        channel_bindings=channel_bindings,
    )


def _channel_binding_identity(
    binding: CommandChannelBinding,
) -> _ChannelBindingIdentity:
    return (
        binding.entity_id,
        binding.channel_id,
        binding.capability,
    )


def channel_signature(
    bindings: Sequence[CommandChannelBinding],
) -> _ChannelSignature:
    return tuple(_channel_binding_identity(binding) for binding in bindings)


def _bind_collect(
    products: Sequence[ProductDef],
    product_uses: Sequence[ProductUse],
    acquire: AcquireEffect,
    resources: Mapping[LogicalResourcePortId, _ResourceEntitySelection],
    *,
    point_uid: str,
    point_index: int,
    point_count: int,
    problems: list[Problem],
) -> CollectOperation | None:
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
            )
        )
        return None
    selected = tuple(
        (
            acquired,
            products_by_id[acquired.product_id],
            tuple(use.id for use in uses_by_product[acquired.product_id]),
        )
        for acquired in requested
    )
    operation_id = "collect-" + stable_content_hash(
        {
            "kind": "scopecat.collect_operation.v1",
            "point_id": point_uid,
            "acquisition_id": acquire.id.qualified_name,
            "instrument_id": instrument_id,
        }
    )
    return CollectOperation(
        operation_id=operation_id,
        instrument_id=instrument_id,
        result_bindings=tuple(
            CollectionResultBinding(
                provider_key=acquired.provider_key,
                product_use_ids=product_use_ids,
            )
            for acquired, _product, product_use_ids in selected
        ),
        command=CollectCommand(
            operation_id=operation_id,
            instrument_id=instrument_id,
            point_index=point_index,
            point_count=point_count,
            requests=[
                CollectProductRequest(
                    id=acquired.provider_key,
                    capability_id=acquire.capability_id,
                    unit=product.unit,
                    dtype=product.dtype,
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
                        for axis in product.axes
                    ],
                    entity_ids=list(entity_ids),
                    channel_bindings=list(channel_bindings),
                    metadata=cast(
                        "dict[str, JsonValue]",
                        thaw_json_value(acquired.metadata),
                    ),
                )
                for acquired, product, _product_use_ids in selected
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
) -> Problem:
    return compiler_problem(code, message, location)
