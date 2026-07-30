"""Lower source resource declarations and desired-state bindings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from scopecat.authoring._binding_intents import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_value_ref,
)
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entity,
)
from scopecat.compiler.frontend.problems import (
    raise_entity_resolution_problem,
)
from scopecat.compiler.frontend.value_binding import (
    bind_scalar_input_refs,
)
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    verify_scalar_value_expr,
)
from scopecat.compiler.typed.invocation import (
    InvokeArgument,
    InvokeEffect,
    InvokeId,
)
from scopecat.compiler.typed.program import (
    LogicalResourceRequirement,
    set_state_property,
)
from scopecat.compiler.typed.state import EnsureStateSpec, SetStateSpec
from scopecat.graph.relations.model import (
    LiteralScalarExpr,
    ScalarExpr,
    as_scalar_expr,
)
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Entity, Scalar
from scopecat.records.config import Topology


def lower_state_binding(
    intent: BindingIntent,
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> SetStateSpec:
    """Lower one verified authoring binding into typed desired state."""

    value_type: Scalar | None
    value = intent.value
    if isinstance(value, ValueRef):
        value_type = cast("Scalar", value.value_type)
        lowered = internal_lower_value_ref(value)
    else:
        value_type = None
        lowered = as_scalar_expr(value)
    return set_state_property(
        resource_port_id=intent.port_id,
        interface_id=intent.interface_id,
        component_path=intent.component_path,
        property_id=intent.property_id,
        value=(
            lowered
            if isinstance(lowered, ComputeResultRef)
            else verify_scalar_value_expr(
                bind_scalar_input_refs(cast("ScalarExpr", lowered), inputs),
                bindings=type_bindings,
                expected_type=value_type,
            )
        ),
    )


def lower_ensure_state(
    intent: EnsureStateIntent,
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> EnsureStateSpec:
    """Lower one coherent authoring target into typed desired state."""

    return EnsureStateSpec(
        tuple(
            lower_state_binding(
                assignment,
                inputs=inputs,
                type_bindings=type_bindings,
            )
            for assignment in intent.assignments
        )
    )


def lower_invocation(
    intent: InvocationIntent,
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> InvokeEffect:
    """Lower one verified atomic operation invocation."""

    arguments: list[InvokeArgument] = []
    for argument in intent.arguments:
        value_type: Scalar | None
        if isinstance(argument.value, ValueRef):
            value_type = cast("Scalar", argument.value.value_type)
            lowered = internal_lower_value_ref(argument.value)
        else:
            value_type = None
            lowered = as_scalar_expr(argument.value)
        arguments.append(
            InvokeArgument(
                id=argument.id,
                value_use=(
                    lowered
                    if isinstance(lowered, ComputeResultRef)
                    else relation_use(
                        verify_scalar_value_expr(
                            bind_scalar_input_refs(
                                cast("ScalarExpr", lowered),
                                inputs,
                            ),
                            bindings=type_bindings,
                            expected_type=value_type,
                        )
                    )
                ),
            )
        )
    return InvokeEffect(
        id=InvokeId(SymbolId(scope=intent.scope, local_id=intent.id)),
        resource_port_id=intent.port_id,
        interface_id=intent.interface_id,
        component_path=intent.component_path,
        operation_id=intent.operation_id,
        arguments=tuple(arguments),
    )


def build_resource_requirements(
    topology: Topology,
    ports: Sequence[ResourcePort],
    *,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> list[LogicalResourceRequirement]:
    resource_requirements: list[LogicalResourceRequirement] = []
    for port in ports:
        resource_requirements.append(
            LogicalResourceRequirement(
                port_id=port.symbol_id,
                interfaces=tuple(port.selector.interfaces),
                entity_uses=tuple(
                    relation_use(
                        _resource_entity_expr(
                            topology,
                            input_id,
                            inputs,
                            type_bindings=type_bindings,
                        )
                    )
                    for input_id in port.selector.entity_inputs
                ),
            )
        )
    return resource_requirements


def _resource_entity_expr(
    topology: Topology,
    source: ValueRef,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
) -> ScalarValueExpr:
    value_type = source.value_type
    lowered = internal_lower_value_ref(source)
    if not (
        isinstance(value_type, Scalar)
        and isinstance(value_type.atom, Entity)
        and isinstance(lowered, ScalarExpr)
    ):
        raise AssertionError("verified resource entity source must be a scalar entity")
    bound = bind_scalar_input_refs(lowered, inputs)
    if isinstance(bound, LiteralScalarExpr):
        bound = replace(
            bound,
            value=_resolve_target_entity(
                topology,
                cast("EntityRef | str", bound.value),
            ),
        )
    return verify_scalar_value_expr(
        bound,
        bindings=type_bindings,
        expected_type=value_type,
    )


def _resolve_target_entity(
    topology: Topology,
    value: EntityRef | str,
) -> EntityRef:
    try:
        return resolve_entity(topology, value)
    except EntityResolutionError as error:
        raise_entity_resolution_problem(error)
