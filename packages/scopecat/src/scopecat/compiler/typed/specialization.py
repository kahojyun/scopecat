"""Configuration specialization over the complete typed program surface."""

from __future__ import annotations

from dataclasses import replace
from typing import overload

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.specialization import (
    KnownScalar,
    ParameterCellBinding,
    residual_scalar_expression,
    specialize_relation,
    specialize_scalar,
)
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    TableValueExpr,
    ValueExpr,
    verify_scalar_value_expr,
    verify_table_value_expr,
)
from scopecat.compiler.typed.parameter_overlays import (
    PointParameterOverlay,
    resolve_parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    ComputeEdge,
    ComputeInput,
    CoreEffect,
    CoreProgram,
    LogicalResourceRequirement,
    TypedComputeNode,
    TypedDomainExecution,
    ValueInput,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.graph.relations.model import lit
from scopecat.graph.relations.point_domain import (
    map_point_axis_centers,
)
from scopecat.graph.values import ComputeResultRef, OperationId


def specialize_core_program(
    program: CoreProgram,
    *,
    parameters: ParameterRelationData,
) -> CoreProgram:
    """Partially evaluate pure values across one CoreProgram."""

    base_known = EvalContext(params=parameters)
    parameter_cells = resolve_parameter_cell_bindings(
        program.parameter_overlays,
        known=base_known,
    )
    # Any overlay makes the whole table point-local, including dynamic keys
    # that cannot produce a static ParameterCellBinding.
    known = EvalContext(
        params=parameters.without_tables(
            {overlay.table_id for overlay in program.parameter_overlays}
        )
    )
    return replace(
        program,
        point_domain=_specialize_point_domain(
            program.point_domain,
            known=base_known,
        ),
        parameter_overlays=tuple(
            _specialize_parameter_overlay(
                overlay,
                known=known,
                parameter_cells=parameter_cells,
            )
            for overlay in program.parameter_overlays
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
    )


def _specialize_parameter_overlay(
    overlay: PointParameterOverlay,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> PointParameterOverlay:
    return replace(
        overlay,
        key_uses={
            column_id: _specialize_relation_use(
                use,
                known=known,
                parameter_cells=parameter_cells,
            )
            for column_id, use in overlay.key_uses.items()
        },
        value_use=_specialize_relation_use(
            overlay.value_use,
            known=known,
            parameter_cells=parameter_cells,
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
        value = specialize_value_expression(
            center.value,
            known=known,
            parameter_cells=(),
        )
        return RelationUse(value)

    return replace(
        domain,
        root=map_point_axis_centers(domain.root, specialize_center),
    )


def _live_compute_nodes(program: CoreProgram) -> tuple[TypedComputeNode, ...]:
    """Keep the dependency closure of compute results observed by effects."""

    demanded = {
        effect.value_use.value_id
        for effect in program.effects
        if isinstance(effect, SetStateSpec)
        and isinstance(effect.value_use, ComputeResultRef)
    }

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


def specialize_value_input(
    value: ValueInput,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ValueInput:
    expression = specialize_value_expression(
        value.value,
        known=known,
        parameter_cells=parameter_cells,
    )
    return replace(value, value=expression)


@overload
def specialize_value_expression(
    value: ScalarValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ScalarValueExpr: ...


@overload
def specialize_value_expression(
    value: TableValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> TableValueExpr: ...


@overload
def specialize_value_expression(
    value: ValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ValueExpr: ...


def specialize_value_expression(
    value: ValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ValueExpr:
    """Specialize one typed value."""

    if isinstance(value, ScalarValueExpr):
        result = specialize_scalar(
            value.plan.root,
            known=known,
            parameter_cells=parameter_cells,
        )
        expression = verify_scalar_value_expr(
            (
                lit(result.value)
                if isinstance(result, KnownScalar)
                else residual_scalar_expression(result)
            ),
            bindings=value.plan.bindings,
            expected_type=value.value_type,
        )
        return expression
    residual = specialize_relation(
        value.plan.root,
        known=known,
        parameter_cells=parameter_cells,
    )
    expression = verify_table_value_expr(
        residual,
        bindings=value.plan.bindings,
        expected_type=value.value_type,
    )
    return expression


def _specialize_compute(
    node: TypedComputeNode,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> TypedComputeNode:
    inputs: dict[str, ComputeInput] = {}
    for name, value in node.inputs.items():
        inputs[name] = (
            specialize_value_input(
                value,
                known=known,
                parameter_cells=parameter_cells,
            )
            if isinstance(value, ValueInput)
            else value
        )
    return replace(node, inputs=inputs)


def _specialize_effect(
    effect: CoreEffect,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> CoreEffect:
    if isinstance(effect, AcquireEffect):
        return effect
    if isinstance(effect, TypedDomainExecution):
        return replace(
            effect,
            inputs={
                name: specialize_value_input(
                    value,
                    known=known,
                    parameter_cells=parameter_cells,
                )
                for name, value in effect.inputs.items()
            },
            compiler_inputs={
                name: specialize_value_input(
                    value,
                    known=known,
                    parameter_cells=parameter_cells,
                )
                for name, value in effect.compiler_inputs.items()
            },
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
        target_entity_uses=tuple(
            _specialize_relation_use(
                use,
                known=known,
                parameter_cells=parameter_cells,
            )
            for use in state.target_entity_uses
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
            _specialize_relation_use(
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
    return _specialize_relation_use(
        use,
        known=known,
        parameter_cells=parameter_cells,
    )


def _specialize_relation_use[ValueT: ValueExpr](
    use: RelationUse[ValueT],
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> RelationUse[ValueT]:
    value = specialize_value_expression(
        use.value,
        known=known,
        parameter_cells=parameter_cells,
    )
    return replace(use, value=value)
