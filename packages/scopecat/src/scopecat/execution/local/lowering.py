"""Lower a config-bound compiler plan into the executable program boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

from pydantic import JsonValue

from scopecat.compiler.linking.bound import (
    BoundAction,
    BoundPlan,
    BoundPoint,
    BoundResourceState,
    CollectionRequest,
)
from scopecat.compiler.linking.bound import (
    BoundValue as CompilerBoundValue,
)
from scopecat.compiler.semantic.model import OperationId
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
    ExecutionProgram,
    InstrumentActionOperation,
    OutputInput,
    PayloadSlot,
    PointProgram,
    RecordProjection,
    StateTarget,
)
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.problems import has_blocking_problems
from scopecat.records.config import RoutingChannelBinding
from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments.contracts import (
    CollectAxisRequest,
    CollectCommand,
    CollectProductRequest,
)


def build_execution_program(
    plan: BoundPlan,
    *,
    instrument_order: Sequence[str] = (),
) -> ExecutionProgram:
    """Build the sole executable program consumed by ``ExecutionEngine``.

    ``instrument_order`` comes from the bound driver/resource selection, never
    from provider list iteration. Every local collection already owns one
    physical instrument target.
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
        if isinstance(stage, ApplyStateStage | ActionStage | CollectStage)
        for operation in stage.operations
    }
    resource_order = tuple(
        instrument_id
        for instrument_id in selected_instrument_order
        if instrument_id in used_instruments
    )
    claims = _resource_claims(plan, instrument_order=resource_order)
    local_product_realizations = plan.local_product_realizations
    if local_product_realizations is None:
        raise AssertionError("valid local plan lost its product realization selection")
    return ExecutionProgram(
        experiment_id=plan.experiment_id,
        points=points,
        product_uses=plan.product_uses,
        collection_product_use_ids=tuple(
            realization.product_use_id
            for realization in local_product_realizations.entries
        ),
        record_projections=tuple(
            RecordProjection(
                record_id=record.id,
                product_use_id=record.product_use_id,
                product_id=record.product_id,
            )
            for record in plan.records
            if record.kind == "observable"
        ),
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
    actions = _action_stage(point)
    collect = _collect_stage(
        point,
        point_count=point_count,
        instrument_order=instrument_order,
    )
    return PointProgram(
        point_index=point.point_index,
        point_uid=point.logical_id.value,
        coordinates=dict(point.coordinates),
        stages=tuple(
            stage for stage in (compute, state, actions, collect) if stage.operations
        ),
    )


def _compute_stage(
    point: BoundPoint,
) -> ComputeStage:
    operations: list[ComputeOperation] = []
    for call in point.compute:
        inputs: dict[str, BoundInput | OutputInput] = {}
        for name, value in call.inputs.items():
            if isinstance(value, CompilerBoundValue):
                inputs[name] = BoundInput(value.value)
            else:
                inputs[name] = OutputInput(value.value_id)
        operations.append(
            ComputeOperation(
                operation_id=_compute_operation_id(
                    point.logical_id.value,
                    call.operation_id,
                ),
                semantic_operation_id=call.operation_id.qualified_name,
                implementation_id=call.implementation_id.value,
                contract=call.contract,
                kernel=call.implementation.kernel,
                inputs=inputs,
                result=ComputeResultSlot(
                    id=call.result.id,
                    value_type=call.result.value_type,
                ),
                dependencies=dict(call.dependencies),
                payload_slot=(
                    PayloadSlot(id=call.payload_id, schema_id=call.payload_schema_id)
                    if call.payload_id is not None
                    and call.payload_schema_id is not None
                    else None
                ),
                cache_namespace=call.operation_id.qualified_name,
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
        states_by_instrument.setdefault(state.resource_id.value, []).append(state)
    operations: list[ApplyStateOperation] = []
    for instrument_id in instrument_order:
        states = states_by_instrument.get(instrument_id)
        if not states:
            continue
        operations.append(
            ApplyStateOperation(
                operation_id=f"{point.logical_id.value}.state.{instrument_id}",
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
    requests_by_instrument: dict[str, list[CollectionRequest]] = {}
    for collect in point.collect:
        requests_by_instrument.setdefault(collect.resource_id.value, []).extend(
            collect.requests
        )
    operations: list[CollectOperation] = []
    for instrument_id in instrument_order:
        requests = requests_by_instrument.get(instrument_id)
        if not requests:
            continue
        provider_keys = [request.provider_key for request in requests]
        if len(provider_keys) != len(set(provider_keys)):
            msg = f"instrument {instrument_id} has duplicate collection product keys"
            raise ValueError(msg)
        operation_id = f"{point.logical_id.value}.collect.{instrument_id}"
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
                    for request in requests
                ),
                command=CollectCommand(
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                    point_index=point.point_index,
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
                        for request in requests
                    ],
                ),
            )
        )
    return CollectStage(operations=tuple(operations))


def _action_stage(point: BoundPoint) -> ActionStage:
    return ActionStage(
        operations=tuple(_action_operation(point, action) for action in point.actions)
    )


def _action_operation(
    point: BoundPoint,
    action: BoundAction,
) -> InstrumentActionOperation:
    return InstrumentActionOperation(
        operation_id=(f"{point.logical_id.value}.action.{action.id.qualified_name}"),
        instrument_id=action.resource_id.value,
        capability_id=action.capability_id,
        fields=tuple(
            ActionField(
                id=field.id,
                value=field.value,
                entity_ids=field.entity_ids,
                channel_bindings=tuple(
                    _command_channel_binding(binding)
                    for binding in field.channel_bindings
                ),
            )
            for field in action.fields
        ),
    )


def _explicit_instrument_order(
    plan: BoundPlan,
    *,
    instrument_order: Sequence[str],
) -> tuple[str, ...]:
    selected = tuple(instrument_order)
    if len(selected) != len(set(selected)) or any(not item for item in selected):
        msg = "instrument_order must contain unique non-empty ids"
        raise ValueError(msg)
    fixed: set[str] = (
        {
            state.resource_id.value
            for point in plan.points
            for state in point.desired_state
        }
        | {
            collect.resource_id.value
            for point in plan.points
            for collect in point.collect
        }
        | {
            action.resource_id.value
            for point in plan.points
            for action in point.actions
        }
    )
    missing = sorted(fixed - set(selected))
    if selected and missing:
        msg = "instrument_order is missing bound resources: " + ", ".join(missing)
        raise ValueError(msg)
    if not selected:
        return tuple(sorted(fixed))
    return selected


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
        channel_bindings = (
            binding for route in point.routes for binding in route.channel_bindings
        )
        state_bindings = (
            binding
            for state in point.desired_state
            for field in state.fields
            for binding in field.channel_bindings
        )
        collect_bindings = (
            binding
            for collect in point.collect
            for request in collect.requests
            for binding in request.channel_bindings
        )
        action_bindings = (
            binding
            for action in point.actions
            for field in action.fields
            for binding in field.channel_bindings
        )
        for binding in (
            *channel_bindings,
            *state_bindings,
            *action_bindings,
            *collect_bindings,
        ):
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


def _compute_operation_id(logical_point_id: str, operation_id: OperationId) -> str:
    return f"{logical_point_id}.compute.{operation_id.qualified_name}"


__all__ = ["build_execution_program"]
