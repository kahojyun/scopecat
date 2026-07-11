"""Link one composed authoring assembly into a transient compiler program."""

from __future__ import annotations

from scopecat._compiler.graph import ComputeGraphError, order_compute_nodes
from scopecat._compiler.program import TypedProgram
from scopecat.authoring._assembly_lowering import (
    coerce_assembly_inputs,
    input_row,
    lower_compute_node_intent,
    lower_parameter_overlay_intent,
    lower_point_source,
    lower_state_intent,
    state_specs,
    validate_assembly_conflicts,
    validate_consumed_inputs,
    validate_entity_inputs,
)
from scopecat.authoring._binding_lowering import (
    build_route_intents,
    lower_binding_intent,
    ports_by_id,
)
from scopecat.authoring._context import ExperimentAuthoringContext
from scopecat.authoring._module_composition import ExperimentAssemblyInternal
from scopecat.authoring._parameter_contract_validation import (
    validate_parameter_contracts,
)
from scopecat.authoring._record_lowering import (
    lower_product_selections,
    lower_records,
)
from scopecat.authoring._value_binding import (
    bind_relation_input_refs,
    bind_series_input_refs,
)


def link_experiment_assembly_internal(
    assembly: ExperimentAssemblyInternal,
    ctx: ExperimentAuthoringContext,
) -> TypedProgram:
    if not assembly.experiment_id:
        ctx.raise_diagnostic(
            "experiment_assembly_entrypoint_missing_id",
            "experiment assembly must be linked with an experiment id",
            "experiment_id",
        )
    if not assembly.kind:
        ctx.raise_diagnostic(
            "experiment_assembly_entrypoint_missing_kind",
            "experiment assembly must be linked with an experiment kind",
            "kind",
        )
    validate_parameter_contracts(ctx, assembly.parameter_contracts)
    validate_assembly_conflicts(ctx, assembly)
    inputs = coerce_assembly_inputs(ctx, assembly.input_ports, assembly.inputs)
    validate_consumed_inputs(ctx, assembly, inputs)
    validate_entity_inputs(ctx, assembly.entity_inputs, inputs)
    resource_ports = ports_by_id(ctx, assembly.resource_ports)
    route_intents = build_route_intents(
        ctx,
        assembly.resource_ports,
        inputs=inputs,
    )
    bindings = [
        lower_binding_intent(binding, ctx, resource_ports)
        for binding in assembly.bindings
    ]
    point_source = lower_point_source(
        assembly.point_source,
        inputs=inputs,
        entity_input_ids=assembly.entity_inputs,
    )
    records = [
        *lower_records(
            ctx,
            assembly.records,
            inputs,
            bind_series_input_refs=bind_series_input_refs,
            bind_relation_input_refs=bind_relation_input_refs,
            input_row=input_row,
        ),
        *lower_product_selections(
            ctx,
            assembly.record_selections,
            assembly.product_ports,
            inputs,
            bind_series_input_refs=bind_series_input_refs,
            bind_relation_input_refs=bind_relation_input_refs,
            input_row=input_row,
        ),
    ]
    lowered_compute_nodes = tuple(
        lower_compute_node_intent(node, inputs) for node in assembly.compute_nodes
    )
    try:
        compute_nodes = order_compute_nodes(lowered_compute_nodes)
    except ComputeGraphError as error:
        ctx.raise_diagnostic(error.code, str(error), error.path)
    return TypedProgram(
        id=assembly.experiment_id,
        kind=assembly.kind,
        point_source=point_source,
        route_intents=tuple(route_intents),
        compute_nodes=compute_nodes,
        parameter_overlays=tuple(
            lower_parameter_overlay_intent(ctx, intent, inputs)
            for intent in assembly.parameter_overlays
        ),
        state=(
            *state_specs(bindings, inputs=inputs),
            *(
                lower_state_intent(ctx, intent, resource_ports, inputs)
                for intent in assembly.state_intents
            ),
        ),
        records=tuple(records),
        metadata=dict(assembly.metadata),
    )


__all__ = ["link_experiment_assembly_internal"]
