"""Locally materialized experiment plan shared by preview and execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from scopecat.compiler.linking.implementations import (
    SelectedLocalImplementation,
)
from scopecat.compiler.linking.product_realizations import (
    SelectedLocalProductRealizations,
)
from scopecat.compiler.relations.model import Row
from scopecat.compiler.semantic.model import (
    ActionId,
    ImplementationId,
    OperationId,
    ValueId,
)
from scopecat.compiler.semantic.operation_contract import OperationContract
from scopecat.compiler.typed.point_domain import LogicalPointId
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

    @property
    def implementation_id(self) -> ImplementationId:
        return self.implementation.implementation_id


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


@dataclass(frozen=True, slots=True)
class BoundStateField:
    field_path: str
    value: StateValue
    resource_port_id: LogicalResourcePortId | None = None
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[RoutingChannelBinding, ...] = ()


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


@dataclass(frozen=True, slots=True)
class BoundAction:
    id: ActionId
    resource_id: PhysicalResourceId
    resource_port_id: LogicalResourcePortId
    capability_id: str
    fields: tuple[BoundActionField, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundAxis:
    id: str
    kind: str
    size: int
    unit: str | None = None
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


@dataclass(frozen=True, slots=True)
class BoundCollect:
    resource_id: PhysicalResourceId
    requests: tuple[CollectionRequest, ...]


@dataclass(frozen=True, slots=True)
class BoundPoint:
    point_index: int
    logical_id: LogicalPointId
    row: Row
    coordinates: Mapping[str, CoordinateValue]
    compute: tuple[BoundComputeCall, ...]
    routes: tuple[BoundRoute, ...]
    desired_state: tuple[BoundResourceState, ...]
    collect: tuple[BoundCollect, ...]
    actions: tuple[BoundAction, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundPlan:
    """Executable local per-point plan for one accepted config snapshot."""

    experiment_id: str
    points: tuple[BoundPoint, ...]
    product_uses: tuple[ProductUse, ...]
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
