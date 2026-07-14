"""Link one composed authoring assembly into a transient compiler program."""

from __future__ import annotations

from dataclasses import replace

from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    ParameterLookupContract,
    ParameterValueContract,
    merge_parameter_contracts,
)
from scopecat.authoring._point_domain_intents import (
    point_domain_intent_parameter_contracts,
)
from scopecat.compiler.frontend.assembly_lowering import (
    coerce_assembly_inputs,
    input_row,
    lower_action_effect,
    lower_parameter_overlay_intent,
    lower_point_domain,
    lower_semantic_compute_graph,
    lower_semantic_domain_graph,
    lower_state_region,
    state_specs,
    validate_assembly_conflicts,
    validate_consumed_inputs,
    validate_entity_inputs,
)
from scopecat.compiler.frontend.binding_lowering import (
    build_route_intents,
    lower_binding_intent,
    ports_by_id,
)
from scopecat.compiler.frontend.context import ExperimentAuthoringContext
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.frontend.measurement_transform_lowering import (
    authored_measurement_transform_output_product_ids,
    lower_semantic_measurement_transform_graph,
)
from scopecat.compiler.frontend.parameter_contract_validation import (
    validate_parameter_contracts,
)
from scopecat.compiler.frontend.record_lowering import (
    lower_product_selections,
    lower_records,
)
from scopecat.compiler.frontend.value_binding import (
    bind_relation_input_refs,
    bind_series_input_refs,
)
from scopecat.compiler.relations.verification import (
    ParameterLookupSignature,
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.graph import ComputeGraphError, order_compute_nodes
from scopecat.compiler.typed.program import TypedProgram
from scopecat.compiler.typed.verification import verify_typed_program
from scopecat.kernel.value_types import Scalar, Table, ValueType


def link_experiment_assembly_internal(
    assembly: SemanticExperimentIR,
    ctx: ExperimentAuthoringContext,
) -> TypedProgram:
    """Link one assembly while mapping proof failures into authoring problems."""

    try:
        return _link_experiment_assembly(assembly, ctx)
    except RelationPlanVerificationError as error:
        ctx.raise_problem(
            f"relation_plan_{error.code}",
            error.reason,
            "relation_plan",
            path=error.path,
            details={
                "relation_code": error.code,
                "plan_path": list(error.path),
            },
        )


def _link_experiment_assembly(
    assembly: SemanticExperimentIR,
    ctx: ExperimentAuthoringContext,
) -> TypedProgram:
    if not assembly.experiment_id:
        ctx.raise_problem(
            "experiment_assembly_entrypoint_missing_id",
            "experiment assembly must be linked with an experiment id",
            "experiment_id",
        )
    if not assembly.kind:
        ctx.raise_problem(
            "experiment_assembly_entrypoint_missing_kind",
            "experiment assembly must be linked with an experiment kind",
            "kind",
        )
    verified_graph = verify_assembly_graph(assembly)
    validate_parameter_contracts(ctx, _assembly_parameter_contracts(assembly))
    validate_assembly_conflicts(ctx, assembly)
    inputs = coerce_assembly_inputs(ctx, assembly.input_ports, assembly.inputs)
    validate_consumed_inputs(ctx, assembly, inputs)
    validate_entity_inputs(ctx, assembly.entity_inputs, inputs)
    resource_ports = ports_by_id(ctx, assembly.resource_ports)
    bindings = [
        lower_binding_intent(binding, ctx, resource_ports)
        for binding in assembly.bindings
    ]
    root_type_bindings = _relation_type_bindings(assembly, ctx)
    point_domain = lower_point_domain(
        assembly.point_domain,
        inputs=inputs,
        type_bindings=root_type_bindings,
        entity_input_ids=assembly.entity_inputs,
    )
    type_bindings = replace(
        root_type_bindings,
        point_row=RowType.from_table(point_domain.value_type),
    )
    route_intents = build_route_intents(
        ctx,
        assembly.resource_ports,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    inline_products = lower_records(
        ctx,
        assembly.records,
        inputs,
        type_bindings=type_bindings,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
    )
    declared_products = lower_product_selections(
        ctx,
        assembly.record_selections,
        assembly.product_ports,
        inputs,
        type_bindings=type_bindings,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
        non_instrument_product_ids=(
            frozenset(
                product_id
                for call in verified_graph.semantic_graph.graph.domain_calls
                for _result_id, product_id in call.results
            )
            | authored_measurement_transform_output_product_ids(
                verified_graph.semantic_graph
            )
        ),
    )
    lowered_compute_nodes, implementation_catalog = lower_semantic_compute_graph(
        verified_graph.semantic_graph,
        assembly.implementation_catalog,
        inputs,
        type_bindings=type_bindings,
    )
    try:
        compute_nodes = order_compute_nodes(lowered_compute_nodes)
    except ComputeGraphError as error:
        ctx.raise_problem(
            error.code,
            str(error),
            error.location.root,
            path=error.location.path,
        )
    record_product_uses = (
        *inline_products.product_uses,
        *declared_products.product_uses,
    )
    measurement_transforms = lower_semantic_measurement_transform_graph(
        verified_graph.semantic_graph,
        record_product_uses,
    )
    product_uses = (
        *record_product_uses,
        *measurement_transforms.input_product_uses,
    )
    domain_programs, domain_calls, domain_product_producers = (
        lower_semantic_domain_graph(
            verified_graph.semantic_graph,
            inputs,
            type_bindings=type_bindings,
            product_uses=product_uses,
        )
    )
    program = TypedProgram(
        id=assembly.experiment_id,
        kind=assembly.kind,
        point_domain=point_domain,
        route_intents=tuple(route_intents),
        compute_nodes=compute_nodes,
        domain_programs=domain_programs,
        domain_calls=domain_calls,
        measurement_transforms=measurement_transforms.transforms,
        implementation_catalog=implementation_catalog,
        source_map=verified_graph.source_map,
        parameter_overlays=tuple(
            lower_parameter_overlay_intent(
                ctx,
                intent,
                inputs,
                type_bindings=type_bindings,
            )
            for intent in assembly.parameter_overlays
        ),
        state=(
            *state_specs(
                bindings,
                inputs=inputs,
                type_bindings=type_bindings,
            ),
            *(
                lower_state_region(
                    ctx,
                    region,
                    verified_graph.semantic_graph,
                    resource_ports,
                    inputs,
                    type_bindings=type_bindings,
                )
                for region in verified_graph.semantic_graph.graph.row_regions
            ),
        ),
        actions=tuple(
            lower_action_effect(
                ctx,
                action,
                verified_graph.semantic_graph,
                resource_ports,
                inputs,
                type_bindings=type_bindings,
            )
            for action in verified_graph.semantic_graph.graph.actions
        ),
        product_defs=(*inline_products.product_defs, *declared_products.product_defs),
        instrument_product_producers=(
            *inline_products.instrument_product_producers,
            *declared_products.instrument_product_producers,
        ),
        domain_product_producers=domain_product_producers,
        measurement_transform_product_producers=measurement_transforms.producers,
        product_uses=product_uses,
        record_uses=(*inline_products.record_uses, *declared_products.record_uses),
        metadata=dict(assembly.metadata),
    )
    return verify_typed_program(program)


def _relation_type_bindings(
    assembly: SemanticExperimentIR,
    ctx: ExperimentAuthoringContext,
) -> RelationTypeBindings:
    """Project assembly contracts into the final plan-verification environment."""

    contracts = _assembly_parameter_contracts(assembly)
    return RelationTypeBindings(
        inputs={port.id: port.value_type for port in assembly.input_ports},
        parameters={
            contract.parameter_id: _catalog_parameter_type(
                ctx,
                contract.parameter_id,
                contract.value_type,
            )
            for contract in contracts
            if isinstance(contract, ParameterValueContract)
        },
        parameter_lookups=tuple(
            ParameterLookupSignature(
                table_id=contract.parameter_id,
                key_input_types=contract.key_types,
                column_id=contract.column_id,
                result_type=_catalog_lookup_result_type(ctx, contract),
            )
            for contract in contracts
            if isinstance(contract, ParameterLookupContract)
        ),
    )


def _assembly_parameter_contracts(
    assembly: SemanticExperimentIR,
) -> tuple[ParameterContract, ...]:
    """Return every config contract consumed while linking the assembly."""

    return merge_parameter_contracts(
        assembly.parameter_contracts,
        point_domain_intent_parameter_contracts(assembly.point_domain),
    )


def _catalog_parameter_type(
    ctx: ExperimentAuthoringContext,
    parameter_id: str,
    fallback: ValueType,
) -> ValueType:
    definition = ctx.config.parameter_catalog.get(parameter_id)
    return definition.value_type if definition is not None else fallback


def _catalog_lookup_result_type(
    ctx: ExperimentAuthoringContext,
    contract: ParameterLookupContract,
) -> Scalar:
    definition = ctx.config.parameter_catalog.get(contract.parameter_id)
    if definition is not None and isinstance(definition.value_type, Table):
        for column in definition.value_type.columns:
            if column.id == contract.column_id:
                return column.value_type
    return contract.value_type


__all__ = ["link_experiment_assembly_internal"]
