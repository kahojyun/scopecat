"""Hardware-neutral contracts for lowering quantum programs to targets.

The objects in this module describe the boundary between the reusable quantum
package and a laboratory-owned target adapter.  They intentionally say
nothing about physical instruments, transport, wiring, or artifact layout.

A target compiler is pure and consumes canonical scheduled programs. Concrete
payloads remain opaque and laboratory-owned; stable target, compiler, capability,
artifact, entry, and acquisition identities provide correlation without defining
a universal hardware schema. Adapter fingerprints must cover opaque artifact
content because core cannot interpret that content itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.pulses import ScheduledPulseProgram


def _require_text(value: str, *, field: str) -> None:
    if not value.strip():
        msg = f"{field} must be non-empty"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TargetAcquisitionAddress:
    """Entry-qualified identity of one scheduled acquisition result."""

    entry_id: TargetCompileEntryId
    slot_id: AcquisitionSlotId


@dataclass(frozen=True, slots=True)
class TargetCompileEntry:
    """One ordered, identity-bearing scheduled program in a compile request."""

    id: TargetCompileEntryId
    program: ScheduledPulseProgram

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        """Return exact acquisition-slot coverage in canonical program order."""

        return tuple(
            TargetAcquisitionAddress(entry_id=self.id, slot_id=slot.id)
            for slot in self.program.acquisition_slots
        )


@dataclass(frozen=True, slots=True)
class TargetCompileRequest:
    """Closed target-lowering input for a finite batch.

    Entry order is semantic and is therefore retained.  Each entry already
    contains a canonical :class:`ScheduledPulseProgram`; target adapters are
    responsible only for accepting and lowering that representation.
    """

    entries: tuple[TargetCompileEntry, ...]
    repetitions: int

    def __post_init__(self) -> None:
        if not self.entries:
            msg = "target compile requests require at least one entry"
            raise ValueError(msg)
        entry_ids = tuple(entry.id for entry in self.entries)
        if len(set(entry_ids)) != len(entry_ids):
            msg = "target compile entry ids must be unique"
            raise ValueError(msg)
        if self.repetitions <= 0:
            msg = "target compile repetitions must be a positive finite integer"
            raise ValueError(msg)

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        """Return exact result coverage in semantic entry and slot order."""

        return tuple(
            address for entry in self.entries for address in entry.acquisition_addresses
        )

    @property
    def source_entry_ids(self) -> tuple[TargetCompileEntryId, ...]:
        """Return the ordered source inventory covered by the request."""

        return tuple(entry.id for entry in self.entries)


class TargetCompilationIssueDimension(StrEnum):
    """Hardware-neutral part of target compilation that rejected input."""

    CAPABILITY = "capability"
    PROGRAM = "program"


@dataclass(frozen=True, slots=True)
class TargetCompilationIssue:
    """One structured target-compilation finding."""

    dimension: TargetCompilationIssueDimension
    code: str
    message: str
    entry_id: TargetCompileEntryId | None = None

    def __post_init__(self) -> None:
        _require_text(self.code, field="target compilation issue code")
        _require_text(self.message, field="target compilation issue message")


class TargetCompilationError(ValueError):
    """Aggregate deterministic rejection from a target compiler."""

    def __init__(self, issues: tuple[TargetCompilationIssue, ...]) -> None:
        if not issues:
            msg = "target compilation errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(
            sorted(
                issues,
                key=lambda issue: (
                    "" if issue.entry_id is None else issue.entry_id.value,
                    issue.dimension.value,
                    issue.code,
                    issue.message,
                ),
            )
        )
        super().__init__("; ".join(issue.message for issue in self.issues))


@runtime_checkable
class TargetArtifact(Protocol):
    """Identity and provenance common to every target-owned artifact.

    Implementations are required by contract to be logically immutable after
    ``compile`` returns, and ``artifact_fingerprint`` must identify the opaque
    payload as well as its metadata. Python's structural protocol cannot
    enforce either property; concrete adapter contract tests must do so.
    """

    @property
    def id(self) -> TargetArtifactId: ...

    @property
    def target_id(self) -> TargetId: ...

    @property
    def compiler_id(self) -> TargetCompilerId: ...

    @property
    def capability_fingerprint(self) -> str: ...

    @property
    def artifact_fingerprint(self) -> str: ...

    @property
    def source_entry_ids(self) -> tuple[TargetCompileEntryId, ...]: ...

    @property
    def repetitions(self) -> int: ...
