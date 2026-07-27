"""Seal the invariants introduced while lowering a verified assembly."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.point_domain import (
    PointDomainVerificationError,
    VerifiedPointDomain,
    verify_point_domain,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    ValueInput,
    core_acquisitions,
    core_domain_executions,
    core_state,
)
from scopecat.compiler.typed.relation_consumers import ProgramRelationConsumerKind
from scopecat.graph.relations.analysis import PlanNode
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


def _seal_core_program(
    program: CoreProgram,
) -> VerifiedPointDomain:
    """Build final proofs without rechecking facts owned by earlier stages."""

    problems: list[Problem] = list(_product_demand_problems(program))
    try:
        point_domain = verify_point_domain(
            program.point_domain,
            program_id=program.id,
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
                    point_count=1,
                ),
                phase=ProblemPhase.AUTHORING,
            )
        )

    if problems:
        raise CheckFailed(problems)
    if point_domain is None:
        raise AssertionError("successful typed sealing lost its point-domain proof")
    return point_domain


def _product_demand_problems(program: CoreProgram) -> tuple[Problem, ...]:
    """Close ownership after record demand has introduced exact product uses."""

    owned_products = {
        product.product_id
        for acquisition in core_acquisitions(program)
        for product in acquisition.products
    }
    owned_products.update(
        result.product_id
        for execution in core_domain_executions(program)
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
    """One relation plan paired with its semantic role and diagnostic path."""

    kind: ProgramRelationConsumerKind
    plan: VerifiedRelationPlan[PlanNode]
    location: ModelLocation


@dataclass(frozen=True, slots=True)
class VerifiedCoreProgram:
    """A trusted lowered program paired with its final derived proofs."""

    program: CoreProgram
    point_domain: VerifiedPointDomain = dc_field(init=False)

    def __post_init__(self) -> None:
        point_domain = _seal_core_program(self.program)
        object.__setattr__(self, "point_domain", point_domain)


def seal_typed_program(
    program: CoreProgram,
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> VerifiedCoreProgram:
    """Seal lowering-owned facts on one trusted transient program."""

    try:
        return VerifiedCoreProgram(program)
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
    value: ValueExpr,
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
            center.value,
            model_location("point_domain", *path, "source", "center"),
        )


def program_relation_consumers(
    verified: VerifiedCoreProgram,
) -> Iterator[ProgramRelationConsumer]:
    """Iterate relation plans with paths only when diagnostics need them."""

    yield from _point_axis_center_consumers(verified.point_domain)
    yield from _program_relation_consumers(verified.program)


def _program_relation_consumers(
    program: CoreProgram,
) -> Iterator[ProgramRelationConsumer]:
    """Index relation proofs already built with their exact lowering bindings."""

    for requirement_index, requirement in enumerate(program.resource_requirements):
        for expression_index, use in enumerate(requirement.entity_uses):
            yield _consumer(
                ProgramRelationConsumerKind.RESOURCE_ENTITY,
                use.value,
                model_location(
                    "resource_requirements",
                    requirement_index,
                    "entity_exprs",
                    expression_index,
                ),
            )

    for node in program.compute_nodes:
        for input_name, input_value in node.inputs.items():
            if not isinstance(input_value, ValueInput):
                continue
            yield _consumer(
                ProgramRelationConsumerKind.COMPUTE_INPUT,
                input_value.value,
                model_location(
                    "compute_nodes",
                    *node.id.scope,
                    node.id.local_id,
                    "inputs",
                    input_name,
                ),
            )

    for execution_index, execution in enumerate(core_domain_executions(program)):
        for input_name, input_value in execution.inputs.items():
            yield _consumer(
                ProgramRelationConsumerKind.DOMAIN_EXECUTION_INPUT,
                input_value.value,
                model_location(
                    "domain_executions",
                    execution_index,
                    "inputs",
                    input_name,
                ),
            )
        for input_name, input_value in execution.compiler_inputs.items():
            yield _consumer(
                ProgramRelationConsumerKind.DOMAIN_COMPILER_INPUT,
                input_value.value,
                model_location(
                    "domain_executions",
                    execution_index,
                    "compiler_inputs",
                    input_name,
                ),
            )

    for state_index, state in enumerate(core_state(program)):
        if not isinstance(state.value_use, ComputeResultRef):
            yield _consumer(
                ProgramRelationConsumerKind.STATE_VALUE,
                state.value_use.value,
                model_location("state", state_index, "value"),
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
    "VerifiedCoreProgram",
    "seal_typed_program",
]
