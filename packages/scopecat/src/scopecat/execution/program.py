"""Closed residual operations consumed by the run interpreter."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field

from scopecat.execution.local.collection_contract import BoundLocalCollectionValues
from scopecat.execution.local.program import (
    ActionStage,
    ApplyStateStage,
    CollectStage,
    ComputeStage,
    ExecutionStage,
    PointProgram,
)
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.projection import MeasurementProjection
from scopecat.measurements.results import CoordinateValue
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    InstrumentProvider,
    InstrumentProviderContext,
)


@dataclass(frozen=True, slots=True)
class RunHostBinding:
    """Provisioning contract for host effects referenced by a RunProgram."""

    experiment_id: str
    product_use_ids: tuple[ProductUseId, ...]
    resource_order: tuple[str, ...]
    point_count: int
    context: InstrumentProviderContext = field(repr=False)
    provider_id: str
    instrument_order: tuple[str, ...]
    advertised_descriptions: dict[str, InstrumentDescription] = field(repr=False)
    provider: InstrumentProvider = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class RunDomainJob:
    """One fully prepared domain operation over exact logical points."""

    id: str
    point_ordinals: tuple[int, ...]
    prepared: PreparedDomainExecution = field(repr=False)

    @property
    def resource_claims(self) -> tuple[ResourceClaim, ...]:
        return self.prepared.resource_claims


@dataclass(frozen=True, slots=True)
class RunPointStart:
    """Open the execution frame for one logical point."""

    point_index: int
    logical_id: LogicalPointId
    coordinates: Mapping[str, CoordinateValue]
    compute_step_count: int
    compute_operation_ids: tuple[str, ...]
    route_count: int
    state_resource_count: int
    action_count: int
    stage_count: int


@dataclass(frozen=True, slots=True)
class RunPointStage:
    """Execute one already-ordered stage inside an open point frame."""

    point_index: int
    stage: ExecutionStage


@dataclass(frozen=True, slots=True)
class RunPointEnd:
    """Close one logical point and emit its terminal point transition."""

    point_index: int


@dataclass(frozen=True, slots=True)
class RunPointLoop:
    """Budget-closed sequential loop over concrete logical point iterations."""

    points: tuple[PointProgram, ...]


@dataclass(frozen=True, slots=True)
class RunComputeStage:
    """Execute point-invariant host computations once for the complete run."""

    stage: ComputeStage


type RunAtomicOperation = (
    RunComputeStage | RunPointStart | RunPointStage | RunPointEnd | RunDomainJob
)
type RunOperation = RunAtomicOperation | RunPointLoop


def run_point_start(point: PointProgram) -> RunPointStart:
    """Project point identity and observation metadata into its start operation."""

    return RunPointStart(
        point_index=point.point_index,
        logical_id=point.logical_id,
        coordinates=point.coordinates,
        compute_step_count=sum(
            len(stage.operations)
            for stage in point.stages
            if isinstance(stage, ComputeStage)
        ),
        compute_operation_ids=tuple(
            operation.semantic_operation_id
            for stage in point.stages
            if isinstance(stage, ComputeStage)
            for operation in stage.operations
        ),
        route_count=sum(
            len(operation.command.requests)
            for stage in point.stages
            if isinstance(stage, CollectStage)
            for operation in stage.operations
        ),
        state_resource_count=sum(
            len(stage.operations)
            for stage in point.stages
            if isinstance(stage, ApplyStateStage)
        ),
        action_count=sum(
            len(stage.operations)
            for stage in point.stages
            if isinstance(stage, ActionStage)
        ),
        stage_count=len(point.stages),
    )


def iter_run_operations(
    operations: Iterable[RunOperation],
) -> Iterator[RunAtomicOperation]:
    """Iterate the final atomic sequence without expanding stored point loops."""

    for operation in operations:
        if isinstance(operation, RunPointLoop):
            for point in operation.points:
                yield run_point_start(point)
                yield from (
                    RunPointStage(point.point_index, stage) for stage in point.stages
                )
                yield RunPointEnd(point.point_index)
        else:
            yield operation


@dataclass(frozen=True, slots=True)
class RunProgram:
    """Closed residual effect program consumed by the run interpreter."""

    host: RunHostBinding | None
    operations: tuple[RunOperation, ...]
    measurements: MeasurementProjection = field(repr=False)
    local_values: BoundLocalCollectionValues | None = field(repr=False)
    resource_claims: tuple[ResourceClaim, ...]

    @property
    def experiment_id(self) -> str:
        return self.measurements.catalog.point_catalog.experiment_id

    @property
    def resource_order(self) -> tuple[str, ...]:
        return () if self.host is None else self.host.resource_order
