"""Checked preparation of calibrated circuits for quantum target compilation.

This module closes the pure circuit-to-target boundary without introducing a
runtime or a Scopecat domain-invocation contract.  It preserves the exact
entry-qualified addresses that a target runtime must later return and relates
each address to the existing circuit-to-pulse provenance proof.

Entry identity qualifies event and acquisition addresses, so repeated use of
the same circuit or template never depends on physical list positions or on
manufacturing globally unique domain strings. A prepared batch retains its
proofs while exposing only canonical scheduled programs to the target
compiler.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat_quantum._ids import (
    CircuitId,
    PulseProgramId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.calibrations import CalibrationSelection
from scopecat_quantum.circuit_pulses import (
    CircuitPulseAcquisitionProvenance,
    CircuitPulseEventProvenance,
    LoweredCircuitPulseProgram,
    lower_circuit_to_pulses,
)
from scopecat_quantum.circuits import VerifiedCircuitProgram
from scopecat_quantum.pulses import ScheduledPulseProgram, schedule
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetCompileEntry,
    TargetCompileRequest,
    TargetEventAddress,
)


@dataclass(frozen=True, slots=True, init=False)
class CircuitTargetEventOrigin:
    """Circuit origin of one entry-qualified target event address."""

    source_circuit_id: CircuitId
    address: TargetEventAddress
    provenance: CircuitPulseEventProvenance

    def __init__(
        self,
        source_circuit_id: CircuitId,
        address: TargetEventAddress,
        provenance: CircuitPulseEventProvenance,
    ) -> None:
        if not isinstance(cast("object", source_circuit_id), CircuitId):
            msg = "circuit target event origins require a CircuitId"
            raise TypeError(msg)
        if not isinstance(cast("object", address), TargetEventAddress):
            msg = "circuit target event origins require a TargetEventAddress"
            raise TypeError(msg)
        if not isinstance(cast("object", provenance), CircuitPulseEventProvenance):
            msg = "circuit target event origins require circuit pulse provenance"
            raise TypeError(msg)
        if address.event_id != provenance.event_id:
            msg = "target event address must identify its circuit pulse provenance"
            raise ValueError(msg)
        object.__setattr__(self, "source_circuit_id", source_circuit_id)
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "provenance", provenance)


@dataclass(frozen=True, slots=True, init=False)
class CircuitTargetAcquisitionOrigin:
    """Circuit origin of one entry-qualified target acquisition address."""

    source_circuit_id: CircuitId
    address: TargetAcquisitionAddress
    provenance: CircuitPulseAcquisitionProvenance

    def __init__(
        self,
        source_circuit_id: CircuitId,
        address: TargetAcquisitionAddress,
        provenance: CircuitPulseAcquisitionProvenance,
    ) -> None:
        if not isinstance(cast("object", source_circuit_id), CircuitId):
            msg = "circuit target acquisition origins require a CircuitId"
            raise TypeError(msg)
        if not isinstance(cast("object", address), TargetAcquisitionAddress):
            msg = (
                "circuit target acquisition origins require a TargetAcquisitionAddress"
            )
            raise TypeError(msg)
        if not isinstance(
            cast("object", provenance),
            CircuitPulseAcquisitionProvenance,
        ):
            msg = "circuit target acquisition origins require circuit pulse provenance"
            raise TypeError(msg)
        if address.slot_id != provenance.acquisition_slot_id:
            msg = (
                "target acquisition address must identify its circuit pulse provenance"
            )
            raise ValueError(msg)
        object.__setattr__(self, "source_circuit_id", source_circuit_id)
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "provenance", provenance)


@dataclass(frozen=True, slots=True, init=False)
class PreparedCircuitTargetEntry:
    """Sealed circuit, calibration, pulse, schedule, and target-entry proof."""

    circuit: VerifiedCircuitProgram
    selection: CalibrationSelection
    lowered: LoweredCircuitPulseProgram
    scheduled: ScheduledPulseProgram
    target_entry: TargetCompileEntry
    event_origins: tuple[CircuitTargetEventOrigin, ...]
    acquisition_origins: tuple[CircuitTargetAcquisitionOrigin, ...]

    def __init__(
        self,
        circuit: VerifiedCircuitProgram,
        selection: CalibrationSelection,
        lowered: LoweredCircuitPulseProgram,
        scheduled: ScheduledPulseProgram,
        target_entry: TargetCompileEntry,
        event_origins: tuple[CircuitTargetEventOrigin, ...],
        acquisition_origins: tuple[CircuitTargetAcquisitionOrigin, ...],
    ) -> None:
        selected_event_origins = tuple(event_origins)
        selected_acquisition_origins = tuple(acquisition_origins)
        _validate_entry_congruence(
            circuit=circuit,
            selection=selection,
            lowered=lowered,
            scheduled=scheduled,
            target_entry=target_entry,
            event_origins=selected_event_origins,
            acquisition_origins=selected_acquisition_origins,
        )
        object.__setattr__(self, "circuit", circuit)
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "lowered", lowered)
        object.__setattr__(self, "scheduled", scheduled)
        object.__setattr__(self, "target_entry", target_entry)
        object.__setattr__(self, "event_origins", selected_event_origins)
        object.__setattr__(
            self,
            "acquisition_origins",
            selected_acquisition_origins,
        )

    @property
    def id(self) -> TargetCompileEntryId:
        return self.target_entry.id

    @property
    def source_circuit_id(self) -> CircuitId:
        return self.circuit.program.id

    @property
    def event_addresses(self) -> tuple[TargetEventAddress, ...]:
        return tuple(origin.address for origin in self.event_origins)

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return tuple(origin.address for origin in self.acquisition_origins)

    def event_origin_for(
        self,
        address: TargetEventAddress,
    ) -> CircuitTargetEventOrigin:
        for origin in self.event_origins:
            if origin.address == address:
                return origin
        msg = f"target event address {address!r} does not belong to entry {self.id}"
        raise KeyError(msg)

    def acquisition_origin_for(
        self,
        address: TargetAcquisitionAddress,
    ) -> CircuitTargetAcquisitionOrigin:
        for origin in self.acquisition_origins:
            if origin.address == address:
                return origin
        msg = (
            f"target acquisition address {address!r} does not belong to entry {self.id}"
        )
        raise KeyError(msg)


def prepare_circuit_target_entry(
    entry_id: TargetCompileEntryId,
    circuit: VerifiedCircuitProgram,
    selection: CalibrationSelection,
    *,
    output_id: PulseProgramId,
) -> PreparedCircuitTargetEntry:
    """Lower and schedule one exactly calibrated circuit target entry."""

    if not isinstance(cast("object", entry_id), TargetCompileEntryId):
        msg = "circuit target entry_id must be a TargetCompileEntryId"
        raise TypeError(msg)
    if not isinstance(cast("object", circuit), VerifiedCircuitProgram):
        msg = "circuit target preparation requires a VerifiedCircuitProgram"
        raise TypeError(msg)
    if not isinstance(cast("object", selection), CalibrationSelection):
        msg = "circuit target preparation requires a CalibrationSelection"
        raise TypeError(msg)
    if not isinstance(cast("object", output_id), PulseProgramId):
        msg = "circuit target output_id must be a PulseProgramId"
        raise TypeError(msg)

    lowered = lower_circuit_to_pulses(circuit, selection, output_id=output_id)
    scheduled = schedule(lowered.program)
    target_entry = TargetCompileEntry(id=entry_id, program=scheduled)
    event_origins = _event_origins(
        circuit.program.id,
        target_entry,
        lowered,
    )
    acquisition_origins = _acquisition_origins(
        circuit.program.id,
        target_entry,
        lowered,
    )
    return PreparedCircuitTargetEntry(
        circuit,
        selection,
        lowered,
        scheduled,
        target_entry,
        event_origins,
        acquisition_origins,
    )


@dataclass(frozen=True, slots=True, init=False)
class PreparedCircuitTargetBatch:
    """Sealed ordered batch with exact entry-qualified origin coverage."""

    entries: tuple[PreparedCircuitTargetEntry, ...]
    request: TargetCompileRequest
    event_origins: tuple[CircuitTargetEventOrigin, ...]
    acquisition_origins: tuple[CircuitTargetAcquisitionOrigin, ...]
    _entries_by_id: Mapping[TargetCompileEntryId, PreparedCircuitTargetEntry] = field(
        repr=False, compare=False, hash=False
    )
    _event_origins_by_address: Mapping[TargetEventAddress, CircuitTargetEventOrigin] = (
        field(repr=False, compare=False, hash=False)
    )
    _acquisition_origins_by_address: Mapping[
        TargetAcquisitionAddress, CircuitTargetAcquisitionOrigin
    ] = field(repr=False, compare=False, hash=False)

    def __init__(
        self,
        entries: tuple[PreparedCircuitTargetEntry, ...],
        request: TargetCompileRequest,
        event_origins: tuple[CircuitTargetEventOrigin, ...],
        acquisition_origins: tuple[CircuitTargetAcquisitionOrigin, ...],
    ) -> None:
        selected_entries = tuple(entries)
        selected_event_origins = tuple(event_origins)
        selected_acquisition_origins = tuple(acquisition_origins)
        if not isinstance(cast("object", request), TargetCompileRequest):
            msg = "prepared circuit target batches require a TargetCompileRequest"
            raise TypeError(msg)
        if not selected_entries or not all(
            isinstance(entry, PreparedCircuitTargetEntry)
            for entry in cast("tuple[object, ...]", selected_entries)
        ):
            msg = (
                "prepared circuit target batches require PreparedCircuitTargetEntry "
                "values"
            )
            raise TypeError(msg)
        expected_target_entries = tuple(
            entry.target_entry for entry in selected_entries
        )
        if request.entries != expected_target_entries:
            msg = "target compile request must exactly retain prepared entry order"
            raise ValueError(msg)
        entry_ids = tuple(entry.id for entry in selected_entries)
        if len(set(entry_ids)) != len(entry_ids):
            msg = "prepared circuit target entry ids must be unique"
            raise ValueError(msg)
        expected_event_origins = tuple(
            origin for entry in selected_entries for origin in entry.event_origins
        )
        expected_acquisition_origins = tuple(
            origin for entry in selected_entries for origin in entry.acquisition_origins
        )
        if selected_event_origins != expected_event_origins:
            msg = "batch event origins must exactly cover prepared entries in order"
            raise ValueError(msg)
        if selected_acquisition_origins != expected_acquisition_origins:
            msg = (
                "batch acquisition origins must exactly cover prepared entries in order"
            )
            raise ValueError(msg)
        if tuple(origin.address for origin in selected_event_origins) != (
            request.event_addresses
        ):
            msg = "batch event origins must exactly cover target request addresses"
            raise ValueError(msg)
        if tuple(origin.address for origin in selected_acquisition_origins) != (
            request.acquisition_addresses
        ):
            msg = (
                "batch acquisition origins must exactly cover target request addresses"
            )
            raise ValueError(msg)

        entries_by_id = {entry.id: entry for entry in selected_entries}
        event_origins_by_address = {
            origin.address: origin for origin in selected_event_origins
        }
        acquisition_origins_by_address = {
            origin.address: origin for origin in selected_acquisition_origins
        }
        if len(event_origins_by_address) != len(selected_event_origins):
            msg = "prepared circuit target event addresses must be unique"
            raise ValueError(msg)
        if len(acquisition_origins_by_address) != len(selected_acquisition_origins):
            msg = "prepared circuit target acquisition addresses must be unique"
            raise ValueError(msg)
        object.__setattr__(self, "entries", selected_entries)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "event_origins", selected_event_origins)
        object.__setattr__(
            self,
            "acquisition_origins",
            selected_acquisition_origins,
        )
        object.__setattr__(
            self,
            "_entries_by_id",
            MappingProxyType(entries_by_id),
        )
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
    ) -> PreparedCircuitTargetEntry:
        try:
            return self._entries_by_id[entry_id]
        except KeyError as error:
            msg = f"target compile entry {entry_id!r} is not in this batch"
            raise KeyError(msg) from error

    def event_origin_for(
        self,
        address: TargetEventAddress,
    ) -> CircuitTargetEventOrigin:
        try:
            return self._event_origins_by_address[address]
        except KeyError as error:
            msg = f"target event address {address!r} is not in this batch"
            raise KeyError(msg) from error

    def acquisition_origin_for(
        self,
        address: TargetAcquisitionAddress,
    ) -> CircuitTargetAcquisitionOrigin:
        try:
            return self._acquisition_origins_by_address[address]
        except KeyError as error:
            msg = f"target acquisition address {address!r} is not in this batch"
            raise KeyError(msg) from error


def prepare_circuit_target_batch(
    entries: Sequence[PreparedCircuitTargetEntry],
    *,
    target_id: TargetId,
    compiler_id: TargetCompilerId,
    capability_fingerprint: str,
    repetitions: int,
) -> PreparedCircuitTargetBatch:
    """Close an ordered circuit-entry batch into one target compile request."""

    selected_entries = tuple(entries)
    if not selected_entries or not all(
        isinstance(entry, PreparedCircuitTargetEntry)
        for entry in cast("tuple[object, ...]", selected_entries)
    ):
        msg = "circuit target batches require at least one PreparedCircuitTargetEntry"
        raise TypeError(msg)
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
    return PreparedCircuitTargetBatch(
        selected_entries,
        request,
        event_origins,
        acquisition_origins,
    )


def _event_origins(
    source_circuit_id: CircuitId,
    target_entry: TargetCompileEntry,
    lowered: LoweredCircuitPulseProgram,
) -> tuple[CircuitTargetEventOrigin, ...]:
    return tuple(
        CircuitTargetEventOrigin(
            source_circuit_id=source_circuit_id,
            address=address,
            provenance=lowered.provenance_for(address.event_id),
        )
        for address in target_entry.event_addresses
    )


def _acquisition_origins(
    source_circuit_id: CircuitId,
    target_entry: TargetCompileEntry,
    lowered: LoweredCircuitPulseProgram,
) -> tuple[CircuitTargetAcquisitionOrigin, ...]:
    return tuple(
        CircuitTargetAcquisitionOrigin(
            source_circuit_id=source_circuit_id,
            address=address,
            provenance=lowered.acquisition_provenance_for(address.slot_id),
        )
        for address in target_entry.acquisition_addresses
    )


def _validate_entry_congruence(
    *,
    circuit: VerifiedCircuitProgram,
    selection: CalibrationSelection,
    lowered: LoweredCircuitPulseProgram,
    scheduled: ScheduledPulseProgram,
    target_entry: TargetCompileEntry,
    event_origins: tuple[CircuitTargetEventOrigin, ...],
    acquisition_origins: tuple[CircuitTargetAcquisitionOrigin, ...],
) -> None:
    if not isinstance(cast("object", circuit), VerifiedCircuitProgram):
        msg = "prepared circuit target entries require a verified circuit"
        raise TypeError(msg)
    if not isinstance(cast("object", selection), CalibrationSelection):
        msg = "prepared circuit target entries require a calibration selection"
        raise TypeError(msg)
    if not isinstance(cast("object", lowered), LoweredCircuitPulseProgram):
        msg = "prepared circuit target entries require a lowered pulse proof"
        raise TypeError(msg)
    if not isinstance(cast("object", scheduled), ScheduledPulseProgram):
        msg = "prepared circuit target entries require a scheduled pulse proof"
        raise TypeError(msg)
    if not isinstance(cast("object", target_entry), TargetCompileEntry):
        msg = "prepared circuit target entries require a target compile entry"
        raise TypeError(msg)
    if not all(
        isinstance(origin, CircuitTargetEventOrigin)
        for origin in cast("tuple[object, ...]", event_origins)
    ):
        msg = "prepared circuit target event origins have an invalid runtime shape"
        raise TypeError(msg)
    if not all(
        isinstance(origin, CircuitTargetAcquisitionOrigin)
        for origin in cast("tuple[object, ...]", acquisition_origins)
    ):
        msg = (
            "prepared circuit target acquisition origins have an invalid runtime shape"
        )
        raise TypeError(msg)

    source_circuit_id = circuit.program.id
    expected_operation_ids = tuple(operation.id for operation in circuit.operations)
    if (
        selection.circuit_id != source_circuit_id
        or selection.operation_ids != expected_operation_ids
    ):
        msg = "calibration selection must exactly cover the prepared circuit"
        raise ValueError(msg)
    if lowered.source_circuit_id != source_circuit_id:
        msg = "lowered pulse proof must belong to the prepared circuit"
        raise ValueError(msg)
    if target_entry.program != scheduled:
        msg = "target compile entry must retain the exact scheduled pulse program"
        raise ValueError(msg)

    expected_event_origins = _event_origins(
        source_circuit_id,
        target_entry,
        lowered,
    )
    expected_acquisition_origins = _acquisition_origins(
        source_circuit_id,
        target_entry,
        lowered,
    )
    if event_origins != expected_event_origins:
        msg = "target event origins must exactly cover scheduled events in order"
        raise ValueError(msg)
    if acquisition_origins != expected_acquisition_origins:
        msg = "target acquisition origins must exactly cover scheduled slots in order"
        raise ValueError(msg)


__all__ = [
    "CircuitTargetAcquisitionOrigin",
    "CircuitTargetEventOrigin",
    "PreparedCircuitTargetBatch",
    "PreparedCircuitTargetEntry",
    "prepare_circuit_target_batch",
    "prepare_circuit_target_entry",
]
