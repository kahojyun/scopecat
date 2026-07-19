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
    input_row,
    lower_action_effect,
    lower_parameter_overlay_intent,
    lower_point_domain,
    lower_semantic_compute_graph,
    lower_semantic_domain_graph,
    lower_state_region,
    state_specs,
    validate_entity_inputs,
)
from scopecat.compiler.frontend.binding_lowering import (
    build_route_intents,
    lower_binding_intent,
)
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.frontend.graph_validation import VerifiedAssembly
from scopecat.compiler.frontend.measurement_transform_lowering import (
    authored_measurement_transform_output_product_ids,
    lower_semantic_measurement_transform_graph,
)
from scopecat.compiler.frontend.parameter_contract_validation import (
    validate_parameter_contracts,
)
from scopecat.compiler.frontend.problems import raise_frontend_problem
from scopecat.compiler.frontend.record_lowering import (
    lower_product_selections,
    lower_records,
)
from scopecat.compiler.frontend.static_evaluation import StaticRelationEvaluator
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
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.verification import (
    VerifiedCoreProgram,
    seal_typed_program,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.value_types import Scalar, Table, ValueType
from scopecat.records.parameter import ParameterCatalog


def bind_verified_assembly(
    verified: VerifiedAssembly,
    environment: ValidatedConfigEnvironment,
) -> VerifiedCoreProgram:
    """Bind a config-free assembly proof to one validated config environment."""

    if not environment.valid:
        raise CheckFailed(environment.problems)

    try:
        return _bind_verified_assembly(
            verified,
            environment,
        )
    except RelationPlanVerificationError as error:
        raise_frontend_problem(
            f"relation_plan_{error.code}",
            error.reason,
            "relation_plan",
            path=error.path,
            details={
                "relation_code": error.code,
                "plan_path": list(error.path),
            },
        )


def _bind_verified_assembly(
    verified: VerifiedAssembly,
    environment: ValidatedConfigEnvironment,
) -> VerifiedCoreProgram:
    assembly = verified.source
    verified_graph = verified.graph
    config = environment.config
    parameter_catalog = config.parameter_catalog
    topology = config.topology
    inputs = assembly.inputs
    validate_parameter_contracts(
        parameter_catalog,
        _assembly_parameter_contracts(assembly),
    )
    validate_entity_inputs(topology, assembly.entity_inputs, inputs)
    resource_ports = verified_graph.resource_ports
    bindings = [
        lower_binding_intent(binding, resource_ports[binding.port_id])
        for binding in assembly.bindings
    ]
    root_type_bindings = _relation_type_bindings(assembly, parameter_catalog)
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
        topology,
        assembly.resource_ports,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    static_evaluator = StaticRelationEvaluator(
        environment.parameters,
    )
    inline_products = lower_records(
        static_evaluator,
        topology,
        assembly.records,
        inputs,
        type_bindings=type_bindings,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
    )
    declared_products = lower_product_selections(
        static_evaluator,
        topology,
        assembly.record_selections,
        verified_graph.product_ports,
        inputs,
        type_bindings=type_bindings,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
        non_instrument_product_ids=(
            frozenset(
                product_id
                for execution in verified_graph.semantic_graph.graph.domain_executions
                for _result_id, product_id in execution.results
            )
            | authored_measurement_transform_output_product_ids(
                verified_graph.semantic_graph
            )
        ),
    )
    compute_nodes, implementation_catalog = lower_semantic_compute_graph(
        verified_graph.semantic_graph,
        verified_graph.implementation_catalog,
        inputs,
        type_bindings=type_bindings,
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
    domain_executions, domain_product_producers = lower_semantic_domain_graph(
        verified_graph.semantic_graph,
        inputs,
        type_bindings=type_bindings,
        product_uses=product_uses,
    )
    program = CoreProgram(
        id=verified.experiment_id,
        kind=verified.kind,
        point_domain=point_domain,
        route_intents=tuple(route_intents),
        compute_nodes=compute_nodes,
        effects=(
            *state_specs(
                bindings,
                inputs=inputs,
                type_bindings=type_bindings,
            ),
            *(
                lower_state_region(
                    region,
                    verified_graph.semantic_graph,
                    resource_ports,
                    inputs,
                    type_bindings=type_bindings,
                )
                for region in verified_graph.semantic_graph.graph.row_regions
            ),
            *(
                lower_action_effect(
                    action,
                    verified_graph.semantic_graph,
                    resource_ports,
                    inputs,
                    type_bindings=type_bindings,
                )
                for action in verified_graph.semantic_graph.graph.actions
            ),
            *domain_executions,
        ),
        measurement_transforms=measurement_transforms.transforms,
        implementation_catalog=implementation_catalog,
        source_map=verified_graph.source_map,
        parameter_overlays=tuple(
            lower_parameter_overlay_intent(
                parameter_catalog,
                intent,
                inputs,
                type_bindings=type_bindings,
            )
            for intent in assembly.parameter_overlays
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
    return seal_typed_program(program, phase=ProblemPhase.PLANNING)


def _relation_type_bindings(
    assembly: SemanticExperimentIR,
    parameter_catalog: ParameterCatalog,
) -> RelationTypeBindings:
    """Project assembly contracts into the final plan-verification environment."""

    contracts = _assembly_parameter_contracts(assembly)
    return RelationTypeBindings(
        inputs={port.id: port.value_type for port in assembly.input_ports},
        parameters={
            contract.parameter_id: _catalog_parameter_type(
                parameter_catalog,
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
                result_type=_catalog_lookup_result_type(parameter_catalog, contract),
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
    parameter_catalog: ParameterCatalog,
    parameter_id: str,
    fallback: ValueType,
) -> ValueType:
    definition = parameter_catalog.get(parameter_id)
    return definition.value_type if definition is not None else fallback


def _catalog_lookup_result_type(
    parameter_catalog: ParameterCatalog,
    contract: ParameterLookupContract,
) -> Scalar:
    definition = parameter_catalog.get(contract.parameter_id)
    if definition is not None and isinstance(definition.value_type, Table):
        for column in definition.value_type.columns:
            if column.id == contract.column_id:
                return column.value_type
    return contract.value_type
