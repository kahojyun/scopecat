"""Construction of opaque module handles from validated authoring parts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.authoring._binding_intents import ResourcePort
from scopecat.authoring._intents import (
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.authoring._module_handles import (
    ExperimentModule,
    ModuleBuilder,
    ModuleCall,
    ModuleInvocation,
)
from scopecat.authoring._module_ir import (
    ModuleBodyIR,
    ModuleEffectIR,
    ModuleImportBinding,
    ModuleInstanceIR,
    ModuleInstanceLookup,
    ModuleInterfaceIR,
    ModuleIR,
    ModuleProductExport,
    ModulePythonImplementation,
    ModuleResourceBinding,
    ModuleValueExport,
)
from scopecat.authoring._products import (
    ModuleProductDecl,
)
from scopecat.authoring.measurements import MeasurementTransform
from scopecat.authoring.values import MetadataValue
from scopecat.kernel.frozen import freeze_json_mapping


def module_from_parts_internal(
    *,
    id: str,  # noqa: A002
    invocations: Sequence[ModuleInvocation] = (),
    input_ports: Sequence[ModuleInputPort] = (),
    output_ports: Sequence[ModuleValueExport] = (),
    resources: Sequence[ResourcePort] = (),
    procedure: Sequence[ModuleEffectIR] = (),
    operations: Sequence[ModuleOperationDecl] = (),
    python_implementations: Sequence[ModulePythonImplementation] = (),
    measurement_transforms: Sequence[MeasurementTransform] = (),
    product_declarations: Sequence[ModuleProductDecl] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule:
    instances = tuple(_module_instance_ir(invocation) for invocation in invocations)
    projected_products = tuple(
        product.projected_by(instance.lookup)
        for instance in instances
        for product in instance.module.interface.products
    )
    declared_products = tuple(
        ModuleProductExport.from_declaration(product)
        for product in product_declarations
    )
    module_ir = ModuleIR(
        id=id,
        interface=ModuleInterfaceIR(
            imports=tuple(input_ports),
            exports=tuple(output_ports),
            resources=tuple(resources),
            products=(*projected_products, *declared_products),
        ),
        body=ModuleBodyIR(
            instances=instances,
            procedure=tuple(procedure),
            operations=tuple(operations),
            measurement_transforms=tuple(measurement_transforms),
            products=tuple(product_declarations),
        ),
        python_implementations=tuple(python_implementations),
        metadata=freeze_json_mapping(metadata or {}),
    )
    return ExperimentModule(
        _ir=module_ir,
    )


def _module_instance_ir(invocation: ModuleInvocation) -> ModuleInstanceIR:
    bindings = tuple(
        ModuleImportBinding(import_id=import_id, source=source)
        for import_id, source in invocation.inputs.items()
    )
    return ModuleInstanceIR(
        lookup=ModuleInstanceLookup(
            invocation_key=invocation.invocation_key,
            instance_id=invocation.instance_id,
        ),
        module=invocation.module.ir,
        input_bindings=bindings,
        resource_bindings=tuple(
            ModuleResourceBinding(import_id=child_id, source_id=parent_id)
            for child_id, parent_id in invocation.resource_bindings.items()
        ),
    )


def module(
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ModuleBuilder:
    return ModuleBuilder(
        id=id,
        invocations=(),
        input_ports=(),
        output_ports=(),
        metadata=freeze_json_mapping(metadata or {}),
    )


def build_module_from_builder(
    builder: ModuleBuilder,
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule:
    module_id = id or builder.id
    if not module_id:
        msg = "module builder requires an id before conversion to ExperimentModule"
        raise ValueError(msg)
    merged_metadata: dict[str, MetadataValue] = dict(builder.metadata)
    merged_metadata.update(dict(metadata or {}))
    return module_from_parts_internal(
        id=module_id,
        invocations=builder.invocations,
        input_ports=builder.input_ports,
        output_ports=builder.output_ports,
        resources=builder.resources,
        procedure=builder.procedure,
        operations=builder.operations,
        python_implementations=builder.python_implementations,
        measurement_transforms=builder.measurement_transform_intents,
        product_declarations=builder.product_declarations,
        metadata=merged_metadata,
    )


def module_use_invocation(
    selected: ModuleInvocation | ModuleCall | object,
) -> ModuleInvocation:
    if isinstance(selected, ModuleInvocation):
        return selected
    invocation = getattr(selected, "module_invocation", None)
    if isinstance(invocation, ModuleInvocation):
        return invocation
    msg = "module composition requires a ModuleInvocation or a domain module call"
    raise TypeError(msg)
