"""Core-only projection bridge between compiler plans and the domain SDK."""

from __future__ import annotations

from typing import cast

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
)
from scopecat.compiler.measurement_projection import (
    project_measurement_catalog,
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
from scopecat.sdk.domain.batch import (
    DomainBatchInputs,
    DomainBatchRequest,
)
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainInputPortView,
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
    DomainProgramView,
    DomainResultBindingView,
    DomainResultPortView,
)


def make_domain_call_view(
    linked: LinkedPlan,
    execution_id: str,
    result_closure: DomainResultClosure,
) -> DomainCallView:
    """Project static domain semantics once before bounded compilation."""

    typed_execution = next(
        item
        for item in core_domain_executions(linked.program)
        if item.id == execution_id
    )
    (
        product_contracts,
        product_use_refs,
        product_use_refs_by_id,
    ) = _project_domain_assets(linked)
    owned_use_ids = set(result_closure.product_use_ids)
    return DomainCallView(
        id=typed_execution.id,
        program=_domain_program_view(typed_execution.program),
        results=_domain_result_views(
            typed_execution,
            product_contracts,
            product_use_refs_by_id,
        ),
        product_uses=tuple(
            product_use
            for product_use in product_use_refs
            if product_use_id(product_use) in owned_use_ids
        ),
    )


def make_domain_batch_request(
    call: DomainCallView,
    linked_points: MaterializedLinkedPoints,
    point_ordinals: tuple[int, ...],
    *,
    batch_ordinal: int,
) -> DomainBatchRequest:
    """Resolve every input and project one complete bounded batch."""

    program_input_ids = tuple(port.id for port in call.program.inputs)
    compiler_input_ids = tuple(port.id for port in call.program.compiler_inputs)
    inputs = DomainBatchInputs(
        program=linked_points.bind_domain_inputs(
            call.id,
            "program",
            program_input_ids,
            point_ordinals,
        ),
        compiler=linked_points.bind_domain_inputs(
            call.id,
            "compiler",
            compiler_input_ids,
            point_ordinals,
        ),
    )
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
    return DomainBatchRequest(
        batch_ordinal=batch_ordinal,
        call=call,
        inputs=inputs,
        points=point_refs,
        measurement_catalog=project_measurement_catalog(
            linked_points,
            point_ordinals,
        ),
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
    return (
        product_contracts,
        product_use_refs,
        product_use_refs_by_id,
    )
