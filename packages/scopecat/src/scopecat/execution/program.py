"""Closed residual operations consumed by the run interpreter."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.compiler.typed.program import TypedMeasurementPostprocessor
from scopecat.execution.local.program import LocalOperation
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
    """Advertised daemon-instrument contract referenced by a RunProgram."""

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
    """Execute one bound local operation for one logical point."""

    point_index: int
    operation: LocalOperation


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
    complete and repeatedly inspectable before the daemon provisions the
    admitted instrument claims.
    """

    config_content_hash: ConfigContentHash
    host: RunHostBinding | None
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
