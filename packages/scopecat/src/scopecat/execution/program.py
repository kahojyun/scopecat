"""Closed residual operations consumed by the run interpreter.

``RunProgram`` separates point-invariant compute from a single-use source of
bounded coverage. This keeps peak planning state and resource lifetimes bounded
while exact point coverage and checkpoints preserve logical result identity.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from scopecat.execution.local.program import ComputeOperation, LocalOperation
from scopecat.execution.points import RunPoint, RunPointCatalog
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.projection import MeasurementProjection
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
)


@dataclass(frozen=True, slots=True)
class RunHostBinding:
    """Provisioning contract for host effects referenced by a RunProgram."""

    resource_order: tuple[str, ...]
    provider_id: str
    instrument_order: tuple[str, ...]
    advertised_descriptions: dict[str, InstrumentDescription] = field(repr=False)


type DomainExecutionPreparation = Callable[[], PreparedDomainExecution]


@dataclass(slots=True)
class RunDomainJob:
    """One lightweight, single-use domain operation over exact logical points."""

    id: str
    point_ordinals: tuple[int, ...]
    resource_claims: tuple[ResourceClaim, ...]
    _prepare: DomainExecutionPreparation | None = field(repr=False, compare=False)

    def prepare(self) -> PreparedDomainExecution:
        """Materialize target payloads once and release the compiler closure."""

        prepare = self._prepare
        if prepare is None:
            raise RuntimeError("domain job preparation is single-use")
        self._prepare = None
        return prepare()


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

    point_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.point_indices or len(self.point_indices) != len(
            set(self.point_indices)
        ):
            raise ValueError("coverage checkpoint must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class RunCompute:
    """Execute one point-invariant computation for the complete run."""

    operation: ComputeOperation


type RunCoveredOperation = RunCoverageCheckpoint | RunCoverageEffect | RunDomainJob


@dataclass(frozen=True, slots=True)
class RunCoverageBlock:
    """Execute bounded host/domain effects over one exact point coverage.

    Points are admitted and block-local resources acquired only when this block
    is consumed. Checkpoints may commit completed prefixes before the complete
    block finishes without changing its logical inventory.
    """

    points: tuple[RunPoint, ...]
    operations: tuple[RunCoveredOperation, ...]
    resource_claims: tuple[ResourceClaim, ...] = ()

    @property
    def point_indices(self) -> tuple[int, ...]:
        return tuple(point.ordinal for point in self.points)


type RunOperation = RunCompute | RunCoverageBlock


@dataclass(frozen=True, slots=True)
class RunProgram:
    """Closed, single-use residual effect program for one accepted run.

    Logical point identity and measurement correlation are independent of how
    ``coverage`` partitions physical work. Concrete providers remain outside
    the program and are provisioned by the run boundary.
    """

    host: RunHostBinding | None
    preamble: tuple[RunCompute, ...]
    coverage: Iterator[RunCoverageBlock] = field(repr=False, compare=False)
    points: RunPointCatalog = field(repr=False)
    measurements: MeasurementProjection = field(repr=False)
    resource_claims: tuple[ResourceClaim, ...]

    @property
    def experiment_id(self) -> str:
        return self.points.experiment_id

    @property
    def resource_order(self) -> tuple[str, ...]:
        return () if self.host is None else self.host.resource_order
