"""Core-only projection bridge between compiler plans and the domain SDK."""

from __future__ import annotations

from dataclasses import replace
from typing import TypeGuard, cast

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
)
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    LiteralScalarExpr,
    PointColumnScalarExpr,
    RelationExpr,
    ScalarExpr,
    ScalarExpression,
    SeriesExpr,
)
from scopecat.compiler.semantic.model import MeasurementTransformId
from scopecat.compiler.typed.domain_results import (
    DomainResultClosure,
)
from scopecat.compiler.typed.iteration import (
    PointIterationLinearValues,
)
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    TypedDomainProgram,
    core_domain_executions,
)
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.measurements._bridge import (
    project_measurement_catalog,
    project_run_point_catalog,
)
from scopecat.sdk.domain.compiler import (
    DomainCompileRequest,
    DomainCompileTemplate,
    DomainInput,
    DomainInputBinder,
    DomainIterationLayout,
    DomainLiteral,
    DomainPointAffine,
    DomainPointAxis,
    DomainPointLinearValues,
)
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainExecutionPointView,
    DomainExecutionView,
    DomainInputPortView,
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
    DomainProgramView,
    DomainResourceBindingView,
    DomainResultBindingView,
    DomainResultPortView,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)


def make_domain_compile_request(
    linked: LinkedPlan,
    execution_id: str,
    result_closure: DomainResultClosure,
    barrier_regions: tuple[tuple[int, ...], ...],
    bind_program_inputs: DomainInputBinder,
    bind_compiler_inputs: DomainInputBinder,
) -> DomainCompileRequest:
    """Project one typed symbolic domain call for pure target compilation."""

    return make_domain_compile_template(
        linked,
        execution_id,
        result_closure,
    ).bind_coverage(
        barrier_regions,
        bind_program_inputs,
        bind_compiler_inputs,
    )


def make_domain_compile_template(
    linked: LinkedPlan,
    execution_id: str,
    result_closure: DomainResultClosure,
) -> DomainCompileTemplate:
    """Project static domain semantics once before coverage binding."""

    typed_execution = next(
        item
        for item in core_domain_executions(linked.program)
        if item.id == execution_id
    )
    (
        product_contracts,
        product_use_refs,
        product_use_refs_by_id,
        transform_refs,
    ) = _project_domain_assets(linked)
    program_inputs: list[DomainInput] = []
    for port in typed_execution.program.input_ports:
        residual = typed_execution.inputs[port.id].value
        program_inputs.append(
            DomainInput(
                id=port.id,
                normal_form=_domain_input_normal_form(residual.plan.root),
            )
        )
    compiler_inputs: list[DomainInput] = []
    for port in typed_execution.program.compiler_input_ports:
        residual = typed_execution.compiler_inputs[port.id].value
        compiler_inputs.append(
            DomainInput(
                id=port.id,
                normal_form=_domain_input_normal_form(residual.plan.root),
            )
        )
    owned_use_ids = set(result_closure.product_use_ids)
    return DomainCompileTemplate(
        call=DomainCallView(
            id=typed_execution.id,
            program=_domain_program_view(typed_execution.program),
            results=_domain_result_views(
                typed_execution,
                product_contracts,
                product_use_refs_by_id,
            ),
            measurement_transforms=tuple(
                transform_refs[transform.id] for transform in result_closure.transforms
            ),
            product_uses=tuple(
                product_use
                for product_use in product_use_refs
                if product_use_id(product_use) in owned_use_ids
            ),
            resources=tuple(
                DomainResourceBindingView(
                    role=role,
                    resource_port_id=resource_id.qualified_name,
                    capabilities=next(
                        port.capabilities
                        for port in typed_execution.program.resource_ports
                        if port.id == role
                    ),
                )
                for role, resource_id in typed_execution.resources.items()
            ),
        ),
        program_inputs=tuple(program_inputs),
        compiler_inputs=tuple(compiler_inputs),
        iteration_layout=_iteration_layout(linked),
    )


type _CoreInputExpression = ScalarExpr | SeriesExpr | RelationExpr
type _AffineTerms = tuple[str | None, int | float, int | float]


def _domain_input_normal_form(
    expression: _CoreInputExpression,
) -> DomainLiteral | DomainPointAffine | None:
    if isinstance(expression, LiteralScalarExpr):
        return DomainLiteral(expression.value)
    if not isinstance(expression, ScalarExpr):
        return None
    terms = _affine_terms(cast("ScalarExpression", expression))
    if terms is None:
        return None
    column_id, scale, offset = terms
    if column_id is None:
        return None
    return DomainPointAffine(column_id, scale, offset)


def _affine_terms(expression: ScalarExpression) -> _AffineTerms | None:
    if isinstance(expression, PointColumnScalarExpr):
        return (expression.name, 1, 0)
    if isinstance(expression, LiteralScalarExpr):
        if _is_affine_number(expression.value):
            return (None, 0, expression.value)
        return None
    if not isinstance(expression, BinaryScalarExpr):
        return None
    left = _affine_terms(expression.left)
    right = _affine_terms(expression.right)
    if left is None or right is None:
        return None
    left_column, left_scale, left_offset = left
    right_column, right_scale, right_offset = right
    if expression.op in {"+", "-"}:
        if (
            left_column is not None
            and right_column is not None
            and left_column != right_column
        ):
            return None
        direction = 1 if expression.op == "+" else -1
        return (
            left_column or right_column,
            left_scale + direction * right_scale,
            left_offset + direction * right_offset,
        )
    if expression.op == "*":
        if left_column is None:
            return (
                right_column,
                left_offset * right_scale,
                left_offset * right_offset,
            )
        if right_column is None:
            return (
                left_column,
                right_offset * left_scale,
                right_offset * left_offset,
            )
        return None
    if expression.op == "/" and right_column is None and right_offset != 0:
        return (
            left_column,
            left_scale / right_offset,
            left_offset / right_offset,
        )
    return None


def _is_affine_number(value: object) -> TypeGuard[int | float]:
    return type(value) in {int, float}


def _iteration_layout(linked: LinkedPlan) -> DomainIterationLayout:
    source = linked.verified_program.iteration_layout
    return DomainIterationLayout(
        axes=tuple(
            DomainPointAxis(
                axis.id,
                (
                    DomainPointLinearValues(
                        axis.values.center,
                        axis.values.span,
                        axis.values.count,
                    )
                    if isinstance(axis.values, PointIterationLinearValues)
                    else axis.values
                ),
                axis.repeat_each,
            )
            for axis in source.axes
        ),
        preferred_tile_size=source.preferred_tile_size,
    )


def make_domain_batch_context(
    request: DomainCompileRequest,
    linked_points: MaterializedLinkedPoints,
    point_ordinals: tuple[int, ...],
    *,
    batch_ordinal: int,
    absorbed_input_ids: tuple[str, ...] = (),
    absorbed_transform_ids: tuple[str, ...] = (),
) -> DomainBatchContext:
    call = request.call
    absorbed_input_set = set(absorbed_input_ids)
    residual_inputs = request.resolve_program_inputs(
        tuple(
            input_value.id
            for input_value in request.program_inputs
            if input_value.id not in absorbed_input_set
        ),
        point_ordinals,
        max_points=len(point_ordinals),
    )
    residual_input_ids = tuple(name for name, _values in residual_inputs.columns)
    residual_input_set = set(residual_input_ids)
    points_by_ordinal = {
        point.logical_ordinal: point for point in linked_points.point_domain.points
    }
    selected_points = tuple(points_by_ordinal[ordinal] for ordinal in point_ordinals)
    point_refs = tuple(
        DomainPointRef(
            id=point.logical_id.value,
            ordinal=point.logical_ordinal,
            native=point.logical_id,
        )
        for point in selected_points
    )
    absorbed_ids = set(absorbed_transform_ids)
    absorbed_transforms = tuple(
        transform
        for transform in call.measurement_transforms
        if transform.id in absorbed_ids
    )
    residual_transforms = tuple(
        transform
        for transform in call.measurement_transforms
        if transform.id not in absorbed_ids
    )
    execution = DomainExecutionView(
        id=call.id,
        program=replace(
            call.program,
            inputs=tuple(
                port for port in call.program.inputs if port.id in residual_input_set
            ),
        ),
        points=tuple(
            DomainExecutionPointView(
                ref=point,
                inputs=tuple(
                    (name, values[index]) for name, values in residual_inputs.columns
                ),
            )
            for index, point in enumerate(point_refs)
        ),
        results=call.results,
        measurement_transforms=residual_transforms,
    )
    absorbed_output_ids = {
        product_use_id(product_use)
        for transform in absorbed_transforms
        for output in transform.outputs
        for product_use in output.product_uses
    }
    residual_output_ids = {
        product_use_id(product_use)
        for transform in residual_transforms
        for output in transform.outputs
        for product_use in output.product_uses
    }
    direct_ids = {
        product_use_id(product_use)
        for result in call.results
        for product_use in result.product_uses
    } | absorbed_output_ids
    derived_ids = residual_output_ids
    owned = call.product_uses
    direct = tuple(
        product_use
        for product_use in owned
        if product_use_id(product_use) in direct_ids
    )
    derived = tuple(
        product_use
        for product_use in owned
        if product_use_id(product_use) in derived_ids
    )
    return DomainBatchContext(
        batch_ordinal=batch_ordinal,
        execution=execution,
        direct_product_uses=direct,
        derived_product_uses=derived,
        measurement_catalog=project_measurement_catalog(
            linked_points,
            point_ordinals,
        ),
        run_points=project_run_point_catalog(
            linked_points,
            point_ordinals,
        ).points,
    )


def point_id(ref: DomainPointRef) -> LogicalPointId:
    return cast("LogicalPointId", ref.native)


def product_use_id(ref: DomainProductUseRef) -> ProductUseId:
    return cast("ProductUseId", ref.native)


def _product_contract_view(product: ProductDef) -> DomainProductContractView:
    return DomainProductContractView(
        id=product.id.qualified_name,
        kind=product.kind,
        unit=product.unit,
        dtype=product.dtype,
        axes=tuple(
            DomainProductAxisView(
                id=axis.id,
                kind=axis.kind,
                size=axis.size,
                unit=axis.unit,
                metadata=axis.metadata,
            )
            for axis in product.axes
        ),
        metadata=product.metadata,
    )


def _domain_program_view(program: TypedDomainProgram) -> DomainProgramView:
    return DomainProgramView(
        id=program.id.qualified_name,
        dialect_id=program.dialect_id,
        dialect_version=program.dialect_version,
        body=program.body,
        inputs=tuple(
            DomainInputPortView(port.id, port.value_type)
            for port in program.input_ports
        ),
        compiler_inputs=tuple(
            DomainInputPortView(port.id, port.value_type)
            for port in program.compiler_input_ports
        ),
        results=tuple(
            DomainResultPortView(port.id, port.contract)
            for port in program.result_ports
        ),
    )


def _domain_result_views(
    execution: TypedDomainExecution,
    product_contracts: dict[ProductId, DomainProductContractView],
    product_use_refs: dict[ProductUseId, DomainProductUseRef],
) -> tuple[DomainResultBindingView, ...]:
    return tuple(
        DomainResultBindingView(
            id=result.id,
            product=product_contracts[result.product_id],
            product_uses=tuple(
                product_use_refs[use_id] for use_id in result.product_use_ids
            ),
            contract=next(
                port.contract
                for port in execution.program.result_ports
                if port.id == result.id
            ),
        )
        for result in execution.results
    )


def _project_domain_assets(
    linked: LinkedPlan,
) -> tuple[
    dict[ProductId, DomainProductContractView],
    tuple[DomainProductUseRef, ...],
    dict[ProductUseId, DomainProductUseRef],
    dict[MeasurementTransformId, DomainMeasurementTransform],
]:
    product_contracts = {
        product.id: _product_contract_view(product)
        for product in linked.program.product_defs
    }
    product_use_refs = tuple(
        DomainProductUseRef(
            id=use.id.value,
            product=product_contracts[use.product_id],
            native=use.id,
        )
        for use in linked.program.product_uses
    )
    product_use_refs_by_id = {
        cast("ProductUseId", ref.native): ref for ref in product_use_refs
    }
    transform_refs = {
        transform.id: DomainMeasurementTransform(
            id=transform.id.qualified_name,
            semantic=transform.semantic,
            inputs=tuple(
                DomainTransformInputPort(
                    id=port.id,
                    product_use=product_use_refs_by_id[port.product_use_id],
                    product=product_contracts[port.product_id],
                )
                for port in transform.inputs
            ),
            outputs=tuple(
                DomainTransformOutputPort(
                    id=port.id,
                    product=product_contracts[port.product_id],
                    product_uses=tuple(
                        product_use_refs_by_id[use_id]
                        for use_id in port.product_use_ids
                    ),
                )
                for port in transform.outputs
            ),
        )
        for transform in linked.program.measurement_transforms
    }
    return (
        product_contracts,
        product_use_refs,
        product_use_refs_by_id,
        transform_refs,
    )
