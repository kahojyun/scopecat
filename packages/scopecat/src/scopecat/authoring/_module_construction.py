"""Close module builders into IR and create reusable authoring handles."""

from __future__ import annotations

import inspect
import keyword
from collections.abc import Mapping, Sequence

from scopecat.authoring._intents import ModuleInputPort
from scopecat.authoring._module_handles import (
    ExperimentModule,
    ModuleBuilder,
    ModuleCall,
    ModuleInvocation,
    create_experiment_module_internal,
)
from scopecat.authoring._module_ir import (
    ModuleBodyIR,
    ModuleImportBinding,
    ModuleInstanceIR,
    ModuleInstanceLookup,
    ModuleInterfaceIR,
    ModuleIR,
    ModuleResourceBinding,
)
from scopecat.authoring.values import MetadataValue
from scopecat.kernel.frozen import freeze_json_mapping


def build_module_ir(
    builder: ModuleBuilder,
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ModuleIR:
    """Close a builder at the single module-definition boundary."""

    module_id = id or builder.id
    if not module_id:
        msg = "module builder requires an id before conversion to ModuleIR"
        raise ValueError(msg)
    merged_metadata: dict[str, MetadataValue] = dict(builder.metadata)
    merged_metadata.update(dict(metadata or {}))
    closed_procedure = tuple(
        _module_instance_ir(effect) if isinstance(effect, ModuleInvocation) else effect
        for effect in builder.procedure
    )
    return ModuleIR(
        id=module_id,
        interface=ModuleInterfaceIR(
            imports=builder.input_ports,
            exports=builder.output_ports,
            resources=builder.resources,
        ),
        body=ModuleBodyIR(
            procedure=closed_procedure,
            operations=builder.operations,
            measurement_transforms=builder.measurement_transform_intents,
            products=builder.product_declarations,
        ),
        python_implementations=builder.python_implementations,
        metadata=freeze_json_mapping(merged_metadata),
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


def build_module_from_builder(
    builder: ModuleBuilder,
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule[...]:
    module_ir = build_module_ir(builder, id=id, metadata=metadata)
    return create_experiment_module_internal(
        module_ir,
        signature=_module_signature(module_ir.interface.imports),
    )


def _module_signature(
    input_ports: Sequence[ModuleInputPort],
) -> inspect.Signature:
    input_ids = {port.id for port in input_ports}
    extra_name = "_inputs"
    while extra_name in input_ids:
        extra_name = f"_{extra_name}"
    parameters = [
        inspect.Parameter(
            port.id,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=port.value_type,
        )
        for port in input_ports
        if port.id.isidentifier() and not keyword.iskeyword(port.id)
    ]
    parameters.append(
        inspect.Parameter(
            extra_name,
            inspect.Parameter.VAR_KEYWORD,
        )
    )
    return inspect.Signature(parameters)


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
