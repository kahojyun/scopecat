"""Checked target preparation for mixed quantum programs.

Mixed gate-and-pulse authoring converges on
:class:`~scopecat_quantum.programs.LoweredQuantumPulseProgram` before this
module is entered.  Preparation therefore has one source-neutral job: schedule
the canonical pulse program, qualify every event and acquisition with a target
entry identity, and retain the exact mixed-source provenance for correlation.

This module is the scheduled-target preparation path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat_quantum._ids import (
    QuantumProgramId,
    TargetCompileEntryId,
)
from scopecat_quantum.programs import (
    LoweredQuantumPulseProgram,
    QuantumPulseAcquisitionProvenance,
    QuantumPulseEventProvenance,
)
from scopecat_quantum.pulses import ScheduledPulseProgram, schedule
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetCompileEntry,
    TargetCompileRequest,
    TargetEventAddress,
)


@dataclass(frozen=True, slots=True)
class QuantumTargetEventOrigin:
    """Mixed-source origin of one entry-qualified target event."""

    source_program_id: QuantumProgramId
    address: TargetEventAddress
    provenance: QuantumPulseEventProvenance

    def __post_init__(self) -> None:
        if self.address.event_id != self.provenance.event_id:
            msg = "target event address must identify its mixed pulse provenance"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class QuantumTargetAcquisitionOrigin:
    """Mixed-source origin of one entry-qualified acquisition result."""

    source_program_id: QuantumProgramId
    address: TargetAcquisitionAddress
    provenance: QuantumPulseAcquisitionProvenance

    def __post_init__(self) -> None:
        if self.address.slot_id != self.provenance.acquisition_slot_id:
            msg = "target acquisition address must identify its mixed pulse provenance"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PreparedQuantumTargetEntry:
    """One scheduled target entry with its mixed-source provenance."""

    lowered: LoweredQuantumPulseProgram
    target_entry: TargetCompileEntry
    event_origins: tuple[QuantumTargetEventOrigin, ...]
    acquisition_origins: tuple[QuantumTargetAcquisitionOrigin, ...]

    @property
    def id(self) -> TargetCompileEntryId:
        return self.target_entry.id

    @property
    def scheduled(self) -> ScheduledPulseProgram:
        return self.target_entry.program

    @property
    def source_program_id(self) -> QuantumProgramId:
        return self.lowered.source_program_id

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return tuple(origin.address for origin in self.acquisition_origins)

    def acquisition_origin_for(
        self,
        address: TargetAcquisitionAddress,
    ) -> QuantumTargetAcquisitionOrigin:
        for origin in self.acquisition_origins:
            if origin.address == address:
                return origin
        msg = (
            f"target acquisition address {address!r} does not belong to entry {self.id}"
        )
        raise KeyError(msg)


def prepare_quantum_target_entry(
    entry_id: TargetCompileEntryId,
    lowered: LoweredQuantumPulseProgram,
) -> PreparedQuantumTargetEntry:
    """Schedule one lowered mixed program and retain total source provenance."""

    scheduled = schedule(lowered.program)
    target_entry = TargetCompileEntry(id=entry_id, program=scheduled)
    event_origins = _event_origins(lowered, target_entry)
    acquisition_origins = _acquisition_origins(lowered, target_entry)
    return PreparedQuantumTargetEntry(
        lowered,
        target_entry,
        event_origins,
        acquisition_origins,
    )


@dataclass(frozen=True, slots=True)
class PreparedQuantumTargetBatch:
    """Factory-built ordered batch with its compile request and origins."""

    entries: tuple[PreparedQuantumTargetEntry, ...]
    request: TargetCompileRequest

    @property
    def acquisition_origins(self) -> tuple[QuantumTargetAcquisitionOrigin, ...]:
        return tuple(
            origin for entry in self.entries for origin in entry.acquisition_origins
        )

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return tuple(
            address for entry in self.entries for address in entry.acquisition_addresses
        )

    def acquisition_origin_for(
        self,
        address: TargetAcquisitionAddress,
    ) -> QuantumTargetAcquisitionOrigin:
        for origin in self.acquisition_origins:
            if origin.address == address:
                return origin
        msg = f"target acquisition address {address!r} is not in this batch"
        raise KeyError(msg)


def prepare_quantum_target_batch(
    entries: Sequence[PreparedQuantumTargetEntry],
    *,
    repetitions: int,
) -> PreparedQuantumTargetBatch:
    """Close ordered mixed-program entries into one target compile request."""

    selected_entries = tuple(entries)
    if not selected_entries:
        msg = "quantum target batches require at least one PreparedQuantumTargetEntry"
        raise ValueError(msg)
    request = TargetCompileRequest(
        entries=tuple(entry.target_entry for entry in selected_entries),
        repetitions=repetitions,
    )
    return PreparedQuantumTargetBatch(
        entries=selected_entries,
        request=request,
    )


def _event_origins(
    lowered: LoweredQuantumPulseProgram,
    target_entry: TargetCompileEntry,
) -> tuple[QuantumTargetEventOrigin, ...]:
    provenance_by_id = {item.event_id: item for item in lowered.event_provenance}
    try:
        return tuple(
            QuantumTargetEventOrigin(
                source_program_id=lowered.source_program_id,
                address=address,
                provenance=provenance_by_id[address.event_id],
            )
            for address in target_entry.event_addresses
        )
    except KeyError as error:
        msg = "scheduled target events are not totally covered by mixed provenance"
        raise ValueError(msg) from error


def _acquisition_origins(
    lowered: LoweredQuantumPulseProgram,
    target_entry: TargetCompileEntry,
) -> tuple[QuantumTargetAcquisitionOrigin, ...]:
    provenance_by_id = {
        item.acquisition_slot_id: item for item in lowered.acquisition_provenance
    }
    try:
        return tuple(
            QuantumTargetAcquisitionOrigin(
                source_program_id=lowered.source_program_id,
                address=address,
                provenance=provenance_by_id[address.slot_id],
            )
            for address in target_entry.acquisition_addresses
        )
    except KeyError as error:
        msg = (
            "scheduled target acquisitions are not totally covered by mixed provenance"
        )
        raise ValueError(msg) from error
