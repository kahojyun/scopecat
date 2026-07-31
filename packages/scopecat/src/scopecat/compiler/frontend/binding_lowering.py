"""Lower source resource declarations and desired-state bindings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entity,
)
from scopecat.compiler.frontend.assembly_lowering import lower_logical_value
from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.compiler.frontend.problems import (
    raise_entity_resolution_problem,
)
from scopecat.compiler.frontend.value_binding import (
    bind_scalar_input_refs,
)
from scopecat.compiler.relations.uses import RelationUse, relation_use
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
    ComputeEdge,
    LogicalResourceRequirement,
    set_state_property,
)
from scopecat.compiler.typed.state import EnsureStateSpec, SetStateSpec
from scopecat.graph.relations.model import LiteralScalarExpr, ScalarExpr
from scopecat.graph.values import ComputeResultRef, ValueId
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Entity, Scalar
from scopecat.program.bindings import ResourcePort
from scopecat.program.logical import (
    LogicalEnsureState,
    LogicalInvocation,
    LogicalStateAssignment,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_value_ref,
)
from scopecat.records.config import Topology


def lower_state_binding(
    assignment: LogicalStateAssignment,
    *,
    program: VerifiedLogicalProgram,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> SetStateSpec:
    """Bind one closed logical state edge to its typed value."""

    value = _lower_effect_value(
        assignment.value_id,
        program=program,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    return set_state_property(
        resource_port_id=assignment.port_id,
        interface_id=assignment.interface_id,
        component_path=assignment.component_path,
        property_id=assignment.property_id,
        value=value,
    )


def lower_ensure_state(
    effect: LogicalEnsureState,
    *,
    program: VerifiedLogicalProgram,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> EnsureStateSpec:
    """Bind one coherent logical target into typed desired state."""

    return EnsureStateSpec(
        tuple(
            lower_state_binding(
                assignment,
                program=program,
                inputs=inputs,
                type_bindings=type_bindings,
            )
            for assignment in effect.assignments
        )
    )


def lower_invocation(
    invocation: LogicalInvocation,
    *,
    program: VerifiedLogicalProgram,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> InvokeEffect:
    """Bind one verified logical operation invocation."""

    arguments: list[InvokeArgument] = []
    for argument in invocation.arguments:
        arguments.append(
            InvokeArgument(
                id=argument.id,
                value_use=_effect_value_use(
                    _lower_effect_value(
                        argument.value_id,
                        program=program,
                        inputs=inputs,
                        type_bindings=type_bindings,
                    )
                ),
            )
        )
    return InvokeEffect(
        id=InvokeId(SymbolId(scope=invocation.scope, local_id=invocation.id)),
        resource_port_id=invocation.port_id,
        interface_id=invocation.interface_id,
        component_path=invocation.component_path,
        operation_id=invocation.operation_id,
        arguments=tuple(arguments),
    )


def _lower_effect_value(
    value_id: ValueId,
    *,
    program: VerifiedLogicalProgram,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
) -> ScalarValueExpr | ComputeResultRef:
    lowered = lower_logical_value(
        program,
        value_id,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    if isinstance(lowered, ComputeEdge):
        return ComputeResultRef(lowered.value_id)
    if not isinstance(lowered, ScalarValueExpr):
        raise AssertionError("verified logical effect values must be scalar")
    return lowered


def _effect_value_use(
    value: ScalarValueExpr | ComputeResultRef,
) -> RelationUse[ScalarValueExpr] | ComputeResultRef:
    return value if isinstance(value, ComputeResultRef) else relation_use(value)


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
