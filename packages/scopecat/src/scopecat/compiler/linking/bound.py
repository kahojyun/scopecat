"""Locally materialized experiment plan shared by preview and execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from scopecat.compiler.linking.implementations import (
    SelectedLocalImplementation,
    SelectedLocalImplementations,
)
from scopecat.compiler.linking.product_realizations import (
    SelectedLocalProductRealizations,
)
from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.model import Row
from scopecat.compiler.semantic.availability import ValueAvailability
from scopecat.compiler.semantic.model import (
    ActionId,
    ImplementationId,
    OperationId,
    ValueId,
)
from scopecat.compiler.semantic.operation_contract import (
    OperationContract,
    operation_contract_issues,
)
from scopecat.compiler.typed.point_domain import LogicalPointId
from scopecat.compiler.typed.products import InstrumentProductProducer, ProductDef
from scopecat.compiler.typed.program import ResourceRouteIntent
from scopecat.compiler.typed.records import RecordUse
from scopecat.kernel.problems import Problem, has_blocking_problems
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
)
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import ValueType
from scopecat.measurements.results import (
    CoordinateValue,
    MeasurementDatasetSchema,
    MeasurementDType,
)
from scopecat.records.config import RoutingChannelBinding


def _empty_dependencies() -> dict[str, tuple[str, ...]]:
    return {}


def _empty_metadata() -> dict[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class BoundValue:
    """A concrete compute input resolved from config and one point."""

    value: object


@dataclass(frozen=True, slots=True)
class BoundComputeResult:
    """Exact typed value defined by one locally bound compute call."""

    id: ValueId
    value_type: ValueType
    availability: ValueAvailability


@dataclass(frozen=True, slots=True)
class BoundComputeOutput:
    """Reference to an earlier topologically ordered compute call."""

    value_id: ValueId


type BoundComputeInput = BoundValue | BoundComputeOutput


@dataclass(frozen=True, slots=True)
class BoundComputeCall:
    operation_id: OperationId
    implementation: SelectedLocalImplementation = field(repr=False)
    contract: OperationContract
    inputs: Mapping[str, BoundComputeInput]
    result: BoundComputeResult
    cache_key: str
    dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=_empty_dependencies
    )
    payload_id: str | None = None
    payload_schema_id: str | None = None

    def __post_init__(self) -> None:
        issues = operation_contract_issues(self.contract)
        if issues:
            msg = "invalid bound compute contract: " + "; ".join(
                issue.message for issue in issues
            )
            raise ValueError(msg)
        if self.implementation.operation_id != self.operation_id:
            msg = "bound compute implementation must own the invoked operation"
            raise ValueError(msg)
        if self.implementation.operation_contract != self.contract:
            msg = "bound compute implementation contract does not match the call"
            raise ValueError(msg)
        if self.implementation.interface.output_type != self.result.value_type:
            msg = "bound compute output type does not match the selected interface"
            raise ValueError(msg)
        if tuple(sorted(self.inputs)) != self.implementation.interface.input_names:
            msg = "bound compute inputs do not match the selected interface"
            raise ValueError(msg)
        if (self.payload_id is None) != (self.payload_schema_id is None):
            msg = "compute payload id and schema must be present together"
            raise ValueError(msg)

    @property
    def implementation_id(self) -> ImplementationId:
        return self.implementation.implementation_id


@dataclass(frozen=True, slots=True)
class BoundComputeDefinition:
    """Run-level compute identity and its exact declared result facts."""

    operation_id: OperationId
    result: BoundComputeResult


@dataclass(frozen=True, slots=True)
class BoundRoute:
    port_id: LogicalResourcePortId
    resource_id: PhysicalResourceId
    resource_kind: str
    capabilities: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    served_entity_ids: tuple[str, ...] = ()
    product_axis_order: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.resource_kind:
            msg = "bound route resource kind must be non-empty"
            raise ValueError(msg)
        if any(not entity_id for entity_id in self.entity_ids):
            msg = "bound route entity ids must be non-empty"
            raise ValueError(msg)
        if len(self.entity_ids) != len(set(self.entity_ids)):
            msg = "bound route entity ids must be unique"
            raise ValueError(msg)
        if any(not entity_id for entity_id in self.served_entity_ids):
            msg = "bound route served entity ids must be non-empty"
            raise ValueError(msg)
        if len(self.served_entity_ids) != len(set(self.served_entity_ids)):
            msg = "bound route served entity ids must be unique"
            raise ValueError(msg)
        if not set(self.entity_ids) <= set(self.served_entity_ids):
            msg = "bound route entity ids must be served by the resource"
            raise ValueError(msg)
        _validate_bound_entity_target(
            tuple(dict.fromkeys((*self.entity_ids, *self.served_entity_ids))),
            self.channel_bindings,
            label="bound route",
        )


@dataclass(frozen=True, slots=True)
class BoundStateField:
    field_path: str
    value: StateValue
    resource_port_id: LogicalResourcePortId | None = None
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        _validate_bound_entity_target(
            self.entity_ids,
            self.channel_bindings,
            label="bound state field",
        )


@dataclass(frozen=True, slots=True)
class BoundResourceState:
    resource_id: PhysicalResourceId
    capability_id: str
    fields: tuple[BoundStateField, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundActionField:
    id: str
    value: StateValue
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            msg = "bound action field ids must be non-empty"
            raise ValueError(msg)
        _validate_bound_entity_target(
            self.entity_ids,
            self.channel_bindings,
            label="bound action field",
        )


@dataclass(frozen=True, slots=True)
class BoundAction:
    id: ActionId
    resource_id: PhysicalResourceId
    resource_port_id: LogicalResourcePortId
    capability_id: str
    fields: tuple[BoundActionField, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id:
            msg = "bound action capability ids must be non-empty"
            raise ValueError(msg)
        field_ids = tuple(field.id for field in self.fields)
        if len(field_ids) != len(set(field_ids)):
            msg = "bound action field ids must be unique"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BoundAxis:
    id: str
    kind: str
    size: int
    unit: str | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class BoundRecord:
    id: str
    product_use_id: ProductUseId
    product_id: ProductId
    kind: str
    unit: str | None
    dtype: MeasurementDType
    axes: tuple[BoundAxis, ...]
    dims: tuple[str, ...]
    shape: tuple[int, ...]
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    product_use_id: ProductUseId
    product_id: ProductId
    provider_key: str
    capability: str | None
    unit: str | None
    dtype: MeasurementDType
    resource_port_id: LogicalResourcePortId | None = None
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()
    axes: tuple[BoundAxis, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _validate_bound_entity_target(
            self.entity_ids,
            self.channel_bindings,
            label="bound collection product",
        )


@dataclass(frozen=True, slots=True)
class BoundCollect:
    resource_id: PhysicalResourceId
    requests: tuple[CollectionRequest, ...]


@dataclass(frozen=True, slots=True)
class PlannedStateChange:
    point_index: int
    resource_id: PhysicalResourceId
    capability_id: str
    field_path: str
    before: object
    after: object
    resource_port_id: LogicalResourcePortId | None = None
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        _validate_bound_entity_target(
            self.entity_ids,
            self.channel_bindings,
            label="planned state change",
        )

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


def _validate_bound_entity_target(
    entity_ids: Sequence[str],
    channel_bindings: Sequence[RoutingChannelBinding],
    *,
    label: str,
) -> None:
    if any(not entity_id for entity_id in entity_ids):
        msg = f"{label} entity ids must be non-empty"
        raise ValueError(msg)
    if len(entity_ids) != len(set(entity_ids)):
        msg = f"{label} entity ids must be unique"
        raise ValueError(msg)
    unbound = sorted(
        {
            binding.entity_id
            for binding in channel_bindings
            if binding.entity_id not in entity_ids
        }
    )
    if unbound:
        msg = f"{label} channel bindings reference untargeted entities: " + ", ".join(
            unbound
        )
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BoundPoint:
    point_index: int
    logical_id: LogicalPointId
    row: Row
    parameters: ParameterRelationData
    coordinates: Mapping[str, CoordinateValue]
    compute: tuple[BoundComputeCall, ...]
    routes: tuple[BoundRoute, ...]
    desired_state: tuple[BoundResourceState, ...]
    collect: tuple[BoundCollect, ...]
    actions: tuple[BoundAction, ...] = ()

    def __post_init__(self) -> None:
        if self.point_index != self.logical_id.logical_ordinal:
            msg = "bound point index must equal its logical ordinal"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BoundPlan:
    """Complete local per-point plan for one accepted config snapshot."""

    experiment_id: str
    experiment_kind: str
    point_coordinate_ids: tuple[str, ...]
    points: tuple[BoundPoint, ...]
    product_defs: tuple[ProductDef, ...]
    instrument_product_producers: tuple[InstrumentProductProducer, ...]
    product_uses: tuple[ProductUse, ...]
    record_uses: tuple[RecordUse, ...]
    records: tuple[BoundRecord, ...]
    route_intents: tuple[ResourceRouteIntent, ...]
    state_changes: tuple[PlannedStateChange, ...]
    expected_dataset_schema: MeasurementDatasetSchema | None
    compute_definitions: tuple[BoundComputeDefinition, ...]
    local_implementations: SelectedLocalImplementations | None = field(repr=False)
    local_product_realizations: SelectedLocalProductRealizations | None = field(
        repr=False
    )
    problems: tuple[Problem, ...] = ()

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def valid(self) -> bool:
        return not has_blocking_problems(self.problems)

    @property
    def expected_output_ids(self) -> frozenset[str]:
        return frozenset(
            record.id for record in self.records if record.kind == "observable"
        )


def normalize_collection_channel_bindings(
    bindings: Sequence[RoutingChannelBinding],
    *,
    capability: str | None,
) -> tuple[RoutingChannelBinding, ...]:
    selected = tuple(
        binding
        for binding in bindings
        if binding.capability is None
        or capability is None
        or binding.capability == capability
    )
    if capability is not None:
        return selected
    normalized: list[RoutingChannelBinding] = []
    seen: set[tuple[str, str, str | None, tuple[str, ...]]] = set()
    for binding in selected:
        identity = (
            binding.entity_id,
            binding.channel_id,
            binding.line_id,
            tuple(sorted(binding.group_ids)),
        )
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(binding.model_copy(update={"capability": None}))
    return tuple(normalized)
