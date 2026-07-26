"""Core-only projection bridge between compiler plans and the domain SDK."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
)
from scopecat.compiler.measurement_projection import (
    project_measurement_catalog,
    project_run_point_catalog,
)
from scopecat.compiler.semantic.model import (
    MeasurementTransformId,
)
from scopecat.compiler.typed.domain_results import (
    DomainResultClosure,
)
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    core_domain_executions,
)
from scopecat.domain.program import DomainProgramDef
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.measurements.products import ProductDef
from scopecat.sdk.domain._identities import product_use_id
from scopecat.sdk.domain.compiler import (
    DomainCompileRequest,
    DomainCompileTemplate,
    DomainInput,
    DomainIterationLayout,
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
    program_inputs = tuple(
        DomainInput(port.id) for port in typed_execution.program.input_ports
    )
    compiler_inputs = tuple(
        DomainInput(port.id) for port in typed_execution.program.compiler_input_ports
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
        program_inputs=program_inputs,
        compiler_inputs=compiler_inputs,
        iteration_layout=_iteration_layout(linked),
    )


def _iteration_layout(linked: LinkedPlan) -> DomainIterationLayout:
    source = linked.verified_program.iteration_layout
    return DomainIterationLayout(
        preferred_tile_size=source.preferred_tile_size,
    )


def make_domain_batch_context(
    request: DomainCompileRequest,
    linked_points: MaterializedLinkedPoints,
    point_ordinals: tuple[int, ...],
    *,
    batch_ordinal: int,
    absorbed_input_ids: tuple[str, ...] = (),
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
        measurement_transforms=call.measurement_transforms,
    )
    derived_ids = {
        product_use_id(product_use)
        for transform in call.measurement_transforms
        for output in transform.outputs
        for product_use in output.product_uses
    }
    direct_ids = {
        product_use_id(product_use)
        for result in call.results
        for product_use in result.product_uses
    }
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


def _product_contract_view(product: ProductDef) -> DomainProductContractView:
    return DomainProductContractView(
        id=product.id.qualified_name,
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


def _domain_program_view(program: DomainProgramDef) -> DomainProgramView:
    return DomainProgramView(
        id=program.symbol_id.qualified_name,
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
