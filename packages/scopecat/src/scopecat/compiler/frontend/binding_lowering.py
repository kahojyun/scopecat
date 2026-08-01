"""Lower source resource declarations and desired-state bindings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.compiler.bound_facts import (
    LogicalResourceRequirement,
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
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    verify_scalar_expression,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.value_types import Entity, Scalar
from scopecat.program.bindings import ResourcePort
from scopecat.program.expressions import (
    LiteralScalarExpr,
    ScalarExpr,
    lit,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_value_ref,
)
from scopecat.records.config import Topology


def build_resource_requirements(
    topology: Topology,
    ports: Sequence[ResourcePort],
    *,
    inputs: Mapping[str, object],
    type_bindings: ExpressionTypeBindings,
) -> list[LogicalResourceRequirement]:
    resource_requirements: list[LogicalResourceRequirement] = []
    for port in ports:
        resource_requirements.append(
            LogicalResourceRequirement(
                port_id=port.symbol_id,
                interfaces=tuple(port.selector.interfaces),
                entity_uses=tuple(
                    _resource_entity_expr(
                        topology,
                        input_id,
                        inputs,
                        type_bindings=type_bindings,
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
    type_bindings: ExpressionTypeBindings,
) -> ScalarExpr:
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
        bound = lit(
            _resolve_target_entity(
                topology,
                cast("EntityRef | str", bound.value),
            ),
            bound.value_type,
        )
    return verify_scalar_expression(
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
