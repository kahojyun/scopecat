"""Verify logical scalar expressions and effect value references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import cast

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.frontend.value_binding import (
    bind_scalar_input_refs,
    bind_table_source,
)
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    ExpressionVerificationError,
    RowType,
    verify_scalar_expression,
)
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.problems import Problem, ProblemPhase, model_location
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.program.expression_analysis import expression_point_refs
from scopecat.program.expressions import ScalarExpr
from scopecat.program.logical import LogicalComputeNode, LogicalProgram, ValueDef
from scopecat.program.parameters import ParameterValueContract
from scopecat.program.point_domain import analyze_point_domain


def bind_value_definition_inputs(
    definition: ValueDef,
    inputs: Mapping[str, object],
) -> ValueDef:
    source = definition.source
    if isinstance(source, ScalarExpr):
        return replace(definition, source=bind_scalar_input_refs(source, inputs))
    return replace(definition, source=bind_table_source(source, inputs))


def verify_scalar_values(
    program: LogicalProgram,
    problems: list[Problem],
) -> Mapping[ValueId, ScalarExpr]:
    point_columns = analyze_point_domain(
        program.point_domain,
        layout=program.point_domain_layout,
    ).columns
    bindings = ExpressionTypeBindings(
        inputs={
            port.id: port.value_type
            for port in program.input_ports
            if isinstance(port.value_type, Scalar)
        },
        parameters={
            contract.parameter_id: contract.value_type
            for contract in program.parameter_contracts
            if isinstance(contract, ParameterValueContract)
            and isinstance(contract.value_type, Scalar)
        },
        point_row=RowType(point_columns) if point_columns else None,
    )
    verified: dict[ValueId, ScalarExpr] = {}
    for definition in sorted(
        program.value_defs,
        key=lambda item: item.id.qualified_name,
    ):
        source = definition.source
        if not isinstance(source, ScalarExpr):
            continue
        try:
            verified[definition.id] = verify_scalar_expression(
                source,
                bindings=bindings,
                expected_type=cast("Scalar", definition.value_type),
            )
        except ExpressionVerificationError as error:
            problems.append(
                compiler_problem(
                    f"expression_{error.code}",
                    error.reason,
                    model_location(
                        "logical_program",
                        "values",
                        definition.id.qualified_name,
                        *error.path,
                    ),
                    phase=ProblemPhase.AUTHORING,
                    details={
                        "relation_code": error.code,
                        "expression_path": list(error.path),
                    },
                )
            )
    return MappingProxyType(verified)


def verify_effect_value_references(
    program: LogicalProgram,
    definition_ids: set[ValueId],
    operation_results: Mapping[ValueId, LogicalComputeNode],
    problems: list[Problem],
) -> None:
    values = [
        (model_location("bindings", index, "value"), binding.value_id)
        for index, binding in enumerate(program.bindings)
    ]
    values.extend(
        (
            model_location("invocations", invocation_index, "arguments", argument.id),
            argument.value_id,
        )
        for invocation_index, invocation in enumerate(program.invocations)
        for argument in invocation.arguments
    )
    for location, value_id in values:
        operation = operation_results.get(value_id)
        if operation is None:
            if value_id not in definition_ids:
                problems.append(
                    compiler_problem(
                        "logical_effect_value_unknown",
                        "logical effect references unknown value "
                        f"{value_id.qualified_name!r}",
                        location,
                        phase=ProblemPhase.AUTHORING,
                    )
                )
            continue
        if not _is_payload_type(operation.result_type):
            problems.append(
                compiler_problem(
                    "compute_payload_unavailable",
                    "state compute output is not an available payload: "
                    f"{operation.result_id.qualified_name!r}",
                    location,
                    phase=ProblemPhase.AUTHORING,
                )
            )


def verify_value_record_references(
    program: LogicalProgram,
    definition_ids: set[ValueId],
    operation_results: Mapping[ValueId, LogicalComputeNode],
    problems: list[Problem],
) -> None:
    """Verify that every durable scalar selection closes over the value graph."""

    known_ids = definition_ids | set(operation_results)
    for index, record in enumerate(program.value_record_selections):
        if record.value_id in known_ids:
            continue
        problems.append(
            compiler_problem(
                "logical_value_record_unknown",
                "dataset record references unknown value "
                f"{record.value_id.qualified_name!r}",
                model_location("value_record_selections", index, "value_id"),
                phase=ProblemPhase.AUTHORING,
            )
        )


def verify_success_state_values(
    program: LogicalProgram,
    problems: list[Problem],
) -> None:
    success_state = program.success_state
    if success_state is None:
        return
    definitions = {definition.id: definition for definition in program.value_defs}
    operation_result_ids = {operation.result_id for operation in program.compute_nodes}
    for index, assignment in enumerate(success_state.assignments):
        location = model_location("success_state", index, "value")
        if assignment.value_id in operation_result_ids:
            problems.append(
                compiler_problem(
                    "experiment_success_state_requires_execution",
                    "experiment on_success state cannot depend on point-local "
                    "computation",
                    location,
                    phase=ProblemPhase.AUTHORING,
                )
            )
        definition = definitions.get(assignment.value_id)
        source = None if definition is None else definition.source
        if isinstance(source, ScalarExpr) and expression_point_refs(source):
            problems.append(
                compiler_problem(
                    "experiment_success_state_depends_on_point",
                    "experiment on_success state cannot depend on point coordinates",
                    location,
                    phase=ProblemPhase.AUTHORING,
                )
            )


def _is_payload_type(value_type: object) -> bool:
    return isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload)
