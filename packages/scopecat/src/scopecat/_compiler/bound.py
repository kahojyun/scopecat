"""Locally materialized experiment plan shared by preview and execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from scopecat._compiler.implementations import (
    SelectedLocalImplementation,
    SelectedLocalImplementations,
)
from scopecat._compiler.point_domain import LogicalPointId
from scopecat._compiler.product_realizations import SelectedLocalProductRealizations
from scopecat._compiler.products import InstrumentProductProducer, ProductDef
from scopecat._compiler.program import ResourceRouteIntent
from scopecat._compiler.records import RecordUse
from scopecat._operation_contract import OperationContract, operation_contract_issues
from scopecat._product_identity import ProductId, ProductUse, ProductUseId
from scopecat._relation_backend import ParameterRelationData
from scopecat._relations import Row
from scopecat._resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
)
from scopecat._semantic_graph import ImplementationId, OperationId, ValueId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.state import StateValue
from scopecat.problems import Problem, has_blocking_problems
from scopecat.results import (
    CoordinateValue,
    MeasurementDatasetSchema,
    MeasurementDType,
)
from scopecat.value_types import ValueType


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
    relation_backend_id: str
    compute_definitions: tuple[BoundComputeDefinition, ...]
    local_implementations: SelectedLocalImplementations | None = field(repr=False)
    local_product_realizations: SelectedLocalProductRealizations | None = field(
        repr=False
    )
    problems: tuple[Problem, ...] = ()

    def __post_init__(self) -> None:
        if not self.relation_backend_id:
            msg = "bound plan relation backend id must be non-empty"
            raise ValueError(msg)
        definition_operation_ids = tuple(
            definition.operation_id for definition in self.compute_definitions
        )
        result_ids = tuple(
            definition.result.id for definition in self.compute_definitions
        )
        definitions_by_operation = {
            definition.operation_id: definition
            for definition in self.compute_definitions
        }
        blocking = has_blocking_problems(self.problems)
        if not blocking:
            if len(definition_operation_ids) != len(set(definition_operation_ids)):
                msg = "bound compute definitions require unique operation identities"
                raise ValueError(msg)
            if len(result_ids) != len(set(result_ids)):
                msg = "bound compute definitions require unique result identities"
                raise ValueError(msg)
            unsupported_results = tuple(
                definition.result.id
                for definition in self.compute_definitions
                if definition.result.availability
                != ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)
            )
            if unsupported_results:
                msg = (
                    "valid local bound plans require execute/point compute results: "
                    + ", ".join(
                        result_id.qualified_name for result_id in unsupported_results
                    )
                )
                raise ValueError(msg)
            self._validate_product_realization()
            expected_ports = tuple(intent.port_id for intent in self.route_intents)
            if len(expected_ports) != len(set(expected_ports)):
                msg = "valid bound plans require unique logical route-port identities"
                raise ValueError(msg)
            for point in self.points:
                actual_ports = tuple(route.port_id for route in point.routes)
                if actual_ports != expected_ports:
                    msg = (
                        "valid bound points must exactly cover the ordered logical "
                        "resource-port inventory"
                    )
                    raise ValueError(msg)
                for intent, route in zip(
                    self.route_intents,
                    point.routes,
                    strict=True,
                ):
                    if route.capabilities != intent.capabilities:
                        msg = (
                            "valid bound routes must retain their declared capability "
                            "contract"
                        )
                        raise ValueError(msg)
                    if not route.resource_kind:
                        msg = "valid bound routes require a physical resource kind"
                        raise ValueError(msg)
                    if (
                        intent.fixed_resource_id is not None
                        and route.resource_id != intent.fixed_resource_id
                    ):
                        msg = (
                            "valid bound routes must retain their fixed physical "
                            "resource identity"
                        )
                        raise ValueError(msg)
        if self.local_implementations is None:
            if not blocking:
                msg = (
                    "valid bound plans require a sealed local implementation selection"
                )
                raise ValueError(msg)
            if any(point.compute for point in self.points):
                msg = "bound compute calls require a local implementation selection"
                raise ValueError(msg)
            return
        selected_operation_ids = tuple(
            entry.operation_id for entry in self.local_implementations.entries
        )
        if selected_operation_ids != definition_operation_ids:
            msg = "local implementation selection must cover the compute inventory"
            raise ValueError(msg)
        for definition, selected in zip(
            self.compute_definitions,
            self.local_implementations.entries,
            strict=True,
        ):
            if definition.result.value_type != selected.interface.output_type:
                msg = (
                    "bound compute definition result does not match its selected "
                    "interface"
                )
                raise ValueError(msg)
        for point in self.points:
            for call in point.compute:
                selected = self.local_implementations.selected_for(call.operation_id)
                if selected is not call.implementation:
                    msg = (
                        "bound compute call must retain the plan's exact selected "
                        "implementation"
                    )
                    raise ValueError(msg)
                definition = definitions_by_operation.get(call.operation_id)
                if definition is None or call.result != definition.result:
                    msg = (
                        "bound compute call must retain its exact declared result facts"
                    )
                    raise ValueError(msg)
            if not blocking:
                actual_definitions = tuple(
                    BoundComputeDefinition(call.operation_id, call.result)
                    for call in point.compute
                )
                if actual_definitions != self.compute_definitions:
                    msg = (
                        "valid bound points must retain the complete ordered compute "
                        "definition inventory"
                    )
                    raise ValueError(msg)
                available_results: dict[ValueId, BoundComputeResult] = {}
                for call in point.compute:
                    expected_inputs = dict(call.implementation.interface.inputs)
                    for input_name, input_value in call.inputs.items():
                        if not isinstance(input_value, BoundComputeOutput):
                            continue
                        producer_result = available_results.get(input_value.value_id)
                        if producer_result is None:
                            msg = (
                                "bound compute output inputs must reference an "
                                "earlier result definition"
                            )
                            raise ValueError(msg)
                        if producer_result.value_type != expected_inputs[input_name]:
                            msg = (
                                "bound compute output input type does not match its "
                                "selected interface"
                            )
                            raise ValueError(msg)
                    available_results[call.result.id] = call.result
                actual_implementations = tuple(
                    call.implementation for call in point.compute
                )
                expected_implementations = self.local_implementations.entries
                if any(
                    selected is not retained
                    for selected, retained in zip(
                        expected_implementations,
                        actual_implementations,
                        strict=True,
                    )
                ):
                    msg = (
                        "valid bound points must retain the complete ordered local "
                        "implementation selection"
                    )
                    raise ValueError(msg)

    def _validate_product_realization(self) -> None:
        products_by_id = {product.id: product for product in self.product_defs}
        if len(products_by_id) != len(self.product_defs):
            msg = "valid bound plans require unique logical product definitions"
            raise ValueError(msg)
        producers_by_id = {
            producer.id: producer for producer in self.instrument_product_producers
        }
        if len(producers_by_id) != len(self.instrument_product_producers):
            msg = "valid bound plans require unique instrument product producers"
            raise ValueError(msg)
        if any(
            producer.product_id not in products_by_id
            for producer in self.instrument_product_producers
        ):
            msg = "valid instrument product producers must reference retained products"
            raise ValueError(msg)
        uses_by_id = {use.id: use for use in self.product_uses}
        if len(uses_by_id) != len(self.product_uses):
            msg = "valid bound plans require unique logical product uses"
            raise ValueError(msg)
        if any(use.product_id not in products_by_id for use in self.product_uses):
            msg = "valid bound product uses must reference retained definitions"
            raise ValueError(msg)
        if self.local_product_realizations is None:
            msg = "valid bound plans require sealed local product realizations"
            raise ValueError(msg)
        selected = self.local_product_realizations.entries
        if tuple(entry.product_use_id for entry in selected) != tuple(
            use.id for use in self.product_uses
        ):
            msg = (
                "local product realizations must exactly cover the ordered use "
                "inventory"
            )
            raise ValueError(msg)
        for entry, use in zip(selected, self.product_uses, strict=True):
            product = products_by_id[use.product_id]
            producer = producers_by_id.get(entry.producer_id)
            if entry.product_id != use.product_id or entry.product != product:
                msg = "local product realizations must retain the selected product"
                raise ValueError(msg)
            if (
                producer is None
                or entry.producer != producer
                or producer.product_id != product.id
            ):
                msg = "local product realizations must retain the selected producer"
                raise ValueError(msg)
            applicable_producers = tuple(
                candidate
                for candidate in self.instrument_product_producers
                if candidate.product_id == product.id
            )
            if applicable_producers != (producer,):
                msg = (
                    "local product realizations require exactly one retained "
                    "instrument producer per demanded product"
                )
                raise ValueError(msg)
            if (
                producer.resource_target is not None
                and entry.implicit_resource_id is not None
            ):
                msg = "explicit producer targets cannot retain an implicit resource"
                raise ValueError(msg)
            if producer.resource_target is None and entry.implicit_resource_id is None:
                msg = "implicit producer targets require a selected physical resource"
                raise ValueError(msg)
        self._validate_record_projections(products_by_id, uses_by_id)
        expected_use_ids = {entry.product_use_id for entry in selected}
        realizations_by_use = {entry.product_use_id: entry for entry in selected}
        for point in self.points:
            requests: list[CollectionRequest] = []
            collects_by_use: dict[ProductUseId, BoundCollect] = {}
            for collect in point.collect:
                for request in collect.requests:
                    requests.append(request)
                    collects_by_use[request.product_use_id] = collect
            requests_by_use = {request.product_use_id: request for request in requests}
            if len(requests_by_use) != len(requests):
                msg = "bound collection requests require unique product-use identities"
                raise ValueError(msg)
            if set(requests_by_use) != expected_use_ids:
                msg = "each bound point must exactly realize every logical product use"
                raise ValueError(msg)
            for use_id, request in requests_by_use.items():
                use = uses_by_id[use_id]
                if request.product_id != use.product_id:
                    msg = (
                        "collection requests must retain their logical product identity"
                    )
                    raise ValueError(msg)
                product = products_by_id[use.product_id]
                self._validate_collection_request(
                    point,
                    collects_by_use[use_id],
                    request,
                    product,
                    realizations_by_use[use_id].producer,
                    realizations_by_use[use_id].implicit_resource_id,
                )

    def _validate_record_projections(
        self,
        products_by_id: Mapping[ProductId, ProductDef],
        uses_by_id: Mapping[ProductUseId, ProductUse],
    ) -> None:
        if tuple(record.id for record in self.records) != tuple(
            record.id for record in self.record_uses
        ):
            msg = "bound records must exactly cover the ordered record-use inventory"
            raise ValueError(msg)
        record_ids = [record.id for record in self.record_uses]
        if len(record_ids) != len(set(record_ids)):
            msg = "bound record-use identities must be unique"
            raise ValueError(msg)
        for record_use, record in zip(self.record_uses, self.records, strict=True):
            use = uses_by_id.get(record_use.product_use_id)
            if use is None or record.product_use_id != use.id:
                msg = "bound records must reference their exact logical product use"
                raise ValueError(msg)
            product = products_by_id[use.product_id]
            expected_axes = tuple(
                BoundAxis(
                    id=axis.id,
                    kind=axis.kind,
                    size=axis.size,
                    unit=axis.unit,
                    metadata=axis.metadata,
                )
                for axis in product.axes
            )
            if (
                record.product_id != product.id
                or record.kind != product.kind
                or record.unit != product.unit
                or record.dtype != product.dtype
                or record.axes != expected_axes
                or record.dims != ("point", *(axis.id for axis in product.axes))
                or record.shape
                != (len(self.points), *(axis.size for axis in product.axes))
                or dict(record.metadata) != {**product.metadata, **record_use.metadata}
            ):
                msg = "bound record projection does not match product and record use"
                raise ValueError(msg)

    @staticmethod
    def _validate_collection_request(
        point: BoundPoint,
        collect: BoundCollect,
        request: CollectionRequest,
        product: ProductDef,
        producer: InstrumentProductProducer,
        implicit_resource_id: PhysicalResourceId | None,
    ) -> None:
        expected_axes = tuple(
            BoundAxis(
                id=axis.id,
                kind=axis.kind,
                size=axis.size,
                unit=axis.unit,
                metadata=axis.metadata,
            )
            for axis in product.axes
        )
        if (
            request.unit != product.unit
            or request.dtype != product.dtype
            or request.axes != expected_axes
        ):
            msg = "collection request does not match its logical product definition"
            raise ValueError(msg)
        if (
            request.provider_key != producer.provider_key
            or request.capability != producer.capability
            or dict(request.metadata) != producer.metadata
        ):
            msg = "collection request does not match its selected producer contract"
            raise ValueError(msg)
        target = producer.resource_target
        if isinstance(target, PhysicalResourceId):
            if (
                collect.resource_id != target
                or request.resource_port_id is not None
                or request.entity_ids
                or request.channel_bindings
            ):
                msg = "collection request does not retain its physical producer target"
                raise ValueError(msg)
            return
        if isinstance(target, LogicalResourcePortId):
            route = next(
                (item for item in point.routes if item.port_id == target),
                None,
            )
            if (
                route is None
                or collect.resource_id != route.resource_id
                or request.resource_port_id != target
            ):
                msg = "collection request does not retain its logical producer target"
                raise ValueError(msg)
            expected_bindings = normalize_collection_channel_bindings(
                route.channel_bindings,
                capability=producer.capability,
            )
            expected_entities = route.entity_ids or tuple(
                dict.fromkeys(binding.entity_id for binding in expected_bindings)
            )
            if (
                request.entity_ids != expected_entities
                or request.channel_bindings != expected_bindings
            ):
                msg = (
                    "collection request does not retain its routed entity and "
                    "channel target"
                )
                raise ValueError(msg)
            return
        if implicit_resource_id is None or collect.resource_id != implicit_resource_id:
            msg = "collection request does not retain its selected implicit target"
            raise ValueError(msg)
        if (
            request.resource_port_id is not None
            or request.entity_ids
            or request.channel_bindings
        ):
            msg = "implicitly targeted collection request has an invalid routed target"
            raise ValueError(msg)

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


__all__ = [
    "BoundAxis",
    "BoundCollect",
    "BoundComputeCall",
    "BoundComputeDefinition",
    "BoundComputeInput",
    "BoundComputeOutput",
    "BoundComputeResult",
    "BoundPlan",
    "BoundPoint",
    "BoundRecord",
    "BoundResourceState",
    "BoundRoute",
    "BoundStateField",
    "BoundValue",
    "CollectionRequest",
    "PlannedStateChange",
    "normalize_collection_channel_bindings",
]
