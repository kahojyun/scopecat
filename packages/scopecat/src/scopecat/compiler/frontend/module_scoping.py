"""Localize module declarations and effects across instance boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
    ResourceSelector,
)
from scopecat.program.domain import DomainExecution
from scopecat.program.identities import InvocationKey
from scopecat.program.logical import AcquireEffect
from scopecat.program.measurements import MeasurementCompute
from scopecat.program.operations import ComputeNodeInputValue, ModuleOperationDecl
from scopecat.program.products import (
    ModuleProductDecl,
    localize_product_input_refs,
    prefix_product_decl,
)
from scopecat.program.value_refs import ValueRef
from scopecat.program.value_transforms import (
    internal_bind_value_ref_inputs,
    internal_scope_value_ref,
)
from scopecat.program.value_types import Table as TableType

type DefinitionEffect = (
    BindingIntent
    | EnsureStateIntent
    | InvocationIntent
    | DomainExecution
    | AcquireEffect
)


@dataclass(frozen=True, slots=True)
class InstanceBoundary:
    """One child-to-parent localization step in a hierarchy traversal."""

    instance_id: str
    invocation_key: InvocationKey
    inputs: Mapping[str, ValueRef]

    @property
    def scope(self) -> tuple[str, ...]:
        return (self.instance_id,)

    @property
    def origin(self) -> tuple[object, ...]:
        return (self.invocation_key,)


def localize_value_ref(
    value: ValueRef,
    boundaries: Sequence[InstanceBoundary],
) -> ValueRef:
    selected = value
    for boundary in boundaries:
        selected = scope_value_ref(
            selected,
            boundary.inputs,
            scope=boundary.scope,
            origin=boundary.origin,
        )
    return selected


def localize_operation(
    operation: ModuleOperationDecl,
    boundaries: Sequence[InstanceBoundary],
) -> ModuleOperationDecl:
    selected = operation
    for boundary in boundaries:
        selected = _scope_operation(
            selected,
            boundary.inputs,
            scope=boundary.scope,
            origin=boundary.origin,
        )
    return selected


def localize_measurement_compute(
    compute: MeasurementCompute,
    boundaries: Sequence[InstanceBoundary],
) -> MeasurementCompute:
    selected = compute
    for boundary in boundaries:
        selected = _scope_measurement_compute(
            selected,
            boundary.inputs,
            scope=boundary.scope,
            origin=boundary.origin,
        )
    return selected


def localize_product_declaration(
    product: ModuleProductDecl,
    boundaries: Sequence[InstanceBoundary],
) -> ModuleProductDecl:
    selected = product
    for boundary in boundaries:
        selected = _scope_product_declaration(
            selected,
            boundary.inputs,
            scope=boundary.scope,
            origin=boundary.origin,
        )
    return selected


def localize_resource_port(
    port: ResourcePort,
    boundaries: Sequence[InstanceBoundary],
) -> ResourcePort:
    port_id = port.symbol_id
    for boundary in boundaries:
        port_id = port_id.prefixed(*boundary.scope)
    entity_inputs = tuple(
        localize_value_ref(source, boundaries) for source in port.selector.entity_inputs
    )
    if any(isinstance(source.value_type, TableType) for source in entity_inputs):
        msg = (
            "resource entity source must be scalar-shaped; "
            "declare the resource footprint explicitly"
        )
        raise TypeError(msg)
    return replace(
        port,
        symbol_id=port_id,
        selector=ResourceSelector(
            capabilities=port.selector.capabilities,
            entity_inputs=entity_inputs,
            role=port.selector.role,
        ),
    )


def localize_effect(
    effect: DefinitionEffect,
    boundaries: Sequence[InstanceBoundary],
) -> DefinitionEffect:
    selected = effect
    for boundary in boundaries:
        resource_ids = {
            port_id: port_id.prefixed(*boundary.scope)
            for port_id in _effect_resource_ids(selected)
        }
        selected = _scope_effect(
            selected,
            boundary.inputs,
            scope=boundary.scope,
            origin=boundary.origin,
            resource_ids=resource_ids,
        )
    return selected


def scope_value_ref(
    value: ValueRef,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> ValueRef:
    """Attach a typed child-input environment without lowering its value graph."""

    typed_inputs = {
        input_id: selected
        for input_id, selected in inputs.items()
        if isinstance(selected, ValueRef)
    }
    if len(typed_inputs) != len(inputs):
        msg = "localized module inputs must remain typed values"
        raise TypeError(msg)
    return internal_bind_value_ref_inputs(
        internal_scope_value_ref(value, *scope, origin=origin),
        typed_inputs,
    )


def _effect_resource_ids(
    effect: DefinitionEffect,
) -> tuple[LogicalResourcePortId, ...]:
    if isinstance(effect, BindingIntent):
        return (effect.port_id,)
    if isinstance(effect, EnsureStateIntent):
        return tuple(assignment.port_id for assignment in effect.assignments)
    if isinstance(effect, InvocationIntent):
        return (effect.port_id,)
    if isinstance(effect, AcquireEffect):
        return (effect.resource_port_id,)
    return ()


def _scope_effect(
    effect: DefinitionEffect,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> DefinitionEffect:
    if isinstance(effect, BindingIntent):
        return _scope_binding(
            effect,
            inputs,
            scope=scope,
            origin=origin,
            resource_ids=resource_ids,
        )
    if isinstance(effect, EnsureStateIntent):
        return replace(
            effect,
            assignments=tuple(
                _scope_binding(
                    assignment,
                    inputs,
                    scope=scope,
                    origin=origin,
                    resource_ids=resource_ids,
                )
                for assignment in effect.assignments
            ),
        )
    if isinstance(effect, InvocationIntent):
        return _scope_invocation(
            effect,
            inputs,
            scope=scope,
            origin=origin,
            resource_ids=resource_ids,
        )
    if isinstance(effect, DomainExecution):
        return _scope_domain_execution(
            effect,
            inputs,
            scope=scope,
            origin=origin,
        )
    return replace(
        effect,
        id=effect.id.prefixed(*scope),
        resource_port_id=resource_ids.get(
            effect.resource_port_id,
            effect.resource_port_id,
        ),
        results=tuple(
            replace(result, product_id=result.product_id.prefixed(*scope))
            for result in effect.results
        ),
    )


def _scope_domain_execution(
    execution: DomainExecution,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> DomainExecution:
    return replace(
        execution,
        id="/".join((*scope, execution.id)),
        input_bindings=tuple(
            (
                name,
                scope_value_ref(value, inputs, scope=scope, origin=origin)
                if isinstance(value, ValueRef)
                else value,
            )
            for name, value in execution.input_bindings
        ),
        compiler_input_bindings=tuple(
            (
                name,
                scope_value_ref(value, inputs, scope=scope, origin=origin)
                if isinstance(value, ValueRef)
                else value,
            )
            for name, value in execution.compiler_input_bindings
        ),
        result_bindings=tuple(
            (
                name,
                replace(
                    product,
                    product_id=product.product_id.prefixed(*scope),
                    origin=(*origin, *product.origin),
                ),
            )
            for name, product in execution.result_bindings
        ),
    )


def _scope_product_declaration(
    product: ModuleProductDecl,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> ModuleProductDecl:
    localized = localize_product_input_refs(
        product,
        inputs,
        localize_value_ref=lambda value, selected_inputs: scope_value_ref(
            value,
            selected_inputs,
            scope=scope,
            origin=origin,
        ),
    )
    return prefix_product_decl(localized, *scope, origin=origin)


def _scope_binding(
    binding: BindingIntent,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> BindingIntent:
    port_id = resource_ids.get(binding.port_id, binding.port_id)
    if isinstance(binding.value, ValueRef):
        return replace(
            binding,
            port_id=port_id,
            value=scope_value_ref(
                binding.value,
                inputs,
                scope=scope,
                origin=origin,
            ),
        )
    return replace(binding, port_id=port_id)


def _scope_invocation(
    invocation: InvocationIntent,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> InvocationIntent:
    return replace(
        invocation,
        scope=(*scope, *invocation.scope),
        port_id=resource_ids.get(invocation.port_id, invocation.port_id),
        arguments=tuple(
            replace(
                argument,
                value=(
                    scope_value_ref(
                        argument.value,
                        inputs,
                        scope=scope,
                        origin=origin,
                    )
                    if isinstance(argument.value, ValueRef)
                    else argument.value
                ),
            )
            for argument in invocation.arguments
        ),
    )


def _scope_operation(
    operation: ModuleOperationDecl,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> ModuleOperationDecl:
    return replace(
        operation,
        scope=(*scope, *operation.scope),
        instance_path=(*origin, *operation.instance_path),
        inputs=tuple(
            (
                name,
                _scope_operation_input(
                    value,
                    inputs,
                    scope=scope,
                    origin=origin,
                ),
            )
            for name, value in operation.inputs
        ),
    )


def _scope_measurement_compute(
    compute: MeasurementCompute,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> MeasurementCompute:
    return replace(
        compute,
        scope=(*scope, *compute.scope),
        input_bindings=tuple(
            (name, product_id.prefixed(*scope))
            for name, product_id in compute.input_bindings
        ),
        value_input_bindings=tuple(
            (
                name,
                _scope_operation_input(
                    value,
                    inputs,
                    scope=scope,
                    origin=origin,
                ),
            )
            for name, value in compute.value_input_bindings
        ),
        output_bindings=tuple(
            (role, product_id.prefixed(*scope))
            for role, product_id in compute.output_bindings
        ),
    )


def _scope_operation_input(
    value: ComputeNodeInputValue,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> ComputeNodeInputValue:
    if isinstance(value, ValueRef):
        return scope_value_ref(value, inputs, scope=scope, origin=origin)
    return value
