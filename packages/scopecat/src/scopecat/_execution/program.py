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

from scopecat.instruments.sdk import (
    CollectCommand,
    CommandChannelBinding,
    InstrumentStateCommandField,
)
from scopecat.models.state import StateValue
from scopecat.results import (
    CoordinateValue,
    MeasurementDatasetSchema,
)
from scopecat.value_types import ValueType

type ComputeKernel = Callable[..., object]


def _empty_dependencies() -> dict[str, tuple[str, ...]]:
    return {}


@dataclass(frozen=True, slots=True)
class BoundInput:
    """One already-bound value passed to a pure compute operation."""

    value: object


@dataclass(frozen=True, slots=True)
class OutputInput:
    """Reference an earlier compute operation in the same point."""

    operation_id: str


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
class ComputeOperation:
    """One point-local pure compute kernel invocation."""

    operation_id: str
    kernel_id: str
    kernel: ComputeKernel
    inputs: Mapping[str, ComputeInput]
    output_type: ValueType
    dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=_empty_dependencies
    )
    payload_slot: PayloadSlot | None = None
    cache_namespace: str | None = None
    cache_key: object | None = None

    def __post_init__(self) -> None:
        if not self.operation_id or not self.kernel_id:
            msg = "compute operation and kernel ids must be non-empty"
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
    channel_bindings: tuple[CommandChannelBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id or not self.field_path:
            msg = "state target capability_id and field_path must be non-empty"
            raise ValueError(msg)

    def command_field(self, *, resource_id: str) -> InstrumentStateCommandField:
        return InstrumentStateCommandField(
            resource_id=resource_id,
            capability_id=self.capability_id,
            field_path=self.field_path,
            value=self.value.model_copy(deep=True),
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
class CollectOperation:
    """One instrument collection command and its logical output bindings."""

    operation_id: str
    instrument_id: str
    command: CollectCommand
    record_bindings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.operation_id or not self.instrument_id:
            msg = "collect operation and instrument ids must be non-empty"
            raise ValueError(msg)
        if self.command.instrument_id != self.instrument_id:
            msg = "collect command instrument must match its operation"
            raise ValueError(msg)
        request_ids = [request.id for request in self.command.requests]
        if any(not request_id for request_id in request_ids):
            msg = "collect command product request ids must be non-empty"
            raise ValueError(msg)
        if len(request_ids) != len(set(request_ids)):
            msg = "collect command product request ids must be unique"
            raise ValueError(msg)
        if set(request_ids) != set(self.record_bindings):
            msg = "collect record bindings must match command product requests"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CollectStage:
    """Explicitly ordered collection operations."""

    operations: tuple[CollectOperation, ...]
    kind: Literal["collect"] = field(default="collect", init=False)


type ExecutionStage = ComputeStage | ApplyStateStage | CollectStage


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
class ResourceClaim:
    """Run-level exclusive resource claim acquired before hardware effects."""

    id: str
    kind: Literal["instrument", "channel", "group"] = "instrument"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "resource claim id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExecutionProgram:
    """Closed executable program produced from a config-bound plan."""

    experiment_id: str
    points: tuple[PointProgram, ...]
    expected_output_ids: frozenset[str]
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
        used_instruments = tuple(
            dict.fromkeys(
                operation.instrument_id
                for point in self.points
                for stage in point.stages
                if isinstance(stage, ApplyStateStage | CollectStage)
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


def _point_operation_ids(point: PointProgram) -> tuple[str, ...]:
    return tuple(
        operation.operation_id
        for stage in point.stages
        for operation in stage.operations
    )


def _validate_point_compute_order(point: PointProgram) -> None:
    available: set[str] = set()
    for stage in point.stages:
        if not isinstance(stage, ComputeStage):
            continue
        for operation in stage.operations:
            missing = sorted(
                value.operation_id
                for value in operation.inputs.values()
                if isinstance(value, OutputInput)
                and value.operation_id not in available
            )
            if missing:
                msg = (
                    f"compute operation {operation.operation_id!r} references "
                    "outputs that are not topologically available: "
                    + ", ".join(missing)
                )
                raise ValueError(msg)
            available.add(operation.operation_id)


def _validate_point_stage_order(point: PointProgram) -> None:
    order = {"compute": 0, "apply_state": 1, "collect": 2}
    stage_kinds = [stage.kind for stage in point.stages]
    if len(stage_kinds) != len(set(stage_kinds)):
        msg = "point execution stages must not repeat a stage kind"
        raise ValueError(msg)
    if [order[kind] for kind in stage_kinds] != sorted(
        order[kind] for kind in stage_kinds
    ):
        msg = "point execution stages must follow compute, apply_state, collect order"
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
    "ApplyStateOperation",
    "ApplyStateStage",
    "BoundInput",
    "CollectOperation",
    "CollectStage",
    "ComputeInput",
    "ComputeKernel",
    "ComputeOperation",
    "ComputeStage",
    "ExecutionProgram",
    "ExecutionStage",
    "OutputInput",
    "PayloadSlot",
    "PointProgram",
    "ResourceClaim",
    "StateTarget",
]
