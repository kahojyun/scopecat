"""Lower a config-bound compiler plan into the executable program boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from scopecat._compiler.bound import (
    BoundCollect,
    BoundPlan,
    BoundPoint,
    BoundProduct,
    BoundResourceState,
)
from scopecat._compiler.bound import (
    BoundValue as CompilerBoundValue,
)
from scopecat._compiler.ids import NodeId
from scopecat._execution.program import (
    ApplyStateOperation,
    ApplyStateStage,
    BoundInput,
    CollectOperation,
    CollectStage,
    ComputeOperation,
    ComputeStage,
    ExecutionProgram,
    OutputInput,
    PayloadSlot,
    PointProgram,
    ResourceClaim,
    StateTarget,
)
from scopecat.instruments.sdk import (
    CollectAxisRequest,
    CollectCommand,
    CollectProductRequest,
    CommandChannelBinding,
)
from scopecat.models.config import RoutingChannelBinding
from scopecat.problems import has_blocking_problems


def build_execution_program(
    plan: BoundPlan,
    *,
    instrument_order: Sequence[str] = (),
) -> ExecutionProgram:
    """Build the sole executable program consumed by ``ExecutionEngine``.

    ``instrument_order`` comes from the bound driver/resource selection, never
    from provider list iteration.  It is required when a collection target is
    intentionally broadcast (``BoundCollect.instrument_id is None``).
    """

    if has_blocking_problems(plan.problems):
        msg = "cannot build an execution program from a plan with blocking problems"
        raise ValueError(msg)
    selected_instrument_order = _explicit_instrument_order(
        plan,
        instrument_order=instrument_order,
    )
    points = tuple(
        _point_program(
            point,
            point_count=plan.point_count,
            instrument_order=selected_instrument_order,
        )
        for point in plan.points
    )
    used_instruments = {
        operation.instrument_id
        for point in points
        for stage in point.stages
        if isinstance(stage, ApplyStateStage | CollectStage)
        for operation in stage.operations
    }
    resource_order = tuple(
        instrument_id
        for instrument_id in selected_instrument_order
        if instrument_id in used_instruments
    )
    claims = _resource_claims(plan, instrument_order=selected_instrument_order)
    return ExecutionProgram(
        experiment_id=plan.experiment_id,
        points=points,
        expected_output_ids=plan.expected_output_ids,
        resource_order=resource_order,
        resource_claims=claims,
        expected_dataset_schema=plan.expected_dataset_schema,
    )


def _point_program(
    point: BoundPoint,
    *,
    point_count: int,
    instrument_order: tuple[str, ...],
) -> PointProgram:
    compute = _compute_stage(point)
    state = _state_stage(point, instrument_order=instrument_order)
    collect = _collect_stage(
        point,
        point_count=point_count,
        instrument_order=instrument_order,
    )
    return PointProgram(
        point_index=point.point_index,
        point_uid=point.point_uid,
        coordinates=dict(point.coordinates),
        stages=tuple(stage for stage in (compute, state, collect) if stage.operations),
    )


def _compute_stage(point: BoundPoint) -> ComputeStage:
    operation_ids = {
        call.node_id: _compute_operation_id(point.point_uid, call.node_id)
        for call in point.compute
    }
    operations: list[ComputeOperation] = []
    for call in point.compute:
        if not callable(call.fn):
            msg = f"bound compute node {call.node_id} has no callable kernel"
            raise ValueError(msg)
        inputs: dict[str, BoundInput | OutputInput] = {}
        for name, value in call.inputs.items():
            if isinstance(value, CompilerBoundValue):
                inputs[name] = BoundInput(value.value)
            else:
                try:
                    producer_id = operation_ids[value.producer]
                except KeyError as error:
                    msg = f"compute producer {value.producer} is not in the bound point"
                    raise ValueError(msg) from error
                inputs[name] = OutputInput(producer_id)
        operations.append(
            ComputeOperation(
                operation_id=operation_ids[call.node_id],
                kernel_id=call.node_id.qualified_name,
                kernel=call.fn,
                inputs=inputs,
                output_type=call.output_type,
                dependencies=dict(call.dependencies),
                payload_slot=(
                    PayloadSlot(id=call.payload_id, schema_id=call.payload_schema_id)
                    if call.payload_id is not None
                    and call.payload_schema_id is not None
                    else None
                ),
                cache_namespace=call.node_id.qualified_name,
                cache_key=call.cache_key,
            )
        )
    return ComputeStage(operations=tuple(operations))


def _state_stage(
    point: BoundPoint,
    *,
    instrument_order: tuple[str, ...],
) -> ApplyStateStage:
    states_by_instrument: dict[str, list[BoundResourceState]] = {}
    for state in point.desired_state:
        states_by_instrument.setdefault(state.resource_id, []).append(state)
    operations: list[ApplyStateOperation] = []
    for instrument_id in instrument_order:
        states = states_by_instrument.get(instrument_id)
        if not states:
            continue
        operations.append(
            ApplyStateOperation(
                operation_id=f"{point.point_uid}.state.{instrument_id}",
                instrument_id=instrument_id,
                targets=tuple(
                    StateTarget(
                        capability_id=state.capability_id,
                        field_path=field.field_path,
                        value=field.value,
                        channel_bindings=tuple(
                            _command_channel_binding(binding)
                            for binding in field.channel_bindings
                        ),
                    )
                    for state in states
                    for field in state.fields
                ),
            )
        )
    return ApplyStateStage(operations=tuple(operations))


def _collect_stage(
    point: BoundPoint,
    *,
    point_count: int,
    instrument_order: tuple[str, ...],
) -> CollectStage:
    products_by_instrument: dict[str, list[BoundProduct]] = {}
    for collect in point.collect:
        targets = _collect_targets(collect, instrument_order=instrument_order)
        for instrument_id in targets:
            products_by_instrument.setdefault(instrument_id, []).extend(
                collect.products
            )
    operations: list[CollectOperation] = []
    routes_by_instrument = {
        instrument_id: tuple(
            route for route in point.routes if route.resource_id == instrument_id
        )
        for instrument_id in instrument_order
    }
    for instrument_id in instrument_order:
        products = products_by_instrument.get(instrument_id)
        if not products:
            continue
        record_bindings = {
            product.product_key: product.record_id for product in products
        }
        if len(record_bindings) != len(products):
            msg = f"instrument {instrument_id} has duplicate collection product keys"
            raise ValueError(msg)
        operation_id = f"{point.point_uid}.collect.{instrument_id}"
        operations.append(
            CollectOperation(
                operation_id=operation_id,
                instrument_id=instrument_id,
                record_bindings=record_bindings,
                command=CollectCommand(
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                    point_index=point.point_index,
                    point_count=point_count,
                    requests=[
                        CollectProductRequest(
                            id=product.product_key,
                            capability_id=product.capability,
                            unit=product.unit,
                            dtype=product.dtype,
                            dimensions=[
                                CollectAxisRequest(
                                    id=axis.id,
                                    kind=axis.kind,
                                    size=axis.size,
                                    unit=axis.unit,
                                    metadata=dict(axis.metadata),
                                )
                                for axis in product.axes
                            ],
                            channel_bindings=[
                                _command_channel_binding(binding)
                                for route in routes_by_instrument[instrument_id]
                                if product.capability is None
                                or product.capability in route.capabilities
                                for binding in route.channel_bindings
                                if binding.capability is None
                                or product.capability is None
                                or binding.capability == product.capability
                            ],
                            metadata=dict(product.metadata),
                        )
                        for product in products
                    ],
                ),
            )
        )
    return CollectStage(operations=tuple(operations))


def _explicit_instrument_order(
    plan: BoundPlan,
    *,
    instrument_order: Sequence[str],
) -> tuple[str, ...]:
    selected = tuple(instrument_order)
    if len(selected) != len(set(selected)) or any(not item for item in selected):
        msg = "instrument_order must contain unique non-empty ids"
        raise ValueError(msg)
    fixed: set[str] = {
        state.resource_id for point in plan.points for state in point.desired_state
    } | {
        collect.instrument_id
        for point in plan.points
        for collect in point.collect
        if collect.instrument_id is not None
    }
    broadcasts = any(
        collect.instrument_id is None
        for point in plan.points
        for collect in point.collect
    )
    if broadcasts and not selected:
        msg = "instrument_order is required for broadcast collection"
        raise ValueError(msg)
    missing = sorted(fixed - set(selected))
    if selected and missing:
        msg = "instrument_order is missing bound resources: " + ", ".join(missing)
        raise ValueError(msg)
    if not selected:
        return tuple(sorted(fixed))
    return selected


def _collect_targets(
    collect: BoundCollect,
    *,
    instrument_order: tuple[str, ...],
) -> tuple[str, ...]:
    if collect.instrument_id is None:
        return instrument_order
    return (collect.instrument_id,)


def _resource_claims(
    plan: BoundPlan,
    *,
    instrument_order: tuple[str, ...],
) -> tuple[ResourceClaim, ...]:
    claims: list[ResourceClaim] = [
        ResourceClaim(id=instrument_id) for instrument_id in instrument_order
    ]
    seen = {(claim.kind, claim.id) for claim in claims}
    for point in plan.points:
        for route in point.routes:
            for binding in route.channel_bindings:
                candidates: tuple[tuple[Literal["channel", "group"], str], ...] = (
                    ("channel", binding.channel_id),
                    *(("group", group_id) for group_id in binding.group_ids),
                )
                for kind, identifier in candidates:
                    key = (kind, identifier)
                    if key in seen:
                        continue
                    seen.add(key)
                    claims.append(
                        ResourceClaim(
                            id=identifier,
                            kind=kind,
                        )
                    )
    return tuple(claims)


def _command_channel_binding(binding: RoutingChannelBinding) -> CommandChannelBinding:
    return CommandChannelBinding(
        entity_id=binding.entity_id,
        channel_id=binding.channel_id,
        line_id=binding.line_id,
        capability=binding.capability,
        group_ids=list(binding.group_ids),
        metadata=dict(binding.metadata),
    )


def _compute_operation_id(point_uid: str, node_id: NodeId) -> str:
    return f"{point_uid}.compute.{node_id.qualified_name}"


__all__ = ["build_execution_program"]
