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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.pulses import ScheduledPulseProgram
from scopecat_quantum.result_collections import ResultCollection, iter_result_leaves


def _require_text(value: str, *, field: str) -> None:
    if not value.strip():
        msg = f"{field} must be non-empty"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TargetEventAddress:
    """Entry-qualified identity of one scheduled pulse event."""

    entry_id: TargetCompileEntryId
    event_id: PulseEventId


@dataclass(frozen=True, slots=True)
class TargetAcquisitionAddress:
    """Entry-qualified identity of one scheduled acquisition result."""

    entry_id: TargetCompileEntryId
    slot_id: AcquisitionSlotId


type TargetResultAddress = (
    TargetAcquisitionAddress | ResultCollection[TargetAcquisitionAddress]
)


def target_result_entry_id(address: TargetResultAddress) -> TargetCompileEntryId:
    """Return the one target entry owning every leaf of a result address."""

    entry_ids = {leaf.entry_id for leaf in iter_result_leaves(address)}
    if len(entry_ids) != 1:
        raise ValueError("one target result address cannot span compile entries")
    return next(iter(entry_ids))


def target_result_acquisition_addresses(
    address: TargetResultAddress,
) -> tuple[TargetAcquisitionAddress, ...]:
    """Flatten one logical result address in recursive axis order."""

    return tuple(iter_result_leaves(address))


@dataclass(frozen=True, slots=True)
class TargetCompileEntry:
    """One ordered, identity-bearing scheduled program in a compile request."""

    id: TargetCompileEntryId
    program: ScheduledPulseProgram

    @property
    def event_addresses(self) -> tuple[TargetEventAddress, ...]:
        """Return exact scheduled-event coverage in canonical program order."""

        return tuple(
            TargetEventAddress(entry_id=self.id, event_id=event.id)
            for event in self.program.events
        )

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

    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    entries: tuple[TargetCompileEntry, ...]
    repetitions: int

    def __post_init__(self) -> None:
        _require_text(
            self.capability_fingerprint,
            field="target capability fingerprint",
        )
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
    def event_addresses(self) -> tuple[TargetEventAddress, ...]:
        """Return exact event coverage in semantic entry and program order."""

        return tuple(
            address for entry in self.entries for address in entry.event_addresses
        )

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


@runtime_checkable
class TargetCompileRequestLike(Protocol):
    """Common dispatch and provenance carried by every target-owned request."""

    @property
    def target_id(self) -> TargetId: ...

    @property
    def compiler_id(self) -> TargetCompilerId: ...

    @property
    def capability_fingerprint(self) -> str: ...

    @property
    def source_entry_ids(self) -> tuple[TargetCompileEntryId, ...]: ...

    @property
    def repetitions(self) -> int: ...


class TargetCompilationIssueDimension(StrEnum):
    """Hardware-neutral part of target compilation that rejected input."""

    REQUEST = "request"
    CAPABILITY = "capability"
    PROGRAM = "program"
    COMPILER = "compiler"


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


@runtime_checkable
class TargetCompiler[
    RequestT: TargetCompileRequestLike,
    ArtifactT: TargetArtifact,
](Protocol):
    """Lower one closed target-owned request into one target artifact.

    This protocol does not own domain routing or input resolution. When used in
    an ``ExperimentSystem`` integration, it is an internal stage invoked by the
    domain compiler rather than a second system compiler. The request type is an
    associated adapter contract: no universal instruction shape is imposed here.
    """

    @property
    def id(self) -> TargetCompilerId: ...

    @property
    def target_id(self) -> TargetId: ...

    @property
    def capability_fingerprint(self) -> str: ...

    def compile(self, request: RequestT) -> ArtifactT: ...


@dataclass(frozen=True, slots=True)
class CompiledTargetArtifact[ArtifactT: TargetArtifact]:
    """Checked snapshot of return-time artifact provenance.

    This result records checks made immediately after the trusted in-process
    compiler returns. It is not a security boundary and cannot independently
    inspect or prove the meaning of a target-owned opaque payload.
    """

    request: TargetCompileRequestLike
    artifact: ArtifactT
    _artifact_id: TargetArtifactId = field(init=False)
    _artifact_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        issues = _target_artifact_issues(self.request, self.artifact)
        if issues:
            raise TargetCompilationError(issues)
        object.__setattr__(self, "_artifact_id", self.artifact.id)
        object.__setattr__(
            self,
            "_artifact_fingerprint",
            self.artifact.artifact_fingerprint,
        )

    @property
    def artifact_id(self) -> TargetArtifactId:
        return self._artifact_id

    @property
    def artifact_fingerprint(self) -> str:
        return self._artifact_fingerprint

    @property
    def target_id(self) -> TargetId:
        return self.request.target_id

    @property
    def compiler_id(self) -> TargetCompilerId:
        return self.request.compiler_id

    @property
    def capability_fingerprint(self) -> str:
        return self.request.capability_fingerprint

    @property
    def source_entry_ids(self) -> tuple[TargetCompileEntryId, ...]:
        return self.request.source_entry_ids

    @property
    def repetitions(self) -> int:
        return self.request.repetitions


def _target_artifact_issues(
    request: TargetCompileRequestLike,
    artifact: TargetArtifact,
) -> tuple[TargetCompilationIssue, ...]:
    expected_entry_ids = request.source_entry_ids
    issues: list[TargetCompilationIssue] = []
    if artifact.target_id != request.target_id:
        issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_target_mismatch",
                message="target artifact identifies another target",
            )
        )
    if artifact.compiler_id != request.compiler_id:
        issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_compiler_mismatch",
                message="target artifact identifies another compiler",
            )
        )
    if artifact.capability_fingerprint != request.capability_fingerprint:
        issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="target_artifact_capability_mismatch",
                message="target artifact has another capability fingerprint",
            )
        )
    if artifact.source_entry_ids != expected_entry_ids:
        issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_entry_coverage_mismatch",
                message="target artifact does not preserve ordered entry coverage",
            )
        )
    if artifact.repetitions != request.repetitions:
        issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_repetitions_mismatch",
                message="target artifact does not preserve finite repetitions",
            )
        )
    if not artifact.artifact_fingerprint.strip():
        issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_fingerprint_missing",
                message="target artifact requires a non-empty artifact fingerprint",
            )
        )
    return tuple(issues)


def compile_target[
    RequestT: TargetCompileRequestLike,
    ArtifactT: TargetArtifact,
](
    compiler: TargetCompiler[RequestT, ArtifactT],
    request: RequestT,
) -> CompiledTargetArtifact[ArtifactT]:
    """Check dispatch and return-time provenance around one compiler call.

    Expected target rejections remain ``TargetCompilationError``. Unexpected
    exceptions raised by the laboratory compiler are deliberately not caught
    or reclassified at this pure domain boundary. The compiler is trusted
    in-process domain code; untrusted or deserialized artifacts require fresh
    adapter-specific validation.
    """

    preflight_issues: list[TargetCompilationIssue] = []
    if request.target_id != compiler.target_id:
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.REQUEST,
                code="target_compile_request_target_mismatch",
                message="compile request does not select this compiler's target",
            )
        )
    if request.compiler_id != compiler.id:
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.REQUEST,
                code="target_compile_request_compiler_mismatch",
                message="compile request does not select this compiler",
            )
        )
    if request.capability_fingerprint != compiler.capability_fingerprint:
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="target_compile_request_capability_mismatch",
                message="compile request capability fingerprint is stale",
            )
        )
    if preflight_issues:
        raise TargetCompilationError(tuple(preflight_issues))

    artifact = compiler.compile(request)
    return CompiledTargetArtifact(request, artifact)
