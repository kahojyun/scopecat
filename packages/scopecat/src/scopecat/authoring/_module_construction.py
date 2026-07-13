"""Construction of opaque module handles from validated authoring parts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat._frozen import freeze_json_mapping
from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
)
from scopecat.authoring._handles import create_handle
from scopecat.authoring._intents import (
    ComputeNodeIntent,
    ExperimentStateIntent,
    ModuleInputPort,
    ModuleOutputPort,
)
from scopecat.authoring._module_handles import (
    ExperimentModule,
    ModuleBuilder,
    ModuleInvocation,
)
from scopecat.authoring._record_intents import ModuleProductPort, RecordIntent
from scopecat.authoring.values import MetadataValue


def module_from_parts_internal(
    *,
    id: str,  # noqa: A002
    invocations: Sequence[ModuleInvocation] = (),
    input_ports: Sequence[ModuleInputPort] = (),
    output_ports: Sequence[ModuleOutputPort] = (),
    resources: Sequence[ResourcePort] = (),
    bindings: Sequence[ExperimentBindingIntent] = (),
    state_intents: Sequence[ExperimentStateIntent] = (),
    compute_nodes: Sequence[ComputeNodeIntent] = (),
    records: Sequence[RecordIntent] = (),
    product_ports: Sequence[ModuleProductPort] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule:
    return _module(
        id=id,
        invocations=invocations,
        input_ports=input_ports,
        output_ports=output_ports,
        resources=resources,
        bindings=bindings,
        state_intents=state_intents,
        compute_nodes=compute_nodes,
        records=records,
        product_ports=product_ports,
        metadata=metadata,
    )


def _module(
    *,
    id: str,  # noqa: A002
    invocations: Sequence[ModuleInvocation] = (),
    input_ports: Sequence[ModuleInputPort] = (),
    output_ports: Sequence[ModuleOutputPort] = (),
    resources: Sequence[ResourcePort] = (),
    bindings: Sequence[ExperimentBindingIntent] = (),
    state_intents: Sequence[ExperimentStateIntent] = (),
    compute_nodes: Sequence[ComputeNodeIntent] = (),
    records: Sequence[RecordIntent] = (),
    product_ports: Sequence[ModuleProductPort] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule:
    return create_handle(
        ExperimentModule,
        id=id,
        invocations=tuple(invocations),
        input_ports=tuple(input_ports),
        output_ports=tuple(output_ports),
        resource_ports=tuple(resources),
        bindings=tuple(bindings),
        state_intents=tuple(state_intents),
        compute_nodes=tuple(compute_nodes),
        records=tuple(records),
        product_ports=tuple(product_ports),
        metadata=freeze_json_mapping(metadata or {}),
    )


def module(
    id: str | None = None,  # noqa: A002
    *,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ModuleBuilder:
    return create_handle(
        ModuleBuilder,
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
        bindings=builder.bindings,
        state_intents=builder.state_intents,
        compute_nodes=builder.compute_nodes,
        records=builder.records,
        product_ports=builder.product_ports,
        metadata=merged_metadata,
    )


def module_use_invocation(
    selected: ExperimentModule | ModuleBuilder | ModuleInvocation,
) -> ModuleInvocation:
    if isinstance(selected, ModuleInvocation):
        return selected
    if isinstance(selected, ExperimentModule):
        return selected()
    return selected.build()()


__all__ = ["module"]
