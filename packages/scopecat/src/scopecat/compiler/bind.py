"""Bind one verified logical program to an accepted configuration."""

from __future__ import annotations

from dataclasses import dataclass, replace

from scopecat.compiler.diagnostics import compiler_problem
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
    lower_ensure_state,
    lower_invocation,
    lower_state_binding,
)
from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.compiler.frontend.measurement_postprocessor_lowering import (
    lower_semantic_measurement_postprocessor_graph,
)
from scopecat.compiler.frontend.parameter_contract_validation import (
    validate_parameter_contracts,
)
from scopecat.compiler.frontend.problems import raise_frontend_problem
from scopecat.compiler.frontend.product_lowering import lower_products
from scopecat.compiler.frontend.static_evaluation import StaticRelationEvaluator
from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.relations.evaluation import (
    normalize_relation_parameter_import,
)
from scopecat.compiler.relations.verification import (
    PlanImportNamespace,
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import VerifiedPointDomain
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.specialization import specialize_core_program
from scopecat.compiler.typed.verification import (
    ProgramRelationConsumer,
    VerifiedCoreProgram,
    program_relation_consumers,
    seal_typed_program,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem, ProblemPhase, model_location
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.program.bindings import (
    EnsureStateIntent,
    ExperimentBindingIntent,
    InvocationIntent,
)
from scopecat.program.logical import AcquireEffect, LogicalProgram
from scopecat.program.parameters import (
    ParameterValueContract,
)
from scopecat.records.parameter import ParameterCatalog


@dataclass(frozen=True, slots=True)
class BoundPlan:
    """One symbolic program bound to its sole accepted configuration.

    ``VerifiedCoreProgram`` is a private transitional residual while logical
    expressions and effects move into the shared program model. Physical
    points and targets remain planning concerns.
    """

    _verified_program: VerifiedCoreProgram
    environment: ConfigEnvironment

    @property
    def program(self) -> CoreProgram:
        """Return the specialized residual program."""

        return self._verified_program.program

    @property
    def point_domain(self) -> VerifiedPointDomain:
        return self._verified_program.point_domain


def bind_program(
    program: VerifiedLogicalProgram,
    environment: ConfigEnvironment,
) -> BoundPlan:
    """Lower, specialize, verify, and bind one logical program exactly once."""

    try:
        lowered = _lower_logical_program(
            program,
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
    return _bind_core_program(
        lowered,
        environment,
    )


def _lower_logical_program(
    verified: VerifiedLogicalProgram,
    environment: ConfigEnvironment,
) -> CoreProgram:
    assembly = verified.program
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
        verified.product_declarations,
        inputs,
        type_bindings=type_bindings,
        input_row=input_row,
    )
    compute_nodes = lower_semantic_compute_graph(
        verified,
        inputs,
        type_bindings=type_bindings,
    )
    record_product_uses = products.product_uses
    measurement_postprocessors = lower_semantic_measurement_postprocessor_graph(
        verified,
        record_product_uses,
    )
    product_uses = (
        *record_product_uses,
        *measurement_postprocessors.input_product_uses,
    )
    domain_executions = lower_semantic_domain_graph(
        verified,
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
        else lower_ensure_state(
            effect,
            inputs=inputs,
            type_bindings=type_bindings,
        )
        if isinstance(effect, EnsureStateIntent)
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
    final_state = (
        None
        if assembly.final_state is None
        else lower_ensure_state(
            assembly.final_state,
            inputs=inputs,
            type_bindings=type_bindings,
        )
    )
    return CoreProgram(
        id=verified.experiment_id,
        kind=verified.kind,
        point_domain=point_domain,
        resource_requirements=tuple(resource_requirements),
        compute_nodes=compute_nodes,
        effects=ordered_effects,
        final_state=final_state,
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
    assembly: LogicalProgram,
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


def _bind_core_program(
    program: CoreProgram,
    environment: ConfigEnvironment,
) -> BoundPlan:
    """Specialize and seal the transitional residual compiler program."""

    verified_program = seal_typed_program(
        specialize_core_program(
            program,
            parameters=environment.parameters,
        ),
        phase=ProblemPhase.PLANNING,
    )
    problems = list(
        _relation_import_problems(
            verified_program,
            environment.parameters,
        )
    )
    if problems:
        raise CheckFailed(problems)
    return BoundPlan(
        verified_program,
        environment,
    )


def _relation_import_problems(
    verified_program: VerifiedCoreProgram,
    parameters: ParameterRelationData,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for consumer in program_relation_consumers(verified_program):
        plan = consumer.plan
        for imported in plan.imports:
            if imported.namespace is PlanImportNamespace.INPUT:
                problems.append(_unresolved_input_problem(consumer, imported.id))
                continue
            try:
                normalize_relation_parameter_import(
                    plan,
                    imported,
                    parameters,
                )
            except ValueValidationError as error:
                problems.append(_parameter_import_problem(consumer, error))
    return tuple(problems)


def _unresolved_input_problem(
    consumer: ProgramRelationConsumer,
    input_id: str,
) -> Problem:
    return compiler_problem(
        "bound_input_unresolved",
        f"bound relation still depends on unresolved input {input_id!r}",
        model_location(
            consumer.location.root,
            *consumer.location.path,
            "inputs",
            input_id,
        ),
        phase=ProblemPhase.PLANNING,
        details={
            "consumer_kind": consumer.kind.value,
            "input_id": input_id,
        },
    )


def _parameter_import_problem(
    consumer: ProgramRelationConsumer,
    error: ValueValidationError,
) -> Problem:
    missing = error.code == "unknown_parameter"
    parameter_id = (
        error.path[1]
        if len(error.path) > 1 and isinstance(error.path[1], str)
        else None
    )
    return compiler_problem(
        "bound_parameter_missing" if missing else "bound_parameter_contract_mismatch",
        (
            "accepted configuration cannot satisfy relation "
            f"parameter import: {error.reason}"
        ),
        model_location(
            consumer.location.root,
            *consumer.location.path,
            *error.path,
        ),
        phase=ProblemPhase.PLANNING,
        details={
            "consumer_kind": consumer.kind.value,
            **({"parameter_id": parameter_id} if parameter_id is not None else {}),
            "value_path": list(error.path),
        },
    )
