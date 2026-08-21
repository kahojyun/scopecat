"""Runtime boundary for one prepared domain-program execution.

Domain compilers consume the target-neutral bound program and close target,
result, and value decisions before a bounded batch enters domain effects.
Scopecat retains ownership of job advancement, correlation, recording, and
terminal run evidence. Synchronous targets finish from ``start``; externally
resumable targets may expose one or more correlated checkpoint transitions.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field

from scopecat.inspection import (
    CompiledArtifactInspection,
    CompiledProgramInspectionQuery,
)
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.state import StateValue
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.sdk.domain.invocation import ClosedDomainInvocation
from scopecat.sdk.domain.runtime import (
    DomainExecutionResult,
    DomainJobRuntime,
    DomainSetup,
)

type ErasedDomainInvocation = ClosedDomainInvocation[Hashable, object]
type ErasedDomainJobRuntime = DomainJobRuntime[object, object]
type ErasedDomainSetup = DomainSetup[object]
type ErasedDomainResultSink = Callable[[MeasurementValueCandidate], None]
type ErasedDomainRealizer = Callable[
    [DomainExecutionResult[object], ErasedDomainResultSink],
    None,
]
type CompiledInspectionProjector = Callable[
    [CompiledProgramInspectionQuery | None],
    CompiledArtifactInspection,
]


@dataclass(frozen=True, slots=True, order=True)
class DomainStateAddress:
    """One exact physical property in a prepared domain state contract.

    Write ownership, host requirements, and knowledge invalidation use the same
    address without conflating their semantics. Instrument reservation remains
    run-wide, while ordered effects may share one instrument.
    """

    instrument_id: str
    interface_id: InterfaceId
    property_id: str
    component_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainStateRequirement:
    """One host-managed physical value required at the realtime boundary.

    Planning proves the value from preceding host desired state. Execution may
    idempotently reconcile that exact value after target setup, without giving
    the target runtime authority to choose it. Its instrument may therefore sit
    outside the target's executable instrument footprint.
    """

    address: DomainStateAddress
    value: StateValue


@dataclass(frozen=True, slots=True, order=True)
class DomainResidencyAddress:
    """One connection-owned opaque target setup slot.

    Residency is runtime knowledge such as the content currently loaded in an
    AWG or FPGA program bank. It is deliberately separate from public
    instrument interface state: experiment authors do not select it, drivers
    need not make it queryable, and losing the connection loses the knowledge.
    """

    instrument_id: str
    slot_id: str

    def __post_init__(self) -> None:
        if not self.instrument_id or not self.slot_id:
            raise ValueError("domain residency identity fields must be non-empty")


@dataclass(frozen=True, slots=True)
class DomainResidencyRequirement:
    """Content that target setup leaves resident in one opaque slot."""

    address: DomainResidencyAddress
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not self.content_fingerprint:
            raise ValueError("domain residency fingerprint must be non-empty")


@dataclass(frozen=True, slots=True)
class PreparedDomainExecution:
    """A pure proof that one bound program is ready for domain effects.

    The type-erased runtime fields form an existential adapter boundary: an
    adapter constructs all three from one concrete address/payload/result type
    family, while core only inspects the exact physical instrument footprint
    and state contract needed to compose it with host stages. Setup completes
    before core reconciles host-managed requirements; runtime execution begins
    only after that boundary. Write footprints declare target authority and an
    unknown postcondition; invalidations only withdraw planner knowledge and may
    name physically coupled properties outside the target footprint. The
    continuation maximum is compiler feedback from this concrete artifact; it
    bounds the next candidate after payload shape and device limits are known.
    The compiler still selects the candidate's compatible prefix, without
    making those resource dimensions part of core semantics.
    """

    instrument_ids: tuple[str, ...]
    setup_write_footprint: tuple[DomainStateAddress, ...]
    setup_state_invalidations: tuple[DomainStateAddress, ...]
    state_requirements: tuple[DomainStateRequirement, ...]
    realtime_write_footprint: tuple[DomainStateAddress, ...]
    realtime_state_invalidations: tuple[DomainStateAddress, ...]
    next_batch_max_points: int
    invocation: ErasedDomainInvocation = field(repr=False)
    setup: ErasedDomainSetup | None = field(repr=False, compare=False)
    job_runtime: ErasedDomainJobRuntime = field(repr=False, compare=False)
    realize_into: ErasedDomainRealizer = field(repr=False, compare=False)
    inspection: CompiledArtifactInspection | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    inspection_projector: CompiledInspectionProjector | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    setup_residency_requirements: tuple[DomainResidencyRequirement, ...] = ()
    setup_residency_invalidations: tuple[DomainResidencyAddress, ...] = ()
    realtime_residency_invalidations: tuple[DomainResidencyAddress, ...] = ()

    def __post_init__(self) -> None:
        if self.next_batch_max_points <= 0:
            raise ValueError("next domain batch maximum must be positive")
        if any(not instrument_id for instrument_id in self.instrument_ids):
            raise ValueError("prepared domain instrument ids must be non-empty")
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise ValueError("prepared domain instrument ids must be unique")
        if any(
            write.instrument_id not in self.instrument_ids
            for write in (*self.setup_write_footprint, *self.realtime_write_footprint)
        ):
            raise ValueError(
                "prepared domain write footprints must belong to its instrument "
                "footprint"
            )
        residency_addresses = tuple(
            requirement.address for requirement in self.setup_residency_requirements
        )
        if len(residency_addresses) != len(set(residency_addresses)):
            raise ValueError("prepared domain residency slots must be unique")
        if self.setup is None and (
            self.setup_residency_requirements or self.setup_residency_invalidations
        ):
            raise ValueError("domain setup residency contract requires target setup")
        if any(
            address.instrument_id not in self.instrument_ids
            for address in (
                *residency_addresses,
                *self.setup_residency_invalidations,
                *self.realtime_residency_invalidations,
            )
        ):
            raise ValueError(
                "prepared domain residency slots must belong to its instrument "
                "footprint"
            )


__all__ = [
    "DomainResidencyAddress",
    "DomainResidencyRequirement",
    "DomainStateAddress",
    "DomainStateRequirement",
    "PreparedDomainExecution",
]
