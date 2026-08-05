"""Elaborate hierarchical module definitions into one flat logical program."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.compiler.frontend.logical_closure import (
    LogicalProgramBuilder,
)
from scopecat.compiler.frontend.logical_dependencies import (
    entity_input_ids,
    logical_value_roots,
    nested_value_refs,
    require_closed_logical_values,
    summarize_value_ref_dependencies,
)
from scopecat.compiler.frontend.module_resolution import (
    HierarchyRoot,
    ModuleValueResolver,
    lower_module_effect,
    resolve_operation,
    resolve_product,
    resolve_resource_port,
)
from scopecat.compiler.frontend.module_scoping import (
    DefinitionEffect,
    InstanceBoundary,
    localize_effect,
    localize_measurement_postprocessor,
    localize_operation,
    localize_product_declaration,
    localize_resource_port,
    localize_value_ref,
)
from scopecat.compiler.frontend.scan_lowering import lower_scans_point_domain
from scopecat.kernel.point_identity import PointDomainLayout
from scopecat.kernel.product_identity import parse_product_id
from scopecat.kernel.value_types import Scalar
from scopecat.program.bindings import (
    EnsureStateIntent,
    ResourcePort,
)
from scopecat.program.definitions import ExperimentDef
from scopecat.program.domain import DomainExecution
from scopecat.program.identities import InvocationKey
from scopecat.program.logical import LogicalProgram
from scopecat.program.module import (
    ModuleDef,
    ModuleInstance,
)
from scopecat.program.parameters import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.program.point_domain import PointAxes
from scopecat.program.products import (
    ModuleProductDecl,
)
from scopecat.program.recording import (
    LogicalRecordSelection,
    LogicalValueRecordSelection,
    ProgramRecordSelection,
    ValueRecordSelection,
)
from scopecat.program.scans import (
    AxisSpec,
    PointTraversal,
    RepeatMode,
    axis_parameter_contracts,
)
from scopecat.program.value_refs import ValueRef, internal_value_ref_source_id
from scopecat.program.value_transforms import internal_bind_value_ref_inputs


class _LogicalProgramComposer:
    """Recursively flatten definitions directly into logical-program fields."""

    def __init__(self) -> None:
        self.logical = LogicalProgramBuilder()
        self.resource_ports: list[ResourcePort] = []
        self.product_declarations: list[ModuleProductDecl] = []
        self.dependency_roots: list[object] = []

    def add_hierarchy(self, root: HierarchyRoot) -> tuple[DefinitionEffect, ...]:
        return self._add_module(root, boundaries=())

    def _add_module(
        self,
        module: HierarchyRoot,
        *,
        boundaries: tuple[InstanceBoundary, ...],
    ) -> tuple[DefinitionEffect, ...]:
        resolver = ModuleValueResolver(module)
        child_effects: dict[InvocationKey, tuple[DefinitionEffect, ...]] = {}
        for instance in module.body.child_instances:
            boundary = InstanceBoundary(
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
            localize_effect(
                lower_module_effect(effect, resolver=resolver),
                boundaries,
            )
            for effect in module.body.effects
            if not isinstance(effect, ModuleInstance)
        )
        ordered: list[DefinitionEffect] = []
        own_effect_iterator = iter(own_effects)
        for effect in module.body.effects:
            if isinstance(effect, ModuleInstance):
                ordered.extend(child_effects[effect.invocation_key])
            else:
                ordered.append(next(own_effect_iterator))
        return tuple(ordered)

    def _add_declarations(
        self,
        module: HierarchyRoot,
        *,
        resolver: ModuleValueResolver,
        boundaries: tuple[InstanceBoundary, ...],
    ) -> None:
        implementations = {
            implementation.declaration_key: implementation.fn
            for implementation in module.python_implementations
        }
        for port in module.interface.resources:
            localized = localize_resource_port(
                resolve_resource_port(port, resolver=resolver),
                boundaries,
            )
            if localized is not None:
                self.resource_ports.append(localized)
        for operation in module.body.operations:
            localized = localize_operation(
                resolve_operation(operation, resolver=resolver),
                boundaries,
            )
            self.logical.add_authored_operation(
                localized,
                implementations[operation.declaration_key],
            )
            self.dependency_roots.extend(value for _name, value in localized.inputs)
        for postprocessor in module.body.measurement_postprocessors:
            self.logical.add_measurement_postprocessor(
                localize_measurement_postprocessor(postprocessor, boundaries)
            )
        self.product_declarations.extend(
            localize_product_declaration(
                resolve_product(product, resolver=resolver),
                boundaries,
            )
            for product in module.body.products
        )
        self.dependency_roots.extend(
            localize_value_ref(resolver.resolve(export.source), boundaries)
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
        success_state=None,
    )


def compose_experiment(
    definition: ExperimentDef,
    *,
    inputs: Mapping[str, object],
    scans: Sequence[AxisSpec] = (),
    point_domain_layout: PointDomainLayout = "product_grid",
    point_repeat: int = 1,
    point_repeat_mode: RepeatMode = "point",
    point_traversal: PointTraversal = "forward",
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
        parameter_overlays=tuple(axis for axis in scans if axis.overlay is not None),
        record_selections=definition.record_selections,
        additional_parameter_contracts=merge_parameter_contracts(
            *(axis_parameter_contracts(axis) for axis in scans),
        ),
        point_domain=lower_scans_point_domain(scans, inputs=inputs),
        point_domain_layout=point_domain_layout,
        point_repeat=point_repeat,
        point_repeat_mode=point_repeat_mode,
        point_traversal=point_traversal,
        success_state=definition.success_state,
    )


def _elaborate_hierarchy(
    root: HierarchyRoot,
    *,
    experiment_id: str,
    kind: str,
    inputs: Mapping[str, object],
    logical_inputs: Mapping[str, object] | None = None,
    parameter_overlays: Sequence[AxisSpec] = (),
    record_selections: Sequence[ProgramRecordSelection] = (),
    additional_parameter_contracts: tuple[ParameterContract, ...] = (),
    point_domain: PointAxes[ValueRef] = (),
    point_domain_layout: PointDomainLayout = "product_grid",
    point_repeat: int = 1,
    point_repeat_mode: RepeatMode = "point",
    point_traversal: PointTraversal = "forward",
    success_state: EnsureStateIntent | None,
) -> LogicalProgram:
    composer = _LogicalProgramComposer()
    effects = composer.add_hierarchy(root)
    root_resolver = ModuleValueResolver(root)
    value_record_selections = tuple(
        selection
        for selection in record_selections
        if isinstance(selection, ValueRecordSelection)
    )
    resolved_record_values = tuple(
        root_resolver.resolve(selection.value) for selection in value_record_selections
    )
    resolved_value_records = tuple(
        _resolve_value_record_selection(
            selection,
            value=value,
            builder=composer.logical,
        )
        for selection, value in zip(
            value_record_selections,
            resolved_record_values,
            strict=True,
        )
    )
    value_record_iterator = iter(resolved_value_records)
    logical_record_selections: tuple[LogicalRecordSelection, ...] = tuple(
        next(value_record_iterator)
        if isinstance(selection, ValueRecordSelection)
        else selection
        for selection in record_selections
    )
    execution_ids = tuple(
        effect.id for effect in effects if isinstance(effect, DomainExecution)
    )
    if len(execution_ids) != len(set(execution_ids)):
        raise ValueError("logical program contains repeated domain execution ids")
    value_roots = logical_value_roots(
        resource_ports=composer.resource_ports,
        product_declarations=composer.product_declarations,
        effects=effects,
    )
    success_state_values = tuple(
        assignment.value
        for assignment in (() if success_state is None else success_state.assignments)
    )
    require_closed_logical_values(
        inputs,
        (
            *value_roots,
            *resolved_record_values,
            *success_state_values,
        ),
    )
    typed_inputs = {
        input_id: value
        for input_id, value in inputs.items()
        if isinstance(value, ValueRef)
    }
    dependencies = summarize_value_ref_dependencies(
        internal_bind_value_ref_inputs(value, typed_inputs)
        for source in (
            *value_roots,
            *composer.dependency_roots,
            *resolved_record_values,
            *success_state_values,
        )
        for value in nested_value_refs(source)
    )
    logical_effects = tuple(
        composer.logical.add_effect(effect, effect_index=effect_index)
        for effect_index, effect in enumerate(effects)
    )
    for root_value in (*value_roots, *success_state_values):
        if isinstance(root_value, ValueRef):
            composer.logical.add_value_root(cast("ValueRef[object]", root_value))
    return composer.logical.finish(
        experiment_id=experiment_id,
        kind=kind,
        inputs=dict(inputs if logical_inputs is None else logical_inputs),
        input_ports=root.interface.imports,
        entity_inputs=entity_input_ids(root.interface.imports),
        resource_ports=tuple(composer.resource_ports),
        point_dependencies=dependencies.point,
        parameter_overlays=parameter_overlays,
        product_declarations=tuple(composer.product_declarations),
        record_selections=logical_record_selections,
        parameter_contracts=merge_parameter_contracts(
            dependencies.parameters,
            additional_parameter_contracts,
        ),
        point_domain=point_domain,
        point_domain_layout=point_domain_layout,
        point_repeat=point_repeat,
        point_repeat_mode=point_repeat_mode,
        point_traversal=point_traversal,
        effects=logical_effects,
        success_state=(
            None
            if success_state is None
            else composer.logical.add_ensure_state(
                success_state,
                scope=("success_state",),
            )
        ),
    )


def _resolve_value_record_selection(
    selection: ValueRecordSelection,
    *,
    value: ValueRef,
    builder: LogicalProgramBuilder,
) -> LogicalValueRecordSelection:
    if not isinstance(value.value_type, Scalar):
        raise TypeError("dataset value records must be scalar")
    default_source_id = internal_value_ref_source_id(value)
    if selection.record_id is None and default_source_id is None:
        raise ValueError("recording an unnamed symbolic expression requires record_id")
    source_value_id = default_source_id or selection.record_id
    if source_value_id is None:
        raise AssertionError("value record identity was not resolved")
    selected_id = (
        selection.record_id
        or parse_product_id(source_value_id)
        .prefixed(*selection.namespace)
        .qualified_name
    )
    return LogicalValueRecordSelection(
        id=selected_id,
        value_id=builder.add_value_root(value),
        source_value_id=source_value_id,
        value_type=value.value_type,
        role=selection.role,
        metadata=selection.metadata,
    )
