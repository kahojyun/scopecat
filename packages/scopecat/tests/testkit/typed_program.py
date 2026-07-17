"""Low-level compiler program builders used only by tests."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    _environment_link_problems,
    link_verified_program,
)
from scopecat.compiler.relations.model import ScalarExpr, as_scalar_expr
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    OperationId,
    SourceMap,
    ValueId,
    operation_result_id,
)
from scopecat.compiler.semantic.value_expressions import verify_scalar_value_expr
from scopecat.compiler.typed.action import ActionSpec
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    DomainProductProducer,
    InstrumentProductProducer,
    MeasurementTransformProductProducer,
    ProductAxisDef,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    ResourceRouteIntent,
    TypedComputeNode,
    TypedDomainExecution,
    TypedMeasurementTransform,
    TypedProgram,
    product_output,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.state import StateSpecVariant
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import (
    ProblemPhase,
    has_blocking_problems,
)
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
    ProductUse,
    product_producer_id,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
    ResourceTarget,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Scalar
from scopecat.measurements.results import MeasurementDType


def overlay_parameter_cell(
    table_id: str,
    *,
    key: dict[str, object],
    key_types: dict[str, Scalar],
    column_id: str,
    value: object,
    value_type: Scalar,
    bindings: RelationTypeBindings,
) -> PointParameterOverlay:
    """Build a typed point-local cell overlay."""

    if set(key) != set(key_types):
        msg = "parameter overlay key and key_types must contain the same columns"
        raise ValueError(msg)
    return PointParameterOverlay(
        table_id=table_id,
        key_uses={
            name: relation_use(
                verify_scalar_value_expr(
                    _require_scalar_expression(expression),
                    bindings=bindings,
                    expected_type=key_types[name],
                )
            )
            for name, expression in key.items()
        },
        column_id=column_id,
        value_use=relation_use(
            verify_scalar_value_expr(
                _require_scalar_expression(value),
                bindings=bindings,
                expected_type=value_type,
            )
        ),
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
    id: str | ProductId,  # noqa: A002
    *,
    unit: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[ProductAxisDef] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> ProductDef:
    return product_output(
        id,
        kind="observable",
        unit=unit,
        dtype=dtype,
        axes=axes,
        metadata=metadata,
    )


def instrument_product_producer(
    product: ProductDef | ProductId,
    *,
    id: ProductProducerId | str | None = None,  # noqa: A002
    resource_port_id: LogicalResourcePortId | str | None = None,
    physical_resource_id: PhysicalResourceId | str | None = None,
    capability: str | None = None,
    provider_key: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> InstrumentProductProducer:
    """Declare an instrument edge separately from logical product schema."""

    selected_product_id = product.id if isinstance(product, ProductDef) else product
    if id is None:
        selected_producer_id = ProductProducerId(selected_product_id.symbol)
    elif isinstance(id, ProductProducerId):
        selected_producer_id = id
    else:
        selected_producer_id = product_producer_id(id)
    return InstrumentProductProducer(
        id=selected_producer_id,
        product_id=selected_product_id,
        resource_target=_product_resource_target(
            resource_port_id=resource_port_id,
            physical_resource_id=physical_resource_id,
        ),
        capability=capability,
        provider_key=provider_key or selected_product_id.local_id,
        metadata=dict(metadata or {}),
    )


def typed_program(
    *,
    id: str,  # noqa: A002
    kind: str,
    point_domain: PointDomain,
    route_intents: Sequence[ResourceRouteIntent] = (),
    parameter_overlays: Sequence[PointParameterOverlay] = (),
    compute_nodes: Sequence[TypedComputeNode] = (),
    domain_execution: TypedDomainExecution | None = None,
    measurement_transforms: Sequence[TypedMeasurementTransform] = (),
    implementation_catalog: ImplementationCatalog | None = None,
    source_map: SourceMap | None = None,
    state: Sequence[StateSpecVariant] = (),
    actions: Sequence[ActionSpec] = (),
    product_defs: Sequence[ProductDef] = (),
    instrument_product_producers: Sequence[InstrumentProductProducer] = (),
    domain_product_producers: Sequence[DomainProductProducer] = (),
    measurement_transform_product_producers: Sequence[
        MeasurementTransformProductProducer
    ] = (),
    product_uses: Sequence[ProductUse] = (),
    record_uses: Sequence[RecordUse] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> TypedProgram:
    """Build one low-level typed program from explicitly ordered components."""

    return TypedProgram(
        id=id,
        kind=kind,
        point_domain=point_domain,
        route_intents=tuple(route_intents),
        parameter_overlays=tuple(parameter_overlays),
        compute_nodes=tuple(compute_nodes),
        domain_execution=domain_execution,
        measurement_transforms=tuple(measurement_transforms),
        implementation_catalog=implementation_catalog or ImplementationCatalog(),
        source_map=source_map or SourceMap(),
        state=tuple(state),
        actions=tuple(actions),
        product_defs=tuple(product_defs),
        instrument_product_producers=tuple(instrument_product_producers),
        domain_product_producers=tuple(domain_product_producers),
        measurement_transform_product_producers=tuple(
            measurement_transform_product_producers
        ),
        product_uses=tuple(product_uses),
        record_uses=tuple(record_uses),
        metadata=dict(metadata or {}),
    )


def link_program(
    program: TypedProgram,
    environment: ValidatedConfigEnvironment,
) -> LinkedPlan:
    """Snapshot, seal, and link an externally constructed test program."""

    try:
        verified_program = seal_typed_program(
            deepcopy(program),
            phase=ProblemPhase.PLANNING,
        )
    except CheckFailed as error:
        problems = [*_environment_link_problems(environment), *error.problems]
        if has_blocking_problems(problems):
            raise CheckFailed(problems) from error
        raise AssertionError(
            "failed program seal produced no blocking problem"
        ) from error
    return link_verified_program(verified_program, environment)


def _require_scalar_expression(value: object) -> ScalarExpr:
    return value if isinstance(value, ScalarExpr) else as_scalar_expr(value)


def _product_resource_target(
    *,
    resource_port_id: LogicalResourcePortId | str | None,
    physical_resource_id: PhysicalResourceId | str | None,
) -> ResourceTarget | None:
    if resource_port_id is not None and physical_resource_id is not None:
        msg = "product output cannot target both a logical and physical resource"
        raise ValueError(msg)
    if resource_port_id is not None:
        return (
            resource_port_id
            if isinstance(resource_port_id, LogicalResourcePortId)
            else logical_resource_port_id(resource_port_id)
        )
    if physical_resource_id is not None:
        return (
            physical_resource_id
            if isinstance(physical_resource_id, PhysicalResourceId)
            else PhysicalResourceId(physical_resource_id)
        )
    return None
