"""Elaborate hierarchical Module IR into one closed, flat experiment IR."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
    ResourceSelector,
    prefix_resource_port,
)
from scopecat.authoring._frozen_values import empty_frozen_mapping
from scopecat.authoring._intents import (
    ComputeNodeInputValue,
    ExperimentStateIntent,
    ModuleActionDecl,
    ModuleInputPort,
    ModuleOperationDecl,
    ParameterScanOverlayIntent,
    StateEachIntent,
)
from scopecat.authoring._module_handles import ExperimentModule
from scopecat.authoring._module_ir import (
    InvocationKey,
    ModuleAcquireEffect,
    ModuleActionEffect,
    ModuleBindingEffect,
    ModuleInstanceEffect,
    ModuleInstanceIR,
    ModuleIR,
    ModuleStateEffect,
)
from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.authoring._point_domain_intents import (
    PointDomainIntent,
    compose_point_domain_intents,
    iter_point_domain_value_refs,
    map_point_domain_value_refs,
)
from scopecat.authoring._products import (
    ModuleProductDecl,
    RecordSelection,
    localize_product_input_refs,
    prefix_product_decl,
)
from scopecat.authoring._value_refs import (
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
from scopecat.authoring.domain import LoweredDomainExecution, lower_domain_execution
from scopecat.authoring.measurements import MeasurementTransform
from scopecat.authoring.value_types import (
    Entity as EntityType,
)
from scopecat.authoring.value_types import (
    Scalar as ScalarType,
)
from scopecat.authoring.value_types import (
    Series as SeriesType,
)
from scopecat.authoring.value_types import (
    Table as TableType,
)
from scopecat.authoring.values import MetadataValue
from scopecat.compiler.frontend.semantic_elaboration import (
    ScopedPythonImplementation,
    elaborate_semantic_graph,
    semantic_operation_id,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.semantic.model import (
    AcquireEffect,
    AcquireEffectRef,
    AcquireId,
    AcquireProduct,
    ActionEffectRef,
    ActionId,
    BindingEffectRef,
    DomainEffectRef,
    ImplementationCatalog,
    SemanticEffectRef,
    SemanticGraphIR,
    SourceMap,
    StateEffectRef,
    merge_implementation_catalogs,
    merge_semantic_graphs,
    merge_source_maps,
    state_each_region_id,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId


@dataclass(frozen=True)
class _ExperimentEnvelope:
    """Non-dataflow intents carried alongside transient semantic graphs."""

    experiment_id: str | None = None
    kind: str | None = None
    inputs: dict[str, object] = field(default_factory=dict)
    input_ports: tuple[ModuleInputPort, ...] = ()
    entity_inputs: tuple[str, ...] = ()
    resource_ports: tuple[ResourcePort, ...] = ()
    point_domain: PointDomainIntent = POINT_UNIT
    point_dependencies: tuple[PointValueDependency, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    parameter_overlays: tuple[ParameterScanOverlayIntent, ...] = ()
    product_declarations: tuple[ModuleProductDecl, ...] = ()
    record_selections: tuple[RecordSelection, ...] = ()
    parameter_contracts: tuple[ParameterContract, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)


@dataclass(frozen=True)
class _ModuleFragment(_ExperimentEnvelope):
    """Hierarchy-free module declarations before semantic graph closure."""

    operations: tuple[ModuleOperationDecl, ...] = ()
    python_implementations: tuple[ScopedPythonImplementation, ...] = ()
    measurement_transforms: tuple[MeasurementTransform, ...] = ()
    domain_executions: tuple[LoweredDomainExecution, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    actions: tuple[ModuleActionDecl, ...] = ()
    acquisitions: tuple[AcquireEffect, ...] = ()
    effect_order: tuple[SemanticEffectRef, ...] = ()


@dataclass(frozen=True, slots=True)
class _ValueRefDependencies:
    point: tuple[PointValueDependency, ...]
    parameters: tuple[ParameterContract, ...]


@dataclass(frozen=True, slots=True)
class _ModuleFragmentValueRoots:
    consumed: tuple[object, ...]
    semantic: tuple[object, ...]


@dataclass(frozen=True)
class SemanticExperimentIR(_ExperimentEnvelope):
    """Closed config-free semantic graph plus plan and resource intents."""

    semantic_graph: SemanticGraphIR = field(default_factory=SemanticGraphIR)
    implementation_catalog: ImplementationCatalog = field(
        default_factory=ImplementationCatalog,
        repr=False,
        compare=False,
    )
    source_map: SourceMap = field(
        default_factory=SourceMap,
        repr=False,
        compare=False,
    )
    effect_order: tuple[SemanticEffectRef, ...] = ()

    def __post_init__(self) -> None:
        expected: tuple[SemanticEffectRef, ...] = (
            *(BindingEffectRef(index) for index in range(len(self.bindings))),
            *(StateEffectRef(region.id) for region in self.semantic_graph.row_regions),
            *(ActionEffectRef(action.id) for action in self.semantic_graph.actions),
            *(
                AcquireEffectRef(acquire.id)
                for acquire in self.semantic_graph.acquisitions
            ),
            *(
                DomainEffectRef(execution.id)
                for execution in self.semantic_graph.domain_executions
            ),
        )
        if Counter(self.effect_order) != Counter(expected):
            raise ValueError(
                "semantic experiment effect order must reference every effect "
                "exactly once"
            )


def merge_semantic_experiments(
    *,
    experiment_id: str,
    kind: str,
    fragments: Sequence[SemanticExperimentIR],
    metadata: Mapping[str, MetadataValue] | None = None,
) -> SemanticExperimentIR:
    """Merge closed semantic fragments without implicit domain-level union."""

    if not fragments:
        msg = "semantic experiment merge requires at least one fragment"
        raise ValueError(msg)
    merged_metadata: dict[str, MetadataValue] = {}
    merged_inputs: dict[str, object] = {}
    input_ports: list[ModuleInputPort] = []
    entity_inputs: list[str] = []
    resource_ports: list[ResourcePort] = []
    point_domains: list[PointDomainIntent] = []
    point_dependencies: list[tuple[PointValueDependency, ...]] = []
    bindings: list[ExperimentBindingIntent] = []
    parameter_overlays: list[ParameterScanOverlayIntent] = []
    semantic_graphs: list[SemanticGraphIR] = []
    implementation_catalogs: list[ImplementationCatalog] = []
    source_maps: list[SourceMap] = []
    product_declarations: list[ModuleProductDecl] = []
    record_selections: list[RecordSelection] = []
    parameter_contracts: list[tuple[ParameterContract, ...]] = []
    effect_order: list[SemanticEffectRef] = []
    binding_offset = 0
    for fragment in fragments:
        merged_inputs.update(fragment.inputs)
        merged_metadata.update(fragment.metadata)
        input_ports.extend(fragment.input_ports)
        entity_inputs.extend(fragment.entity_inputs)
        resource_ports.extend(fragment.resource_ports)
        point_domains.append(fragment.point_domain)
        point_dependencies.append(fragment.point_dependencies)
        bindings.extend(fragment.bindings)
        parameter_overlays.extend(fragment.parameter_overlays)
        semantic_graphs.append(fragment.semantic_graph)
        implementation_catalogs.append(fragment.implementation_catalog)
        source_maps.append(fragment.source_map)
        product_declarations.extend(fragment.product_declarations)
        record_selections.extend(fragment.record_selections)
        parameter_contracts.append(fragment.parameter_contracts)
        effect_order.extend(
            _rebase_binding_effects(fragment.effect_order, binding_offset)
        )
        binding_offset += len(fragment.bindings)
    merged_metadata.update(dict(metadata or {}))
    return SemanticExperimentIR(
        experiment_id=experiment_id,
        kind=kind,
        inputs=merged_inputs,
        input_ports=tuple(input_ports),
        entity_inputs=tuple(entity_inputs),
        resource_ports=tuple(resource_ports),
        point_domain=compose_point_domain_intents(*point_domains),
        point_dependencies=_merge_point_dependencies(*point_dependencies),
        bindings=tuple(bindings),
        parameter_overlays=tuple(parameter_overlays),
        semantic_graph=merge_semantic_graphs(*semantic_graphs),
        implementation_catalog=merge_implementation_catalogs(*implementation_catalogs),
        source_map=merge_source_maps(*source_maps),
        product_declarations=tuple(product_declarations),
        record_selections=tuple(record_selections),
        parameter_contracts=merge_parameter_contracts(*parameter_contracts),
        metadata=merged_metadata,
        effect_order=tuple(effect_order),
    )


def _merge_module_fragments(
    *,
    experiment_id: str,
    kind: str,
    fragments: Sequence[_ModuleFragment],
    metadata: Mapping[str, MetadataValue] | None = None,
) -> _ModuleFragment:
    if not fragments:
        msg = "module fragment merge requires at least one fragment"
        raise ValueError(msg)
    merged_metadata: dict[str, MetadataValue] = {}
    merged_inputs: dict[str, object] = {}
    input_ports: list[ModuleInputPort] = []
    entity_inputs: list[str] = []
    resource_ports: list[ResourcePort] = []
    point_domains: list[PointDomainIntent] = []
    point_dependencies: list[tuple[PointValueDependency, ...]] = []
    bindings: list[ExperimentBindingIntent] = []
    state_intents: list[ExperimentStateIntent] = []
    actions: list[ModuleActionDecl] = []
    acquisitions: list[AcquireEffect] = []
    parameter_overlays: list[ParameterScanOverlayIntent] = []
    operations: list[ModuleOperationDecl] = []
    measurement_transforms: list[MeasurementTransform] = []
    domain_executions: list[LoweredDomainExecution] = []
    python_implementations: list[ScopedPythonImplementation] = []
    product_declarations: list[ModuleProductDecl] = []
    record_selections: list[RecordSelection] = []
    parameter_contracts: list[tuple[ParameterContract, ...]] = []
    effect_order: list[SemanticEffectRef] = []
    binding_offset = 0
    for fragment in fragments:
        merged_inputs.update(fragment.inputs)
        merged_metadata.update(fragment.metadata)
        input_ports.extend(fragment.input_ports)
        entity_inputs.extend(fragment.entity_inputs)
        resource_ports.extend(fragment.resource_ports)
        point_domains.append(fragment.point_domain)
        point_dependencies.append(fragment.point_dependencies)
        bindings.extend(fragment.bindings)
        state_intents.extend(fragment.state_intents)
        actions.extend(fragment.actions)
        acquisitions.extend(fragment.acquisitions)
        parameter_overlays.extend(fragment.parameter_overlays)
        operations.extend(fragment.operations)
        measurement_transforms.extend(fragment.measurement_transforms)
        domain_executions.extend(fragment.domain_executions)
        python_implementations.extend(fragment.python_implementations)
        product_declarations.extend(fragment.product_declarations)
        record_selections.extend(fragment.record_selections)
        parameter_contracts.append(fragment.parameter_contracts)
        effect_order.extend(
            _rebase_binding_effects(fragment.effect_order, binding_offset)
        )
        binding_offset += len(fragment.bindings)
    merged_metadata.update(dict(metadata or {}))
    point_domain = compose_point_domain_intents(*point_domains)
    merged_point_dependencies = _merge_point_dependencies(*point_dependencies)
    execution_ids = tuple(execution.id for execution in domain_executions)
    if len(execution_ids) != len(set(execution_ids)):
        raise ValueError("module fragments contain repeated domain execution ids")
    return _ModuleFragment(
        experiment_id=experiment_id,
        kind=kind,
        inputs=merged_inputs,
        input_ports=tuple(input_ports),
        entity_inputs=tuple(entity_inputs),
        resource_ports=tuple(resource_ports),
        point_domain=point_domain,
        point_dependencies=merged_point_dependencies,
        bindings=tuple(bindings),
        state_intents=tuple(state_intents),
        actions=tuple(actions),
        acquisitions=tuple(acquisitions),
        parameter_overlays=tuple(parameter_overlays),
        operations=tuple(operations),
        measurement_transforms=tuple(measurement_transforms),
        domain_executions=tuple(domain_executions),
        python_implementations=tuple(python_implementations),
        product_declarations=tuple(product_declarations),
        record_selections=tuple(record_selections),
        parameter_contracts=merge_parameter_contracts(*parameter_contracts),
        metadata=merged_metadata,
        effect_order=tuple(effect_order),
    )


def _rebase_binding_effects(
    effects: Sequence[SemanticEffectRef],
    offset: int,
) -> tuple[SemanticEffectRef, ...]:
    if offset == 0:
        return tuple(effects)
    return tuple(
        BindingEffectRef(effect.index + offset)
        if isinstance(effect, BindingEffectRef)
        else effect
        for effect in effects
    )


def elaborate_module(
    module: ExperimentModule,
    /,
    **inputs: object,
) -> SemanticExperimentIR:
    """Elaborate one root module through the only hierarchy-flattening pass."""

    fragment = _elaborate_module_ir(
        module.ir,
        inputs=inputs,
    )
    value_roots = _module_fragment_value_roots(fragment)
    _require_closed_module_fragment(fragment, value_roots.consumed)
    semantic = elaborate_semantic_graph(
        fragment.operations,
        fragment.python_implementations,
        measurement_transforms=fragment.measurement_transforms,
        domain_executions=fragment.domain_executions,
        actions=fragment.actions,
        acquisitions=fragment.acquisitions,
        value_roots=value_roots.semantic,
        state_regions=fragment.state_intents,
        input_types={port.id: port.value_type for port in fragment.input_ports},
        point_dependencies=fragment.point_dependencies,
        parameter_contracts=fragment.parameter_contracts,
    )
    return SemanticExperimentIR(
        experiment_id=fragment.experiment_id,
        kind=fragment.kind,
        inputs=fragment.inputs,
        input_ports=fragment.input_ports,
        entity_inputs=fragment.entity_inputs,
        resource_ports=fragment.resource_ports,
        point_domain=fragment.point_domain,
        point_dependencies=fragment.point_dependencies,
        bindings=fragment.bindings,
        parameter_overlays=fragment.parameter_overlays,
        semantic_graph=semantic.graph,
        implementation_catalog=semantic.implementations,
        source_map=semantic.source_map,
        product_declarations=fragment.product_declarations,
        record_selections=fragment.record_selections,
        parameter_contracts=fragment.parameter_contracts,
        metadata=fragment.metadata,
        effect_order=fragment.effect_order,
    )


def _elaborate_module_ir(
    module: ModuleIR,
    *,
    inputs: Mapping[str, object],
) -> _ModuleFragment:
    resolver = _ModuleValueResolver(module)
    source_fragments = {
        instance.invocation_key: _elaborate_instance(instance, resolver=resolver)
        for instance in module.body.instances
    }

    implementations = {
        implementation.declaration_key: implementation
        for implementation in module.python_implementations
    }
    lowered_executions = tuple(
        _resolve_domain_execution(
            lower_domain_execution(execution),
            resolver=resolver,
        )
        for execution in module.body.domain_executions
    )
    domain_input_values = tuple(
        value
        for execution in lowered_executions
        for _name, value in (
            *execution.input_bindings,
            *execution.compiler_input_bindings,
        )
        if isinstance(value, ValueRef)
    )
    value_dependencies = _module_value_dependencies(
        module,
        inputs,
        resolver,
        additional_values=domain_input_values,
    )
    own = _ModuleFragment(
        inputs=dict(inputs),
        input_ports=module.interface.imports,
        entity_inputs=_entity_input_ids(module.interface.imports),
        resource_ports=tuple(
            _resolve_resource_port(port, resolver=resolver)
            for port in module.interface.resources
        ),
        point_dependencies=value_dependencies.point,
        bindings=tuple(
            _resolve_binding(binding, resolver=resolver)
            for binding in module.body.bindings
        ),
        state_intents=tuple(
            _resolve_state(state, resolver=resolver) for state in module.body.state
        ),
        actions=tuple(
            _resolve_action(action, resolver=resolver) for action in module.body.actions
        ),
        acquisitions=tuple(
            AcquireEffect(
                id=AcquireId(SymbolId(local_id=acquire.id)),
                resource_port_id=acquire.resource_port_id,
                capability_id=acquire.capability_id,
                products=tuple(
                    AcquireProduct(
                        product_id=product.product.product_id,
                        provider_key=product.provider_key,
                        metadata=product.metadata,
                    )
                    for product in acquire.products
                ),
            )
            for acquire in module.body.acquisitions
        ),
        operations=tuple(
            _resolve_operation(operation, resolver=resolver)
            for operation in module.body.operations
        ),
        measurement_transforms=module.body.measurement_transforms,
        domain_executions=lowered_executions,
        effect_order=_own_effect_order(module),
        python_implementations=tuple(
            ScopedPythonImplementation(
                operation_id=semantic_operation_id(operation.operation_id),
                declaration_key=operation.declaration_key,
                fn=implementations[operation.declaration_key].fn,
            )
            for operation in module.body.operations
        ),
        product_declarations=tuple(
            _resolve_product(product, resolver=resolver)
            for product in module.body.products
        ),
        parameter_contracts=value_dependencies.parameters,
        metadata=dict(module.metadata),
    )
    if not source_fragments:
        return own

    ordered_sources = tuple(
        source_fragments[instance.invocation_key] for instance in module.body.instances
    )
    combined = _merge_module_fragments(
        experiment_id=module.id,
        kind=module.id,
        fragments=(*ordered_sources, own),
    )
    child_binding_offsets: dict[InvocationKey, int] = {}
    binding_offset = 0
    for instance, fragment in zip(module.body.instances, ordered_sources, strict=True):
        child_binding_offsets[instance.invocation_key] = binding_offset
        binding_offset += len(fragment.bindings)
    own_binding_offset = binding_offset
    effect_order: list[SemanticEffectRef] = []
    own_binding_index = 0
    for effect in module.body.procedure:
        if isinstance(effect, ModuleInstanceEffect):
            child = source_fragments[effect.invocation_key]
            effect_order.extend(
                _rebase_binding_effects(
                    child.effect_order,
                    child_binding_offsets[effect.invocation_key],
                )
            )
        elif isinstance(effect, ModuleBindingEffect):
            effect_order.append(
                BindingEffectRef(own_binding_offset + own_binding_index)
            )
            own_binding_index += 1
        elif isinstance(effect, ModuleStateEffect):
            effect_order.append(
                StateEffectRef(state_each_region_id(effect.intent.row_scope_id))
            )
        elif isinstance(effect, ModuleActionEffect):
            effect_order.append(ActionEffectRef(ActionId(effect.intent.action_id)))
        elif isinstance(effect, ModuleAcquireEffect):
            effect_order.append(
                AcquireEffectRef(AcquireId(SymbolId(local_id=effect.id)))
            )
        else:
            effect_order.append(DomainEffectRef(effect.execution.id))
    return replace(
        combined,
        experiment_id=None,
        kind=None,
        effect_order=tuple(effect_order),
    )


def _own_effect_order(module: ModuleIR) -> tuple[SemanticEffectRef, ...]:
    effects: list[SemanticEffectRef] = []
    binding_index = 0
    for effect in module.body.procedure:
        if isinstance(effect, ModuleInstanceEffect):
            continue
        if isinstance(effect, ModuleBindingEffect):
            effects.append(BindingEffectRef(binding_index))
            binding_index += 1
        elif isinstance(effect, ModuleStateEffect):
            effects.append(
                StateEffectRef(state_each_region_id(effect.intent.row_scope_id))
            )
        elif isinstance(effect, ModuleActionEffect):
            effects.append(ActionEffectRef(ActionId(effect.intent.action_id)))
        elif isinstance(effect, ModuleAcquireEffect):
            effects.append(AcquireEffectRef(AcquireId(SymbolId(local_id=effect.id))))
        else:
            effects.append(DomainEffectRef(effect.execution.id))
    return tuple(effects)


def _elaborate_instance(
    instance: ModuleInstanceIR,
    *,
    resolver: _ModuleValueResolver,
) -> _ModuleFragment:
    local_inputs = {
        binding.import_id: resolver.resolve(binding.source)
        for binding in instance.input_bindings
    }
    fragment = _elaborate_module_ir(instance.module, inputs=local_inputs)
    return _scope_instance_graph(
        fragment,
        instance=instance,
        local_inputs=local_inputs,
    )


def _module_value_dependencies(
    module: ModuleIR,
    inputs: Mapping[str, object],
    resolver: _ModuleValueResolver,
    *,
    additional_values: Sequence[ValueRef] = (),
) -> _ValueRefDependencies:
    """Summarize dependencies reachable from the module's authored roots."""

    typed_inputs = {
        input_id: value
        for input_id, value in inputs.items()
        if isinstance(value, ValueRef)
    }

    def bound_values() -> Iterable[ValueRef]:
        for root in _module_value_roots(module):
            for value_ref in _nested_value_refs(root):
                yield internal_bind_value_ref_inputs(
                    resolver.resolve(value_ref),
                    typed_inputs,
                )
        yield from additional_values

    return _summarize_value_ref_dependencies(bound_values())


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


def _module_value_roots(module: ModuleIR) -> tuple[object, ...]:
    """Return authored values that can affect the assembled module."""

    values: list[object] = []
    values.extend(
        source
        for port in module.interface.resources
        for source in port.selector.entity_inputs
    )
    values.extend(binding.value for binding in module.body.bindings)
    for intent in module.body.state:
        values.extend(
            (
                intent.relation,
                intent.value,
                *intent.target_entities,
            )
        )
    values.extend(
        value for action in module.body.actions for _name, value in action.fields
    )
    values.extend(
        value
        for execution in module.body.domain_executions
        for _name, value in (
            *execution.input_bindings,
            *execution.compiler_input_bindings,
        )
    )
    values.extend(
        value
        for operation in module.body.operations
        for _name, value in operation.inputs
    )
    values.extend(export.source for export in module.interface.exports)
    values.extend(
        axis.size for product in module.body.products for axis in product.axes
    )
    return tuple(values)


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

    def __init__(self, module: ModuleIR) -> None:
        self._instances = {
            instance.invocation_key: instance for instance in module.body.instances
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
                    blocking_problem(
                        code="module_export_cycle",
                        category=ProblemCategory.CONFLICT,
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
                    blocking_problem(
                        code="module_export_foreign_instance",
                        category=ProblemCategory.INVALID_INPUT,
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
                    blocking_problem(
                        code="module_export_unknown",
                        category=ProblemCategory.NOT_FOUND,
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
        if (
            isinstance(port.value_type, ScalarType)
            and isinstance(port.value_type.atom, EntityType)
        )
        or (
            isinstance(port.value_type, SeriesType)
            and isinstance(port.value_type.item_type.atom, EntityType)
        )
    )


def _resolve_resource_port(
    port: ResourcePort,
    *,
    resolver: _ModuleValueResolver,
) -> ResourcePort:
    return replace(
        port,
        selector=ResourceSelector(
            capabilities=port.selector.capabilities,
            entity_inputs=tuple(
                resolver.resolve(value) for value in port.selector.entity_inputs
            ),
        ),
    )


def _resolve_binding(
    binding: ExperimentBindingIntent,
    *,
    resolver: _ModuleValueResolver,
) -> ExperimentBindingIntent:
    return replace(
        binding,
        value=(
            resolver.resolve(binding.value)
            if isinstance(binding.value, ValueRef)
            else binding.value
        ),
    )


def _resolve_state(
    intent: StateEachIntent,
    *,
    resolver: _ModuleValueResolver,
) -> StateEachIntent:
    return replace(
        intent,
        relation=resolver.resolve(intent.relation),
        value=(
            resolver.resolve(intent.value)
            if isinstance(intent.value, ValueRef)
            else intent.value
        ),
        target_entities=tuple(
            resolver.resolve(entity) if isinstance(entity, ValueRef) else entity
            for entity in intent.target_entities
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
    execution: LoweredDomainExecution,
    *,
    resolver: _ModuleValueResolver,
) -> LoweredDomainExecution:
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


def _resolve_action(
    action: ModuleActionDecl,
    *,
    resolver: _ModuleValueResolver,
) -> ModuleActionDecl:
    return replace(
        action,
        fields=tuple(
            (
                name,
                resolver.resolve(value) if isinstance(value, ValueRef) else value,
            )
            for name, value in action.fields
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
            internal_require_resolved_value_ref(value, context="semantic experiment")


def _module_fragment_value_roots(
    fragment: _ModuleFragment,
) -> _ModuleFragmentValueRoots:
    """Summarize values that contribute to the fragment's two root sets.

    ``fragment.inputs`` is the environment available to those roots, not a set
    of uses.  Rooting every supplied binding would turn an otherwise unused
    child input into a dependency of the whole experiment.
    """

    consumed: list[object] = [
        value for _path, value in iter_point_domain_value_refs(fragment.point_domain)
    ]
    semantic: list[object] = []

    def add_semantic_roots(values: Iterable[object]) -> None:
        selected = tuple(values)
        consumed.extend(selected)
        semantic.extend(selected)

    add_semantic_roots(
        source
        for port in fragment.resource_ports
        for source in port.selector.entity_inputs
    )
    add_semantic_roots(binding.value for binding in fragment.bindings)
    for intent in fragment.state_intents:
        consumed.extend((intent.relation, intent.value, *intent.target_entities))
    consumed.extend(
        value for action in fragment.actions for _name, value in action.fields
    )
    add_semantic_roots(
        value for operation in fragment.operations for _name, value in operation.inputs
    )
    add_semantic_roots(
        value
        for execution in fragment.domain_executions
        for _name, value in (
            *execution.input_bindings,
            *execution.compiler_input_bindings,
        )
    )
    add_semantic_roots(
        axis.size for product in fragment.product_declarations for axis in product.axes
    )
    return _ModuleFragmentValueRoots(
        consumed=tuple(consumed),
        semantic=tuple(semantic),
    )


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
    measurement_transforms = tuple(
        _scope_measurement_transform(transform, scope=scope)
        for transform in fragment.measurement_transforms
    )
    scoped = replace(
        fragment,
        # Module metadata describes the module declaration itself.  It is not
        # experiment metadata and therefore does not implicitly bubble through
        # composition; the root module/template owns that entry-point choice.
        metadata={},
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
        point_domain=map_point_domain_value_refs(
            fragment.point_domain,
            lambda value, _path: _scope_value_ref(
                value,
                local_inputs,
                scope=scope,
                origin=origin,
            ),
        ),
        resource_ports=resource_ports,
        bindings=tuple(
            _scope_binding(
                binding,
                local_inputs,
                scope=scope,
                origin=origin,
                resource_ids=resource_ids,
            )
            for binding in fragment.bindings
        ),
        state_intents=tuple(
            _scope_state(
                intent,
                local_inputs,
                scope=scope,
                origin=origin,
                resource_ids=resource_ids,
            )
            for intent in fragment.state_intents
        ),
        actions=tuple(
            _scope_action(
                action,
                local_inputs,
                scope=scope,
                origin=origin,
                resource_ids=resource_ids,
            )
            for action in fragment.actions
        ),
        acquisitions=tuple(
            replace(
                acquire,
                id=acquire.id.prefixed(*scope),
                resource_port_id=resource_ids.get(
                    acquire.resource_port_id,
                    acquire.resource_port_id,
                ),
                products=tuple(
                    replace(
                        product,
                        product_id=product.product_id.prefixed(*scope),
                    )
                    for product in acquire.products
                ),
            )
            for acquire in fragment.acquisitions
        ),
        domain_executions=tuple(
            _scope_domain_execution(
                execution,
                local_inputs,
                scope=scope,
                origin=origin,
                resource_ids=resource_ids,
            )
            for execution in fragment.domain_executions
        ),
        effect_order=_scope_effect_order(fragment.effect_order, scope=scope),
        operations=tuple(
            _scope_operation(
                operation,
                local_inputs,
                scope=scope,
                origin=origin,
            )
            for operation in fragment.operations
        ),
        measurement_transforms=measurement_transforms,
        python_implementations=tuple(
            replace(
                implementation,
                operation_id=implementation.operation_id.prefixed(*scope),
            )
            for implementation in fragment.python_implementations
        ),
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
        value for root in value_roots.consumed for value in _nested_value_refs(root)
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


def _scope_effect_order(
    effects: Sequence[SemanticEffectRef],
    *,
    scope: tuple[str, ...],
) -> tuple[SemanticEffectRef, ...]:
    return tuple(
        StateEffectRef(effect.id.prefixed(*scope))
        if isinstance(effect, StateEffectRef)
        else ActionEffectRef(effect.id.prefixed(*scope))
        if isinstance(effect, ActionEffectRef)
        else AcquireEffectRef(effect.id.prefixed(*scope))
        if isinstance(effect, AcquireEffectRef)
        else DomainEffectRef(_scope_domain_execution_id(effect.id, scope))
        if isinstance(effect, DomainEffectRef)
        else effect
        for effect in effects
    )


def _scope_domain_execution(
    execution: LoweredDomainExecution,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> LoweredDomainExecution:
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
            (name, product_id.prefixed(*scope))
            for name, product_id in execution.result_bindings
        ),
        resource_bindings=tuple(
            (role, _scoped_resource_id(resource_id, resource_ids))
            for role, resource_id in execution.resource_bindings
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
                    "resource entity source must be scalar or series-shaped; "
                    "select table entity columns with table.entities(...)"
                )
                raise TypeError(msg)
            entity_inputs.append(localized)
        localized = replace(
            port,
            selector=ResourceSelector(
                capabilities=port.selector.capabilities,
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
    binding: ExperimentBindingIntent,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> ExperimentBindingIntent:
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


def _scope_state(
    intent: StateEachIntent,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> StateEachIntent:
    relation = _scope_value_ref(
        intent.relation,
        inputs,
        scope=scope,
        origin=origin,
    )
    if not isinstance(relation.value_type, TableType):
        msg = "state_each relation must be table-shaped"
        raise TypeError(msg)
    return replace(
        intent,
        relation=relation,
        row_scope_id=intent.row_scope_id.prefixed(*scope),
        value=(
            _scope_value_ref(
                intent.value,
                inputs,
                scope=scope,
                origin=origin,
            )
            if isinstance(intent.value, ValueRef)
            else intent.value
        ),
        target_entities=tuple(
            _scope_value_ref(
                entity,
                inputs,
                scope=scope,
                origin=origin,
            )
            if isinstance(entity, ValueRef)
            else entity
            for entity in intent.target_entities
        ),
        resource_port=resource_ids.get(intent.resource_port, intent.resource_port),
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


def _scope_measurement_transform(
    transform: MeasurementTransform,
    *,
    scope: tuple[str, ...],
) -> MeasurementTransform:
    return replace(
        transform,
        scope=(*scope, *transform.scope),
        input_bindings=tuple(
            (role, product_id.prefixed(*scope))
            for role, product_id in transform.input_bindings
        ),
        output_bindings=tuple(
            (role, product_id.prefixed(*scope))
            for role, product_id in transform.output_bindings
        ),
    )


def _scope_action(
    action: ModuleActionDecl,
    inputs: Mapping[str, object],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> ModuleActionDecl:
    return replace(
        action,
        scope=(*scope, *action.scope),
        resource_port_id=resource_ids.get(
            action.resource_port_id,
            action.resource_port_id,
        ),
        fields=tuple(
            (
                name,
                _scope_value_ref(
                    value,
                    inputs,
                    scope=scope,
                    origin=origin,
                )
                if isinstance(value, ValueRef)
                else value,
            )
            for name, value in action.fields
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


def _scoped_resource_id(
    resource_id: LogicalResourcePortId | None,
    resource_ids: Mapping[LogicalResourcePortId, LogicalResourcePortId],
) -> LogicalResourcePortId | None:
    if resource_id is None:
        return None
    return resource_ids.get(resource_id, resource_id)
