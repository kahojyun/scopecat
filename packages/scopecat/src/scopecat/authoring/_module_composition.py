"""Compose typed module handles into a source-level experiment assembly."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
    ResourceSelector,
)
from scopecat.authoring._frozen_values import empty_frozen_mapping
from scopecat.authoring._intents import (
    ComputeNodeInputValue,
    ComputeNodeIntent,
    ExperimentStateIntent,
    ModuleInputPort,
    ParameterScanOverlayIntent,
    PointSourceInput,
    StateEachIntent,
)
from scopecat.authoring._module_handles import (
    ExperimentModule,
    ModuleInvocation,
    entity_input_ids_internal,
    module_exposed_input_types_internal,
)
from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.authoring._record_intents import (
    ModuleProductPort,
    ProductSelectionIntent,
    RecordIntent,
    localize_product_input_refs,
    localize_record_input_refs,
)
from scopecat.authoring._value_refs import (
    PointValueDependency,
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_literal_value_ref,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
    require_assignable,
)
from scopecat.authoring.value_types import (
    Table as TableType,
)
from scopecat.authoring.value_types import ValueType
from scopecat.authoring.values import MetadataValue


@dataclass(frozen=True)
class ExperimentAssemblyInternal:
    """Internal source-level experiment IR produced before config linking."""

    experiment_id: str | None = None
    kind: str | None = None
    inputs: dict[str, object] = field(default_factory=dict)
    input_ports: tuple[ModuleInputPort, ...] = ()
    entity_inputs: tuple[str, ...] = ()
    resource_ports: tuple[ResourcePort, ...] = ()
    point_source: PointSourceInput = None
    point_dependencies: tuple[PointValueDependency, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state_intents: tuple[ExperimentStateIntent, ...] = ()
    parameter_overlays: tuple[ParameterScanOverlayIntent, ...] = ()
    compute_nodes: tuple[ComputeNodeIntent, ...] = ()
    records: tuple[RecordIntent, ...] = ()
    product_ports: tuple[ModuleProductPort, ...] = ()
    record_selections: tuple[ProductSelectionIntent, ...] = ()
    parameter_contracts: tuple[ParameterContract, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    @classmethod
    def combine(
        cls,
        *,
        experiment_id: str,
        kind: str,
        assemblies: Sequence[ExperimentAssemblyInternal],
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ExperimentAssemblyInternal:
        if not assemblies:
            msg = "experiment assembly combine requires at least one assembly"
            raise ValueError(msg)
        merged_metadata: dict[str, MetadataValue] = {}
        merged_inputs: dict[str, object] = {}
        for assembly in assemblies:
            merged_inputs.update(assembly.inputs)
            merged_metadata.update(assembly.metadata)
        merged_metadata.update(dict(metadata or {}))
        resource_ports = _merge_resource_ports(
            tuple(item for assembly in assemblies for item in assembly.resource_ports)
        )
        return cls(
            experiment_id=experiment_id,
            kind=kind,
            inputs=merged_inputs,
            input_ports=tuple(
                item for assembly in assemblies for item in assembly.input_ports
            ),
            entity_inputs=tuple(
                item for assembly in assemblies for item in assembly.entity_inputs
            ),
            resource_ports=resource_ports,
            point_source=_combined_point_source(
                tuple(assembly.point_source for assembly in assemblies)
            ),
            point_dependencies=_merge_point_dependencies(
                *(assembly.point_dependencies for assembly in assemblies)
            ),
            bindings=tuple(
                item for assembly in assemblies for item in assembly.bindings
            ),
            state_intents=tuple(
                item for assembly in assemblies for item in assembly.state_intents
            ),
            parameter_overlays=tuple(
                item for assembly in assemblies for item in assembly.parameter_overlays
            ),
            compute_nodes=tuple(
                item for assembly in assemblies for item in assembly.compute_nodes
            ),
            records=tuple(item for assembly in assemblies for item in assembly.records),
            product_ports=tuple(
                item for assembly in assemblies for item in assembly.product_ports
            ),
            record_selections=tuple(
                item for assembly in assemblies for item in assembly.record_selections
            ),
            parameter_contracts=merge_parameter_contracts(
                *(assembly.parameter_contracts for assembly in assemblies)
            ),
            metadata=merged_metadata,
        )


def assemble_module_internal(
    module: ExperimentModule,
    /,
    **inputs: object,
) -> ExperimentAssemblyInternal:
    """Assemble one module at the private compiler boundary."""

    own = ExperimentAssemblyInternal(
        inputs=dict(inputs),
        input_ports=module.input_ports,
        entity_inputs=entity_input_ids_internal(module.input_ports),
        resource_ports=_merge_resource_ports(module.resource_ports),
        point_dependencies=_module_point_dependencies(module, inputs),
        bindings=module.bindings,
        state_intents=module.state_intents,
        compute_nodes=module.compute_nodes,
        records=module.records,
        product_ports=module.product_ports,
        parameter_contracts=_module_parameter_contracts(module, inputs),
        metadata=dict(module.metadata),
    )
    if not module.invocations:
        return own
    source_assemblies = tuple(
        _localize_module_invocation_assembly(source) for source in module.invocations
    )
    combined = ExperimentAssemblyInternal.combine(
        experiment_id=module.id,
        kind=module.id,
        assemblies=(*source_assemblies, own),
    )
    return replace(combined, experiment_id=None, kind=None)


def assemble_invocation_internal(
    invocation: ModuleInvocation,
) -> ExperimentAssemblyInternal:
    return assemble_module_internal(invocation.module, **invocation.inputs)


def _module_invocation_inputs(
    invocation: ModuleInvocation,
) -> dict[str, object]:
    input_types = module_exposed_input_types_internal(invocation.module)
    return {
        input_id: _module_invocation_input_expr(
            value,
            input_id=input_id,
            value_type=input_types[input_id],
        )
        for input_id, value in invocation.inputs.items()
    }


def _module_parameter_contracts(
    module: ExperimentModule,
    inputs: Mapping[str, object],
) -> tuple[ParameterContract, ...]:
    """Collect parameter provenance reachable from the module's value graph."""

    return merge_parameter_contracts(
        *(
            internal_value_ref_parameter_contracts(value)
            for value in _reachable_module_value_refs(module, inputs)
        )
    )


def _module_point_dependencies(
    module: ExperimentModule,
    inputs: Mapping[str, object],
) -> tuple[PointValueDependency, ...]:
    """Collect point contracts reachable from the module's value graph."""

    return _merge_point_dependencies(
        *(
            internal_value_ref_point_dependencies(value)
            for value in _reachable_module_value_refs(module, inputs)
        )
    )


def _reachable_module_value_refs(
    module: ExperimentModule,
    inputs: Mapping[str, object],
) -> tuple[ValueRef, ...]:
    """Bind only input values reachable from an authored module value root."""

    typed_inputs = {
        input_id: value
        for input_id, value in inputs.items()
        if isinstance(value, ValueRef)
    }
    return tuple(
        internal_bind_value_ref_inputs(value_ref, typed_inputs)
        for root in _module_value_roots(module)
        for value_ref in _nested_value_refs(root)
    )


def _module_value_roots(module: ExperimentModule) -> tuple[object, ...]:
    """Return authored values that can affect the assembled module."""

    values: list[object] = []
    values.extend(
        source
        for port in module.resource_ports
        for source in port.selector.entity_inputs
    )
    values.extend(binding.value for binding in module.bindings)
    for intent in module.state_intents:
        values.extend(
            (
                intent.relation,
                intent.resource,
                intent.value,
                *intent.route_entities,
            )
        )
    values.extend(
        value for node in module.compute_nodes for _name, value in node.inputs
    )
    values.extend(axis.size for record in module.records for axis in record.axes)
    values.extend(
        axis.size for product in module.product_ports for axis in product.axes
    )
    return tuple(values)


def _nested_value_refs(
    value: object,
    *,
    seen: frozenset[int] = frozenset(),
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
        selected = cast("Sequence[object]", value)
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


def _localize_module_invocation_assembly(
    invocation: ModuleInvocation,
) -> ExperimentAssemblyInternal:
    local_inputs = _module_invocation_inputs(invocation)
    assembly = assemble_module_internal(invocation.module, **local_inputs)
    if not local_inputs:
        return assembly
    resource_ports = _localize_resource_port_input_refs(
        assembly.resource_ports,
        local_inputs,
    )
    return replace(
        assembly,
        inputs={
            key: value
            for key, value in assembly.inputs.items()
            if key not in local_inputs
        },
        input_ports=tuple(
            port for port in assembly.input_ports if port.id not in local_inputs
        ),
        entity_inputs=tuple(
            input_id
            for input_id in assembly.entity_inputs
            if input_id not in local_inputs
        ),
        resource_ports=resource_ports,
        bindings=tuple(
            _localize_binding_input_refs(binding, local_inputs)
            for binding in assembly.bindings
        ),
        state_intents=tuple(
            _localize_state_input_refs(intent, local_inputs)
            for intent in assembly.state_intents
        ),
        compute_nodes=tuple(
            _localize_compute_input_refs(node, local_inputs)
            for node in assembly.compute_nodes
        ),
        records=tuple(
            localize_record_input_refs(
                record,
                local_inputs,
                localize_value_ref=_localize_value_ref,
            )
            for record in assembly.records
        ),
        product_ports=tuple(
            localize_product_input_refs(
                product,
                local_inputs,
                localize_value_ref=_localize_value_ref,
            )
            for product in assembly.product_ports
        ),
    )


def _localize_resource_port_input_refs(
    ports: Sequence[ResourcePort],
    inputs: Mapping[str, object],
) -> tuple[ResourcePort, ...]:
    localized_ports: list[ResourcePort] = []
    for port in ports:
        entity_inputs: list[ValueRef] = []
        for source in port.selector.entity_inputs:
            localized = _localize_value_ref(source, inputs)
            if isinstance(localized.value_type, TableType):
                msg = (
                    "resource entity source must be scalar or series-shaped; "
                    "select table entity columns with table.entities(...)"
                )
                raise TypeError(msg)
            entity_inputs.append(localized)
        localized_ports.append(
            replace(
                port,
                selector=ResourceSelector(
                    capabilities=port.selector.capabilities,
                    entity_inputs=tuple(entity_inputs),
                ),
            )
        )
    return tuple(localized_ports)


def _module_invocation_input_expr(
    value: object,
    *,
    input_id: str,
    value_type: ValueType,
) -> ValueRef:
    path = f"inputs.{input_id}"
    if isinstance(value, ValueRef):
        require_assignable(value.value_type, value_type, path=path)
        return value
    return internal_literal_value_ref(
        value,
        value_type,
        path=path,
    )


def _localize_value_ref(
    value: ValueRef,
    inputs: Mapping[str, object],
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
        value,
        typed_inputs,
    )


def _localize_binding_input_refs(
    binding: ExperimentBindingIntent,
    inputs: Mapping[str, object],
) -> ExperimentBindingIntent:
    if isinstance(binding.value, ValueRef):
        return replace(
            binding,
            value=_localize_value_ref(binding.value, inputs),
        )
    return binding


def _localize_state_input_refs(
    intent: StateEachIntent,
    inputs: Mapping[str, object],
) -> StateEachIntent:
    relation = _localize_value_ref(intent.relation, inputs)
    if not isinstance(relation.value_type, TableType):
        msg = "state_each relation must be table-shaped"
        raise TypeError(msg)
    return replace(
        intent,
        relation=relation,
        resource=(
            _localize_value_ref(intent.resource, inputs)
            if isinstance(intent.resource, ValueRef)
            else intent.resource
        ),
        value=(
            _localize_value_ref(intent.value, inputs)
            if isinstance(intent.value, ValueRef)
            else intent.value
        ),
        route_entities=tuple(
            _localize_value_ref(entity, inputs)
            if isinstance(entity, ValueRef)
            else entity
            for entity in intent.route_entities
        ),
    )


def _localize_compute_input_refs(
    node: ComputeNodeIntent,
    inputs: Mapping[str, object],
) -> ComputeNodeIntent:
    return replace(
        node,
        inputs=tuple(
            (
                name,
                _localize_compute_input_value(value, inputs),
            )
            for name, value in node.inputs
        ),
    )


def _localize_compute_input_value(
    value: ComputeNodeInputValue,
    inputs: Mapping[str, object],
) -> ComputeNodeInputValue:
    if isinstance(value, ValueRef):
        return _localize_value_ref(value, inputs)
    return value


def _merge_resource_ports(roles: Sequence[ResourcePort]) -> tuple[ResourcePort, ...]:
    merged: dict[str, ResourcePort] = {}
    for role in roles:
        existing = merged.get(role.id)
        if existing is None:
            merged[role.id] = role
            continue
        capabilities = tuple(
            dict.fromkeys(
                (*existing.selector.capabilities, *role.selector.capabilities)
            )
        )
        entity_inputs = tuple(
            _unique_value_handles(
                (*existing.selector.entity_inputs, *role.selector.entity_inputs)
            )
        )
        merged[role.id] = ResourcePort(
            id=role.id,
            selector=ResourceSelector(
                capabilities=capabilities,
                entity_inputs=entity_inputs,
            ),
        )
    return tuple(merged.values())


def _unique_value_handles(values: Sequence[ValueRef]) -> list[ValueRef]:
    """Deduplicate repeated handles without conflating equal-looking graphs."""

    selected: list[ValueRef] = []
    for value in values:
        if not any(existing is value for existing in selected):
            selected.append(value)
    return selected


def _combined_point_source(
    point_sources: Sequence[PointSourceInput],
) -> PointSourceInput:
    selected = [
        point_source for point_source in point_sources if point_source is not None
    ]
    if not selected:
        return None
    return _combined_point_source_input(selected)


def _combined_point_source_input(
    point_sources: Sequence[ValueRef],
) -> PointSourceInput:
    if not point_sources:
        return None
    if len(point_sources) == 1:
        return point_sources[0]
    point_source = point_sources[0]
    for next_source in point_sources[1:]:
        point_source = point_source.cross(next_source)
    return point_source


__all__ = [
    "ExperimentAssemblyInternal",
    "assemble_invocation_internal",
    "assemble_module_internal",
]
