"""Core-only projection bridge between compiler plans and the domain SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    MaterializedLinkedPointSet,
)
from scopecat.compiler.relations.analysis import (
    PlanNode,
    PlanReferenceKind,
    plan_references,
)
from scopecat.compiler.relations.evaluation import EvalContext
from scopecat.compiler.relations.model import lit
from scopecat.compiler.relations.specialization import (
    BindingTime,
    KnownScalar,
    residual_scalar_expression,
    specialize_scalar,
)
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    verify_scalar_value_expr,
)
from scopecat.compiler.typed.parameter_overlays import (
    resolve_parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import LogicalPointId
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.program import core_domain_executions
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.planning.domain_placement import (
    DomainExecutionSlice,
    domain_execution_slice,
)
from scopecat.sdk.domain.compiler import (
    DomainBoundPoint,
    DomainCompileRequest,
    DomainResidualInput,
)
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.view import (
    DomainBatchView,
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
    DomainResultBindingView,
    DomainResultPortView,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)


@dataclass(frozen=True, slots=True)
class DomainPlanProjection:
    linked_points: MaterializedLinkedPoints = field(repr=False)
    execution_id: str
    point_refs: tuple[DomainPointRef, ...]
    product_use_refs: tuple[DomainProductUseRef, ...]
    _point_refs_by_id: dict[LogicalPointId, DomainPointRef] = field(
        repr=False,
        compare=False,
    )
    _product_use_refs_by_id: dict[ProductUseId, DomainProductUseRef] = field(
        repr=False,
        compare=False,
    )
    _product_contracts: dict[ProductId, DomainProductContractView] = field(
        repr=False,
        compare=False,
    )
    _measurement_transforms: tuple[DomainMeasurementTransform, ...] = field(
        repr=False,
        compare=False,
    )
    _execution_slice: DomainExecutionSlice = field(
        repr=False,
        compare=False,
    )

    def view(self, selected: MaterializedLinkedPointSet) -> DomainBatchView:
        self._require_owned_points(selected)
        points = tuple(
            self._point_refs_by_id[point.logical_id]
            for point in selected.point_domain.points
        )
        materialized = (
            next(
                execution
                for execution in selected.domain_executions
                if execution.execution.id == self.execution_id
            )
            if isinstance(selected, MaterializedLinkedPoints)
            else selected.domain_execution(self.execution_id)
        )
        return DomainBatchView(
            execution=DomainExecutionView(
                id=materialized.execution.id,
                program=DomainProgramView(
                    id=materialized.execution.program.id.qualified_name,
                    dialect_id=materialized.execution.program.dialect_id,
                    dialect_version=materialized.execution.program.dialect_version,
                    body=materialized.execution.program.body,
                    inputs=tuple(
                        DomainInputPortView(port.id, port.value_type)
                        for port in materialized.execution.program.input_ports
                    ),
                    results=tuple(
                        DomainResultPortView(port.id, port.contract)
                        for port in materialized.execution.program.result_ports
                    ),
                ),
                points=tuple(
                    DomainExecutionPointView(
                        ref=self._point_refs_by_id[point.logical_id],
                        inputs=point.inputs,
                    )
                    for point in materialized.points
                ),
                results=tuple(
                    DomainResultBindingView(
                        id=result.id,
                        product=self._product_contracts[result.product_id],
                        product_uses=tuple(
                            self._product_use_refs_by_id[use_id]
                            for use_id in result.product_use_ids
                        ),
                        contract=next(
                            port.contract
                            for port in materialized.execution.program.result_ports
                            if port.id == result.id
                        ),
                    )
                    for result in materialized.execution.results
                ),
                measurement_transforms=self._measurement_transforms,
            ),
            points=points,
            product_uses=self.product_use_refs,
        )

    def _require_owned_points(self, selected: MaterializedLinkedPointSet) -> None:
        if selected is self.linked_points:
            return
        if (
            isinstance(selected, MaterializedLinkedPointBatch)
            and selected.parent is self.linked_points
        ):
            return
        msg = "domain view projection requires points from its materialized plan"
        raise ValueError(msg)

    def execution_slice(self) -> DomainExecutionSlice:
        return self._execution_slice


def project_domain_plan(
    linked_points: MaterializedLinkedPoints,
    execution_id: str,
) -> DomainPlanProjection:
    product_contracts = {
        product.id: _product_contract_view(product)
        for product in linked_points.linked_plan.product_defs
    }
    point_refs = tuple(
        DomainPointRef(
            id=point.logical_id.value,
            ordinal=point.logical_ordinal,
            native=point.logical_id,
        )
        for point in linked_points.point_domain.points
    )
    point_refs_by_id = {cast("LogicalPointId", ref.native): ref for ref in point_refs}
    product_use_refs = tuple(
        DomainProductUseRef(
            id=use.id.value,
            product=product_contracts[use.product_id],
            native=use.id,
        )
        for use in linked_points.linked_plan.product_uses
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
        for transform in linked_points.linked_plan.program.measurement_transforms
    }
    execution_slice = domain_execution_slice(
        linked_points.linked_plan.program,
        execution_id,
    )
    measurement_transforms = tuple(
        transform_refs[transform.id] for transform in execution_slice.transforms
    )
    return DomainPlanProjection(
        linked_points=linked_points,
        execution_id=execution_id,
        point_refs=point_refs,
        product_use_refs=product_use_refs,
        _point_refs_by_id=point_refs_by_id,
        _product_use_refs_by_id=product_use_refs_by_id,
        _product_contracts=product_contracts,
        _measurement_transforms=measurement_transforms,
        _execution_slice=execution_slice,
    )


def make_domain_compile_request(
    projection: DomainPlanProjection,
    barrier_regions: tuple[MaterializedLinkedPointBatch, ...],
) -> DomainCompileRequest:
    """Project one typed symbolic domain call for pure target compilation."""

    linked_points = projection.linked_points
    view = projection.view(linked_points)
    execution = view.execution
    typed_execution = next(
        item
        for item in core_domain_executions(linked_points.linked_plan.program)
        if item.id == projection.execution_id
    )
    if execution is None:
        raise ValueError("domain compilation requires one typed domain execution")
    known = EvalContext(params=linked_points.linked_plan.environment.parameters)
    parameter_cells = resolve_parameter_cell_bindings(
        linked_points.linked_plan.program.parameter_overlays,
        known=known,
    )
    inputs: list[DomainResidualInput] = []
    for port in typed_execution.program.input_ports:
        input_value = typed_execution.inputs[port.id]
        expression = input_value.value
        if isinstance(expression, ScalarValueExpr):
            result = specialize_scalar(
                expression.plan.root,
                known=known,
                parameter_cells=parameter_cells,
            )
            residual = verify_scalar_value_expr(
                (
                    lit(result.value)
                    if isinstance(result, KnownScalar)
                    else residual_scalar_expression(result)
                ),
                bindings=expression.plan.bindings,
                expected_type=expression.value_type,
            )
            binding_time = (
                BindingTime.CONFIGURATION_STATIC
                if isinstance(result, KnownScalar)
                else result.binding_time
            )
        else:
            residual = expression
            binding_time = _value_binding_time(expression.plan.root)
        inputs.append(
            DomainResidualInput(
                id=port.id,
                value_type=port.value_type,
                expression=residual,
                binding_time=binding_time,
            )
        )
    return DomainCompileRequest(
        call=DomainCallView(
            id=typed_execution.id,
            program=execution.program,
            results=execution.results,
            measurement_transforms=execution.measurement_transforms,
        ),
        point_space=linked_points.verified_program.point_domain,
        inputs=tuple(inputs),
        barrier_regions=tuple(region.point_indices for region in barrier_regions),
        _bound_points=tuple(
            DomainBoundPoint(point.logical_ordinal, point.inputs)
            for point in execution.points
        ),
    )


def make_domain_batch_context(
    projection: DomainPlanProjection,
    batch: MaterializedLinkedPointBatch,
    *,
    compiler_id: str,
    batch_ordinal: int,
    pushed_transform_ids: tuple[str, ...] = (),
) -> DomainBatchContext:
    view = projection.view(batch)
    execution = view.execution
    if execution is None:
        raise AssertionError("selected domain execution is missing")
    execution_slice = projection.execution_slice()
    pushed_ids = set(pushed_transform_ids)
    pushed_transforms = tuple(
        transform
        for transform in execution.measurement_transforms
        if transform.id in pushed_ids
    )
    residual_transforms = tuple(
        transform
        for transform in execution.measurement_transforms
        if transform.id not in pushed_ids
    )
    pushed_output_ids = {
        product_use_id(product_use)
        for transform in pushed_transforms
        for output in transform.outputs
        for product_use in output.product_uses
    }
    residual_output_ids = {
        product_use_id(product_use)
        for transform in residual_transforms
        for output in transform.outputs
        for product_use in output.product_uses
    }
    owned_ids = set(execution_slice.product_use_ids)
    direct_ids = set(execution_slice.direct_product_use_ids) | pushed_output_ids
    derived_ids = residual_output_ids
    owned = tuple(
        product_use
        for product_use in view.product_uses
        if product_use_id(product_use) in owned_ids
    )
    direct = tuple(
        product_use
        for product_use in view.product_uses
        if product_use_id(product_use) in direct_ids
    )
    derived = tuple(
        product_use
        for product_use in view.product_uses
        if product_use_id(product_use) in derived_ids
    )
    return DomainBatchContext(
        batch_ordinal=batch_ordinal,
        execution=execution,
        points=view.points,
        product_uses=owned,
        direct_product_uses=direct,
        derived_product_uses=derived,
        measurement_transforms=residual_transforms,
        linked_points=batch,
        compiler_id=compiler_id,
    )


def _value_binding_time(expression: PlanNode) -> BindingTime:
    references = plan_references(expression)
    kinds = {reference.kind for reference in references}
    if kinds & {
        PlanReferenceKind.CURRENT_COLUMN,
        PlanReferenceKind.OUTER_COLUMN,
        PlanReferenceKind.POINT_COLUMN,
    }:
        return BindingTime.POINT
    if kinds & {
        PlanReferenceKind.PARAMETER_SCALAR,
        PlanReferenceKind.PARAMETER_SERIES,
        PlanReferenceKind.PARAMETER_TABLE,
    }:
        return BindingTime.CONFIGURATION_STATIC
    return BindingTime.REQUEST_STATIC


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
