from __future__ import annotations

from dataclasses import dataclass

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
    TargetCompileRequest,
    TargetEventAddress,
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

    def compile(self, request: TargetCompileRequest) -> _Artifact:
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


def test_target_artifact_protocol_admits_a_laboratory_adapter() -> None:
    compiler = _Compiler(
        id=TargetCompilerId("reference-compiler"),
        target_id=TargetId("reference-target"),
        capability_fingerprint="capabilities:v1",
    )

    artifact: TargetArtifact = compiler.compile(_request())

    assert isinstance(artifact, TargetArtifact)
    assert artifact.source_entry_ids == (TargetCompileEntryId("point-0"),)
    assert artifact.repetitions == 5
    assert artifact.artifact_fingerprint == "artifact-content:v1"


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
            entries=(),
            repetitions=1,
        )

    entry = TargetCompileEntry(
        id=TargetCompileEntryId("point-0"),
        program=_scheduled_program(),
    )
    with pytest.raises(ValueError, match="entry ids must be unique"):
        TargetCompileRequest(
            entries=(entry, entry),
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
