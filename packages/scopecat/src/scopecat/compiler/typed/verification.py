"""Verify invariants introduced while lowering a logical program."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import (
    PointDomainVerificationError,
    VerifiedPointDomain,
    verify_point_domain,
)
from scopecat.compiler.typed.program import (
    BoundProgramFacts,
    ComputeEdge,
    bound_acquisitions,
    bound_domain_executions,
    bound_invocations,
    bound_state,
)
from scopecat.compiler.typed.relation_consumers import ProgramRelationConsumerKind
from scopecat.graph.relations.point_domain import iter_point_axis_linear
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.measurements.records import plan_records, validate_record_axes


def _verify_bound_facts(
    program: BoundProgramFacts,
    *,
    program_id: str,
) -> VerifiedPointDomain:
    """Build final proofs without rechecking facts owned by earlier stages."""

    problems: list[Problem] = list(_product_demand_problems(program))
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
                    program.record_uses,
                ),
                phase=ProblemPhase.AUTHORING,
            )
        )

    if problems:
        raise CheckFailed(problems)
    if point_domain is None:
        raise AssertionError("successful typed sealing lost its point-domain proof")
    return point_domain


def _product_demand_problems(program: BoundProgramFacts) -> tuple[Problem, ...]:
    """Close ownership after record demand has introduced exact product uses."""

    owned_products = {
        result.product_id
        for acquisition in bound_acquisitions(program)
        for result in acquisition.results
    }
    owned_products.update(
        result.product_id
        for execution in bound_domain_executions(program)
        for result in execution.results
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
    """One scalar plan paired with its semantic role and diagnostic path."""

    kind: ProgramRelationConsumerKind
    plan: VerifiedRelationPlan
    location: ModelLocation


def verify_bound_facts(
    program: BoundProgramFacts,
    *,
    program_id: str,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> VerifiedPointDomain:
    """Verify one residual program and return its derived point-domain proof."""

    try:
        return _verify_bound_facts(program, program_id=program_id)
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
    value: ScalarValueExpr,
    location: ModelLocation,
) -> ProgramRelationConsumer:
    return ProgramRelationConsumer(
        kind=kind,
        plan=value.plan,
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
    program: BoundProgramFacts,
    point_domain: VerifiedPointDomain,
) -> Iterator[ProgramRelationConsumer]:
    """Iterate relation plans with paths only when diagnostics need them."""

    yield from _point_axis_center_consumers(point_domain)
    yield from _program_relation_consumers(program)


def _program_relation_consumers(
    program: BoundProgramFacts,
) -> Iterator[ProgramRelationConsumer]:
    """Index relation proofs already built with their exact lowering bindings."""

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

    for node in program.compute_nodes:
        for input_name, input_value in node.inputs.items():
            if isinstance(input_value, ComputeEdge):
                continue
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

    for execution_index, execution in enumerate(bound_domain_executions(program)):
        for input_name, input_value in execution.inputs.items():
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
        for input_name, input_value in execution.compiler_inputs.items():
            if not isinstance(input_value, ScalarValueExpr):
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

    for state_index, state in enumerate(bound_state(program)):
        if not isinstance(state.value_use, ComputeResultRef):
            yield _consumer(
                ProgramRelationConsumerKind.STATE_VALUE,
                state.value_use,
                model_location("state", state_index, "value"),
            )

    for invocation_index, invocation in enumerate(bound_invocations(program)):
        for argument in invocation.arguments:
            if isinstance(argument.value_use, ComputeResultRef):
                continue
            yield _consumer(
                ProgramRelationConsumerKind.INVOCATION_ARGUMENT,
                argument.value_use,
                model_location(
                    "invocations",
                    invocation_index,
                    "arguments",
                    argument.id,
                ),
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
