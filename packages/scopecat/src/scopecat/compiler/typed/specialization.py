"""Configuration specialization over the complete typed program surface."""

from __future__ import annotations

from dataclasses import replace

from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.specialization import (
    ParameterCellBinding,
    specialize_scalar_expression,
)
from scopecat.compiler.typed.parameter_overlays import (
    parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    BoundProgramFacts,
    LogicalResourceRequirement,
)
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ScalarExpr,
)
from scopecat.program.logical import LogicalInvocation
from scopecat.program.point_domain import (
    map_point_axis_centers,
)
from scopecat.program.value_graph import OperationId


def specialize_bound_facts(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
    *,
    parameters: ParameterRelationData,
) -> BoundProgramFacts:
    """Partially evaluate pure values across one bound fact set."""

    base_known = EvalContext(params=parameters)
    parameter_cells = parameter_cell_bindings(program.parameter_overlays)
    known = base_known
    return replace(
        program,
        point_domain=_specialize_point_domain(
            program.point_domain,
            known=base_known,
        ),
        resource_requirements=tuple(
            _specialize_resource_requirement(
                requirement,
                known=known,
                parameter_cells=parameter_cells,
            )
            for requirement in program.resource_requirements
        ),
        live_compute_ids=_live_compute_ids(logical, program),
        values={
            value_id: (
                _specialize_value_use(
                    value,
                    known=known,
                    parameter_cells=parameter_cells,
                )
                if isinstance(value, ScalarExpr)
                else value
            )
            for value_id, value in program.values.items()
        },
    )


def _specialize_point_domain(
    domain: PointDomain,
    *,
    known: EvalContext,
) -> PointDomain:
    """Materialize axis centers from base configuration before point overlays.

    Parameter overlays consume coordinates produced by the point domain. If an
    overlay's residual cell binding were fed back into an around-axis center,
    the centered scan would depend on its own point column instead of the
    accepted snapshot.
    """

    def specialize_center(
        center: ScalarExpr,
        _path: tuple[str | int, ...],
    ) -> ScalarExpr:
        return _specialize_scalar_value(
            center,
            known=known,
            parameter_cells=(),
        )

    return replace(
        domain,
        axes=map_point_axis_centers(domain.axes, specialize_center),
    )


def _live_compute_ids(
    logical: VerifiedLogicalProgram,
    program: BoundProgramFacts,
) -> frozenset[OperationId]:
    """Keep the dependency closure of compute results observed by effects."""

    demanded = {
        state.value_id
        for state in logical.program.bindings
        if isinstance(program.values[state.value_id], ComputeResultScalarExpr)
    }
    demanded.update(
        argument.value_id
        for effect in logical.program.effects
        if isinstance(effect, LogicalInvocation)
        for argument in effect.arguments
        if isinstance(program.values[argument.value_id], ComputeResultScalarExpr)
    )

    owners = {node.result_id: node for node in logical.program.compute_nodes}
    live_ids: set[OperationId] = set()
    pending = list(demanded)
    while pending:
        result_id = pending.pop()
        node = owners.get(result_id)
        if node is None or node.id in live_ids:
            continue
        live_ids.add(node.id)
        pending.extend(
            value.value_id
            for _name, value_id in node.inputs
            if isinstance(
                value := program.values[value_id],
                ComputeResultScalarExpr,
            )
        )
    return frozenset(live_ids)


def _specialize_scalar_value(
    value: ScalarExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ScalarExpr:
    return specialize_scalar_expression(
        value,
        known=known,
        parameter_cells=parameter_cells,
    )


def _specialize_resource_requirement(
    requirement: LogicalResourceRequirement,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> LogicalResourceRequirement:
    return replace(
        requirement,
        entity_uses=tuple(
            _specialize_scalar_value(
                use,
                known=known,
                parameter_cells=parameter_cells,
            )
            for use in requirement.entity_uses
        ),
    )


def _specialize_value_use(
    use: ScalarExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ScalarExpr:
    if isinstance(use, ComputeResultScalarExpr):
        return use
    return _specialize_scalar_value(
        use,
        known=known,
        parameter_cells=parameter_cells,
    )
