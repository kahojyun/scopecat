"""Hardware-neutral contracts for lowering scheduled quantum programs.

The objects in this module describe the boundary between the reusable quantum
package and a laboratory-owned target adapter.  They intentionally say
nothing about physical instruments, transport, wiring, or artifact layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.pulses import ScheduledPulseProgram


def _require_text(value: str, *, field: str) -> None:
    selected = cast("object", value)
    if not isinstance(selected, str) or not selected.strip():
        msg = f"{field} must be non-empty"
        raise ValueError(msg)


def _require_valid_event_id(value: object) -> None:
    if not isinstance(value, PulseEventId):
        msg = "target event address event_id must be a PulseEventId"
        raise TypeError(msg)
    try:
        PulseEventId(local_id=value.local_id, scope=value.scope)
    except (AttributeError, TypeError, ValueError) as error:
        msg = "target event address event_id must be a valid PulseEventId"
        raise ValueError(msg) from error


def _require_valid_acquisition_slot_id(value: object) -> None:
    if not isinstance(value, AcquisitionSlotId):
        msg = "target acquisition address slot_id must be an AcquisitionSlotId"
        raise TypeError(msg)
    try:
        AcquisitionSlotId(local_id=value.local_id, scope=value.scope)
    except (AttributeError, TypeError, ValueError) as error:
        msg = "target acquisition address slot_id must be a valid AcquisitionSlotId"
        raise ValueError(msg) from error


@dataclass(frozen=True, slots=True)
class TargetEventAddress:
    """Entry-qualified identity of one scheduled pulse event."""

    entry_id: TargetCompileEntryId
    event_id: PulseEventId

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.entry_id), TargetCompileEntryId):
            msg = "target event address entry_id must be a TargetCompileEntryId"
            raise TypeError(msg)
        _require_valid_event_id(cast("object", self.event_id))


@dataclass(frozen=True, slots=True)
class TargetAcquisitionAddress:
    """Entry-qualified identity of one scheduled acquisition result."""

    entry_id: TargetCompileEntryId
    slot_id: AcquisitionSlotId

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.entry_id), TargetCompileEntryId):
            msg = "target acquisition address entry_id must be a TargetCompileEntryId"
            raise TypeError(msg)
        _require_valid_acquisition_slot_id(cast("object", self.slot_id))


@dataclass(frozen=True, slots=True)
class TargetCompileEntry:
    """One ordered, identity-bearing scheduled program in a compile request."""

    id: TargetCompileEntryId
    program: ScheduledPulseProgram

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.id), TargetCompileEntryId):
            msg = "target compile entry id must be a TargetCompileEntryId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.program), ScheduledPulseProgram):
            msg = "target compile entries require a scheduled pulse program"
            raise TypeError(msg)

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
        if not isinstance(cast("object", self.target_id), TargetId):
            msg = "target compile request target_id must be a TargetId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.compiler_id), TargetCompilerId):
            msg = "target compile request compiler_id must be a TargetCompilerId"
            raise TypeError(msg)
        _require_text(
            self.capability_fingerprint,
            field="target capability fingerprint",
        )
        entries = cast("object", self.entries)
        if not isinstance(entries, tuple) or not all(
            isinstance(entry, TargetCompileEntry)
            for entry in cast("tuple[object, ...]", entries)
        ):
            msg = "target compile request entries must be TargetCompileEntry values"
            raise TypeError(msg)
        if not self.entries:
            msg = "target compile requests require at least one entry"
            raise ValueError(msg)
        entry_ids = tuple(entry.id for entry in self.entries)
        if len(set(entry_ids)) != len(entry_ids):
            msg = "target compile entry ids must be unique"
            raise ValueError(msg)
        repetitions = cast("object", self.repetitions)
        if (
            isinstance(repetitions, bool)
            or not isinstance(repetitions, int)
            or repetitions <= 0
        ):
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
        if not isinstance(
            cast("object", self.dimension),
            TargetCompilationIssueDimension,
        ):
            msg = "target compilation issue dimension is invalid"
            raise TypeError(msg)
        entry_id = cast("object", self.entry_id)
        if entry_id is not None and not isinstance(entry_id, TargetCompileEntryId):
            msg = "target compilation issue entry_id must be a TargetCompileEntryId"
            raise TypeError(msg)
        _require_text(self.code, field="target compilation issue code")
        _require_text(self.message, field="target compilation issue message")


class TargetCompilationError(ValueError):
    """Aggregate deterministic rejection from a target compiler."""

    def __init__(self, issues: tuple[TargetCompilationIssue, ...]) -> None:
        raw_issues = cast("object", issues)
        if not isinstance(raw_issues, tuple) or not all(
            isinstance(issue, TargetCompilationIssue)
            for issue in cast("tuple[object, ...]", raw_issues)
        ):
            msg = (
                "target compilation errors require a tuple of "
                "TargetCompilationIssue values"
            )
            raise TypeError(msg)
        selected_issues = cast("tuple[TargetCompilationIssue, ...]", raw_issues)
        if not selected_issues:
            msg = "target compilation errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(
            sorted(
                selected_issues,
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
class TargetDescription(Protocol):
    """Minimum description a laboratory target exposes to quantum tooling."""

    @property
    def id(self) -> TargetId: ...

    @property
    def capability_fingerprint(self) -> str: ...


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
class TargetCompiler[ArtifactT: TargetArtifact](Protocol):
    """Laboratory-provided compiler for one quantum target."""

    @property
    def id(self) -> TargetCompilerId: ...

    @property
    def target_id(self) -> TargetId: ...

    @property
    def capability_fingerprint(self) -> str: ...

    def compile(self, request: TargetCompileRequest) -> ArtifactT: ...


@dataclass(frozen=True, slots=True, init=False)
class CompiledTargetArtifact[ArtifactT: TargetArtifact]:
    """Checked snapshot of return-time artifact provenance.

    This result records checks made immediately after the trusted in-process
    compiler returns. It is not a security boundary and cannot independently
    inspect or prove the meaning of a target-owned opaque payload.
    """

    _request: TargetCompileRequest
    _artifact: ArtifactT
    _artifact_id: TargetArtifactId
    _artifact_fingerprint: str

    def __init__(
        self,
        request: TargetCompileRequest,
        artifact: ArtifactT,
        *,
        _verified_artifact_id: TargetArtifactId | None = None,
        _verified_artifact_fingerprint: str | None = None,
    ) -> None:
        if _verified_artifact_id is None or _verified_artifact_fingerprint is None:
            msg = "compiled target artifact result is missing checked provenance"
            raise AssertionError(msg)
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_artifact", artifact)
        object.__setattr__(self, "_artifact_id", _verified_artifact_id)
        object.__setattr__(
            self,
            "_artifact_fingerprint",
            _verified_artifact_fingerprint,
        )

    @property
    def request(self) -> TargetCompileRequest:
        return self._request

    @property
    def artifact(self) -> ArtifactT:
        return self._artifact

    @property
    def artifact_id(self) -> TargetArtifactId:
        return self._artifact_id

    @property
    def artifact_fingerprint(self) -> str:
        return self._artifact_fingerprint

    @property
    def target_id(self) -> TargetId:
        return self._request.target_id

    @property
    def compiler_id(self) -> TargetCompilerId:
        return self._request.compiler_id

    @property
    def capability_fingerprint(self) -> str:
        return self._request.capability_fingerprint

    @property
    def source_entry_ids(self) -> tuple[TargetCompileEntryId, ...]:
        return tuple(entry.id for entry in self._request.entries)

    @property
    def repetitions(self) -> int:
        return self._request.repetitions


def compile_target[ArtifactT: TargetArtifact](
    compiler: TargetCompiler[ArtifactT],
    request: TargetCompileRequest,
) -> CompiledTargetArtifact[ArtifactT]:
    """Check dispatch and return-time provenance around one compiler call.

    Expected target rejections remain ``TargetCompilationError``. Unexpected
    exceptions raised by the laboratory compiler are deliberately not caught
    or reclassified at this pure domain boundary. The compiler is trusted
    in-process domain code; untrusted or deserialized artifacts require fresh
    adapter-specific validation.
    """

    preflight_issues: list[TargetCompilationIssue] = []
    compiler_target_id = cast("object", compiler.target_id)
    if not isinstance(compiler_target_id, TargetId):
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_compiler_target_id_type_invalid",
                message="target compiler target_id is not a TargetId",
            )
        )
    elif request.target_id != compiler_target_id:
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.REQUEST,
                code="target_compile_request_target_mismatch",
                message="compile request does not select this compiler's target",
            )
        )
    compiler_id = cast("object", compiler.id)
    if not isinstance(compiler_id, TargetCompilerId):
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_compiler_id_type_invalid",
                message="target compiler id is not a TargetCompilerId",
            )
        )
    elif request.compiler_id != compiler_id:
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.REQUEST,
                code="target_compile_request_compiler_mismatch",
                message="compile request does not select this compiler",
            )
        )
    compiler_capability = cast("object", compiler.capability_fingerprint)
    if not isinstance(compiler_capability, str) or not compiler_capability.strip():
        preflight_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_compiler_capability_fingerprint_invalid",
                message="target compiler capability fingerprint must be non-empty",
            )
        )
    elif request.capability_fingerprint != compiler_capability:
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
    if not isinstance(cast("object", artifact), TargetArtifact):
        raise TargetCompilationError(
            (
                TargetCompilationIssue(
                    dimension=TargetCompilationIssueDimension.COMPILER,
                    code="target_artifact_contract_invalid",
                    message="target compiler returned an invalid artifact contract",
                ),
            )
        )

    expected_entry_ids = tuple(entry.id for entry in request.entries)
    artifact_issues: list[TargetCompilationIssue] = []
    artifact_id = cast("object", artifact.id)
    if not isinstance(artifact_id, TargetArtifactId):
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_id_type_invalid",
                message="target artifact id is not a TargetArtifactId",
            )
        )
    artifact_target_id = cast("object", artifact.target_id)
    if not isinstance(artifact_target_id, TargetId):
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_target_id_type_invalid",
                message="target artifact target_id is not a TargetId",
            )
        )
    elif artifact_target_id != request.target_id:
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_target_mismatch",
                message="target artifact identifies another target",
            )
        )
    artifact_compiler_id = cast("object", artifact.compiler_id)
    if not isinstance(artifact_compiler_id, TargetCompilerId):
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_compiler_id_type_invalid",
                message="target artifact compiler_id is not a TargetCompilerId",
            )
        )
    elif artifact_compiler_id != request.compiler_id:
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_compiler_mismatch",
                message="target artifact identifies another compiler",
            )
        )
    artifact_capability = cast("object", artifact.capability_fingerprint)
    if not isinstance(artifact_capability, str):
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_capability_fingerprint_type_invalid",
                message="target artifact capability fingerprint must be a string",
            )
        )
    elif artifact_capability != request.capability_fingerprint:
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.CAPABILITY,
                code="target_artifact_capability_mismatch",
                message="target artifact has another capability fingerprint",
            )
        )
    source_entry_ids = cast("object", artifact.source_entry_ids)
    if not isinstance(source_entry_ids, tuple) or not all(
        isinstance(entry_id, TargetCompileEntryId)
        for entry_id in cast("tuple[object, ...]", source_entry_ids)
    ):
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_source_entry_ids_type_invalid",
                message=(
                    "target artifact source_entry_ids must be "
                    "TargetCompileEntryId values"
                ),
            )
        )
    elif source_entry_ids != expected_entry_ids:
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_entry_coverage_mismatch",
                message="target artifact does not preserve ordered entry coverage",
            )
        )
    artifact_repetitions = cast("object", artifact.repetitions)
    if isinstance(artifact_repetitions, bool) or not isinstance(
        artifact_repetitions, int
    ):
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_repetitions_type_invalid",
                message="target artifact repetitions must be an integer",
            )
        )
    elif artifact_repetitions != request.repetitions:
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_repetitions_mismatch",
                message="target artifact does not preserve finite repetitions",
            )
        )
    fingerprint = cast("object", artifact.artifact_fingerprint)
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        artifact_issues.append(
            TargetCompilationIssue(
                dimension=TargetCompilationIssueDimension.COMPILER,
                code="target_artifact_fingerprint_missing",
                message="target artifact requires a non-empty artifact fingerprint",
            )
        )
    if artifact_issues:
        raise TargetCompilationError(tuple(artifact_issues))

    return CompiledTargetArtifact(
        request,
        artifact,
        _verified_artifact_id=cast("TargetArtifactId", artifact_id),
        _verified_artifact_fingerprint=cast("str", fingerprint),
    )


__all__ = [
    "CompiledTargetArtifact",
    "TargetAcquisitionAddress",
    "TargetArtifact",
    "TargetCompilationError",
    "TargetCompilationIssue",
    "TargetCompilationIssueDimension",
    "TargetCompileEntry",
    "TargetCompileRequest",
    "TargetCompiler",
    "TargetDescription",
    "TargetEventAddress",
    "compile_target",
]
