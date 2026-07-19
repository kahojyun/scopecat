"""Typed transient program produced by the authoring compiler.

Nothing in this module is a durable wire format. ``CoreProgram`` retains the
point domain and explicit dataflow edges needed by later compiler passes,
and deliberately has no schema version or round-trip compatibility promise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.relations.model import (
    RowScopeId,
)
from scopecat.compiler.relations.specialization import BindingTime
from scopecat.compiler.relations.uses import (
    RelationUse,
    RelationUseId,
    relation_use,
)
from scopecat.compiler.semantic.availability import ValueAvailability
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    ActionId,
    DomainInputPortDef,
    DomainProgramId,
    DomainResultPortDef,
    ImplementationCatalog,
    MeasurementTransformId,
    OperationId,
    SourceMap,
    ValueId,
)
from scopecat.compiler.semantic.operation_contract import OperationContract
from scopecat.compiler.semantic.value_expressions import (
    ScalarOrSeriesValueExpr,
    ScalarValueExpr,
    TableValueExpr,
    ValueExpr,
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
    ForEachStateSpec,
    LogicalStateResourceTarget,
    PhysicalStateResourceTarget,
    SetStateSpec,
    StateSpecVariant,
)
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
    ProductUse,
    ProductUseId,
    product_id,
    product_use,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
)
from scopecat.kernel.value_types import Route, String, ValueType
from scopecat.measurements.results import MeasurementDType
from scopecat.measurements.semantics import (
    MeasurementTransformRate,
    MeasurementTransformSemanticContract,
)


@dataclass(frozen=True, slots=True)
class ValueInput:
    """Proof-carrying value evaluated for one compute invocation.

    ``origin_input_ids`` is pre-rewrite provenance. The enclosed proof imports
    describe the final materialized local semantics and are deliberately not used
    as a substitute for that provenance.
    """

    value: ValueExpr
    relation_use_id: RelationUseId = field(default_factory=RelationUseId.fresh)
    origin_input_ids: tuple[str, ...] = ()
    binding_time: BindingTime | None = None

    @property
    def value_type(self) -> ValueType:
        return self.value.value_type


@dataclass(frozen=True, slots=True)
class ComputeEdge:
    """Explicit dependency on the result of another compute node."""

    value_id: ValueId
    expected_type: ValueType

    @property
    def value_type(self) -> ValueType:
        return self.expected_type


@dataclass(frozen=True, slots=True)
class RouteInput:
    """Explicit dependency on a point-local resolved resource route."""

    port_id: LogicalResourcePortId
    value_type: Route


type ComputeInput = ValueInput | ComputeEdge | RouteInput


def _empty_value_inputs() -> dict[str, ValueInput]:
    return {}


def _empty_compute_inputs() -> dict[str, ComputeInput]:
    return {}


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class TypedDomainProgram:
    """Opaque domain program retained as trusted frozen transient IR."""

    id: DomainProgramId
    dialect_id: str
    dialect_version: str
    body: object = field(repr=False)
    input_ports: tuple[DomainInputPortDef, ...] = ()
    result_ports: tuple[DomainResultPortDef, ...] = ()

    def __post_init__(self) -> None:
        if not self.dialect_id or not self.dialect_version:
            msg = "domain program dialect id and version must be non-empty"
            raise ValueError(msg)

    def __deepcopy__(
        self,
        _memo: dict[int, object] | None = None,
    ) -> TypedDomainProgram:
        return self


@dataclass(frozen=True, slots=True)
class TypedDomainResultBinding:
    """Exact logical product occurrences produced by one named domain result."""

    id: str
    product_id: ProductId
    producer_id: ProductProducerId
    product_use_ids: tuple[ProductUseId, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            msg = "typed domain result id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TypedDomainExecution:
    """One domain program with executable plan inputs and result bindings."""

    id: str
    program: TypedDomainProgram
    inputs: Mapping[str, ValueInput] = field(default_factory=_empty_value_inputs)
    results: tuple[TypedDomainResultBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("typed domain execution id must be non-empty")
        selected_inputs: dict[str, ValueInput] = dict(self.inputs)
        object.__setattr__(self, "inputs", selected_inputs)


type CoreEffect = StateSpecVariant | ActionSpec | TypedDomainExecution


@dataclass(frozen=True, slots=True)
class TypedMeasurementTransformInput:
    """One exact product-use occurrence consumed by a pure transform role."""

    id: str
    product_id: ProductId
    product_use_id: ProductUseId

    def __post_init__(self) -> None:
        if not self.id:
            msg = "measurement transform input id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TypedMeasurementTransformOutput:
    """One transform-produced product and all of its downstream use slots."""

    id: str
    product_id: ProductId
    producer_id: ProductProducerId
    product_use_ids: tuple[ProductUseId, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            msg = "measurement transform output id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TypedMeasurementTransform:
    """One live authored pure transform in the demand-closed product graph."""

    id: MeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    rate: MeasurementTransformRate
    inputs: tuple[TypedMeasurementTransformInput, ...] = ()
    outputs: tuple[TypedMeasurementTransformOutput, ...] = ()


@dataclass(frozen=True, slots=True)
class TypedComputeOutput:
    """One explicitly identified value defined by a typed compute node."""

    id: ValueId
    value_type: ValueType
    availability: ValueAvailability


@dataclass(frozen=True, slots=True)
class TypedComputeNode:
    """One typed pure-code node in the expanded compute graph."""

    id: OperationId
    contract: OperationContract
    result: TypedComputeOutput
    inputs: Mapping[str, ComputeInput] = field(default_factory=_empty_compute_inputs)

    def __post_init__(self) -> None:
        selected_inputs: dict[str, ComputeInput] = dict(self.inputs)
        object.__setattr__(self, "inputs", selected_inputs)


@dataclass(frozen=True, slots=True)
class ResourceRouteIntent:
    """Symbolic resource route retained until point-local compilation."""

    port_id: LogicalResourcePortId
    capabilities: tuple[str, ...] = ()
    entity_uses: tuple[RelationUse[ScalarOrSeriesValueExpr], ...] = ()
    fixed_resource_id: PhysicalResourceId | None = None


@dataclass(frozen=True, slots=True)
class CoreProgram:
    """Canonical typed meaning of one authored experiment."""

    id: str
    kind: str
    point_domain: PointDomain
    route_intents: tuple[ResourceRouteIntent, ...] = ()
    parameter_overlays: tuple[PointParameterOverlay, ...] = ()
    compute_nodes: tuple[TypedComputeNode, ...] = ()
    effects: tuple[CoreEffect, ...] = ()
    measurement_transforms: tuple[TypedMeasurementTransform, ...] = ()
    implementation_catalog: ImplementationCatalog = field(
        default_factory=ImplementationCatalog
    )
    source_map: SourceMap = field(default_factory=SourceMap)
    product_defs: tuple[ProductDef, ...] = ()
    instrument_product_producers: tuple[InstrumentProductProducer, ...] = ()
    domain_product_producers: tuple[DomainProductProducer, ...] = ()
    measurement_transform_product_producers: tuple[
        MeasurementTransformProductProducer, ...
    ] = ()
    product_uses: tuple[ProductUse, ...] = ()
    record_uses: tuple[RecordUse, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.id or not self.kind:
            msg = "core program id and kind must be non-empty"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
                path=f"core program {self.id!r} metadata",
            ),
        )


def core_domain_executions(program: CoreProgram) -> tuple[TypedDomainExecution, ...]:
    return tuple(
        effect for effect in program.effects if isinstance(effect, TypedDomainExecution)
    )


def core_actions(program: CoreProgram) -> tuple[ActionSpec, ...]:
    return tuple(effect for effect in program.effects if isinstance(effect, ActionSpec))


def core_state(program: CoreProgram) -> tuple[StateSpecVariant, ...]:
    return tuple(
        effect
        for effect in program.effects
        if isinstance(effect, SetStateSpec | ForEachStateSpec)
    )


def set_state_field(
    resource: ScalarValueExpr | None = None,
    *,
    resource_port_id: LogicalResourcePortId | None = None,
    capability_id: str,
    field_path: str,
    value: ScalarValueExpr | ComputeResultRef,
    route_entities: Sequence[ScalarOrSeriesValueExpr] = (),
) -> SetStateSpec:
    """Build desired state from orthogonal capability and field identities."""

    if (resource is None) == (resource_port_id is None):
        msg = "state field requires exactly one physical resource or logical port"
        raise ValueError(msg)
    if resource is not None and not isinstance(resource.value_type.atom, String):
        msg = "physical state resource expressions must have string scalar type"
        raise TypeError(msg)

    return SetStateSpec(
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
        route_entity_uses=tuple(
            relation_use(expression) for expression in route_entities
        ),
    )


def bind_each(
    relation: TableValueExpr,
    *state: StateSpecVariant,
    row_scope_id: RowScopeId | None = None,
) -> ForEachStateSpec:
    return ForEachStateSpec(
        relation_use=relation_use(relation),
        state=tuple(state),
        row_scope_id=row_scope_id,
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


def product_axis(
    id: str,  # noqa: A002
    *,
    size: int,
    kind: str | None = None,
    unit: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> ProductAxisDef:
    return ProductAxisDef(
        id=id,
        kind=kind or id,
        size=size,
        unit=unit,
        metadata=metadata or {},
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
    metadata: Mapping[str, JsonValue] | None = None,
) -> ProductDef:
    selected_id = id if isinstance(id, ProductId) else product_id(id)
    return ProductDef(
        id=selected_id,
        kind=kind,
        unit=unit,
        dtype=dtype,
        axes=tuple(axes),
        metadata=metadata or {},
    )


def record_product(
    product: ProductDef | ProductId,
    *,
    record_id: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> tuple[ProductUse, RecordUse]:
    """Create one product-use occurrence and one durable record consumer."""

    selected_id = product.id if isinstance(product, ProductDef) else product
    use = product_use(selected_id)
    return use, RecordUse(
        id=record_id or selected_id.qualified_name,
        product_use_id=use.id,
        metadata=metadata or {},
    )
