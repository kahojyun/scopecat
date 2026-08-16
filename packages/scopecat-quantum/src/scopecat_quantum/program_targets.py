"""Materialize quantum pulse plans for target compilation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat_quantum._ids import TargetCompileEntryId
from scopecat_quantum.programs import (
    QuantumPulseLoweringPlan,
    materialize_quantum_pulse_program,
)
from scopecat_quantum.pulses import ScheduledPulseProgram, schedule
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetCompileEntry,
    TargetCompileRequest,
)


@dataclass(frozen=True, slots=True)
class PreparedQuantumTargetEntry:
    """One scheduled target entry."""

    target_entry: TargetCompileEntry

    @property
    def id(self) -> TargetCompileEntryId:
        return self.target_entry.id

    @property
    def scheduled(self) -> ScheduledPulseProgram:
        return self.target_entry.program

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return self.target_entry.acquisition_addresses


def prepare_quantum_target_entry(
    entry_id: TargetCompileEntryId,
    plan: QuantumPulseLoweringPlan,
) -> PreparedQuantumTargetEntry:
    """Materialize retained control flow and schedule one pulse plan."""

    scheduled = schedule(materialize_quantum_pulse_program(plan))
    target_entry = TargetCompileEntry(id=entry_id, program=scheduled)
    return PreparedQuantumTargetEntry(target_entry)


@dataclass(frozen=True, slots=True)
class PreparedQuantumTargetBatch:
    """Ordered prepared entries and their compile request."""

    entries: tuple[PreparedQuantumTargetEntry, ...]
    request: TargetCompileRequest

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return self.request.acquisition_addresses


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
