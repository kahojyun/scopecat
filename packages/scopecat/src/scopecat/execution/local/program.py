"""Transient, explicit program consumed by the local execution engine.

The authoring compiler may use richer symbolic IRs.  This module starts after
configuration linking and point binding: values and routes are concrete, pure
compute dependencies are ordered, and hardware effects are represented as
explicit stages.  The program is intentionally not a durable wire format.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.semantic.operation_contract import (
    OperationContract,
    operation_contract_issues,
)
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import ValueType
from scopecat.measurements.results import (
    CoordinateValue,
    MeasurementDatasetSchema,
)
from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments.contracts import (
    CollectCommand,
    InstrumentActionCommandField,
    InstrumentStateCommandField,
)

type ComputeKernel = Callable[..., object]


def _empty_dependencies() -> dict[str, tuple[str, ...]]:
    return {}


@dataclass(frozen=True, slots=True)
class BoundInput:
    """One already-bound value passed to a pure compute operation."""

    value: object


@dataclass(frozen=True, slots=True)
class OutputInput:
    """Reference an earlier compute result in the same point."""

    value_id: ValueId


type ComputeInput = BoundInput | OutputInput


@dataclass(frozen=True, slots=True)
class PayloadSlot:
    """Command payload materialized from a compute output."""

    id: str
    schema_id: str

    def __post_init__(self) -> None:
        if not self.id or not self.schema_id:
            msg = "payload slot id and schema_id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ComputeResultSlot:
    """Semantic result produced by one point-local compute invocation."""

    id: ValueId
    value_type: ValueType


@dataclass(frozen=True, slots=True)
class ComputeOperation:
    """One point-local pure compute kernel invocation."""

    operation_id: str
    semantic_operation_id: str
    implementation_id: str
    contract: OperationContract
    kernel: ComputeKernel
    inputs: Mapping[str, ComputeInput]
    result: ComputeResultSlot
    dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=_empty_dependencies
    )
    payload_slot: PayloadSlot | None = None
    cache_namespace: str | None = None
    cache_key: object | None = None

    def __post_init__(self) -> None:
        issues = operation_contract_issues(self.contract)
        if issues:
            msg = "invalid local compute contract: " + "; ".join(
                issue.message for issue in issues
            )
            raise ValueError(msg)
        if (
            not self.operation_id
            or not self.semantic_operation_id
            or not self.implementation_id
        ):
            msg = (
                "compute invocation, semantic operation, and implementation ids "
                "must be non-empty"
            )
            raise ValueError(msg)
        if self.cache_namespace is None and self.cache_key is not None:
            msg = "compute cache_key requires cache_namespace"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ComputeStage:
    """Topologically ordered pure compute island."""

    operations: tuple[ComputeOperation, ...]
    kind: Literal["compute"] = field(default="compute", init=False)


@dataclass(frozen=True, slots=True)
class StateTarget:
    """One field that must hold before subsequent point stages execute."""

    capability_id: str
    field_path: str
    value: StateValue
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id or not self.field_path:
            msg = "state target capability_id and field_path must be non-empty"
            raise ValueError(msg)
        if any(not entity_id for entity_id in self.entity_ids):
            msg = "state target entity ids must be non-empty"
            raise ValueError(msg)
        if len(self.entity_ids) != len(set(self.entity_ids)):
            msg = "state target entity ids must be unique"
            raise ValueError(msg)
        if any(
            binding.entity_id not in self.entity_ids
            for binding in self.channel_bindings
        ):
            msg = "state target channel bindings must reference targeted entities"
            raise ValueError(msg)

    def command_field(self, *, resource_id: str) -> InstrumentStateCommandField:
        return InstrumentStateCommandField(
            resource_id=resource_id,
            capability_id=self.capability_id,
            field_path=self.field_path,
            value=self.value.model_copy(deep=True),
            entity_ids=list(self.entity_ids),
            channel_bindings=list(self.channel_bindings),
        )


@dataclass(frozen=True, slots=True)
class ApplyStateOperation:
    """Reconcile a concrete instrument with point-local state targets."""

    operation_id: str
    instrument_id: str
    targets: tuple[StateTarget, ...]

    def __post_init__(self) -> None:
        if not self.operation_id or not self.instrument_id:
            msg = "state operation and instrument ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ApplyStateStage:
    """Explicitly ordered state reconciliation operations."""

    operations: tuple[ApplyStateOperation, ...]
    kind: Literal["apply_state"] = field(default="apply_state", init=False)


@dataclass(frozen=True, slots=True)
class ActionField:
    """One concrete field supplied to a one-shot action."""

    id: str
    value: StateValue
    entity_ids: tuple[str, ...] = ()
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            msg = "action field ids must be non-empty"
            raise ValueError(msg)
        if any(not entity_id for entity_id in self.entity_ids):
            msg = "action field entity ids must be non-empty"
            raise ValueError(msg)
        if len(self.entity_ids) != len(set(self.entity_ids)):
            msg = "action field entity ids must be unique"
            raise ValueError(msg)
        if any(
            binding.entity_id not in self.entity_ids
            for binding in self.channel_bindings
        ):
            msg = "action field channel bindings must reference targeted entities"
            raise ValueError(msg)

    def command_field(self) -> InstrumentActionCommandField:
        return InstrumentActionCommandField(
            field_path=self.id,
            value=self.value.model_copy(deep=True),
            entity_ids=list(self.entity_ids),
            channel_bindings=list(self.channel_bindings),
        )


@dataclass(frozen=True, slots=True)
class InstrumentActionOperation:
    """One action attempt that is always delivered when its stage executes."""

    operation_id: str
    instrument_id: str
    capability_id: str
    fields: tuple[ActionField, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation_id or not self.instrument_id or not self.capability_id:
            msg = "action operation, instrument, and capability ids must be non-empty"
            raise ValueError(msg)
        field_ids = tuple(field.id for field in self.fields)
        if len(field_ids) != len(set(field_ids)):
            msg = "action operation field ids must be unique"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ActionStage:
    """Explicitly ordered one-shot instrument effects."""

    operations: tuple[InstrumentActionOperation, ...]
    kind: Literal["action"] = field(default="action", init=False)


@dataclass(frozen=True, slots=True)
class CollectionResultBinding:
    """Map one provider response key to one logical product-use occurrence."""

    provider_key: str
    product_use_id: ProductUseId
    product_id: ProductId

    def __post_init__(self) -> None:
        if not self.provider_key:
            msg = "collection result provider key must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CollectOperation:
    """One instrument collection command and its logical product bindings."""

    operation_id: str
    instrument_id: str
    command: CollectCommand
    result_bindings: tuple[CollectionResultBinding, ...]

    def __post_init__(self) -> None:
        command = self.command.model_copy(deep=True)
        bindings = tuple(self.result_bindings)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "result_bindings", bindings)
        if not self.operation_id or not self.instrument_id:
            msg = "collect operation and instrument ids must be non-empty"
            raise ValueError(msg)
        if command.instrument_id != self.instrument_id:
            msg = "collect command instrument must match its operation"
            raise ValueError(msg)
        if command.operation_id != self.operation_id:
            msg = "collect command identity must match its operation"
            raise ValueError(msg)
        if command.attempt != 1:
            msg = "collect command attempt is runtime-owned and must start at one"
            raise ValueError(msg)
        request_ids = [request.id for request in command.requests]
        if any(not request_id for request_id in request_ids):
            msg = "collect command product request ids must be non-empty"
            raise ValueError(msg)
        if len(request_ids) != len(set(request_ids)):
            msg = "collect command product request ids must be unique"
            raise ValueError(msg)
        binding_keys = tuple(binding.provider_key for binding in bindings)
        if tuple(request_ids) != binding_keys:
            msg = "collect result bindings must match ordered command product requests"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CollectStage:
    """Explicitly ordered collection operations."""

    operations: tuple[CollectOperation, ...]
    kind: Literal["collect"] = field(default="collect", init=False)


type ExecutionStage = ComputeStage | ApplyStateStage | ActionStage | CollectStage


@dataclass(frozen=True, slots=True)
class PointProgram:
    """Concrete stages for one logical experiment point."""

    point_index: int
    point_uid: str
    coordinates: Mapping[str, CoordinateValue]
    stages: tuple[ExecutionStage, ...]

    def __post_init__(self) -> None:
        if self.point_index < 0:
            msg = "point_index must be nonnegative"
            raise ValueError(msg)
        if not self.point_uid:
            msg = "point_uid must be non-empty"
            raise ValueError(msg)
        _validate_point_stage_order(self)
        _validate_point_compute_order(self)


@dataclass(frozen=True, slots=True)
class RecordProjection:
    """Project one logical product result into one durable observable id."""

    record_id: str
    product_use_id: ProductUseId
    product_id: ProductId

    def __post_init__(self) -> None:
        if not self.record_id:
            msg = "record projection id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExecutionProgram:
    """Concrete local program with an explicit instrument-collected subset."""

    experiment_id: str
    points: tuple[PointProgram, ...]
    product_uses: tuple[ProductUse, ...]
    collection_product_use_ids: tuple[ProductUseId, ...]
    record_projections: tuple[RecordProjection, ...]
    resource_order: tuple[str, ...] = ()
    resource_claims: tuple[ResourceClaim, ...] = ()
    expected_dataset_schema: MeasurementDatasetSchema | None = None

    def __post_init__(self) -> None:
        if not self.experiment_id:
            msg = "execution program experiment_id must be non-empty"
            raise ValueError(msg)
        indices = [point.point_index for point in self.points]
        if indices != list(range(len(self.points))):
            msg = "execution program points must be contiguous and ordered from zero"
            raise ValueError(msg)
        point_uids = [point.point_uid for point in self.points]
        if len(point_uids) != len(set(point_uids)):
            msg = "execution program point_uids must be unique"
            raise ValueError(msg)
        operation_ids = [
            operation_id
            for point in self.points
            for operation_id in _point_operation_ids(point)
        ]
        if len(operation_ids) != len(set(operation_ids)):
            msg = "execution program operation ids must be globally unique"
            raise ValueError(msg)
        uses_by_id = {use.id: use for use in self.product_uses}
        if len(uses_by_id) != len(self.product_uses):
            msg = "execution program product-use identities must be unique"
            raise ValueError(msg)
        collection_use_ids = tuple(self.collection_product_use_ids)
        if len(collection_use_ids) != len(set(collection_use_ids)):
            msg = "execution collection product-use identities must be unique"
            raise ValueError(msg)
        unknown_collection_use_ids = tuple(
            use_id for use_id in collection_use_ids if use_id not in uses_by_id
        )
        if unknown_collection_use_ids:
            msg = (
                "execution collection inventory references unknown logical product uses"
            )
            raise ValueError(msg)
        canonical_collection_use_ids = tuple(
            use.id for use in self.product_uses if use.id in set(collection_use_ids)
        )
        if collection_use_ids != canonical_collection_use_ids:
            msg = "execution collection inventory must follow logical product-use order"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "collection_product_use_ids",
            collection_use_ids,
        )
        record_ids = [projection.record_id for projection in self.record_projections]
        if len(record_ids) != len(set(record_ids)):
            msg = "execution program record projection ids must be unique"
            raise ValueError(msg)
        for projection in self.record_projections:
            use = uses_by_id.get(projection.product_use_id)
            if use is None or use.product_id != projection.product_id:
                msg = "record projections must reference retained logical product uses"
                raise ValueError(msg)
            if projection.product_use_id not in set(collection_use_ids):
                msg = (
                    "current local execution record projections require a "
                    "collected product use"
                )
                raise ValueError(msg)
        expected_collection_use_ids = set(collection_use_ids)
        for point in self.points:
            bindings = [
                binding
                for stage in point.stages
                if isinstance(stage, CollectStage)
                for operation in stage.operations
                for binding in operation.result_bindings
            ]
            for binding in bindings:
                use = uses_by_id.get(binding.product_use_id)
                if use is None or use.product_id != binding.product_id:
                    msg = (
                        "collection result bindings must reference their exact "
                        "logical product uses"
                    )
                    raise ValueError(msg)
            actual_use_ids = [binding.product_use_id for binding in bindings]
            if len(actual_use_ids) != len(set(actual_use_ids)):
                msg = "each point requires one producer per collected product use"
                raise ValueError(msg)
            if set(actual_use_ids) != expected_collection_use_ids:
                msg = (
                    "each point must exactly realize the execution collection "
                    "product-use inventory"
                )
                raise ValueError(msg)
            for stage in point.stages:
                if not isinstance(stage, CollectStage):
                    continue
                for operation in stage.operations:
                    if operation.command.point_index != point.point_index:
                        msg = "collect command point index must match its point program"
                        raise ValueError(msg)
                    if operation.command.point_count != len(self.points):
                        msg = (
                            "collect command point count must match the execution "
                            "program"
                        )
                        raise ValueError(msg)
        used_instruments = tuple(
            dict.fromkeys(
                operation.instrument_id
                for point in self.points
                for stage in point.stages
                if isinstance(stage, ApplyStateStage | ActionStage | CollectStage)
                for operation in stage.operations
            )
        )
        if not self.resource_order:
            object.__setattr__(self, "resource_order", used_instruments)
        elif set(self.resource_order) != set(used_instruments):
            msg = "resource_order must contain every used instrument exactly once"
            raise ValueError(msg)
        if len(self.resource_order) != len(set(self.resource_order)):
            msg = "resource_order must not contain duplicates"
            raise ValueError(msg)
        if not self.resource_claims:
            object.__setattr__(
                self,
                "resource_claims",
                tuple(ResourceClaim(id=item) for item in self.resource_order),
            )
        _validate_resource_claims(self)

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def expected_measurement_indices(self) -> set[int]:
        return {point.point_index for point in self.points}

    @property
    def expected_output_ids(self) -> frozenset[str]:
        return frozenset(projection.record_id for projection in self.record_projections)


def _point_operation_ids(point: PointProgram) -> tuple[str, ...]:
    return tuple(
        operation.operation_id
        for stage in point.stages
        for operation in stage.operations
    )


def _validate_point_compute_order(point: PointProgram) -> None:
    available: set[ValueId] = set()
    for stage in point.stages:
        if not isinstance(stage, ComputeStage):
            continue
        for operation in stage.operations:
            missing = sorted(
                (
                    value.value_id
                    for value in operation.inputs.values()
                    if isinstance(value, OutputInput)
                    and value.value_id not in available
                ),
                key=lambda value_id: value_id.qualified_name,
            )
            if missing:
                msg = (
                    f"compute operation {operation.operation_id!r} references "
                    "results that are not topologically available: "
                    + ", ".join(value_id.qualified_name for value_id in missing)
                )
                raise ValueError(msg)
            if operation.result.id in available:
                msg = (
                    "point compute operations must produce unique result ids: "
                    f"{operation.result.id.qualified_name}"
                )
                raise ValueError(msg)
            available.add(operation.result.id)


def _validate_point_stage_order(point: PointProgram) -> None:
    order = {"compute": 0, "apply_state": 1, "action": 2, "collect": 3}
    stage_kinds = [stage.kind for stage in point.stages]
    if len(stage_kinds) != len(set(stage_kinds)):
        msg = "point execution stages must not repeat a stage kind"
        raise ValueError(msg)
    if [order[kind] for kind in stage_kinds] != sorted(
        order[kind] for kind in stage_kinds
    ):
        msg = (
            "point execution stages must follow compute, apply_state, action, "
            "collect order"
        )
        raise ValueError(msg)


def _validate_resource_claims(program: ExecutionProgram) -> None:
    claim_keys = [(claim.kind, claim.id) for claim in program.resource_claims]
    if len(claim_keys) != len(set(claim_keys)):
        msg = "resource_claims must be unique by kind and id"
        raise ValueError(msg)
    claimed_instruments = {
        claim.id for claim in program.resource_claims if claim.kind == "instrument"
    }
    missing = sorted(set(program.resource_order) - claimed_instruments)
    if missing:
        msg = "resource_claims are missing instruments: " + ", ".join(missing)
        raise ValueError(msg)


__all__ = [
    "ActionField",
    "ActionStage",
    "ApplyStateOperation",
    "ApplyStateStage",
    "BoundInput",
    "CollectOperation",
    "CollectStage",
    "CollectionResultBinding",
    "ComputeInput",
    "ComputeKernel",
    "ComputeOperation",
    "ComputeResultSlot",
    "ComputeStage",
    "ExecutionProgram",
    "ExecutionStage",
    "InstrumentActionOperation",
    "OutputInput",
    "PayloadSlot",
    "PointProgram",
    "RecordProjection",
    "ResourceClaim",
    "StateTarget",
]
