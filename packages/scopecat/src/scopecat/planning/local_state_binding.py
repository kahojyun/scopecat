"""Bind desired state and invocation effects for local execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import cast

from scopecat.compiler.bind import BoundPlan
from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.point_domain import MaterializedPoint
from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.value_resolution import resolve_bound_value
from scopecat.execution.local.program import (
    ApplyStateOperation,
    InvokeOperation,
    StateTarget,
)
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.problems import ModelLocation, Problem, model_location
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.value_types import Scalar
from scopecat.planning.local_effects import (
    StateRecord,
    evaluate_effect_value,
    evaluate_state_assignment,
)
from scopecat.planning.local_resources import (
    ChannelSignature,
    ResourceEntitySelection,
    bind_state_resource,
    channel_signature,
)
from scopecat.planning.routing import ResourceBindingError
from scopecat.program.expressions import ComputeResultScalarExpr, ScalarExpr
from scopecat.program.logical import LogicalInvocation, LogicalStateAssignment
from scopecat.program.value_graph import ValueId
from scopecat.sdk.instruments.commands import InstrumentOperationArgument


def bound_scalar_value(bound: BoundPlan, value_id: ValueId) -> ScalarExpr:
    value = resolve_bound_value(bound.program, bound.bindings, value_id)
    if not isinstance(value, ScalarExpr):
        raise AssertionError("verified effect values must be scalar")
    return value


def evaluate_state_records(
    state: LogicalStateAssignment,
    bound: BoundPlan,
    effect_index: int,
    point: MaterializedPoint,
    params: ParameterRelationData,
    *,
    problems: list[Problem],
) -> tuple[StateRecord, ...]:
    ctx = EvalContext(params=params, point_row=point.row)
    try:
        return (
            evaluate_state_assignment(
                state,
                bound_scalar_value(bound, state.value_id),
                cast("Scalar", bound.program.value_types[state.value_id]),
                point_index=point.logical_ordinal,
                ctx=ctx,
            ),
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        problems.append(
            compiler_problem(
                "experiment_state_evaluation_failed",
                f"state binding failed for point {point.logical_ordinal}: {error}",
                model_location("effects", effect_index),
            )
        )
        return ()


def bind_desired_state(
    records: Sequence[StateRecord],
    *,
    point_uid: str,
    state_group_index: int,
    resources: Mapping[LogicalResourcePortId, ResourceEntitySelection],
    point_index: int,
    payload_ids: Mapping[ValueId, str],
    known_compute_results: AbstractSet[ValueId],
    problems: list[Problem],
    state_context: str | None = None,
    state_location: ModelLocation | None = None,
) -> tuple[ApplyStateOperation, ...]:
    selected_context = state_context or f"point {point_index}"
    selected_location = state_location or model_location(
        "points",
        point_index,
        "desired_state",
    )
    grouped: dict[
        str,
        dict[
            tuple[
                InterfaceId,
                tuple[str, ...],
                str,
                tuple[str, ...],
                ChannelSignature,
            ],
            StateTarget,
        ],
    ] = {}
    signatures: dict[
        tuple[
            str,
            InterfaceId,
            tuple[str, ...],
            str,
            tuple[str, ...],
            ChannelSignature,
        ],
        set[str],
    ] = {}
    owners: dict[
        tuple[
            str,
            InterfaceId,
            tuple[str, ...],
            str,
            tuple[str, ...],
            ChannelSignature,
        ],
        set[LogicalResourcePortId],
    ] = {}
    for record in records:
        interface_id = record.interface_id
        component_path = record.component_path
        property_id = record.property_id
        if isinstance(record.value, ComputeResultScalarExpr):
            result_id = record.value.value_id
            if result_id not in known_compute_results:
                problems.append(
                    compiler_problem(
                        "compute_payload_unknown_output",
                        "state references unknown compute result "
                        f"{result_id.qualified_name!r}",
                        selected_location,
                    )
                )
                continue
            payload_id = payload_ids.get(result_id)
            if payload_id is None:
                problems.append(
                    compiler_problem(
                        "compute_payload_unavailable",
                        "state compute output is not an available payload: "
                        f"{result_id.qualified_name!r}",
                        selected_location,
                    )
                )
                continue
            selected_value = StateValue(PayloadRef(payload_id=payload_id))
        else:
            selected_value = _state_value(record.value)
        if selected_value is None:
            problems.append(
                compiler_problem(
                    "state_value_unsupported",
                    "state values must be finite numbers, quantities, "
                    "strings, booleans, or available compute payloads",
                    model_location("desired_state", "value"),
                )
            )
            continue
        try:
            binding = bind_state_resource(
                record.resource_target,
                interface_id=interface_id,
                resources=resources,
            )
        except ResourceBindingError as error:
            problems.append(
                compiler_problem(
                    error.code,
                    str(error),
                    model_location("desired_state", "resource_port_id"),
                )
            )
            continue
        channel_key = channel_signature(binding.channel_bindings)
        group = grouped.setdefault(binding.instrument_id, {})
        key = (
            interface_id,
            component_path,
            property_id,
            binding.entity_ids,
            channel_key,
        )
        signature_key = (
            binding.instrument_id,
            interface_id,
            component_path,
            property_id,
            binding.entity_ids,
            channel_key,
        )
        signatures.setdefault(signature_key, set()).add(
            selected_value.model_dump_json()
        )
        owners.setdefault(signature_key, set()).add(record.resource_target)
        group.setdefault(
            key,
            StateTarget(
                interface_id=interface_id,
                component_path=component_path,
                property_id=property_id,
                value=selected_value,
                entity_ids=binding.entity_ids,
                channel_bindings=binding.channel_bindings,
            ),
        )
    for (
        resource,
        interface,
        component_path,
        property_id,
        _entities,
        _channel,
    ), values in signatures.items():
        if len(values) > 1:
            problems.append(
                compiler_problem(
                    "experiment_conflicting_desired_state",
                    f"{resource}.{interface}/"
                    f"{'/'.join(component_path)}.{property_id} receives "
                    f"multiple values at {selected_context}",
                    selected_location,
                )
            )
    for (
        resource,
        interface,
        component_path,
        property_id,
        _entities,
        _channel,
    ), target_owners in owners.items():
        if len(target_owners) > 1:
            problems.append(
                compiler_problem(
                    "experiment_aliased_desired_state_target",
                    f"{resource}.{interface}/"
                    f"{'/'.join(component_path)}.{property_id} is owned by multiple "
                    f"resource targets at {selected_context}",
                    selected_location,
                )
            )
    return tuple(
        ApplyStateOperation(
            operation_id=f"{point_uid}.state.{state_group_index}.{instrument_id}",
            instrument_id=instrument_id,
            targets=tuple(targets.values()),
        )
        for instrument_id, targets in grouped.items()
    )


def bind_invocation(
    effect: LogicalInvocation,
    bound: BoundPlan,
    resources: Mapping[LogicalResourcePortId, ResourceEntitySelection],
    *,
    point_uid: str,
    point_index: int,
    ctx: EvalContext,
    payload_ids: Mapping[ValueId, str],
    known_compute_results: AbstractSet[ValueId],
    problems: list[Problem],
) -> InvokeOperation | None:
    try:
        binding = bind_state_resource(
            effect.port_id,
            interface_id=effect.interface_id,
            resources=resources,
        )
    except ResourceBindingError as error:
        problems.append(
            compiler_problem(
                error.code,
                str(error),
                model_location("invocations", effect.qualified_name, "resource"),
            )
        )
        return None

    arguments: list[InstrumentOperationArgument] = []
    for argument in effect.arguments:
        try:
            value = evaluate_effect_value(
                bound_scalar_value(bound, argument.value_id),
                cast("Scalar", bound.program.value_types[argument.value_id]),
                ctx=ctx,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            problems.append(
                compiler_problem(
                    "instrument_invocation_argument_evaluation_failed",
                    f"invocation {effect.qualified_name!r} argument "
                    f"{argument.id!r} failed for point {point_index}: {error}",
                    model_location(
                        "invocations",
                        effect.qualified_name,
                        "arguments",
                        argument.id,
                    ),
                )
            )
            continue
        if isinstance(value, ComputeResultScalarExpr):
            if value.value_id not in known_compute_results:
                problems.append(
                    compiler_problem(
                        "compute_payload_unknown_output",
                        "invocation references unknown compute result "
                        f"{value.value_id.qualified_name!r}",
                        model_location(
                            "invocations",
                            effect.qualified_name,
                            "arguments",
                            argument.id,
                        ),
                    )
                )
                continue
            payload_id = payload_ids.get(value.value_id)
            if payload_id is None:
                problems.append(
                    compiler_problem(
                        "compute_payload_unavailable",
                        "invocation compute output is not an available payload: "
                        f"{value.value_id.qualified_name!r}",
                        model_location(
                            "invocations",
                            effect.qualified_name,
                            "arguments",
                            argument.id,
                        ),
                    )
                )
                continue
            selected_value = StateValue(PayloadRef(payload_id=payload_id))
        else:
            selected_value = _state_value(value)
            if selected_value is None:
                problems.append(
                    compiler_problem(
                        "instrument_invocation_argument_unsupported",
                        f"invocation {effect.qualified_name!r} argument "
                        f"{argument.id!r} must be a finite scalar value",
                        model_location(
                            "invocations",
                            effect.qualified_name,
                            "arguments",
                            argument.id,
                        ),
                    )
                )
                continue
        arguments.append(
            InstrumentOperationArgument(id=argument.id, value=selected_value)
        )
    if len(arguments) != len(effect.arguments):
        return None
    return InvokeOperation(
        effect_id=f"{point_uid}.invoke.{effect.qualified_name}",
        instrument_id=binding.instrument_id,
        resource_id=binding.instrument_id,
        interface_id=effect.interface_id,
        component_path=effect.component_path,
        operation_id=effect.operation_id,
        arguments=tuple(arguments),
        entity_ids=binding.entity_ids,
        channel_bindings=binding.channel_bindings,
    )


def _state_value(value: object) -> StateValue | None:
    if isinstance(value, Quantity):
        return StateValue(value) if math.isfinite(value.value) else None
    if isinstance(value, bool | int | str):
        return StateValue(value)
    if isinstance(value, float):
        return StateValue(value) if math.isfinite(value) else None
    return None
