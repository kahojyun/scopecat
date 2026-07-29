"""Link one composed authoring assembly into a transient compiler program."""

from __future__ import annotations

from dataclasses import replace

from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    InvocationIntent,
)
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
    validate_entity_inputs,
)
from scopecat.compiler.frontend.binding_lowering import (
    build_resource_requirements,
    lower_invocation,
    lower_state_binding,
)
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.graph_validation import VerifiedAssembly
from scopecat.compiler.frontend.measurement_postprocessor_lowering import (
    lower_semantic_measurement_postprocessor_graph,
)
from scopecat.compiler.frontend.parameter_contract_validation import (
    validate_parameter_contracts,
)
from scopecat.compiler.frontend.problems import raise_frontend_problem
from scopecat.compiler.frontend.product_lowering import lower_products
from scopecat.compiler.frontend.static_evaluation import StaticRelationEvaluator
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.typed.program import CoreProgram
from scopecat.kernel.value_types import Scalar
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
        input_row=input_row,
    )
    compute_nodes = lower_semantic_compute_graph(
        verified_graph.semantic_graph,
        verified_graph.implementations,
        inputs,
        type_bindings=type_bindings,
    )
    record_product_uses = products.product_uses
    measurement_postprocessors = lower_semantic_measurement_postprocessor_graph(
        verified_graph.semantic_graph,
        record_product_uses,
    )
    product_uses = (
        *record_product_uses,
        *measurement_postprocessors.input_product_uses,
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
        lower_state_binding(
            effect,
            inputs=inputs,
            type_bindings=type_bindings,
        )
        if isinstance(effect, ExperimentBindingIntent)
        else lower_invocation(
            effect,
            inputs=inputs,
            type_bindings=type_bindings,
        )
        if isinstance(effect, InvocationIntent)
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
        measurement_postprocessors=measurement_postprocessors.postprocessors,
        parameter_overlays=tuple(
            lower_parameter_overlay_intent(
                parameter_catalog,
                static_evaluator,
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

    parameter_types: dict[str, Scalar] = {}
    for contract in assembly.parameter_contracts:
        if not isinstance(contract, ParameterValueContract):
            continue
        definition = parameter_catalog.get(contract.parameter_id)
        value_type = (
            definition.value_type if definition is not None else contract.value_type
        )
        if isinstance(value_type, Scalar):
            parameter_types[contract.parameter_id] = value_type
    return RelationTypeBindings(
        inputs={
            port.id: port.value_type
            for port in assembly.input_ports
            if isinstance(port.value_type, Scalar)
        },
        parameters=parameter_types,
    )
