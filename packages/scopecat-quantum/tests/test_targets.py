from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    PulseProgramId,
    QubitId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Delay,
    DriveSignal,
    PulseProgram,
    ScheduledPulseProgram,
    schedule,
)
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetArtifact,
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
    TargetCompileEntry,
    TargetCompiler,
    TargetCompileRequest,
    TargetEventAddress,
    compile_target,
)


def _scheduled_program() -> ScheduledPulseProgram:
    return schedule(
        PulseProgram(
            id=PulseProgramId("scheduled-program"),
            body=Delay(
                id=PulseEventId("delay"),
                signal=DriveSignal(QubitId("q0")),
                duration=Quantity(20, "ns"),
            ),
        )
    )


def _scheduled_acquisition_program(
    program_id: str,
    *,
    qubit_id: str,
) -> ScheduledPulseProgram:
    signal = AcquireSignal(QubitId(qubit_id))
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("result", scope=("local",)),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=signal,
    )
    return schedule(
        PulseProgram(
            id=PulseProgramId(program_id),
            body=Acquire(
                id=PulseEventId("capture", scope=("local",)),
                signal=signal,
                slot_id=slot.id,
                duration=Quantity(20, "ns"),
            ),
            acquisition_slots=(slot,),
        )
    )


def _request(*, repetitions: int = 5) -> TargetCompileRequest:
    return TargetCompileRequest(
        target_id=TargetId("reference-target"),
        compiler_id=TargetCompilerId("reference-compiler"),
        capability_fingerprint="capabilities:v1",
        entries=(
            TargetCompileEntry(
                id=TargetCompileEntryId("point-0"),
                program=_scheduled_program(),
            ),
        ),
        repetitions=repetitions,
    )


@dataclass(frozen=True)
class _Artifact:
    id: TargetArtifactId
    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    artifact_fingerprint: str
    source_entry_ids: tuple[TargetCompileEntryId, ...]
    repetitions: int
    payload: bytes


@dataclass
class _Compiler:
    id: TargetCompilerId
    target_id: TargetId
    capability_fingerprint: str
    calls: int = 0

    def compile(self, request: TargetCompileRequest) -> _Artifact:
        self.calls += 1
        issues: list[TargetCompilationIssue] = []
        if request.target_id != self.target_id:
            issues.append(
                TargetCompilationIssue(
                    dimension=TargetCompilationIssueDimension.REQUEST,
                    code="target_mismatch",
                    message="request selects another target",
                )
            )
        if request.compiler_id != self.id:
            issues.append(
                TargetCompilationIssue(
                    dimension=TargetCompilationIssueDimension.REQUEST,
                    code="compiler_mismatch",
                    message="request selects another compiler",
                )
            )
        if request.capability_fingerprint != self.capability_fingerprint:
            issues.append(
                TargetCompilationIssue(
                    dimension=TargetCompilationIssueDimension.CAPABILITY,
                    code="capability_mismatch",
                    message="target capabilities changed",
                )
            )
        if issues:
            raise TargetCompilationError(tuple(issues))
        return _Artifact(
            id=TargetArtifactId("artifact-0"),
            target_id=self.target_id,
            compiler_id=self.id,
            capability_fingerprint=self.capability_fingerprint,
            artifact_fingerprint="artifact-content:v1",
            source_entry_ids=tuple(entry.id for entry in request.entries),
            repetitions=request.repetitions,
            payload=b"opaque target-owned artifact",
        )


def test_structural_target_protocols_admit_a_laboratory_adapter() -> None:
    compiler: TargetCompiler[_Artifact] = _Compiler(
        id=TargetCompilerId("reference-compiler"),
        target_id=TargetId("reference-target"),
        capability_fingerprint="capabilities:v1",
    )

    compiled = compile_target(compiler, _request())
    artifact: TargetArtifact = compiled.artifact

    assert isinstance(compiler, TargetCompiler)
    assert isinstance(artifact, TargetArtifact)
    assert artifact.source_entry_ids == (TargetCompileEntryId("point-0"),)
    assert artifact.repetitions == 5
    assert artifact.artifact_fingerprint == "artifact-content:v1"
    assert compiled.source_entry_ids == (TargetCompileEntryId("point-0"),)


def test_addresses_cover_entries_in_exact_schedule_order() -> None:
    first = TargetCompileEntry(
        id=TargetCompileEntryId("point-0"),
        program=_scheduled_acquisition_program("first", qubit_id="q0"),
    )
    second = TargetCompileEntry(
        id=TargetCompileEntryId("point-1"),
        program=_scheduled_acquisition_program("second", qubit_id="q1"),
    )
    request = TargetCompileRequest(
        target_id=TargetId("reference-target"),
        compiler_id=TargetCompilerId("reference-compiler"),
        capability_fingerprint="capabilities:v1",
        entries=(second, first),
        repetitions=2,
    )

    shared_event_id = PulseEventId("capture", scope=("local",))
    shared_slot_id = AcquisitionSlotId("result", scope=("local",))
    assert first.event_addresses == (TargetEventAddress(first.id, shared_event_id),)
    assert first.acquisition_addresses == (
        TargetAcquisitionAddress(first.id, shared_slot_id),
    )
    assert request.event_addresses == (
        TargetEventAddress(second.id, shared_event_id),
        TargetEventAddress(first.id, shared_event_id),
    )
    assert request.acquisition_addresses == (
        TargetAcquisitionAddress(second.id, shared_slot_id),
        TargetAcquisitionAddress(first.id, shared_slot_id),
    )
    assert len(set(request.event_addresses)) == 2
    assert len(set(request.acquisition_addresses)) == 2


@pytest.mark.parametrize("repetitions", [0, -1])
def test_compile_request_rejects_non_positive_repetitions(
    repetitions: int,
) -> None:
    with pytest.raises(ValueError, match="positive finite integer"):
        _request(repetitions=repetitions)


def test_compile_request_rejects_empty_and_duplicate_entry_sets() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        TargetCompileRequest(
            target_id=TargetId("reference-target"),
            compiler_id=TargetCompilerId("reference-compiler"),
            capability_fingerprint="capabilities:v1",
            entries=(),
            repetitions=1,
        )

    entry = TargetCompileEntry(
        id=TargetCompileEntryId("point-0"),
        program=_scheduled_program(),
    )
    with pytest.raises(ValueError, match="entry ids must be unique"):
        TargetCompileRequest(
            target_id=TargetId("reference-target"),
            compiler_id=TargetCompilerId("reference-compiler"),
            capability_fingerprint="capabilities:v1",
            entries=(entry, entry),
            repetitions=1,
        )


def test_compile_request_requires_a_capability_fingerprint() -> None:
    with pytest.raises(ValueError, match="capability fingerprint"):
        TargetCompileRequest(
            target_id=TargetId("reference-target"),
            compiler_id=TargetCompilerId("reference-compiler"),
            capability_fingerprint=" ",
            entries=(
                TargetCompileEntry(
                    id=TargetCompileEntryId("point-0"),
                    program=_scheduled_program(),
                ),
            ),
            repetitions=1,
        )


def test_target_compilation_error_carries_stably_ordered_structured_issues() -> None:
    later = TargetCompilationIssue(
        dimension=TargetCompilationIssueDimension.PROGRAM,
        code="unsupported_instruction",
        message="entry b has an unsupported instruction",
        entry_id=TargetCompileEntryId("b"),
    )
    earlier = TargetCompilationIssue(
        dimension=TargetCompilationIssueDimension.CAPABILITY,
        code="duration_limit",
        message="entry a exceeds the target duration limit",
        entry_id=TargetCompileEntryId("a"),
    )

    error = TargetCompilationError((later, earlier))

    assert error.issues == (earlier, later)


def test_compile_target_rejects_dispatch_mismatch_before_calling_compiler() -> None:
    compiler = _Compiler(
        id=TargetCompilerId("reference-compiler"),
        target_id=TargetId("reference-target"),
        capability_fingerprint="capabilities:v1",
    )
    request = replace(_request(), target_id=TargetId("another-target"))

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert compiler.calls == 0
    assert {issue.code for issue in raised.value.issues} == {
        "target_compile_request_target_mismatch"
    }


@dataclass
class _BadArtifactCompiler:
    id: TargetCompilerId
    target_id: TargetId
    capability_fingerprint: str

    def compile(self, request: TargetCompileRequest) -> _Artifact:
        return _Artifact(
            id=TargetArtifactId("bad-artifact"),
            target_id=TargetId("another-target"),
            compiler_id=TargetCompilerId("another-compiler"),
            capability_fingerprint="other-capabilities",
            artifact_fingerprint=" ",
            source_entry_ids=tuple(entry.id for entry in reversed(request.entries)),
            repetitions=request.repetitions + 1,
            payload=b"bad",
        )


def test_compile_target_aggregates_bad_artifact_correlation() -> None:
    compiler = _BadArtifactCompiler(
        id=TargetCompilerId("reference-compiler"),
        target_id=TargetId("reference-target"),
        capability_fingerprint="capabilities:v1",
    )

    request = _request()
    request = replace(
        request,
        entries=(
            *request.entries,
            TargetCompileEntry(
                id=TargetCompileEntryId("point-1"),
                program=_scheduled_program(),
            ),
        ),
    )

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert {issue.code for issue in raised.value.issues} == {
        "target_artifact_target_mismatch",
        "target_artifact_compiler_mismatch",
        "target_artifact_capability_mismatch",
        "target_artifact_entry_coverage_mismatch",
        "target_artifact_repetitions_mismatch",
        "target_artifact_fingerprint_missing",
    }


@dataclass
class _ExplodingCompiler:
    id: TargetCompilerId
    target_id: TargetId
    capability_fingerprint: str

    def compile(self, request: TargetCompileRequest) -> _Artifact:
        _ = request
        raise RuntimeError("unexpected compiler bug")


def test_compile_target_does_not_reclassify_unexpected_compiler_errors() -> None:
    compiler = _ExplodingCompiler(
        id=TargetCompilerId("reference-compiler"),
        target_id=TargetId("reference-target"),
        capability_fingerprint="capabilities:v1",
    )

    with pytest.raises(RuntimeError, match="unexpected compiler bug"):
        compile_target(compiler, _request())
