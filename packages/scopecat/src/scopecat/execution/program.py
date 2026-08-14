"""Bounded residual operations consumed by the run interpreter."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.sdk.payloads import PayloadCodecRegistry

if TYPE_CHECKING:
    from scopecat.compiler.bound_facts import BoundMeasurementCompute
    from scopecat.execution.local.program import (
        ApplyStateOperation,
        ComputeOperation,
        LocalOperation,
    )
    from scopecat.kernel.graph_identity import ValueId
    from scopecat.kernel.points import AcceptedRunPoint, PointProposalAttempt
    from scopecat.kernel.resource_identity import (
        DomainTargetRequirement,
        ResourceRequirement,
    )
    from scopecat.measurements.points import RunPointCatalog
    from scopecat.measurements.projection import MeasurementProjection
    from scopecat.optimization import AdaptiveDomainPlan
    from scopecat.records.config import ConfigContentHash
    from scopecat.sdk.domain.execution import PreparedDomainExecution
    from scopecat.sdk.instruments.contracts import InstrumentDescription


@dataclass(frozen=True, slots=True)
class RunHostBinding:
    """Logical instruments hosted by one daemon backend."""

    resource_order: tuple[str, ...]
    provider_id: str
    advertised_descriptions: dict[str, InstrumentDescription] = field(repr=False)
    payload_codecs: PayloadCodecRegistry = field(
        default_factory=PayloadCodecRegistry,
        repr=False,
        compare=False,
    )


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
    """Commit one completed logical point inside a larger effect block."""

    point_index: int


type RunCoveredOperation = RunCoverageCheckpoint | RunCoverageEffect | RunDomainJob


@dataclass(frozen=True, slots=True)
class RunPointInspection:
    """Pure compilation result for one planned or unaccepted coordinate row."""

    point_index: int | None
    candidate: PointProposalAttempt
    jobs: tuple[RunDomainJob, ...]


@dataclass(frozen=True, slots=True)
class RunAcceptedPointCoverage:
    """One accepted candidate and its eagerly validated bounded operations."""

    point: AcceptedRunPoint
    operations: tuple[RunCoveredOperation, ...]
    inspection: RunPointInspection


class RunCoverage:
    """A lazy operation stream rebuilt for each planning or execution pass."""

    __slots__ = ("_accept", "_accept_all", "_factory", "_inspect")

    def __init__(
        self,
        factory: Callable[[], Iterator[RunCoveredOperation]],
        *,
        inspect: Callable[[int | PointProposalAttempt], RunPointInspection]
        | None = None,
        accept: Callable[[PointProposalAttempt], RunAcceptedPointCoverage]
        | None = None,
        accept_all: Callable[
            [tuple[PointProposalAttempt, ...]],
            tuple[RunAcceptedPointCoverage, ...],
        ]
        | None = None,
    ) -> None:
        self._factory = factory
        self._inspect = inspect
        self._accept = accept
        self._accept_all = accept_all

    def __iter__(self) -> Iterator[RunCoveredOperation]:
        return self._factory()

    def inspect(self, point: int | PointProposalAttempt) -> RunPointInspection | None:
        """Compile target-owned inspection data for exactly one logical point."""

        if self._inspect is None:
            return None
        return self._inspect(point)

    def accept(self, candidate: PointProposalAttempt) -> RunAcceptedPointCoverage:
        """Compile and atomically append one candidate to the run point domain."""

        if self._accept is None:
            raise ValueError("run coverage does not accept adaptive points")
        return self._accept(candidate)

    def accept_all(
        self,
        candidates: tuple[PointProposalAttempt, ...],
    ) -> tuple[RunAcceptedPointCoverage, ...]:
        """Compile and atomically append one complete domain fragment."""

        if self._accept_all is None:
            raise ValueError("run coverage does not accept adaptive domains")
        return self._accept_all(candidates)


@dataclass(frozen=True, slots=True)
class RunProgram:
    """Admissible residual effect program with lazily compiled coverage.

    Logical point identity and measurement correlation are independent of how
    ``coverage`` partitions physical work. Static resource authority is complete
    before admission; domain preparations are rebuilt one bounded batch at a
    time during explicit inspection or execution.
    """

    config_content_hash: ConfigContentHash
    host: RunHostBinding | None
    coverage: RunCoverage = field(repr=False, compare=False)
    points: RunPointCatalog = field(repr=False)
    measurements: MeasurementProjection = field(repr=False)
    resource_requirements: tuple[ResourceRequirement, ...]
    domain_target_requirement: DomainTargetRequirement | None
    adaptive_domain_plan: AdaptiveDomainPlan | None = field(
        default=None,
        repr=False,
    )
    success_state: tuple[ApplyStateOperation, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    measurement_computes: tuple[BoundMeasurementCompute, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    preview_compute_operations: tuple[ComputeOperation, ...] = field(
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

    @property
    def runtime_value_ids(self) -> tuple[ValueId, ...]:
        """Values whose execution results must cross the coverage boundary."""

        return tuple(
            dict.fromkeys(
                (
                    *self.measurements.runtime_value_ids,
                    *(
                        binding.value_id
                        for compute in self.measurement_computes
                        for binding in compute.value_inputs
                    ),
                )
            )
        )
