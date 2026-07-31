"""Elaborate hierarchical Module IR into one closed, flat experiment IR."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol, cast

from scopecat.compiler.frontend.logical_closure import (
    close_logical_program,
    logical_compute_node_id,
)
from scopecat.compiler.frontend.scan_lowering import lower_scans_point_domain
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
from scopecat.program.point_domain import PointAxes
from scopecat.program.products import (
    ModuleProductDecl,
    RecordSelection,
    localize_product_input_refs,
    prefix_product_decl,
)
from scopecat.program.scans import AxisSpec, scan_parameter_contracts
from scopecat.program.value_graph import OperationId
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

type _DefinitionEffect = (
    BindingIntent
    | EnsureStateIntent
    | InvocationIntent
    | DomainExecution
    | AcquireEffect
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


@dataclass(frozen=True, slots=True)
class _InstanceBoundary:
    """One child-to-parent localization step in a hierarchy traversal."""

    instance_id: str
    invocation_key: InvocationKey
    inputs: Mapping[str, ValueRef]
    resource_bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId]

    @property
    def scope(self) -> tuple[str, ...]:
        return (self.instance_id,)

    @property
    def origin(self) -> tuple[object, ...]:
        return (self.invocation_key,)


class _LogicalProgramComposer:
    """Recursively flatten definitions directly into logical-program fields."""

    def __init__(self) -> None:
        self.resource_ports: list[ResourcePort] = []
        self.operations: list[ModuleOperationDecl] = []
        self.python_implementations: dict[OperationId, ComputeFunction] = {}
        self.measurement_postprocessors: list[MeasurementPostprocessor] = []
        self.product_declarations: list[ModuleProductDecl] = []
        self.dependency_roots: list[ValueRef] = []

    def add_hierarchy(self, root: _HierarchyRoot) -> tuple[_DefinitionEffect, ...]:
        return self._add_module(root, boundaries=())

    def _add_module(
        self,
        module: _HierarchyRoot,
        *,
        boundaries: tuple[_InstanceBoundary, ...],
    ) -> tuple[_DefinitionEffect, ...]:
        resolver = _ModuleValueResolver(module)
        child_effects: dict[InvocationKey, tuple[_DefinitionEffect, ...]] = {}
        for instance in module.body.child_instances:
            boundary = _InstanceBoundary(
                instance_id=instance.instance_id,
                invocation_key=instance.invocation_key,
                inputs={
                    binding.import_id: resolver.resolve(binding.source)
                    for binding in instance.input_bindings
                },
                resource_bindings={
                    binding.import_id: binding.source_id
                    for binding in instance.resource_bindings
                },
            )
            child_effects[instance.invocation_key] = self._add_module(
                instance.module,
                boundaries=(boundary, *boundaries),
            )

        self._add_declarations(module, resolver=resolver, boundaries=boundaries)
        own_effects = tuple(
            _localize_effect(
                _lower_module_effect(effect, resolver=resolver),
                boundaries,
            )
            for effect in module.body.effects
            if not isinstance(effect, ModuleInstanceIR)
        )
        ordered: list[_DefinitionEffect] = []
        own_effect_iterator = iter(own_effects)
        for effect in module.body.effects:
            if isinstance(effect, ModuleInstanceIR):
                ordered.extend(child_effects[effect.invocation_key])
            else:
                ordered.append(next(own_effect_iterator))
        return tuple(ordered)

    def _add_declarations(
        self,
        module: _HierarchyRoot,
        *,
        resolver: _ModuleValueResolver,
        boundaries: tuple[_InstanceBoundary, ...],
    ) -> None:
        implementations = {
            implementation.declaration_key: implementation.fn
            for implementation in module.python_implementations
        }
        for port in module.interface.resources:
            localized = _localize_resource_port(
                _resolve_resource_port(port, resolver=resolver),
                boundaries,
            )
            if localized is not None:
                self.resource_ports.append(localized)
        for operation in module.body.operations:
            localized = _localize_operation(
                _resolve_operation(operation, resolver=resolver),
                boundaries,
            )
            self.operations.append(localized)
            self.python_implementations[
                logical_compute_node_id(localized.operation_id)
            ] = implementations[operation.declaration_key]
        self.measurement_postprocessors.extend(
            _localize_measurement_postprocessor(postprocessor, boundaries)
            for postprocessor in module.body.measurement_postprocessors
        )
        self.product_declarations.extend(
            _localize_product_declaration(
                _resolve_product(product, resolver=resolver),
                boundaries,
            )
            for product in module.body.products
        )
        self.dependency_roots.extend(
            _localize_value_ref(resolver.resolve(export.source), boundaries)
            for export in module.interface.exports
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
    scans: Sequence[AxisSpec] = (),
) -> LogicalProgram:
    """Elaborate a native experiment root without a synthetic module."""

    program_input_ids = {port.id for port in definition.interface.imports}
    value_inputs = {
        input_id: value
        for input_id, value in inputs.items()
        if input_id in program_input_ids
    }
    return _elaborate_hierarchy(
        definition,
        experiment_id=definition.id,
        kind=definition.kind,
        inputs=value_inputs,
        logical_inputs=inputs,
        parameter_overlays=tuple(
            axis for axis in scans if axis.parameter_lookup is not None
        ),
        record_selections=definition.record_selections,
        additional_parameter_contracts=merge_parameter_contracts(
            *(scan_parameter_contracts(axis) for axis in scans),
        ),
        point_domain=lower_scans_point_domain(scans, inputs=inputs),
        final_state=definition.final_state,
    )


def _elaborate_hierarchy(
    root: _HierarchyRoot,
    *,
    experiment_id: str,
    kind: str,
    inputs: Mapping[str, object],
    logical_inputs: Mapping[str, object] | None = None,
    parameter_overlays: Sequence[AxisSpec] = (),
    record_selections: Sequence[RecordSelection] = (),
    additional_parameter_contracts: tuple[ParameterContract, ...] = (),
    point_domain: PointAxes[ValueRef] = (),
    final_state: EnsureStateIntent | None,
) -> LogicalProgram:
    composer = _LogicalProgramComposer()
    effects = composer.add_hierarchy(root)
    execution_ids = tuple(
        effect.id for effect in effects if isinstance(effect, DomainExecution)
    )
    if len(execution_ids) != len(set(execution_ids)):
        raise ValueError("logical program contains repeated domain execution ids")
    value_roots = _logical_value_roots(
        resource_ports=composer.resource_ports,
        operations=composer.operations,
        product_declarations=composer.product_declarations,
        effects=effects,
    )
    final_state_values = tuple(
        assignment.value
        for assignment in (() if final_state is None else final_state.assignments)
    )
    _require_closed_logical_values(
        inputs,
        (*value_roots, *final_state_values),
    )
    typed_inputs = {
        input_id: value
        for input_id, value in inputs.items()
        if isinstance(value, ValueRef)
    }
    dependencies = _summarize_value_ref_dependencies(
        internal_bind_value_ref_inputs(value, typed_inputs)
        for source in (
            *value_roots,
            *composer.dependency_roots,
            *final_state_values,
        )
        for value in _nested_value_refs(source)
    )
    return close_logical_program(
        experiment_id=experiment_id,
        kind=kind,
        inputs=dict(inputs if logical_inputs is None else logical_inputs),
        input_ports=root.interface.imports,
        entity_inputs=_entity_input_ids(root.interface.imports),
        resource_ports=tuple(composer.resource_ports),
        point_dependencies=dependencies.point,
        parameter_overlays=parameter_overlays,
        product_declarations=tuple(composer.product_declarations),
        record_selections=record_selections,
        parameter_contracts=merge_parameter_contracts(
            dependencies.parameters,
            additional_parameter_contracts,
        ),
        point_domain=point_domain,
        operations=composer.operations,
        implementations=composer.python_implementations,
        measurement_postprocessors=composer.measurement_postprocessors,
        effects=effects,
        final_state=final_state,
        value_roots=(*value_roots, *final_state_values),
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
) -> _DefinitionEffect:
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


def _require_closed_logical_values(
    inputs: Mapping[str, object],
    consumed_roots: Sequence[object],
) -> None:
    for root in (*inputs.values(), *consumed_roots):
        for value in _nested_value_refs(root):
            internal_require_resolved_value_ref(value, context="logical program")


def _logical_value_roots(
    *,
    resource_ports: Sequence[ResourcePort],
    operations: Sequence[ModuleOperationDecl],
    product_declarations: Sequence[ModuleProductDecl],
    effects: Sequence[_DefinitionEffect],
) -> tuple[object, ...]:
    """Return the values that contribute to the closed logical graph.

    Root inputs are an environment for these uses, not roots themselves.
    Keeping them separate prevents an unused supplied input from becoming a
    dependency of the whole program.
    """

    roots: list[object] = []

    def add_roots(values: Iterable[object]) -> None:
        roots.extend(values)

    add_roots(
        source for port in resource_ports for source in port.selector.entity_inputs
    )
    add_roots(
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
    add_roots(
        argument.value
        for effect in effects
        if isinstance(effect, InvocationIntent)
        for argument in effect.arguments
    )
    add_roots(value for operation in operations for _name, value in operation.inputs)
    add_roots(
        value
        for execution in effects
        if isinstance(execution, DomainExecution)
        for _name, value in (
            *execution.input_bindings,
            *execution.compiler_input_bindings,
        )
    )
    add_roots(axis.size for product in product_declarations for axis in product.axes)
    return tuple(roots)


def _localize_value_ref(
    value: ValueRef,
    boundaries: Sequence[_InstanceBoundary],
) -> ValueRef:
    selected = value
    for boundary in boundaries:
        selected = _scope_value_ref(
            selected,
            boundary.inputs,
            scope=boundary.scope,
            origin=boundary.origin,
        )
    return selected


def _localize_operation(
    operation: ModuleOperationDecl,
    boundaries: Sequence[_InstanceBoundary],
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


def _localize_measurement_postprocessor(
    postprocessor: MeasurementPostprocessor,
    boundaries: Sequence[_InstanceBoundary],
) -> MeasurementPostprocessor:
    selected = postprocessor
    for boundary in boundaries:
        selected = _scope_measurement_postprocessor(selected, scope=boundary.scope)
    return selected


def _localize_product_declaration(
    product: ModuleProductDecl,
    boundaries: Sequence[_InstanceBoundary],
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


def _localize_resource_port(
    port: ResourcePort,
    boundaries: Sequence[_InstanceBoundary],
) -> ResourcePort | None:
    port_id = port.symbol_id
    bound = False
    for boundary in boundaries:
        selected = boundary.resource_bindings.get(port_id)
        if selected is not None:
            port_id = selected
            bound = True
        else:
            port_id = port_id.prefixed(*boundary.scope)
    if bound:
        return None
    entity_inputs = tuple(
        _localize_value_ref(source, boundaries)
        for source in port.selector.entity_inputs
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
            interfaces=port.selector.interfaces,
            entity_inputs=entity_inputs,
        ),
    )


def _localize_effect(
    effect: _DefinitionEffect,
    boundaries: Sequence[_InstanceBoundary],
) -> _DefinitionEffect:
    selected = effect
    for boundary in boundaries:
        resource_ids = {
            port_id: boundary.resource_bindings.get(
                port_id,
                port_id.prefixed(*boundary.scope),
            )
            for port_id in _effect_resource_ids(selected)
        }
        selected = _scope_fragment_effect(
            selected,
            boundary.inputs,
            scope=boundary.scope,
            origin=boundary.origin,
            resource_ids=resource_ids,
        )
    return selected


def _effect_resource_ids(
    effect: _DefinitionEffect,
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


def _scope_fragment_effect(
    effect: _DefinitionEffect,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> _DefinitionEffect:
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
