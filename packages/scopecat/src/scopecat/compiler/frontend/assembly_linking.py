"""Link one composed authoring assembly into a transient compiler program."""

from __future__ import annotations

from dataclasses import replace

from scopecat.authoring._binding_intents import ExperimentBindingIntent
from scopecat.authoring._parameter_contracts import (
    ParameterValueContract,
)
from scopecat.compiler.environment import ConfigEnvironment
from scopecat.compiler.frontend.assembly_lowering import (
    input_row,
    lower_parameter_overlay_intent,
    lower_point_domain,
    lower_semantic_compute_graph,
    lower_semantic_domain_graph,
    state_spec,
    validate_entity_inputs,
)
from scopecat.compiler.frontend.binding_lowering import (
    build_resource_requirements,
    lower_binding_intent,
)
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.graph_validation import VerifiedAssembly
from scopecat.compiler.frontend.measurement_transform_lowering import (
    lower_semantic_measurement_transform_graph,
)
from scopecat.compiler.frontend.parameter_contract_validation import (
    validate_parameter_contracts,
)
from scopecat.compiler.frontend.problems import raise_frontend_problem
from scopecat.compiler.frontend.product_lowering import lower_products
from scopecat.compiler.frontend.static_evaluation import StaticRelationEvaluator
from scopecat.compiler.frontend.value_binding import (
    bind_relation_input_refs,
    bind_series_input_refs,
)
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.typed.program import CoreProgram
from scopecat.kernel.value_types import ValueType
from scopecat.records.parameter import ParameterCatalog


def bind_verified_assembly(
    verified: VerifiedAssembly,
    environment: ConfigEnvironment,
) -> CoreProgram:
    """Bind a config-free assembly proof into one config-dependent program."""

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
    environment: ConfigEnvironment,
) -> CoreProgram:
    assembly = verified.source
    verified_graph = verified.graph
    config = environment.config
    parameter_catalog = config.parameter_catalog
    topology = config.topology
    inputs = assembly.inputs
    validate_parameter_contracts(
        parameter_catalog,
        assembly.parameter_contracts,
    )
    validate_entity_inputs(topology, assembly.entity_inputs, inputs)
    root_type_bindings = _relation_type_bindings(assembly, parameter_catalog)
    point_domain = lower_point_domain(
        assembly.point_domain,
        inputs=inputs,
        type_bindings=root_type_bindings,
    )
    type_bindings = replace(
        root_type_bindings,
        point_row=RowType.from_table(point_domain.value_type),
    )
    resource_requirements = build_resource_requirements(
        topology,
        assembly.resource_ports,
        inputs=inputs,
        type_bindings=type_bindings,
    )
    static_evaluator = StaticRelationEvaluator(
        environment.parameters,
    )
    products = lower_products(
        static_evaluator,
        topology,
        assembly.record_selections,
        verified_graph.product_declarations,
        inputs,
        type_bindings=type_bindings,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
    )
    compute_nodes = lower_semantic_compute_graph(
        verified_graph.semantic_graph,
        verified_graph.implementations,
        inputs,
        type_bindings=type_bindings,
    )
    record_product_uses = products.product_uses
    measurement_transforms = lower_semantic_measurement_transform_graph(
        verified_graph.semantic_graph,
        record_product_uses,
    )
    product_uses = (
        *record_product_uses,
        *measurement_transforms.input_product_uses,
    )
    domain_executions = lower_semantic_domain_graph(
        verified_graph.semantic_graph,
        assembly.domain_executions,
        inputs,
        type_bindings=type_bindings,
        product_uses=product_uses,
    )
    domain_effects = {execution.id: execution for execution in domain_executions}
    ordered_effects = tuple(
        state_spec(
            lower_binding_intent(effect),
            inputs=inputs,
            type_bindings=type_bindings,
        )
        if isinstance(effect, ExperimentBindingIntent)
        else effect
        if isinstance(effect, AcquireEffect)
        else domain_effects[effect.id]
        for effect in assembly.effects
    )
    return CoreProgram(
        id=verified.experiment_id,
        kind=verified.kind,
        point_domain=point_domain,
        resource_requirements=tuple(resource_requirements),
        compute_nodes=compute_nodes,
        effects=ordered_effects,
        measurement_transforms=measurement_transforms.transforms,
        parameter_overlays=tuple(
            lower_parameter_overlay_intent(
                parameter_catalog,
                intent,
                inputs,
                type_bindings=type_bindings,
            )
            for intent in assembly.parameter_overlays
        ),
        product_defs=products.product_defs,
        product_uses=product_uses,
        record_uses=products.record_uses,
    )


def _relation_type_bindings(
    assembly: SemanticExperimentIR,
    parameter_catalog: ParameterCatalog,
) -> RelationTypeBindings:
    """Project assembly contracts into the final plan-verification environment."""

    contracts = assembly.parameter_contracts
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
    )


def _catalog_parameter_type(
    parameter_catalog: ParameterCatalog,
    parameter_id: str,
    fallback: ValueType,
) -> ValueType:
    definition = parameter_catalog.get(parameter_id)
    return definition.value_type if definition is not None else fallback
