"""Elaborate hierarchical Module IR into one closed, flat experiment IR."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol, cast

from scopecat.compiler.frontend.logical_closure import (
    close_logical_program,
    logical_compute_node_id,
)
from scopecat.graph.values import OperationId
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
    ResourceSelector,
    prefix_resource_port,
)
from scopecat.program.definitions import ExperimentDef
from scopecat.program.domain import DomainExecution
from scopecat.program.identities import InvocationKey
from scopecat.program.logical import (
    AcquireEffect,
    AcquireId,
    AcquireResult,
    LogicalProgram,
)
from scopecat.program.measurements import MeasurementPostprocessor
from scopecat.program.module import (
    ModuleAcquireEffect,
    ModuleBodyIR,
    ModuleDef,
    ModuleInstanceIR,
    ModuleInterfaceIR,
    ModulePythonImplementation,
)
from scopecat.program.operations import (
    ComputeNodeInputValue,
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.program.parameters import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.program.products import (
    ModuleProductDecl,
    RecordSelection,
    localize_product_input_refs,
    prefix_product_decl,
)
from scopecat.program.scans import AxisSpec
from scopecat.program.value_refs import (
    PointValueDependency,
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_require_resolved_value_ref,
    internal_scope_value_ref,
    internal_transform_value_ref,
    internal_value_ref_module_export,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)
from scopecat.program.value_types import (
    Entity as EntityType,
)
from scopecat.program.value_types import (
    Scalar as ScalarType,
)
from scopecat.program.value_types import (
    Table as TableType,
)
from scopecat.program.values import ComputeFunction

type _FragmentEffect = (
    BindingIntent
    | EnsureStateIntent
    | InvocationIntent
    | DomainExecution
    | AcquireEffect
)


def _empty_python_implementations() -> dict[OperationId, ComputeFunction]:
    return {}


@dataclass(frozen=True, kw_only=True)
class _ModuleFragment:
    """Hierarchy-free module declarations before logical graph closure."""

    inputs: dict[str, object] = field(default_factory=dict)
    input_ports: tuple[ModuleInputPort, ...] = ()
    entity_inputs: tuple[str, ...] = ()
    resource_ports: tuple[ResourcePort, ...] = ()
    point_dependencies: tuple[PointValueDependency, ...] = ()
    parameter_overlays: tuple[AxisSpec, ...] = ()
    product_declarations: tuple[ModuleProductDecl, ...] = ()
    record_selections: tuple[RecordSelection, ...] = ()
    parameter_contracts: tuple[ParameterContract, ...] = ()
    operations: tuple[ModuleOperationDecl, ...] = ()
    python_implementations: Mapping[OperationId, ComputeFunction] = field(
        default_factory=_empty_python_implementations
    )
    measurement_postprocessors: tuple[MeasurementPostprocessor, ...] = ()
    effects: tuple[_FragmentEffect, ...] = ()

    @property
    def bindings(self) -> tuple[BindingIntent, ...]:
        return tuple(
            binding
            for effect in self.effects
            for binding in (
                (effect,)
                if isinstance(effect, BindingIntent)
                else effect.assignments
                if isinstance(effect, EnsureStateIntent)
                else ()
            )
        )


@dataclass(frozen=True, slots=True)
class _ValueRefDependencies:
    point: tuple[PointValueDependency, ...]
    parameters: tuple[ParameterContract, ...]


class _HierarchyRoot(Protocol):
    """Structural program container accepted by hierarchy elaboration."""

    @property
    def interface(self) -> ModuleInterfaceIR: ...

    @property
    def body(self) -> ModuleBodyIR: ...

    @property
    def python_implementations(
        self,
    ) -> tuple[ModulePythonImplementation, ...]: ...


def _merge_module_fragments(
    *,
    fragments: Sequence[_ModuleFragment],
) -> _ModuleFragment:
    if not fragments:
        msg = "module fragment merge requires at least one fragment"
        raise ValueError(msg)
    merged_inputs: dict[str, object] = {}
    input_ports: list[ModuleInputPort] = []
    entity_inputs: list[str] = []
    resource_ports: list[ResourcePort] = []
    point_dependencies: list[tuple[PointValueDependency, ...]] = []
    parameter_overlays: list[AxisSpec] = []
    operations: list[ModuleOperationDecl] = []
    measurement_postprocessors: list[MeasurementPostprocessor] = []
    python_implementations: dict[OperationId, ComputeFunction] = {}
    product_declarations: list[ModuleProductDecl] = []
    record_selections: list[RecordSelection] = []
    parameter_contracts: list[tuple[ParameterContract, ...]] = []
    effects: list[_FragmentEffect] = []
    for fragment in fragments:
        merged_inputs.update(fragment.inputs)
        input_ports.extend(fragment.input_ports)
        entity_inputs.extend(fragment.entity_inputs)
        resource_ports.extend(fragment.resource_ports)
        point_dependencies.append(fragment.point_dependencies)
        parameter_overlays.extend(fragment.parameter_overlays)
        operations.extend(fragment.operations)
        measurement_postprocessors.extend(fragment.measurement_postprocessors)
        python_implementations.update(fragment.python_implementations)
        product_declarations.extend(fragment.product_declarations)
        record_selections.extend(fragment.record_selections)
        parameter_contracts.append(fragment.parameter_contracts)
        effects.extend(fragment.effects)
    merged_point_dependencies = _merge_point_dependencies(*point_dependencies)
    execution_ids = tuple(
        effect.id for effect in effects if isinstance(effect, DomainExecution)
    )
    if len(execution_ids) != len(set(execution_ids)):
        raise ValueError("module fragments contain repeated domain execution ids")
    return _ModuleFragment(
        inputs=merged_inputs,
        input_ports=tuple(input_ports),
        entity_inputs=tuple(entity_inputs),
        resource_ports=tuple(resource_ports),
        point_dependencies=merged_point_dependencies,
        parameter_overlays=tuple(parameter_overlays),
        operations=tuple(operations),
        measurement_postprocessors=tuple(measurement_postprocessors),
        python_implementations=python_implementations,
        product_declarations=tuple(product_declarations),
        record_selections=tuple(record_selections),
        parameter_contracts=merge_parameter_contracts(*parameter_contracts),
        effects=tuple(effects),
    )


def compose_module(
    module: ModuleDef,
    /,
    **inputs: object,
) -> LogicalProgram:
    """Elaborate one root module through the only hierarchy-flattening pass."""

    return _elaborate_hierarchy(
        module,
        experiment_id=module.id,
        kind=module.id,
        inputs=inputs,
        final_state=None,
    )


def compose_experiment(
    definition: ExperimentDef,
    *,
    inputs: Mapping[str, object],
) -> LogicalProgram:
    """Elaborate a native experiment root without a synthetic module."""

    return _elaborate_hierarchy(
        definition,
        experiment_id=definition.id,
        kind=definition.kind,
        inputs=inputs,
        final_state=definition.final_state,
    )


def _elaborate_hierarchy(
    root: _HierarchyRoot,
    *,
    experiment_id: str,
    kind: str,
    inputs: Mapping[str, object],
    final_state: EnsureStateIntent | None,
) -> LogicalProgram:
    fragment = _elaborate_program_ir(
        root,
        inputs=inputs,
    )
    value_roots = _module_fragment_value_roots(fragment)
    final_state_values = tuple(
        assignment.value
        for assignment in (() if final_state is None else final_state.assignments)
    )
    _require_closed_module_fragment(
        fragment,
        (*value_roots, *final_state_values),
    )
    final_state_dependencies = _summarize_value_ref_dependencies(
        value for root in final_state_values for value in _nested_value_refs(root)
    )
    fragment = replace(
        fragment,
        point_dependencies=_merge_point_dependencies(
            fragment.point_dependencies,
            final_state_dependencies.point,
        ),
        parameter_contracts=merge_parameter_contracts(
            fragment.parameter_contracts,
            final_state_dependencies.parameters,
        ),
    )
    program = LogicalProgram(
        experiment_id=experiment_id,
        kind=kind,
        inputs=fragment.inputs,
        input_ports=fragment.input_ports,
        entity_inputs=fragment.entity_inputs,
        resource_ports=fragment.resource_ports,
        point_dependencies=fragment.point_dependencies,
        parameter_overlays=fragment.parameter_overlays,
        product_declarations=fragment.product_declarations,
        record_selections=fragment.record_selections,
        parameter_contracts=fragment.parameter_contracts,
    )
    return close_logical_program(
        program,
        fragment.operations,
        fragment.python_implementations,
        measurement_postprocessors=fragment.measurement_postprocessors,
        effects=fragment.effects,
        final_state=final_state,
        value_roots=(*value_roots, *final_state_values),
    )


def _elaborate_program_ir(
    module: _HierarchyRoot,
    *,
    inputs: Mapping[str, object],
) -> _ModuleFragment:
    resolver = _ModuleValueResolver(module)
    source_fragments = {
        instance.invocation_key: _elaborate_instance(instance, resolver=resolver)
        for instance in module.body.child_instances
    }

    implementations = {
        implementation.declaration_key: implementation
        for implementation in module.python_implementations
    }
    own_effects: list[_FragmentEffect] = []
    for effect in module.body.effects:
        if isinstance(effect, ModuleInstanceIR):
            continue
        own_effects.append(_lower_module_effect(effect, resolver=resolver))
    own = _ModuleFragment(
        inputs=dict(inputs),
        input_ports=module.interface.imports,
        entity_inputs=_entity_input_ids(module.interface.imports),
        resource_ports=tuple(
            _resolve_resource_port(port, resolver=resolver)
            for port in module.interface.resources
        ),
        operations=tuple(
            _resolve_operation(operation, resolver=resolver)
            for operation in module.body.operations
        ),
        measurement_postprocessors=module.body.measurement_postprocessors,
        effects=tuple(own_effects),
        python_implementations={
            logical_compute_node_id(operation.operation_id): implementations[
                operation.declaration_key
            ].fn
            for operation in module.body.operations
        },
        product_declarations=tuple(
            _resolve_product(product, resolver=resolver)
            for product in module.body.products
        ),
    )
    typed_inputs = {
        input_id: value
        for input_id, value in inputs.items()
        if isinstance(value, ValueRef)
    }
    value_roots = (
        *_module_fragment_value_roots(own),
        *(resolver.resolve(export.source) for export in module.interface.exports),
    )
    value_dependencies = _summarize_value_ref_dependencies(
        internal_bind_value_ref_inputs(value, typed_inputs)
        for root in value_roots
        for value in _nested_value_refs(root)
    )
    own = replace(
        own,
        point_dependencies=value_dependencies.point,
        parameter_contracts=value_dependencies.parameters,
    )
    if not source_fragments:
        return own

    ordered_sources = tuple(
        source_fragments[instance.invocation_key]
        for instance in module.body.child_instances
    )
    combined = _merge_module_fragments(
        fragments=(*ordered_sources, own),
    )
    effects: list[_FragmentEffect] = []
    own_effect_iterator = iter(own.effects)
    for effect in module.body.effects:
        if isinstance(effect, ModuleInstanceIR):
            effects.extend(source_fragments[effect.invocation_key].effects)
        else:
            effects.append(next(own_effect_iterator))
    return replace(
        combined,
        effects=tuple(effects),
    )


def _lower_module_effect(
    effect: (
        BindingIntent
        | EnsureStateIntent
        | InvocationIntent
        | DomainExecution
        | ModuleAcquireEffect
    ),
    *,
    resolver: _ModuleValueResolver,
) -> _FragmentEffect:
    if isinstance(effect, BindingIntent):
        return _resolve_binding(effect, resolver=resolver)
    if isinstance(effect, EnsureStateIntent):
        return replace(
            effect,
            assignments=tuple(
                _resolve_binding(assignment, resolver=resolver)
                for assignment in effect.assignments
            ),
        )
    if isinstance(effect, InvocationIntent):
        return _resolve_invocation(effect, resolver=resolver)
    if isinstance(effect, DomainExecution):
        return _resolve_domain_execution(effect, resolver=resolver)
    return AcquireEffect(
        id=AcquireId(SymbolId(local_id=effect.id)),
        resource_port_id=effect.resource_port_id,
        interface_id=effect.interface_id,
        component_path=effect.component_path,
        acquisition_id=effect.acquisition_id,
        results=tuple(
            AcquireResult(
                product_id=result.product.product_id,
                result_id=result.result_id,
                metadata=result.metadata,
            )
            for result in effect.results
        ),
    )


def _elaborate_instance(
    instance: ModuleInstanceIR,
    *,
    resolver: _ModuleValueResolver,
) -> _ModuleFragment:
    local_inputs = {
        binding.import_id: resolver.resolve(binding.source)
        for binding in instance.input_bindings
    }
    fragment = _elaborate_program_ir(instance.module, inputs=local_inputs)
    return _scope_instance_graph(
        fragment,
        instance=instance,
        local_inputs=local_inputs,
    )


def _summarize_value_ref_dependencies(
    values: Iterable[ValueRef],
) -> _ValueRefDependencies:
    point_groups: list[tuple[PointValueDependency, ...]] = []
    parameter_groups: list[tuple[ParameterContract, ...]] = []
    for value in values:
        point_groups.append(internal_value_ref_point_dependencies(value))
        parameter_groups.append(internal_value_ref_parameter_contracts(value))
    return _ValueRefDependencies(
        point=_merge_point_dependencies(*point_groups),
        parameters=merge_parameter_contracts(*parameter_groups),
    )


_EMPTY_VISITED_VALUE_IDS: frozenset[int] = frozenset()


def _nested_value_refs(
    value: object,
    *,
    seen: frozenset[int] = _EMPTY_VISITED_VALUE_IDS,
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


class _ModuleValueResolver:
    """Resolve explicit instance-export edges within one Module IR boundary."""

    def __init__(self, module: _HierarchyRoot) -> None:
        self._instances = {
            instance.invocation_key: instance
            for instance in module.body.child_instances
        }
        self._exports: dict[tuple[InvocationKey, str], ValueRef] = {}
        self._active: set[tuple[InvocationKey, str]] = set()

    def resolve(self, value: ValueRef) -> ValueRef:
        return internal_transform_value_ref(value, self._resolve_leaf)

    def _resolve_leaf(self, value: ValueRef) -> ValueRef:
        selected = internal_value_ref_module_export(value)
        if selected is None:
            return value
        return self._resolve_export(*selected)

    def _resolve_export(
        self,
        invocation_key: InvocationKey,
        export_id: str,
    ) -> ValueRef:
        cache_key = (invocation_key, export_id)
        cached = self._exports.get(cache_key)
        if cached is not None:
            return cached
        if cache_key in self._active:
            raise CheckFailed(
                [
                    problem(
                        code="module_export_cycle",
                        phase=ProblemPhase.AUTHORING,
                        message=f"module export {export_id!r} forms a cycle",
                        location=model_location("module", "exports", export_id),
                    )
                ]
            )
        instance = self._instances.get(invocation_key)
        if instance is None:
            raise CheckFailed(
                [
                    problem(
                        code="module_export_foreign_instance",
                        phase=ProblemPhase.AUTHORING,
                        message=(
                            f"module export {export_id!r} belongs to an instance "
                            "that is not part of this module"
                        ),
                        location=model_location("module", "exports", export_id),
                    )
                ]
            )
        exports = {export.id: export for export in instance.module.interface.exports}
        export = exports.get(export_id)
        if export is None:
            raise CheckFailed(
                [
                    problem(
                        code="module_export_unknown",
                        phase=ProblemPhase.AUTHORING,
                        message=(
                            f"module instance {instance.instance_id!r} has no "
                            f"export {export_id!r}"
                        ),
                        location=model_location("module", "exports", export_id),
                    )
                ]
            )

        self._active.add(cache_key)
        try:
            child_resolver = _ModuleValueResolver(instance.module)
            local_source = child_resolver.resolve(export.source)
            local_inputs = {
                binding.import_id: self.resolve(binding.source)
                for binding in instance.input_bindings
            }
            localized = _scope_value_ref(
                local_source,
                local_inputs,
                scope=(instance.instance_id,),
                origin=(instance.invocation_key,),
            )
            resolved = self.resolve(localized)
            internal_require_resolved_value_ref(
                resolved,
                context=f"module export {export_id!r}",
            )
            self._exports[cache_key] = resolved
            return resolved
        finally:
            self._active.remove(cache_key)


def _entity_input_ids(ports: Sequence[ModuleInputPort]) -> tuple[str, ...]:
    return tuple(
        port.id
        for port in ports
        if isinstance(port.value_type, ScalarType)
        and isinstance(port.value_type.atom, EntityType)
    )


def _resolve_resource_port(
    port: ResourcePort,
    *,
    resolver: _ModuleValueResolver,
) -> ResourcePort:
    return replace(
        port,
        selector=ResourceSelector(
            interfaces=port.selector.interfaces,
            entity_inputs=tuple(
                resolver.resolve(value) for value in port.selector.entity_inputs
            ),
        ),
    )


def _resolve_binding(
    binding: BindingIntent,
    *,
    resolver: _ModuleValueResolver,
) -> BindingIntent:
    return replace(
        binding,
        value=(
            resolver.resolve(binding.value)
            if isinstance(binding.value, ValueRef)
            else binding.value
        ),
    )


def _resolve_invocation(
    invocation: InvocationIntent,
    *,
    resolver: _ModuleValueResolver,
) -> InvocationIntent:
    return replace(
        invocation,
        arguments=tuple(
            replace(
                argument,
                value=(
                    resolver.resolve(argument.value)
                    if isinstance(argument.value, ValueRef)
                    else argument.value
                ),
            )
            for argument in invocation.arguments
        ),
    )


def _resolve_operation(
    operation: ModuleOperationDecl,
    *,
    resolver: _ModuleValueResolver,
) -> ModuleOperationDecl:
    return replace(
        operation,
        inputs=tuple(
            (
                name,
                resolver.resolve(value) if isinstance(value, ValueRef) else value,
            )
            for name, value in operation.inputs
        ),
    )


def _resolve_domain_execution(
    execution: DomainExecution,
    *,
    resolver: _ModuleValueResolver,
) -> DomainExecution:
    return replace(
        execution,
        input_bindings=tuple(
            (
                name,
                resolver.resolve(value) if isinstance(value, ValueRef) else value,
            )
            for name, value in execution.input_bindings
        ),
        compiler_input_bindings=tuple(
            (
                name,
                resolver.resolve(value) if isinstance(value, ValueRef) else value,
            )
            for name, value in execution.compiler_input_bindings
        ),
    )


def _resolve_product(
    product: ModuleProductDecl,
    *,
    resolver: _ModuleValueResolver,
) -> ModuleProductDecl:
    return localize_product_input_refs(
        product,
        {},
        localize_value_ref=lambda value, _inputs: resolver.resolve(value),
    )


def _require_closed_module_fragment(
    fragment: _ModuleFragment,
    consumed_roots: Sequence[object],
) -> None:
    for root in (*fragment.inputs.values(), *consumed_roots):
        for value in _nested_value_refs(root):
            internal_require_resolved_value_ref(value, context="logical program")


def _module_fragment_value_roots(
    fragment: _ModuleFragment,
) -> tuple[object, ...]:
    """Return the values that contribute to the fragment's logical graph.

    ``fragment.inputs`` is the environment available to those roots, not a set
    of uses.  Rooting every supplied binding would turn an otherwise unused
    child input into a dependency of the whole experiment.
    """

    roots: list[object] = []

    def add_roots(values: Iterable[object]) -> None:
        roots.extend(values)

    add_roots(
        source
        for port in fragment.resource_ports
        for source in port.selector.entity_inputs
    )
    add_roots(binding.value for binding in fragment.bindings)
    add_roots(
        argument.value
        for effect in fragment.effects
        if isinstance(effect, InvocationIntent)
        for argument in effect.arguments
    )
    add_roots(
        value for operation in fragment.operations for _name, value in operation.inputs
    )
    add_roots(
        value
        for execution in fragment.effects
        if isinstance(execution, DomainExecution)
        for _name, value in (
            *execution.input_bindings,
            *execution.compiler_input_bindings,
        )
    )
    add_roots(
        axis.size for product in fragment.product_declarations for axis in product.axes
    )
    return tuple(roots)


def _scope_instance_graph(
    fragment: _ModuleFragment,
    *,
    instance: ModuleInstanceIR,
    local_inputs: Mapping[str, ValueRef],
) -> _ModuleFragment:
    scope = (instance.instance_id,)
    origin = (instance.invocation_key,)
    resource_ports, resource_ids = _scope_resource_ports(
        fragment.resource_ports,
        local_inputs,
        scope=scope,
        origin=origin,
        bindings={
            binding.import_id: binding.source_id
            for binding in instance.resource_bindings
        },
    )
    measurement_postprocessors = tuple(
        _scope_measurement_postprocessor(postprocessor, scope=scope)
        for postprocessor in fragment.measurement_postprocessors
    )
    effects = tuple(
        _scope_fragment_effect(
            effect,
            local_inputs,
            scope=scope,
            origin=origin,
            resource_ids=resource_ids,
        )
        for effect in fragment.effects
    )
    scoped = replace(
        fragment,
        inputs={
            key: value
            for key, value in fragment.inputs.items()
            if key not in local_inputs
        },
        input_ports=tuple(
            port for port in fragment.input_ports if port.id not in local_inputs
        ),
        entity_inputs=tuple(
            input_id
            for input_id in fragment.entity_inputs
            if input_id not in local_inputs
        ),
        resource_ports=resource_ports,
        effects=effects,
        operations=tuple(
            _scope_operation(
                operation,
                local_inputs,
                scope=scope,
                origin=origin,
            )
            for operation in fragment.operations
        ),
        measurement_postprocessors=measurement_postprocessors,
        python_implementations={
            operation_id.prefixed(*scope): implementation
            for operation_id, implementation in fragment.python_implementations.items()
        },
        product_declarations=tuple(
            _scope_product_declaration(
                product,
                local_inputs,
                scope=scope,
                origin=origin,
            )
            for product in fragment.product_declarations
        ),
    )
    value_roots = _module_fragment_value_roots(scoped)
    value_dependencies = _summarize_value_ref_dependencies(
        value for root in value_roots for value in _nested_value_refs(root)
    )
    return replace(
        scoped,
        point_dependencies=_merge_point_dependencies(
            scoped.point_dependencies,
            value_dependencies.point,
        ),
        parameter_contracts=merge_parameter_contracts(
            scoped.parameter_contracts,
            value_dependencies.parameters,
        ),
    )


def _scope_fragment_effect(
    effect: _FragmentEffect,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> _FragmentEffect:
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
            replace(
                result,
                product_id=result.product_id.prefixed(*scope),
            )
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
        id=_scope_domain_execution_id(execution.id, scope),
        input_bindings=tuple(
            (
                name,
                _scope_value_ref(value, inputs, scope=scope, origin=origin)
                if isinstance(value, ValueRef)
                else value,
            )
            for name, value in execution.input_bindings
        ),
        compiler_input_bindings=tuple(
            (
                name,
                _scope_value_ref(value, inputs, scope=scope, origin=origin)
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


def _scope_domain_execution_id(
    execution_id: str,
    scope: tuple[str, ...],
) -> str:
    return "/".join((*scope, execution_id))


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
        localize_value_ref=lambda value, selected_inputs: _scope_value_ref(
            value,
            selected_inputs,
            scope=scope,
            origin=origin,
        ),
    )
    return prefix_product_decl(localized, *scope, origin=origin)


def _scope_resource_ports(
    ports: Sequence[ResourcePort],
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> tuple[
    tuple[ResourcePort, ...],
    dict[LogicalResourcePortId, LogicalResourcePortId],
]:
    localized_ports: list[ResourcePort] = []
    resource_ids: dict[LogicalResourcePortId, LogicalResourcePortId] = {}
    for port in ports:
        bound_resource = bindings.get(port.symbol_id)
        if bound_resource is not None:
            resource_ids[port.symbol_id] = bound_resource
            continue
        entity_inputs: list[ValueRef] = []
        for source in port.selector.entity_inputs:
            localized = _scope_value_ref(
                source,
                inputs,
                scope=scope,
                origin=origin,
            )
            if isinstance(localized.value_type, TableType):
                msg = (
                    "resource entity source must be scalar-shaped; "
                    "declare the resource footprint explicitly"
                )
                raise TypeError(msg)
            entity_inputs.append(localized)
        localized = replace(
            port,
            selector=ResourceSelector(
                interfaces=port.selector.interfaces,
                entity_inputs=tuple(entity_inputs),
            ),
        )
        selected = prefix_resource_port(localized, *scope)
        localized_ports.append(selected)
        resource_ids[port.symbol_id] = selected.symbol_id
    return tuple(localized_ports), resource_ids


def _scope_value_ref(
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
            value=_scope_value_ref(
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
                    _scope_value_ref(
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


def _scope_measurement_postprocessor(
    postprocessor: MeasurementPostprocessor,
    *,
    scope: tuple[str, ...],
) -> MeasurementPostprocessor:
    return replace(
        postprocessor,
        scope=(*scope, *postprocessor.scope),
        input_binding=postprocessor.input_binding.prefixed(*scope),
        output_bindings=tuple(
            (role, product_id.prefixed(*scope))
            for role, product_id in postprocessor.output_bindings
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
        return _scope_value_ref(
            value,
            inputs,
            scope=scope,
            origin=origin,
        )
    return value
