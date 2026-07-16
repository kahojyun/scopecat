"""Checked target preparation for mixed quantum programs.

Mixed gate-and-pulse authoring converges on
:class:`~scopecat_quantum.programs.LoweredQuantumPulseProgram` before this
module is entered.  Preparation therefore has one source-neutral job: schedule
the canonical pulse program, qualify every event and acquisition with a target
entry identity, and retain the exact mixed-source provenance for correlation.

Target compilers remain deliberately outside this module.  They receive only
the resulting :class:`~scopecat_quantum.targets.TargetCompileEntry`, whose
program is a :class:`~scopecat_quantum.pulses.ScheduledPulseProgram`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from scopecat_quantum._ids import (
    QuantumProgramId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
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


@dataclass(frozen=True, slots=True, init=False)
class PreparedQuantumTargetEntry:
    """Sealed mixed-source lowering, schedule, and target-entry proof."""

    lowered: LoweredQuantumPulseProgram
    scheduled: ScheduledPulseProgram
    target_entry: TargetCompileEntry
    event_origins: tuple[QuantumTargetEventOrigin, ...]
    acquisition_origins: tuple[QuantumTargetAcquisitionOrigin, ...]

    def __init__(
        self,
        lowered: LoweredQuantumPulseProgram,
        scheduled: ScheduledPulseProgram,
        target_entry: TargetCompileEntry,
        event_origins: tuple[QuantumTargetEventOrigin, ...],
        acquisition_origins: tuple[QuantumTargetAcquisitionOrigin, ...],
    ) -> None:
        _validate_entry_congruence(
            lowered=lowered,
            scheduled=scheduled,
            target_entry=target_entry,
            event_origins=event_origins,
            acquisition_origins=acquisition_origins,
        )
        object.__setattr__(self, "lowered", lowered)
        object.__setattr__(self, "scheduled", scheduled)
        object.__setattr__(self, "target_entry", target_entry)
        object.__setattr__(self, "event_origins", event_origins)
        object.__setattr__(
            self,
            "acquisition_origins",
            acquisition_origins,
        )

    @property
    def id(self) -> TargetCompileEntryId:
        return self.target_entry.id

    @property
    def source_program_id(self) -> QuantumProgramId:
        return self.lowered.source_program_id

    @property
    def event_addresses(self) -> tuple[TargetEventAddress, ...]:
        return tuple(origin.address for origin in self.event_origins)

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return tuple(origin.address for origin in self.acquisition_origins)

    def event_origin_for(
        self,
        address: TargetEventAddress,
    ) -> QuantumTargetEventOrigin:
        for origin in self.event_origins:
            if origin.address == address:
                return origin
        msg = f"target event address {address!r} does not belong to entry {self.id}"
        raise KeyError(msg)

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
        scheduled,
        target_entry,
        event_origins,
        acquisition_origins,
    )


@dataclass(frozen=True, slots=True, init=False)
class PreparedQuantumTargetBatch:
    """Sealed ordered mixed-program batch with total qualified origins."""

    entries: tuple[PreparedQuantumTargetEntry, ...]
    request: TargetCompileRequest
    event_origins: tuple[QuantumTargetEventOrigin, ...]
    acquisition_origins: tuple[QuantumTargetAcquisitionOrigin, ...]
    _entries_by_id: Mapping[TargetCompileEntryId, PreparedQuantumTargetEntry] = field(
        repr=False,
        compare=False,
        hash=False,
    )
    _event_origins_by_address: Mapping[
        TargetEventAddress,
        QuantumTargetEventOrigin,
    ] = field(repr=False, compare=False, hash=False)
    _acquisition_origins_by_address: Mapping[
        TargetAcquisitionAddress,
        QuantumTargetAcquisitionOrigin,
    ] = field(repr=False, compare=False, hash=False)

    def __init__(
        self,
        entries: tuple[PreparedQuantumTargetEntry, ...],
        request: TargetCompileRequest,
        event_origins: tuple[QuantumTargetEventOrigin, ...],
        acquisition_origins: tuple[QuantumTargetAcquisitionOrigin, ...],
    ) -> None:
        if not entries:
            msg = "prepared quantum target batches require at least one entry"
            raise ValueError(msg)

        expected_target_entries = tuple(entry.target_entry for entry in entries)
        if request.entries != expected_target_entries:
            msg = "target compile request must exactly retain prepared entry order"
            raise ValueError(msg)
        entry_ids = tuple(entry.id for entry in entries)
        if len(set(entry_ids)) != len(entry_ids):
            msg = "prepared quantum target entry ids must be unique"
            raise ValueError(msg)

        expected_event_origins = tuple(
            origin for entry in entries for origin in entry.event_origins
        )
        expected_acquisition_origins = tuple(
            origin for entry in entries for origin in entry.acquisition_origins
        )
        if event_origins != expected_event_origins:
            msg = "batch event origins must exactly cover prepared entries in order"
            raise ValueError(msg)
        if acquisition_origins != expected_acquisition_origins:
            msg = (
                "batch acquisition origins must exactly cover prepared entries in order"
            )
            raise ValueError(msg)
        if tuple(origin.address for origin in event_origins) != (
            request.event_addresses
        ):
            msg = "batch event origins must exactly cover target request addresses"
            raise ValueError(msg)
        if tuple(origin.address for origin in acquisition_origins) != (
            request.acquisition_addresses
        ):
            msg = (
                "batch acquisition origins must exactly cover target request addresses"
            )
            raise ValueError(msg)

        entries_by_id = {entry.id: entry for entry in entries}
        event_origins_by_address = {origin.address: origin for origin in event_origins}
        acquisition_origins_by_address = {
            origin.address: origin for origin in acquisition_origins
        }
        if len(event_origins_by_address) != len(event_origins):
            msg = "prepared quantum target event addresses must be unique"
            raise ValueError(msg)
        if len(acquisition_origins_by_address) != len(acquisition_origins):
            msg = "prepared quantum target acquisition addresses must be unique"
            raise ValueError(msg)

        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "event_origins", event_origins)
        object.__setattr__(
            self,
            "acquisition_origins",
            acquisition_origins,
        )
        object.__setattr__(self, "_entries_by_id", MappingProxyType(entries_by_id))
        object.__setattr__(
            self,
            "_event_origins_by_address",
            MappingProxyType(event_origins_by_address),
        )
        object.__setattr__(
            self,
            "_acquisition_origins_by_address",
            MappingProxyType(acquisition_origins_by_address),
        )

    @property
    def event_addresses(self) -> tuple[TargetEventAddress, ...]:
        return self.request.event_addresses

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return self.request.acquisition_addresses

    def entry_for(
        self,
        entry_id: TargetCompileEntryId,
    ) -> PreparedQuantumTargetEntry:
        try:
            return self._entries_by_id[entry_id]
        except KeyError as error:
            msg = f"target compile entry {entry_id!r} is not in this batch"
            raise KeyError(msg) from error

    def event_origin_for(
        self,
        address: TargetEventAddress,
    ) -> QuantumTargetEventOrigin:
        try:
            return self._event_origins_by_address[address]
        except KeyError as error:
            msg = f"target event address {address!r} is not in this batch"
            raise KeyError(msg) from error

    def acquisition_origin_for(
        self,
        address: TargetAcquisitionAddress,
    ) -> QuantumTargetAcquisitionOrigin:
        try:
            return self._acquisition_origins_by_address[address]
        except KeyError as error:
            msg = f"target acquisition address {address!r} is not in this batch"
            raise KeyError(msg) from error


def prepare_quantum_target_batch(
    entries: Sequence[PreparedQuantumTargetEntry],
    *,
    target_id: TargetId,
    compiler_id: TargetCompilerId,
    capability_fingerprint: str,
    repetitions: int,
) -> PreparedQuantumTargetBatch:
    """Close ordered mixed-program entries into one target compile request."""

    selected_entries = tuple(entries)
    if not selected_entries:
        msg = "quantum target batches require at least one PreparedQuantumTargetEntry"
        raise ValueError(msg)
    request = TargetCompileRequest(
        target_id=target_id,
        compiler_id=compiler_id,
        capability_fingerprint=capability_fingerprint,
        entries=tuple(entry.target_entry for entry in selected_entries),
        repetitions=repetitions,
    )
    event_origins = tuple(
        origin for entry in selected_entries for origin in entry.event_origins
    )
    acquisition_origins = tuple(
        origin for entry in selected_entries for origin in entry.acquisition_origins
    )
    return PreparedQuantumTargetBatch(
        selected_entries,
        request,
        event_origins,
        acquisition_origins,
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


def _validate_entry_congruence(
    *,
    lowered: LoweredQuantumPulseProgram,
    scheduled: ScheduledPulseProgram,
    target_entry: TargetCompileEntry,
    event_origins: tuple[QuantumTargetEventOrigin, ...],
    acquisition_origins: tuple[QuantumTargetAcquisitionOrigin, ...],
) -> None:
    if scheduled.id != lowered.program.id:
        msg = "scheduled pulse proof must retain the lowered pulse program identity"
        raise ValueError(msg)
    if target_entry.program != scheduled:
        msg = "target compile entry must retain the exact scheduled pulse program"
        raise ValueError(msg)

    scheduled_event_ids = tuple(
        address.event_id for address in target_entry.event_addresses
    )
    provenance_event_ids = tuple(item.event_id for item in lowered.event_provenance)
    if len(scheduled_event_ids) != len(provenance_event_ids) or set(
        scheduled_event_ids
    ) != set(provenance_event_ids):
        msg = "scheduled target events must exactly cover mixed pulse provenance"
        raise ValueError(msg)
    scheduled_acquisition_ids = tuple(
        address.slot_id for address in target_entry.acquisition_addresses
    )
    provenance_acquisition_ids = tuple(
        item.acquisition_slot_id for item in lowered.acquisition_provenance
    )
    if len(scheduled_acquisition_ids) != len(provenance_acquisition_ids) or set(
        scheduled_acquisition_ids
    ) != set(provenance_acquisition_ids):
        msg = "scheduled target acquisitions must exactly cover mixed pulse provenance"
        raise ValueError(msg)

    expected_event_origins = _event_origins(lowered, target_entry)
    expected_acquisition_origins = _acquisition_origins(lowered, target_entry)
    if event_origins != expected_event_origins:
        msg = "target event origins must exactly cover scheduled events in order"
        raise ValueError(msg)
    if acquisition_origins != expected_acquisition_origins:
        msg = "target acquisition origins must exactly cover scheduled slots in order"
        raise ValueError(msg)


__all__ = [
    "PreparedQuantumTargetBatch",
    "PreparedQuantumTargetEntry",
    "QuantumTargetAcquisitionOrigin",
    "QuantumTargetEventOrigin",
    "prepare_quantum_target_batch",
    "prepare_quantum_target_entry",
]
