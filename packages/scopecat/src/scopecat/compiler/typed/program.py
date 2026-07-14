"""Typed transient program produced by the authoring compiler.

Nothing in this module is a durable wire format. ``TypedProgram`` retains the
point domain and explicit dataflow edges needed by later compiler passes,
and deliberately has no schema version or round-trip compatibility promise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from scopecat.compiler.relations.model import (
    RowScopeId,
    ScalarExpr,
    as_scalar_expr,
)
from scopecat.compiler.relations.uses import (
    RelationUse,
    RelationUseId,
    relation_use,
)
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.availability import ValueAvailability
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    ActionId,
    DomainCallId,
    DomainInputPortDef,
    DomainProgramId,
    DomainResultPortDef,
    ImplementationCatalog,
    MeasurementTransformId,
    OperationId,
    SourceMap,
    ValueId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import OperationContract
from scopecat.compiler.semantic.value_expressions import (
    ScalarOrSeriesValueExpr,
    ScalarValueExpr,
    TableValueExpr,
    ValueExpr,
    verify_scalar_value_expr,
)
from scopecat.compiler.typed.action import ActionFieldSpec, ActionSpec
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    DomainProductProducer,
    InstrumentProductProducer,
    MeasurementTransformProductProducer,
    ProductAxisDef,
    ProductDef,
    ProductKind,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.state import (
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    StateSpec,
)
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
    ProductUse,
    ProductUseId,
    product_id,
    product_producer_id,
    product_use,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
    ResourceTarget,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Route, Scalar, String, ValueType
from scopecat.measurements.results import MeasurementDType
from scopecat.measurements.semantics import (
    MeasurementTransformRate,
    MeasurementTransformSemanticContract,
)


class ValueInput(BaseModel):
    """Proof-carrying value evaluated for one compute invocation.

    ``origin_input_ids`` is pre-rewrite provenance. The enclosed proof imports
    describe the final bound plan and are deliberately not used as a substitute
    for that provenance.
    """

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    kind: Literal["value"] = "value"
    value: ValueExpr
    relation_use_id: RelationUseId = Field(default_factory=RelationUseId.fresh)
    origin_input_ids: tuple[str, ...] = ()

    @property
    def value_type(self) -> ValueType:
        return self.value.value_type


class ComputeEdge(BaseModel):
    """Explicit dependency on the result of another compute node."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    kind: Literal["compute"] = "compute"
    value_id: ValueId
    expected_type: ValueType

    @property
    def value_type(self) -> ValueType:
        return self.expected_type


class RouteInput(BaseModel):
    """Explicit dependency on a point-local resolved resource route."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    kind: Literal["route"] = "route"
    port_id: LogicalResourcePortId
    value_type: Route


type ComputeInput = Annotated[
    ValueInput | ComputeEdge | RouteInput,
    Field(discriminator="kind"),
]


class TypedDomainProgram(BaseModel):
    """Opaque domain program retained as trusted frozen transient IR."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: DomainProgramId
    dialect_id: str = Field(min_length=1)
    dialect_version: str = Field(min_length=1)
    body: object = Field(repr=False)
    input_ports: tuple[DomainInputPortDef, ...] = ()
    result_ports: tuple[DomainResultPortDef, ...] = ()

    def __deepcopy__(
        self,
        _memo: dict[int, Any] | None = None,
    ) -> TypedDomainProgram:
        return self


class TypedDomainResultBinding(BaseModel):
    """Exact logical product occurrences produced by one named call result."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: str = Field(min_length=1)
    product_id: ProductId
    producer_id: ProductProducerId
    product_use_ids: tuple[ProductUseId, ...] = ()


class TypedDomainCall(BaseModel):
    """One linked prepare-stage call with executable plan value inputs."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: DomainCallId
    program_id: DomainProgramId
    inputs: dict[str, ValueInput] = Field(default_factory=dict)
    results: tuple[TypedDomainResultBinding, ...] = ()


class TypedMeasurementTransformInput(BaseModel):
    """One exact product-use occurrence consumed by a pure transform role."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: str = Field(min_length=1)
    product_id: ProductId
    product_use_id: ProductUseId


class TypedMeasurementTransformOutput(BaseModel):
    """One transform-produced product and all of its downstream use slots."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: str = Field(min_length=1)
    product_id: ProductId
    producer_id: ProductProducerId
    product_use_ids: tuple[ProductUseId, ...] = ()


class TypedMeasurementTransform(BaseModel):
    """One live authored pure transform in the demand-closed product graph."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: MeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    rate: MeasurementTransformRate
    inputs: tuple[TypedMeasurementTransformInput, ...] = ()
    outputs: tuple[TypedMeasurementTransformOutput, ...] = ()


class TypedComputeOutput(BaseModel):
    """One explicitly identified value defined by a typed compute node."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: ValueId
    value_type: ValueType
    availability: ValueAvailability


class TypedComputeNode(BaseModel):
    """One typed pure-code node in the expanded compute graph."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: OperationId
    contract: OperationContract
    inputs: dict[str, ComputeInput] = Field(default_factory=dict)
    result: TypedComputeOutput


class ResourceRouteIntent(BaseModel):
    """Symbolic resource route retained until point-local compilation."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    port_id: LogicalResourcePortId
    capabilities: tuple[str, ...] = ()
    entity_uses: tuple[RelationUse[ScalarOrSeriesValueExpr], ...] = ()
    fixed_resource_id: PhysicalResourceId | None = None


class TypedProgram(BaseModel):
    """Closed typed compiler output for one run segment."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    point_domain: PointDomain
    route_intents: tuple[ResourceRouteIntent, ...] = ()
    parameter_overlays: tuple[PointParameterOverlay, ...] = ()
    compute_nodes: tuple[TypedComputeNode, ...] = ()
    domain_programs: tuple[TypedDomainProgram, ...] = ()
    domain_calls: tuple[TypedDomainCall, ...] = ()
    measurement_transforms: tuple[TypedMeasurementTransform, ...] = ()
    implementation_catalog: ImplementationCatalog = Field(
        default_factory=ImplementationCatalog,
        exclude=True,
    )
    source_map: SourceMap = Field(default_factory=SourceMap, exclude=True)
    state: tuple[StateSpec, ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    product_defs: tuple[ProductDef, ...] = ()
    instrument_product_producers: tuple[InstrumentProductProducer, ...] = ()
    domain_product_producers: tuple[DomainProductProducer, ...] = ()
    measurement_transform_product_producers: tuple[
        MeasurementTransformProductProducer, ...
    ] = ()
    product_uses: tuple[ProductUse, ...] = ()
    record_uses: tuple[RecordUse, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    """Build a typed point-local cell overlay for internal compiler tests."""

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


def set_state_field(
    resource: ScalarValueExpr | None = None,
    *,
    resource_port_id: LogicalResourcePortId | None = None,
    capability_id: str,
    field_path: str,
    value: ScalarValueExpr | ComputeResultRef,
    route_entities: Sequence[ScalarOrSeriesValueExpr] = (),
) -> StateSpec:
    """Build desired state from orthogonal capability and field identities."""

    if (resource is None) == (resource_port_id is None):
        msg = "state field requires exactly one physical resource or logical port"
        raise ValueError(msg)
    if resource is not None and not isinstance(resource.value_type.atom, String):
        msg = "physical state resource expressions must have string scalar type"
        raise TypeError(msg)

    return StateSpec(
        kind="set",
        resource_target=(
            LogicalStateResourceTarget(port_id=resource_port_id)
            if resource_port_id is not None
            else PhysicalStateResourceTarget(
                use=relation_use(cast("ScalarValueExpr", resource))
            )
        ),
        capability_id=capability_id,
        field_path=field_path,
        value_use=value if isinstance(value, ComputeResultRef) else relation_use(value),
        route_entity_uses=[relation_use(expression) for expression in route_entities],
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


def bind_each(
    relation: TableValueExpr,
    *state: StateSpec,
    row_scope_id: RowScopeId | None = None,
) -> StateSpec:
    return StateSpec(
        kind="for_each",
        relation_use=relation_use(relation),
        row_scope_id=row_scope_id,
        state=list(state),
    )


def invoke_action(
    id: ActionId,  # noqa: A002
    *,
    resource_port_id: LogicalResourcePortId,
    capability_id: str,
    fields: Mapping[str, ScalarValueExpr | ComputeResultRef] | None = None,
) -> ActionSpec:
    """Build one ordered instrument action invoked for every point."""

    return ActionSpec(
        id=id,
        resource_port_id=resource_port_id,
        capability_id=capability_id,
        fields=tuple(
            ActionFieldSpec(
                id=field_id,
                value_use=(
                    value
                    if isinstance(value, ComputeResultRef)
                    else relation_use(value)
                ),
            )
            for field_id, value in (fields or {}).items()
        ),
    )


def _require_scalar_expression(value: object) -> ScalarExpr:
    return value if isinstance(value, ScalarExpr) else as_scalar_expr(value)


def product_axis(
    id: str,  # noqa: A002
    *,
    size: int,
    kind: str | None = None,
    unit: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProductAxisDef:
    return ProductAxisDef(
        id=id,
        kind=kind or id,
        size=size,
        unit=unit,
        metadata=dict(metadata or {}),
    )


def shot_axis(size: int) -> ProductAxisDef:
    return product_axis("shot", size=size, kind="shot", unit="count")


def product_output(
    id: str | ProductId,  # noqa: A002
    *,
    kind: ProductKind = "observable",
    unit: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[ProductAxisDef] = (),
    metadata: dict[str, Any] | None = None,
) -> ProductDef:
    selected_id = id if isinstance(id, ProductId) else product_id(id)
    return ProductDef(
        id=selected_id,
        kind=kind,
        unit=unit,
        dtype=dtype,
        axes=tuple(axes),
        metadata=dict(metadata or {}),
    )


def observable_product(
    id: str | ProductId,  # noqa: A002
    *,
    unit: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[ProductAxisDef] = (),
    metadata: dict[str, Any] | None = None,
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
    metadata: dict[str, Any] | None = None,
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


def record_product(
    product: ProductDef | ProductId,
    *,
    record_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[ProductUse, RecordUse]:
    """Create one product-use occurrence and one durable record consumer."""

    selected_id = product.id if isinstance(product, ProductDef) else product
    use = product_use(selected_id)
    return use, RecordUse(
        id=record_id or selected_id.qualified_name,
        product_use_id=use.id,
        metadata=dict(metadata or {}),
    )


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


def typed_program(
    *,
    id: str,  # noqa: A002
    kind: str,
    point_domain: PointDomain,
    route_intents: Sequence[ResourceRouteIntent] = (),
    parameter_overlays: Sequence[PointParameterOverlay] = (),
    compute_nodes: Sequence[TypedComputeNode] = (),
    domain_programs: Sequence[TypedDomainProgram] = (),
    domain_calls: Sequence[TypedDomainCall] = (),
    measurement_transforms: Sequence[TypedMeasurementTransform] = (),
    implementation_catalog: ImplementationCatalog | None = None,
    source_map: SourceMap | None = None,
    state: Sequence[StateSpec] = (),
    actions: Sequence[ActionSpec] = (),
    product_defs: Sequence[ProductDef] = (),
    instrument_product_producers: Sequence[InstrumentProductProducer] = (),
    domain_product_producers: Sequence[DomainProductProducer] = (),
    measurement_transform_product_producers: Sequence[
        MeasurementTransformProductProducer
    ] = (),
    product_uses: Sequence[ProductUse] = (),
    record_uses: Sequence[RecordUse] = (),
    metadata: dict[str, Any] | None = None,
) -> TypedProgram:
    """Build one low-level typed program with topologically ordered computes."""

    from scopecat.compiler.typed.graph import order_compute_nodes

    return TypedProgram(
        id=id,
        kind=kind,
        point_domain=point_domain,
        route_intents=tuple(route_intents),
        parameter_overlays=tuple(parameter_overlays),
        compute_nodes=order_compute_nodes(compute_nodes),
        domain_programs=tuple(domain_programs),
        domain_calls=tuple(domain_calls),
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


__all__ = [
    "ComputeEdge",
    "ComputeInput",
    "ResourceRouteIntent",
    "RouteInput",
    "TypedComputeNode",
    "TypedComputeOutput",
    "TypedDomainCall",
    "TypedDomainProgram",
    "TypedDomainResultBinding",
    "TypedMeasurementTransform",
    "TypedMeasurementTransformInput",
    "TypedMeasurementTransformOutput",
    "TypedProgram",
    "ValueInput",
    "bind_each",
    "compute_result",
    "instrument_product_producer",
    "invoke_action",
    "observable_product",
    "overlay_parameter_cell",
    "product_axis",
    "product_output",
    "record_product",
    "set_state_field",
    "shot_axis",
    "typed_program",
]
