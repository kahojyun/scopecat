"""Closed residual operations consumed by the run interpreter."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.compiler.typed.program import TypedMeasurementPostprocessor
from scopecat.execution.local.program import ComputeOperation, LocalOperation
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.points import RunPointCatalog
from scopecat.measurements.projection import MeasurementProjection
from scopecat.records.config import ConfigContentHash
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
)


@dataclass(frozen=True, slots=True)
class RunHostBinding:
    """Provisioning contract for host effects referenced by a RunProgram."""

    resource_order: tuple[str, ...]
    provider_id: str
    advertised_descriptions: dict[str, InstrumentDescription] = field(repr=False)


@dataclass(frozen=True, slots=True)
class RunDomainJob:
    """One prepared domain operation over exact logical points."""

    id: str
    point_ordinals: tuple[int, ...]
    execution: PreparedDomainExecution = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class RunCoverageEffect:
    """Execute one bound local operation over its exact logical coverage."""

    point_indices: tuple[int, ...]
    operation: LocalOperation

    def __post_init__(self) -> None:
        if not self.point_indices or len(self.point_indices) != len(
            set(self.point_indices)
        ):
            raise ValueError("local effect coverage must be non-empty and unique")

    @classmethod
    def at_point(cls, point_index: int, operation: LocalOperation) -> RunCoverageEffect:
        return cls((point_index,), operation)


@dataclass(frozen=True, slots=True)
class RunCoverageCheckpoint:
    """Commit one completed logical prefix inside a larger effect block."""

    point_index: int


type RunCoveredOperation = RunCoverageCheckpoint | RunCoverageEffect | RunDomainJob


@dataclass(frozen=True, slots=True)
class RunProgram:
    """Closed residual effect program awaiting durable admission.

    Logical point identity and measurement correlation are independent of how
    ``coverage`` partitions physical work. Coverage and domain preparations are
    complete and repeatedly inspectable before the run boundary provisions
    concrete providers.
    """

    config_content_hash: ConfigContentHash
    host: RunHostBinding | None
    preamble: tuple[ComputeOperation, ...]
    coverage: tuple[RunCoveredOperation, ...] = field(repr=False, compare=False)
    points: RunPointCatalog = field(repr=False)
    measurements: MeasurementProjection = field(repr=False)
    resource_claims: tuple[ResourceClaim, ...]
    measurement_postprocessors: tuple[TypedMeasurementPostprocessor, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

    @property
    def experiment_id(self) -> str:
        return self.points.experiment_id

    @property
    def resource_order(self) -> tuple[str, ...]:
        return () if self.host is None else self.host.resource_order
