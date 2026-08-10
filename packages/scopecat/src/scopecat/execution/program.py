"""Closed residual operations consumed by the run interpreter."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.compiler.bound_facts import BoundMeasurementPostprocessor
from scopecat.execution.local.program import ApplyStateOperation, LocalOperation
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.resource_identity import (
    DomainTargetRequirement,
    ResourceRequirement,
)
from scopecat.measurements.points import RunPointCatalog
from scopecat.measurements.projection import MeasurementProjection
from scopecat.records.config import ConfigContentHash
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
)
from scopecat.sdk.payloads import PayloadCodecRegistry


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
class RunProgram:
    """Closed residual effect program awaiting durable admission.

    Logical point identity and measurement correlation are independent of how
    ``coverage`` partitions physical work. Coverage and domain preparations are
    complete and repeatedly inspectable before the daemon provisions the
    admitted instrument requirements.
    """

    config_content_hash: ConfigContentHash
    host: RunHostBinding | None
    coverage: tuple[RunCoveredOperation, ...] = field(repr=False, compare=False)
    points: RunPointCatalog = field(repr=False)
    measurements: MeasurementProjection = field(repr=False)
    resource_requirements: tuple[ResourceRequirement, ...]
    domain_target_requirement: DomainTargetRequirement | None
    success_state: tuple[ApplyStateOperation, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    measurement_postprocessors: tuple[BoundMeasurementPostprocessor, ...] = field(
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
                        for postprocessor in self.measurement_postprocessors
                        for binding in postprocessor.value_inputs
                    ),
                )
            )
        )
