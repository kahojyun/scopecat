"""Low-level compiler program builders used only by tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.compiler.bind import BoundPlan
from scopecat.compiler.environment import ConfigEnvironment
from scopecat.compiler.semantic.model import (
    AcquireEffect,
    AcquireId,
    AcquireResult,
)
from scopecat.compiler.typed.invocation import (
    InvocationValueUse,
    InvokeArgument,
    InvokeEffect,
    InvokeId,
)
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    TypedComputeNode,
    TypedDomainExecution,
    TypedMeasurementPostprocessor,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.graph.relations.model import CellValue
from scopecat.graph.values import (
    ComputeResultRef,
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    product_id,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.products import (
    ProductAxisDef,
    ProductDef,
)
from scopecat.measurements.records import RecordUse
from scopecat.measurements.results import MeasurementDType


def overlay_parameter_cell(
    table_id: str,
    *,
    row_index: int,
    key: dict[str, CellValue],
    column_id: str,
    axis_id: str,
) -> PointParameterOverlay:
    """Build one statically bound point-local cell overlay."""

    return PointParameterOverlay(
        table_id=table_id,
        row_index=row_index,
        key=key,
        column_id=column_id,
        axis_id=axis_id,
    )


def compute_result(value: ValueId | OperationId | str) -> ComputeResultRef:
    """Reference an exact output or one operation's current single result."""

    if isinstance(value, ValueId):
        selected = value
    else:
        operation_id = (
            value
            if isinstance(value, OperationId)
            else OperationId(SymbolId(local_id=value))
        )
        selected = operation_result_id(operation_id)
    return ComputeResultRef(value_id=selected)


def observable_product(
    id: str | ProductId,
    *,
    unit: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[ProductAxisDef] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> ProductDef:
    return ProductDef(
        id=id if isinstance(id, ProductId) else product_id(id),
        unit=unit,
        dtype=dtype,
        axes=tuple(axes),
        metadata=metadata or {},
    )


def instrument_acquisition(
    product: ProductDef | ProductId,
    *,
    id: AcquireId | str | None = None,
    resource_port_id: LogicalResourcePortId | str = "source",
    interface: str,
    acquisition: str = "sample",
    component_path: Sequence[str] = (),
    result_id: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> AcquireEffect:
    """Build one explicit, single-product instrument acquisition."""

    selected_product_id = product.id if isinstance(product, ProductDef) else product
    if id is None:
        selected_acquire_id = AcquireId(
            SymbolId(
                scope=selected_product_id.scope,
                local_id=f"acquire-{selected_product_id.local_id}",
            )
        )
    elif isinstance(id, AcquireId):
        selected_acquire_id = id
    else:
        selected_acquire_id = AcquireId(SymbolId(local_id=id))
    selected_resource_port_id = (
        resource_port_id
        if isinstance(resource_port_id, LogicalResourcePortId)
        else logical_resource_port_id(resource_port_id)
    )
    return AcquireEffect(
        id=selected_acquire_id,
        resource_port_id=selected_resource_port_id,
        interface_id=interface,
        component_path=tuple(component_path),
        acquisition_id=acquisition,
        results=(
            AcquireResult(
                product_id=selected_product_id,
                result_id=result_id or selected_product_id.local_id,
                metadata=dict(metadata or {}),
            ),
        ),
    )


def instrument_acquisitions(
    *products: ProductDef | ProductId,
    resource_port_id: LogicalResourcePortId | str = "source",
    interface: str,
    acquisition: str = "sample",
) -> tuple[AcquireEffect, ...]:
    """Build one independently identified acquisition per logical product."""

    return tuple(
        instrument_acquisition(
            product,
            resource_port_id=resource_port_id,
            interface=interface,
            acquisition=acquisition,
        )
        for product in products
    )


def instrument_invocation(
    *,
    id: str,
    resource_port_id: LogicalResourcePortId | str,
    interface: str,
    operation: str,
    arguments: Mapping[str, InvocationValueUse] | None = None,
    component_path: Sequence[str] = (),
) -> InvokeEffect:
    """Build one ordered atomic instrument invocation."""

    return InvokeEffect(
        id=InvokeId(SymbolId(local_id=id)),
        resource_port_id=(
            resource_port_id
            if isinstance(resource_port_id, LogicalResourcePortId)
            else logical_resource_port_id(resource_port_id)
        ),
        interface_id=interface,
        component_path=tuple(component_path),
        operation_id=operation,
        arguments=tuple(
            InvokeArgument(id=argument_id, value_use=value_use)
            for argument_id, value_use in (arguments or {}).items()
        ),
    )


def typed_program(
    *,
    id: str,
    kind: str,
    point_domain: PointDomain,
    resource_requirements: Sequence[LogicalResourceRequirement] = (),
    parameter_overlays: Sequence[PointParameterOverlay] = (),
    compute_nodes: Sequence[TypedComputeNode] = (),
    domain_execution: TypedDomainExecution | None = None,
    measurement_postprocessors: Sequence[TypedMeasurementPostprocessor] = (),
    state: Sequence[SetStateSpec] = (),
    invocations: Sequence[InvokeEffect] = (),
    product_defs: Sequence[ProductDef] = (),
    instrument_acquisitions: Sequence[AcquireEffect] = (),
    product_uses: Sequence[ProductUse] = (),
    record_uses: Sequence[RecordUse] = (),
) -> CoreProgram:
    """Build one low-level typed program from explicitly ordered components."""

    return CoreProgram(
        id=id,
        kind=kind,
        point_domain=point_domain,
        resource_requirements=tuple(resource_requirements),
        parameter_overlays=tuple(parameter_overlays),
        compute_nodes=tuple(compute_nodes),
        effects=(
            *state,
            *invocations,
            *((domain_execution,) if domain_execution is not None else ()),
            *instrument_acquisitions,
        ),
        measurement_postprocessors=tuple(measurement_postprocessors),
        product_defs=tuple(product_defs),
        product_uses=tuple(product_uses),
        record_uses=tuple(record_uses),
    )


def bind_core_program(
    program: CoreProgram,
    environment: ConfigEnvironment,
) -> BoundPlan:
    """Bind a trusted low-level program for focused compiler tests."""

    return BoundPlan(
        seal_typed_program(
            program,
            phase=ProblemPhase.PLANNING,
        ),
        environment,
    )
