"""Configuration specialization over the complete typed program surface."""

from __future__ import annotations

from dataclasses import replace

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.specialization import (
    KnownScalar,
    ParameterCellBinding,
    residual_scalar_expression,
    specialize_scalar,
)
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    verify_scalar_value_expr,
)
from scopecat.compiler.typed.invocation import InvokeEffect
from scopecat.compiler.typed.parameter_overlays import (
    parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    BoundEffect,
    BoundProgramFacts,
    ComputeEdge,
    ComputeInput,
    LogicalResourceRequirement,
    ScalarValueInput,
    TypedComputeNode,
    TypedDomainExecution,
    ValueInput,
)
from scopecat.compiler.typed.state import EnsureStateSpec, SetStateSpec
from scopecat.graph.relations.model import lit
from scopecat.graph.relations.point_domain import (
    map_point_axis_centers,
)
from scopecat.graph.values import ComputeResultRef, OperationId
from scopecat.program.logical import AcquireEffect


def specialize_bound_facts(
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
        compute_nodes=tuple(
            _specialize_compute(node, known=known, parameter_cells=parameter_cells)
            for node in _live_compute_nodes(program)
        ),
        effects=tuple(
            _specialize_effect(effect, known=known, parameter_cells=parameter_cells)
            for effect in program.effects
        ),
        final_state=(
            None
            if program.final_state is None
            else replace(
                program.final_state,
                assignments=tuple(
                    _specialize_state(
                        state,
                        known=known,
                        parameter_cells=parameter_cells,
                    )
                    for state in program.final_state.assignments
                ),
            )
        ),
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
        center: RelationUse[ScalarValueExpr],
        _path: tuple[str | int, ...],
    ) -> RelationUse[ScalarValueExpr]:
        value = _specialize_scalar_value(
            center.value,
            known=known,
            parameter_cells=(),
        )
        return RelationUse(value)

    return replace(
        domain,
        axes=map_point_axis_centers(domain.axes, specialize_center),
    )


def _live_compute_nodes(program: BoundProgramFacts) -> tuple[TypedComputeNode, ...]:
    """Keep the dependency closure of compute results observed by effects."""

    demanded = {
        state.value_use.value_id
        for effect in program.effects
        for state in (
            effect.assignments
            if isinstance(effect, EnsureStateSpec)
            else (effect,)
            if isinstance(effect, SetStateSpec)
            else ()
        )
        if isinstance(state.value_use, ComputeResultRef)
    }
    demanded.update(
        argument.value_use.value_id
        for effect in program.effects
        if isinstance(effect, InvokeEffect)
        for argument in effect.arguments
        if isinstance(argument.value_use, ComputeResultRef)
    )

    owners = {node.result.id: node for node in program.compute_nodes}
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
            for value in node.inputs.values()
            if isinstance(value, ComputeEdge)
        )
    return tuple(node for node in program.compute_nodes if node.id in live_ids)


def _specialize_scalar_input(
    value: ScalarValueInput,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ScalarValueInput:
    return replace(
        value,
        value=_specialize_scalar_value(
            value.value,
            known=known,
            parameter_cells=parameter_cells,
        ),
    )


def _specialize_scalar_value(
    value: ScalarValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ScalarValueExpr:
    result = specialize_scalar(
        value.plan.root,
        known=known,
        parameter_cells=parameter_cells,
    )
    return verify_scalar_value_expr(
        (
            lit(result.value)
            if isinstance(result, KnownScalar)
            else residual_scalar_expression(result)
        ),
        bindings=value.plan.bindings,
        expected_type=value.value_type,
    )


def _specialize_compute(
    node: TypedComputeNode,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> TypedComputeNode:
    inputs: dict[str, ComputeInput] = {}
    for name, value in node.inputs.items():
        inputs[name] = (
            _specialize_scalar_input(
                value,
                known=known,
                parameter_cells=parameter_cells,
            )
            if isinstance(value, ValueInput)
            else value
        )
    return replace(node, inputs=inputs)


def _specialize_effect(
    effect: BoundEffect,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> BoundEffect:
    if isinstance(effect, AcquireEffect):
        return effect
    if isinstance(effect, TypedDomainExecution):
        return replace(
            effect,
            inputs={
                name: _specialize_scalar_input(
                    value,
                    known=known,
                    parameter_cells=parameter_cells,
                )
                for name, value in effect.inputs.items()
            },
            compiler_inputs={
                name: (
                    ValueInput(
                        _specialize_scalar_value(
                            value.value,
                            known=known,
                            parameter_cells=parameter_cells,
                        )
                    )
                    if isinstance(value.value, ScalarValueExpr)
                    else value
                )
                for name, value in effect.compiler_inputs.items()
            },
        )
    if isinstance(effect, InvokeEffect):
        return replace(
            effect,
            arguments=tuple(
                replace(
                    argument,
                    value_use=_specialize_value_use(
                        argument.value_use,
                        known=known,
                        parameter_cells=parameter_cells,
                    ),
                )
                for argument in effect.arguments
            ),
        )
    if isinstance(effect, EnsureStateSpec):
        return replace(
            effect,
            assignments=tuple(
                _specialize_state(
                    state,
                    known=known,
                    parameter_cells=parameter_cells,
                )
                for state in effect.assignments
            ),
        )
    return _specialize_state(
        effect,
        known=known,
        parameter_cells=parameter_cells,
    )


def _specialize_state(
    state: SetStateSpec,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> SetStateSpec:
    return replace(
        state,
        value_use=_specialize_value_use(
            state.value_use,
            known=known,
            parameter_cells=parameter_cells,
        ),
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
            _specialize_scalar_use(
                use,
                known=known,
                parameter_cells=parameter_cells,
            )
            for use in requirement.entity_uses
        ),
    )


def _specialize_value_use(
    use: RelationUse[ScalarValueExpr] | ComputeResultRef,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> RelationUse[ScalarValueExpr] | ComputeResultRef:
    if isinstance(use, ComputeResultRef):
        return use
    return _specialize_scalar_use(
        use,
        known=known,
        parameter_cells=parameter_cells,
    )


def _specialize_scalar_use(
    use: RelationUse[ScalarValueExpr],
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> RelationUse[ScalarValueExpr]:
    value = _specialize_scalar_value(
        use.value,
        known=known,
        parameter_cells=parameter_cells,
    )
    return replace(use, value=value)
