"""Closed residual operations consumed by the run interpreter."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.compiler.linking.linked import MaterializedLinkedPoints
from scopecat.execution.local.program import PointProgram
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.kernel.problems import Problem
from scopecat.kernel.product_identity import ProductUse, ProductUseId
from scopecat.measurements.projection import BoundMeasurementProjection
from scopecat.measurements.values import SelectedMeasurementValues
from scopecat.sdk.domain.compiler import DomainCompiledJob
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    InstrumentProvider,
    InstrumentProviderContext,
)


@dataclass(frozen=True, slots=True)
class RunLocalEffects:
    """Closed point-local host operations embedded in a RunProgram."""

    id: str
    experiment_id: str
    product_use_ids: tuple[ProductUseId, ...]
    points: tuple[PointProgram, ...]
    product_uses: tuple[ProductUse, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]
    context: InstrumentProviderContext = field(repr=False)
    provider_id: str
    instrument_order: tuple[str, ...]
    advertised_descriptions: dict[str, InstrumentDescription] = field(repr=False)
    problems: tuple[Problem, ...]
    provider: InstrumentProvider = field(repr=False, compare=False)

    @property
    def point_count(self) -> int:
        return len(self.points)


@dataclass(frozen=True, slots=True)
class RunDomainJob:
    """One compiled domain operation over exact logical points."""

    id: str
    source_id: str
    compiled: DomainCompiledJob = field(repr=False)
    prepared: PreparedDomainExecution = field(repr=False)

    @property
    def point_indices(self) -> tuple[int, ...]:
        return self.prepared.context.linked_points.point_indices

    @property
    def resource_claims(self) -> tuple[ResourceClaim, ...]:
        claims = (*self.compiled.resource_claims, *self.prepared.resource_claims)
        if claims:
            return tuple(dict.fromkeys(claims))
        return (
            ResourceClaim(
                self.prepared.invocation.intent.target_id,
                "target",
            ),
        )


@dataclass(frozen=True, slots=True)
class RunPointRegion:
    """One effect-stable logical-point region with ordered domain jobs."""

    point_indices: tuple[int, ...]
    domain_jobs: tuple[RunDomainJob, ...]


type RunOperation = RunLocalEffects | RunPointRegion


@dataclass(frozen=True, slots=True)
class RunProgram:
    """Closed residual effect program consumed by the run interpreter."""

    backend_id: str
    linked_points: MaterializedLinkedPoints = field(repr=False)
    operations: tuple[RunOperation, ...]
    values: SelectedMeasurementValues = field(repr=False)
    projection: BoundMeasurementProjection = field(repr=False)
    resource_claims: tuple[ResourceClaim, ...]


def run_local_effects(program: RunProgram) -> RunLocalEffects | None:
    return next(
        (
            operation
            for operation in program.operations
            if isinstance(operation, RunLocalEffects)
        ),
        None,
    )


def run_point_regions(program: RunProgram) -> tuple[RunPointRegion, ...]:
    return tuple(
        operation
        for operation in program.operations
        if isinstance(operation, RunPointRegion)
    )
