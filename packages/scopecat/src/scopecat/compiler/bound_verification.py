"""Verify invariants introduced while binding a logical program."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from scopecat.compiler.bound_facts import BoundProgramFacts
from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.compiler.point_domain import (
    PointDomainVerificationError,
    VerifiedPointDomain,
    verify_point_domain,
)
from scopecat.compiler.value_resolution import BoundValueResolver
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.measurements.records import (
    plan_records,
    validate_record_axes,
)
from scopecat.program.expressions import (
    ArrayExpr,
    ComputeResultArrayExpr,
    ComputeResultScalarExpr,
    ScalarExpr,
)
from scopecat.program.point_domain import iter_point_axis_linear


class ProgramRelationConsumerKind(StrEnum):
    """The executable role that owns one scalar expression."""

    POINT_AXIS_CENTER = "point_axis_center"
    RESOURCE_ENTITY = "resource_entity"
    COMPUTE_INPUT = "compute_input"
    DOMAIN_EXECUTION_INPUT = "domain_execution_input"
    DOMAIN_COMPILER_INPUT = "domain_compiler_input"
    STATE_VALUE = "state_value"
    INVOCATION_ARGUMENT = "invocation_argument"
    VALUE_RECORD = "value_record"


def _verify_bound_facts(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
    *,
    program_id: str,
) -> VerifiedPointDomain:
    """Build final proofs without rechecking facts owned by earlier stages."""

    problems: list[Problem] = list(_product_demand_problems(logical, program))
    try:
        point_domain = verify_point_domain(
            program.point_domain,
            program_id=program_id,
        )
    except PointDomainVerificationError as error:
        problems.extend(
            _problem(
                issue.code,
                issue.message,
                model_location("point_domain", *issue.path),
            )
            for issue in error.issues
        )
        point_domain = None

    if point_domain is not None:
        problems.extend(
            validate_record_axes(
                plan_records(
                    program.product_defs,
                    program.product_uses,
                    program.product_record_uses,
                ),
                phase=ProblemPhase.AUTHORING,
            )
        )

    if problems:
        raise CheckFailed(problems)
    if point_domain is None:
        raise AssertionError(
            "successful bound verification lost its point-domain proof"
        )
    return point_domain


def _product_demand_problems(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
) -> tuple[Problem, ...]:
    """Close ownership after record demand has introduced exact product uses."""

    owned_products = {
        result.product_id
        for acquisition in logical.program.acquisitions
        for result in acquisition.results
    }
    owned_products.update(
        product_id
        for execution in logical.program.domain_executions
        for _result_id, product_id in execution.results
    )
    owned_products.update(
        output.product_id
        for postprocessor in program.measurement_postprocessors
        for output in postprocessor.outputs
    )
    return tuple(
        _problem(
            "product_acquire_missing",
            f"product {product_id.qualified_name!r} is selected but has no "
            "acquisition, domain, or postprocessor owner",
            model_location("product_uses", product_id.qualified_name),
        )
        for product_id in sorted(
            {use.product_id for use in program.product_uses} - owned_products,
            key=lambda item: item.qualified_name,
        )
    )


@dataclass(frozen=True, slots=True)
class ProgramRelationConsumer:
    """One scalar expression paired with its semantic role and diagnostic path."""

    kind: ProgramRelationConsumerKind
    plan: ScalarExpr
    location: ModelLocation


def verify_bound_facts(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
    *,
    program_id: str,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> VerifiedPointDomain:
    """Verify one residual program and return its derived point-domain proof."""

    try:
        return _verify_bound_facts(logical, program, program_id=program_id)
    except CheckFailed as error:
        if phase is ProblemPhase.AUTHORING:
            raise
        raise CheckFailed(
            tuple(
                problem.model_copy(update={"phase": phase})
                for problem in error.problems
            )
        ) from error


def _consumer(
    kind: ProgramRelationConsumerKind,
    value: ScalarExpr,
    location: ModelLocation,
) -> ProgramRelationConsumer:
    return ProgramRelationConsumer(
        kind=kind,
        plan=value,
        location=location,
    )


def _point_axis_center_consumers(
    point_domain: VerifiedPointDomain,
) -> Iterator[ProgramRelationConsumer]:
    for path, source in iter_point_axis_linear(point_domain.axes):
        center = source.center
        yield _consumer(
            ProgramRelationConsumerKind.POINT_AXIS_CENTER,
            center,
            model_location("point_domain", *path, "source", "center"),
        )


def bound_relation_consumers(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
    point_domain: VerifiedPointDomain,
) -> Iterator[ProgramRelationConsumer]:
    """Iterate scalar expressions with paths only when diagnostics need them."""

    yield from _point_axis_center_consumers(point_domain)
    yield from _program_relation_consumers(logical, program)


def _program_relation_consumers(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
) -> Iterator[ProgramRelationConsumer]:
    """Index canonical expressions with their exact lowering bindings."""

    values = BoundValueResolver(logical, program)
    yield from _value_record_consumers(logical, program)

    for requirement_index, requirement in enumerate(program.resource_requirements):
        for expression_index, use in enumerate(requirement.entity_uses):
            yield _consumer(
                ProgramRelationConsumerKind.RESOURCE_ENTITY,
                use,
                model_location(
                    "resource_requirements",
                    requirement_index,
                    "entity_exprs",
                    expression_index,
                ),
            )

    for node in logical.program.compute_nodes:
        if node.id not in program.live_compute_ids:
            continue
        for input_name, value_id in node.inputs:
            input_value = values[value_id]
            if isinstance(
                input_value,
                ComputeResultScalarExpr | ComputeResultArrayExpr,
            ):
                continue
            if isinstance(input_value, ArrayExpr):
                continue
            if not isinstance(input_value, ScalarExpr):
                raise AssertionError("compute inputs must be scalar")
            yield _consumer(
                ProgramRelationConsumerKind.COMPUTE_INPUT,
                input_value,
                model_location(
                    "compute_nodes",
                    *node.id.scope,
                    node.id.local_id,
                    "inputs",
                    input_name,
                ),
            )

    for execution_index, execution in enumerate(logical.program.domain_executions):
        for input_name, value_id in execution.inputs:
            input_value = values[value_id]
            if isinstance(input_value, ComputeResultScalarExpr):
                continue
            if not isinstance(input_value, ScalarExpr):
                raise AssertionError("domain execution inputs must be scalar")
            yield _consumer(
                ProgramRelationConsumerKind.DOMAIN_EXECUTION_INPUT,
                input_value,
                model_location(
                    "domain_executions",
                    execution_index,
                    "inputs",
                    input_name,
                ),
            )
        for input_name, value_id in execution.compiler_inputs:
            input_value = values[value_id]
            if not isinstance(input_value, ScalarExpr) or isinstance(
                input_value, ComputeResultScalarExpr
            ):
                continue
            yield _consumer(
                ProgramRelationConsumerKind.DOMAIN_COMPILER_INPUT,
                input_value,
                model_location(
                    "domain_executions",
                    execution_index,
                    "compiler_inputs",
                    input_name,
                ),
            )

    for state_index, state in enumerate(logical.program.bindings):
        value = values[state.value_id]
        if isinstance(value, ScalarExpr) and not isinstance(
            value, ComputeResultScalarExpr
        ):
            yield _consumer(
                ProgramRelationConsumerKind.STATE_VALUE,
                value,
                model_location("state", state_index, "value"),
            )

    for invocation_index, invocation in enumerate(logical.program.invocations):
        for argument in invocation.arguments:
            value = values[argument.value_id]
            if not isinstance(value, ScalarExpr) or isinstance(
                value, ComputeResultScalarExpr
            ):
                continue
            yield _consumer(
                ProgramRelationConsumerKind.INVOCATION_ARGUMENT,
                value,
                model_location(
                    "invocations",
                    invocation_index,
                    "arguments",
                    argument.id,
                ),
            )


def _value_record_consumers(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
) -> Iterator[ProgramRelationConsumer]:
    values = BoundValueResolver(logical, program)
    for record_index, record in enumerate(program.value_record_uses):
        value = values[record.value_id]
        if isinstance(value, ComputeResultScalarExpr | ComputeResultArrayExpr):
            continue
        if isinstance(value, ArrayExpr):
            continue
        if not isinstance(value, ScalarExpr):
            raise AssertionError("value records must resolve to scalars")
        yield _consumer(
            ProgramRelationConsumerKind.VALUE_RECORD,
            value,
            model_location("value_record_uses", record_index, "value_id"),
        )


def _problem(code: str, message: str, location: ModelLocation) -> Problem:
    return compiler_problem(
        code,
        message,
        location,
        phase=ProblemPhase.AUTHORING,
    )


__all__ = [
    "ProgramRelationConsumer",
    "ProgramRelationConsumerKind",
    "verify_bound_facts",
]
