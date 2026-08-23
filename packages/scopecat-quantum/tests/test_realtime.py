from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    PulseProgramId,
    QubitId,
    TargetCompileEntryId,
)
from scopecat_quantum.acquisitions import (
    CLASSIFIED_STATE_RESULT,
    INTEGRATED_IQ_RESULT,
    QuantumResultDimension,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    DriveSignal,
    Play,
    PulseProgram,
    ScheduledPulseProgram,
    schedule,
)
from scopecat_quantum.realtime import (
    ClassifiedStatePredicate,
    RealtimeCase,
    RealtimeConditional,
    RealtimeNoOp,
    RealtimeProgramValidationError,
    RealtimeRepeat,
    RealtimeSequence,
    ScheduledBlock,
    TargetProgram,
)
from scopecat_quantum.targets import TargetCompileEntry

Q0 = QubitId("q0")


def _acquisition_program(
    program_id: str,
    *,
    slot_id: AcquisitionSlotId,
    classified: bool,
    duration_ns: int = 8,
    rounds: int | None = None,
    event_id: str = "capture",
) -> ScheduledPulseProgram:
    contract = CLASSIFIED_STATE_RESULT if classified else INTEGRATED_IQ_RESULT
    if rounds is not None:
        contract = replace(
            contract,
            dimensions=(QuantumResultDimension("round", "round", rounds),),
        )
    signal = AcquireSignal(Q0)
    slot = AcquisitionSlot(id=slot_id, contract=contract, signal=signal)
    return schedule(
        PulseProgram(
            id=PulseProgramId(program_id),
            body=Acquire(
                id=PulseEventId(event_id),
                signal=signal,
                slot_id=slot.id,
                duration=Quantity(duration_ns, "ns"),
            ),
            acquisition_slots=(slot,),
        )
    )


def _correction_program(
    program_id: str = "conditional-x",
    *,
    duration_ns: int = 4,
) -> ScheduledPulseProgram:
    return schedule(
        PulseProgram(
            id=PulseProgramId(program_id),
            body=Play(
                id=PulseEventId("x"),
                signal=DriveSignal(Q0),
                envelope=Constant(
                    duration=Quantity(duration_ns, "ns"),
                    amplitude=Quantity(0.25, "arb"),
                ),
            ),
        )
    )


def _active_reset_body(
    measurement: ScheduledPulseProgram,
) -> RealtimeSequence:
    [slot] = measurement.acquisition_slots
    return RealtimeSequence(
        (
            ScheduledBlock(measurement),
            RealtimeConditional(
                predicate=ClassifiedStatePredicate(slot.id),
                cases=(RealtimeCase(1, ScheduledBlock(_correction_program())),),
                default=RealtimeNoOp(),
            ),
        )
    )


def test_static_schedule_is_the_trivial_target_program() -> None:
    scheduled = _correction_program()

    program = TargetProgram.from_scheduled(scheduled)

    assert isinstance(program.body, ScheduledBlock)
    assert program.envelope.minimum_duration_seconds == Decimal("4e-9")
    assert program.envelope.worst_case_duration_seconds == Decimal("4e-9")
    assert program.envelope.worst_case_operation_count == 1
    assert program.envelope.worst_case_acquisition_count == 0
    assert not program.envelope.has_variable_duration


def test_active_reset_retains_variable_branch_for_target_compilation() -> None:
    slot_id = AcquisitionSlotId("state")
    measurement = _acquisition_program(
        "classify",
        slot_id=slot_id,
        classified=True,
    )
    body = _active_reset_body(measurement)

    program = TargetProgram(PulseProgramId("active-reset"), body)
    entry = TargetCompileEntry(TargetCompileEntryId("point-0"), program)

    assert entry.program.body is body
    assert isinstance(entry.program.body, RealtimeSequence)
    assert isinstance(entry.program.body.instructions[1], RealtimeConditional)
    assert program.envelope.minimum_duration_seconds == Decimal("8e-9")
    assert program.envelope.worst_case_duration_seconds == Decimal("12e-9")
    assert program.envelope.has_variable_duration
    assert program.envelope.worst_case_operation_count == 3
    assert program.envelope.worst_case_acquisition_count == 1
    assert program.envelope.acquisition_slots == measurement.acquisition_slots
    assert program.envelope.logical_signals == (
        AcquireSignal(Q0),
        DriveSignal(Q0),
    )
    assert program.envelope.pulse_event_ids == (
        PulseEventId("capture"),
        PulseEventId("x"),
    )


def test_result_producing_repeat_uses_one_slot_with_a_bounded_local_axis() -> None:
    measurement = _acquisition_program(
        "round-classify",
        slot_id=AcquisitionSlotId("syndrome"),
        classified=True,
        rounds=3,
    )
    body = RealtimeRepeat(
        _active_reset_body(measurement),
        count=3,
        result_dimension_id="round",
    )

    program = TargetProgram(PulseProgramId("three-round-correction"), body)

    assert program.envelope.minimum_duration_seconds == Decimal("24e-9")
    assert program.envelope.worst_case_duration_seconds == Decimal("36e-9")
    assert program.envelope.worst_case_operation_count == 9
    assert program.envelope.worst_case_acquisition_count == 3
    assert program.envelope.acquisition_slots == measurement.acquisition_slots
    assert len(program.envelope.events) == 2


@pytest.mark.parametrize("result_dimension_id", [None, "round"])
def test_result_repeat_requires_a_matching_declared_dimension(
    result_dimension_id: str | None,
) -> None:
    measurement = _acquisition_program(
        "unshaped-classify",
        slot_id=AcquisitionSlotId("state"),
        classified=True,
    )
    body = RealtimeRepeat(
        _active_reset_body(measurement),
        count=3,
        result_dimension_id=result_dimension_id,
    )

    with pytest.raises(
        RealtimeProgramValidationError,
        match=(
            "realtime_repeat_result_dimension_missing"
            if result_dimension_id is None
            else "realtime_repeat_result_dimension_mismatch"
        ),
    ):
        TargetProgram(PulseProgramId("invalid-repeat"), body)


def test_predicate_requires_an_earlier_classified_acquisition() -> None:
    slot_id = AcquisitionSlotId("iq")
    measurement = _acquisition_program(
        "integrated-iq",
        slot_id=slot_id,
        classified=False,
    )
    conditional = RealtimeConditional(
        ClassifiedStatePredicate(slot_id),
        cases=(RealtimeCase(1, ScheduledBlock(_correction_program())),),
        default=RealtimeNoOp(),
    )

    with pytest.raises(RealtimeProgramValidationError) as exc_info:
        TargetProgram(
            PulseProgramId("conditional-before-measurement"),
            RealtimeSequence((conditional, ScheduledBlock(measurement))),
        )
    assert {issue.code for issue in exc_info.value.issues} == {
        "realtime_predicate_not_classified",
        "realtime_predicate_slot_unavailable",
    }


def test_acquisition_after_a_conditional_keeps_static_result_coverage() -> None:
    classified = _acquisition_program(
        "classify",
        slot_id=AcquisitionSlotId("state"),
        classified=True,
    )
    verification = _acquisition_program(
        "verify",
        slot_id=AcquisitionSlotId("verification"),
        classified=False,
        event_id="verify-capture",
    )
    body = _active_reset_body(classified)

    program = TargetProgram(
        PulseProgramId("active-reset-with-verification"),
        RealtimeSequence((*body.instructions, ScheduledBlock(verification))),
    )

    assert tuple(slot.id for slot in program.acquisition_slots) == (
        AcquisitionSlotId("state"),
        AcquisitionSlotId("verification"),
    )
    assert program.envelope.worst_case_acquisition_count == 2


def test_conditional_branch_acquisition_is_rejected() -> None:
    measurement = _acquisition_program(
        "classify",
        slot_id=AcquisitionSlotId("state"),
        classified=True,
    )
    branch_measurement = _acquisition_program(
        "branch-capture",
        slot_id=AcquisitionSlotId("branch-result"),
        classified=False,
    )
    [slot] = measurement.acquisition_slots

    with pytest.raises(
        RealtimeProgramValidationError,
        match="realtime_branch_acquisition",
    ):
        TargetProgram(
            PulseProgramId("branch-acquisition"),
            RealtimeSequence(
                (
                    ScheduledBlock(measurement),
                    RealtimeConditional(
                        ClassifiedStatePredicate(slot.id),
                        cases=(RealtimeCase(1, ScheduledBlock(branch_measurement)),),
                        default=RealtimeNoOp(),
                    ),
                )
            ),
        )


def test_event_identity_is_global_across_mutually_exclusive_cases() -> None:
    measurement = _acquisition_program(
        "classify",
        slot_id=AcquisitionSlotId("state"),
        classified=True,
    )
    [slot] = measurement.acquisition_slots

    with pytest.raises(
        RealtimeProgramValidationError,
        match="realtime_pulse_event_duplicate",
    ):
        TargetProgram(
            PulseProgramId("duplicate-case-events"),
            RealtimeSequence(
                (
                    ScheduledBlock(measurement),
                    RealtimeConditional(
                        ClassifiedStatePredicate(slot.id),
                        cases=(
                            RealtimeCase(
                                1,
                                ScheduledBlock(_correction_program("case-one")),
                            ),
                            RealtimeCase(
                                2,
                                ScheduledBlock(_correction_program("case-two")),
                            ),
                        ),
                        default=RealtimeNoOp(),
                    ),
                )
            ),
        )


def test_dimensioned_predicate_is_scalar_only_in_its_current_repeat() -> None:
    measurement = _acquisition_program(
        "round-classify",
        slot_id=AcquisitionSlotId("state"),
        classified=True,
        rounds=3,
    )

    with pytest.raises(
        RealtimeProgramValidationError,
        match="realtime_predicate_dimensions_inactive",
    ):
        TargetProgram(
            PulseProgramId("array-valued-predicate"),
            _active_reset_body(measurement),
        )


def test_realtime_nodes_reject_unbounded_or_ambiguous_local_shapes() -> None:
    with pytest.raises(ValueError, match="positive finite integer"):
        RealtimeRepeat(RealtimeNoOp(), count=0)
    with pytest.raises(ValueError, match="at least one case"):
        RealtimeConditional(
            ClassifiedStatePredicate(AcquisitionSlotId("state")),
            cases=(),
            default=RealtimeNoOp(),
        )
    with pytest.raises(ValueError, match="case states must be unique"):
        RealtimeConditional(
            ClassifiedStatePredicate(AcquisitionSlotId("state")),
            cases=(
                RealtimeCase(1, RealtimeNoOp()),
                RealtimeCase(1, RealtimeNoOp()),
            ),
            default=RealtimeNoOp(),
        )
    with pytest.raises(ValueError, match="case state must be an integer"):
        RealtimeCase(True, RealtimeNoOp())
    with pytest.raises(ValueError, match="case state must be an integer"):
        RealtimeCase(cast("int", 1.0), RealtimeNoOp())


def test_result_free_repeat_rejects_a_result_dimension() -> None:
    with pytest.raises(
        RealtimeProgramValidationError,
        match="realtime_repeat_result_dimension_unused",
    ):
        TargetProgram(
            PulseProgramId("dimension-without-result"),
            RealtimeRepeat(
                ScheduledBlock(_correction_program()),
                count=3,
                result_dimension_id="round",
            ),
        )
