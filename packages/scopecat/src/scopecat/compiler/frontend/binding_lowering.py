"""Lower source resource declarations into typed logical requirements."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from scopecat.authoring._binding_intents import (
    BindingIntent,
    ResourcePort,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_value_ref,
)
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entities,
    resolve_entity,
)
from scopecat.compiler.frontend.problems import (
    raise_entity_resolution_problem,
)
from scopecat.compiler.frontend.value_binding import bind_value_input_refs
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.value_expressions import (
    ScalarOrSeriesValueExpr,
    verify_scalar_value_expr,
    verify_series_value_expr,
)
from scopecat.compiler.typed.program import LogicalResourceRequirement
from scopecat.graph.relations.model import (
    LiteralScalarExpr,
    ScalarExpr,
    SeriesExpr,
    ValuesSeriesExpr,
    as_scalar_expr,
)
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.value_types import Entity, Scalar, Series
from scopecat.records.config import Topology


@dataclass(frozen=True)
class BindingSpec:
    """Private compiler-ready desired-state binding."""

    resource_port_id: LogicalResourcePortId
    capability_id: str
    field_path: str
    value: ScalarExpr | ComputeResultRef
    value_type: Scalar | None


def lower_binding_intent(
    intent: BindingIntent,
) -> BindingSpec:
    """Lower one source binding after config-free graph verification."""

    value = intent.value
    value_type: Scalar | None = None
    if isinstance(value, ValueRef):
        declared_type = value.value_type
        value = internal_lower_value_ref(value)
        if not isinstance(value, ScalarExpr | ComputeResultRef):
            raise AssertionError(
                "verified state binding values must be scalar expressions or "
                "compute results"
            )
        if isinstance(value, ScalarExpr):
            if not isinstance(declared_type, Scalar):
                raise AssertionError(
                    "verified state binding scalar expressions must declare a "
                    "scalar type"
                )
            value_type = declared_type
    return BindingSpec(
        resource_port_id=intent.port_id,
        capability_id=intent.capability_id,
        field_path=intent.field_path,
        value=value if isinstance(value, ComputeResultRef) else as_scalar_expr(value),
        value_type=value_type,
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
                capabilities=tuple(port.selector.capabilities),
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
) -> ScalarOrSeriesValueExpr:
    value_type = source.value_type
    lowered = internal_lower_value_ref(source)
    if not (
        (
            isinstance(value_type, Scalar)
            and isinstance(value_type.atom, Entity)
            and isinstance(lowered, ScalarExpr)
        )
        or (
            isinstance(value_type, Series)
            and isinstance(value_type.item_type.atom, Entity)
            and isinstance(lowered, SeriesExpr)
        )
    ):
        raise AssertionError(
            "verified resource entity source must match its declared entity shape"
        )
    bound = bind_value_input_refs(lowered, inputs)
    if not isinstance(bound, ScalarExpr | SeriesExpr):
        raise AssertionError(
            "binding a verified resource entity source must preserve its shape"
        )
    if isinstance(bound, LiteralScalarExpr):
        bound = replace(
            bound,
            value=_resolve_target_entity(
                topology,
                cast("EntityRef | str", bound.value),
            ),
        )
    if isinstance(bound, ValuesSeriesExpr):
        bound = replace(
            bound,
            items=list(
                _resolve_target_entities(
                    topology, cast("Sequence[EntityRef | str]", bound.items)
                )
            ),
        )
    if isinstance(bound, ScalarExpr) and isinstance(value_type, Scalar):
        return verify_scalar_value_expr(
            bound,
            bindings=type_bindings,
            expected_type=value_type,
        )
    if isinstance(bound, SeriesExpr) and isinstance(value_type, Series):
        return verify_series_value_expr(
            bound,
            bindings=type_bindings,
            expected_type=value_type,
        )
    raise AssertionError(
        "binding a verified resource entity source must preserve its declared shape"
    )


def _resolve_target_entity(
    topology: Topology,
    value: EntityRef | str,
) -> EntityRef:
    try:
        return resolve_entity(topology, value)
    except EntityResolutionError as error:
        raise_entity_resolution_problem(error)


def _resolve_target_entities(
    topology: Topology,
    values: Sequence[EntityRef | str],
) -> tuple[EntityRef, ...]:
    try:
        return resolve_entities(topology, values)
    except EntityResolutionError as error:
        raise_entity_resolution_problem(error)
