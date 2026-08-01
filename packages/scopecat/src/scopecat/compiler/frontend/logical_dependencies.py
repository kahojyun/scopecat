"""Collect closed value roots and dependency contracts for composition."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.frontend.module_scoping import DefinitionEffect
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
)
from scopecat.program.domain import DomainExecution
from scopecat.program.operations import ModuleInputPort
from scopecat.program.parameters import ParameterContract, merge_parameter_contracts
from scopecat.program.products import ModuleProductDecl
from scopecat.program.value_refs import (
    PointValueDependency,
    ValueRef,
    internal_require_resolved_value_ref,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)
from scopecat.program.value_types import Entity as EntityType
from scopecat.program.value_types import Scalar as ScalarType


@dataclass(frozen=True, slots=True)
class ValueRefDependencies:
    point: tuple[PointValueDependency, ...]
    parameters: tuple[ParameterContract, ...]


def summarize_value_ref_dependencies(
    values: Iterable[ValueRef],
) -> ValueRefDependencies:
    point_groups: list[tuple[PointValueDependency, ...]] = []
    parameter_groups: list[tuple[ParameterContract, ...]] = []
    for value in values:
        point_groups.append(internal_value_ref_point_dependencies(value))
        parameter_groups.append(internal_value_ref_parameter_contracts(value))
    return ValueRefDependencies(
        point=_merge_point_dependencies(*point_groups),
        parameters=merge_parameter_contracts(*parameter_groups),
    )


def nested_value_refs(value: object) -> tuple[ValueRef, ...]:
    return _nested_value_refs(value, seen=frozenset())


def entity_input_ids(ports: Sequence[ModuleInputPort]) -> tuple[str, ...]:
    return tuple(
        port.id
        for port in ports
        if isinstance(port.value_type, ScalarType)
        and isinstance(port.value_type.atom, EntityType)
    )


def require_closed_logical_values(
    inputs: Mapping[str, object],
    consumed_roots: Sequence[object],
) -> None:
    for root in (*inputs.values(), *consumed_roots):
        for value in nested_value_refs(root):
            internal_require_resolved_value_ref(value, context="logical program")


def logical_value_roots(
    *,
    resource_ports: Sequence[ResourcePort],
    product_declarations: Sequence[ModuleProductDecl],
    effects: Sequence[DefinitionEffect],
) -> tuple[object, ...]:
    """Return values that contribute to the closed logical graph."""

    roots: list[object] = []
    roots.extend(
        source for port in resource_ports for source in port.selector.entity_inputs
    )
    roots.extend(
        binding.value
        for effect in effects
        for binding in (
            (effect,)
            if isinstance(effect, BindingIntent)
            else effect.assignments
            if isinstance(effect, EnsureStateIntent)
            else ()
        )
    )
    roots.extend(
        argument.value
        for effect in effects
        if isinstance(effect, InvocationIntent)
        for argument in effect.arguments
    )
    roots.extend(
        value
        for execution in effects
        if isinstance(execution, DomainExecution)
        for _name, value in (
            *execution.input_bindings,
            *execution.compiler_input_bindings,
        )
    )
    roots.extend(axis.size for product in product_declarations for axis in product.axes)
    return tuple(roots)


def _nested_value_refs(
    value: object,
    *,
    seen: frozenset[int],
) -> tuple[ValueRef, ...]:
    if isinstance(value, ValueRef):
        return (value,)
    if isinstance(value, Mapping):
        selected = cast("Mapping[object, object]", value)
        marker = id(selected)
        if marker in seen:
            return ()
        nested_seen = seen | {marker}
        return tuple(
            value_ref
            for item in selected.values()
            for value_ref in _nested_value_refs(item, seen=nested_seen)
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        selected = value
        marker = id(selected)
        if marker in seen:
            return ()
        nested_seen = seen | {marker}
        return tuple(
            value_ref
            for item in selected
            for value_ref in _nested_value_refs(item, seen=nested_seen)
        )
    return ()


def _merge_point_dependencies(
    *groups: tuple[PointValueDependency, ...],
) -> tuple[PointValueDependency, ...]:
    selected: dict[str, PointValueDependency] = {}
    for dependency in (item for group in groups for item in group):
        existing = selected.get(dependency.id)
        if existing is not None and existing.value_type != dependency.value_type:
            msg = (
                f"point value {dependency.id!r} is used with conflicting declared types"
            )
            raise TypeError(msg)
        selected.setdefault(dependency.id, dependency)
    return tuple(selected.values())
