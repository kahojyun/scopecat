"""Configuration specialization over the complete typed program surface."""

from __future__ import annotations

from dataclasses import replace
from typing import overload

from scopecat.compiler.relations.analysis import PlanReferenceKind
from scopecat.compiler.relations.evaluation import EvalContext, ParameterRelationData
from scopecat.compiler.relations.model import (
    LiteralRowsRelationExpr,
    ValuesSeriesExpr,
    lit,
    literal_rows,
)
from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointDomainExpr,
    PointProduct,
    PointRelationRows,
    PointUnit,
    PointZip,
    iter_point_relation_rows,
    point_dependent_product,
    point_product,
    point_zip,
)
from scopecat.compiler.relations.specialization import (
    BindingTime,
    KnownScalar,
    ParameterCellBinding,
    residual_scalar_expression,
    specialize_relation,
    specialize_scalar,
    specialize_series,
)
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import OperationId
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
    ValueExpr,
    verify_scalar_value_expr,
    verify_series_value_expr,
    verify_table_value_expr,
)
from scopecat.compiler.typed.action import ActionFieldSpec, ActionSpec
from scopecat.compiler.typed.parameter_overlays import (
    PointParameterOverlay,
    resolve_parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    AcquireSpec,
    ComputeEdge,
    ComputeInput,
    CoreEffect,
    CoreProgram,
    LogicalResourceRequirement,
    TypedComputeNode,
    TypedDomainExecution,
    ValueInput,
)
from scopecat.compiler.typed.state import (
    ForEachStateSpec,
    SetStateSpec,
    StateSpecVariant,
)


def specialize_core_program(
    program: CoreProgram,
    *,
    parameters: ParameterRelationData,
) -> CoreProgram:
    """Partially evaluate pure values across one CoreProgram."""

    known = EvalContext(params=parameters)
    parameter_cells = resolve_parameter_cell_bindings(
        program.parameter_overlays,
        known=known,
    )
    return replace(
        program,
        point_domain=_specialize_point_domain(
            program.point_domain,
            known=known,
            parameter_cells=parameter_cells,
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
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> PointDomain:
    def visit(
        node: PointDomainExpr[TableValueExpr],
    ) -> PointDomainExpr[TableValueExpr]:
        if isinstance(node, PointUnit):
            return POINT_UNIT
        if isinstance(node, PointRelationRows):
            value, _binding_time = specialize_value_expression(
                node.rows,
                known=known,
                parameter_cells=parameter_cells,
            )
            if (
                isinstance(value.plan.root, LiteralRowsRelationExpr)
                and value.plan.root.rows == [{}]
                and not value.value_type.columns
            ):
                return POINT_UNIT
            return PointRelationRows(value, relation_use_id=node.relation_use_id)
        if isinstance(node, PointProduct):
            return point_product(*(visit(factor) for factor in node.factors))
        if isinstance(node, PointZip):
            return point_zip(*(visit(source) for source in node.sources))
        left = visit(node.left)
        right = visit(node.right)
        return (
            point_product(left, right)
            if _is_point_independent(right)
            else point_dependent_product(left, right)
        )

    specialized = replace(domain, root=visit(domain.root))
    if specialized.value_type.max_rows != 0:
        return specialized
    empty_type = replace(specialized.value_type, min_rows=0, max_rows=0)
    empty = verify_table_value_expr(
        literal_rows([]),
        bindings=RelationTypeBindings(),
        expected_type=empty_type,
    )
    return replace(domain, root=PointRelationRows(empty))


def _is_point_independent(root: PointDomainExpr[TableValueExpr]) -> bool:
    return all(
        leaf.rows.plan.external_row_interface.point is None
        for _path, leaf in iter_point_relation_rows(root)
    )


def _live_compute_nodes(program: CoreProgram) -> tuple[TypedComputeNode, ...]:
    """Keep the dependency closure of compute results observed by effects."""

    demanded = {
        field.value_use.value_id
        for effect in program.effects
        if isinstance(effect, ActionSpec)
        for field in effect.fields
        if isinstance(field.value_use, ComputeResultRef)
    }

    def demand_state(state: StateSpecVariant) -> None:
        if isinstance(state, ForEachStateSpec):
            for child in state.state:
                demand_state(child)
        elif isinstance(state.value_use, ComputeResultRef):
            demanded.add(state.value_use.value_id)

    for effect in program.effects:
        if isinstance(effect, ForEachStateSpec | SetStateSpec):
            demand_state(effect)

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
    expression, _binding_time = specialize_value_expression(
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
) -> tuple[ScalarValueExpr, BindingTime]: ...


@overload
def specialize_value_expression(
    value: SeriesValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> tuple[SeriesValueExpr, BindingTime]: ...


@overload
def specialize_value_expression(
    value: TableValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> tuple[TableValueExpr, BindingTime]: ...


@overload
def specialize_value_expression(
    value: ValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> tuple[ValueExpr, BindingTime]: ...


def specialize_value_expression(
    value: ValueExpr,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> tuple[ValueExpr, BindingTime]:
    """Specialize one typed value while retaining its latest binding time."""

    original_binding_time = value_binding_time(value)
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
        return (
            expression,
            original_binding_time
            if isinstance(result, KnownScalar)
            else result.binding_time,
        )
    if isinstance(value, SeriesValueExpr):
        residual = specialize_series(
            value.plan.root,
            known=known,
            parameter_cells=parameter_cells,
        )
        expression = verify_series_value_expr(
            residual,
            bindings=value.plan.bindings,
            expected_type=(
                replace(
                    value.value_type,
                    min_length=len(residual.items),
                    max_length=len(residual.items),
                )
                if isinstance(residual, ValuesSeriesExpr)
                else value.value_type
            ),
        )
        return (
            expression,
            original_binding_time
            if isinstance(residual, ValuesSeriesExpr)
            else value_binding_time(expression),
        )
    residual = specialize_relation(
        value.plan.root,
        known=known,
        parameter_cells=parameter_cells,
    )
    expression = verify_table_value_expr(
        residual,
        bindings=value.plan.bindings,
        expected_type=(
            replace(
                value.value_type,
                min_rows=len(residual.rows),
                max_rows=len(residual.rows),
            )
            if isinstance(residual, LiteralRowsRelationExpr)
            else value.value_type
        ),
    )
    return (
        expression,
        original_binding_time
        if isinstance(residual, LiteralRowsRelationExpr)
        else value_binding_time(expression),
    )


def value_binding_time(value: ValueExpr) -> BindingTime:
    external_row_kinds = {
        reference.kind for reference in value.plan.free_row_references.references
    }
    if external_row_kinds & {
        PlanReferenceKind.CURRENT_COLUMN,
        PlanReferenceKind.OUTER_COLUMN,
        PlanReferenceKind.POINT_COLUMN,
    }:
        return BindingTime.POINT
    kinds = {reference.kind for reference in value.plan.references.references}
    if kinds & {
        PlanReferenceKind.PARAMETER_SCALAR,
        PlanReferenceKind.PARAMETER_SERIES,
        PlanReferenceKind.PARAMETER_TABLE,
    }:
        return BindingTime.CONFIGURATION_STATIC
    return BindingTime.REQUEST_STATIC


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
    if isinstance(effect, AcquireSpec):
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
        )
    if isinstance(effect, ActionSpec):
        return replace(
            effect,
            fields=tuple(
                _specialize_action_field(
                    field,
                    known=known,
                    parameter_cells=parameter_cells,
                )
                for field in effect.fields
            ),
        )
    return _specialize_state(
        effect,
        known=known,
        parameter_cells=parameter_cells,
    )


def _specialize_action_field(
    field: ActionFieldSpec,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> ActionFieldSpec:
    return replace(
        field,
        value_use=_specialize_value_use(
            field.value_use,
            known=known,
            parameter_cells=parameter_cells,
        ),
    )


def _specialize_state(
    state: StateSpecVariant,
    *,
    known: EvalContext,
    parameter_cells: tuple[ParameterCellBinding, ...],
) -> StateSpecVariant:
    if isinstance(state, ForEachStateSpec):
        return replace(
            state,
            state=tuple(
                _specialize_state(
                    child,
                    known=known,
                    parameter_cells=parameter_cells,
                )
                for child in state.state
            ),
        )
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
    value, _binding_time = specialize_value_expression(
        use.value,
        known=known,
        parameter_cells=parameter_cells,
    )
    return replace(use, value=value)
