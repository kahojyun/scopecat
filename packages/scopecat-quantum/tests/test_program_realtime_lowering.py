from __future__ import annotations

import pytest
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    PulseEventId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
    TargetCompileEntryId,
)
from scopecat_quantum.acquisitions import (
    CLASSIFIED_STATE_RESULT,
    INTEGRATED_IQ_RESULT,
    QuantumResultContract,
    QuantumResultDimension,
)
from scopecat_quantum.program_targets import prepare_quantum_target_entry
from scopecat_quantum.programs import (
    Conditional,
    Parallel,
    PulseBlock,
    QuantumProgramIR,
    QuantumProgramVerificationError,
    Repeat,
    Sequence,
    materialize_quantum_pulse_program,
    materialize_quantum_target_program,
    plan_quantum_pulse_lowering,
    verify_quantum_program,
)
from scopecat_quantum.pulse_implementations import ResolvedPulseImplementations
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Delay,
    DriveSignal,
    Play,
    PulseProgram,
    ReadoutSignal,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.realtime import (
    RealtimeConditional,
    RealtimeNoOp,
    RealtimeRepeat,
    RealtimeSequence,
    ScheduledBlock,
)

Q0 = QubitId("q0")


def _acquire(
    operation_id: str,
    output_id: AcquisitionSlotId,
    contract: QuantumResultContract,
) -> PulseBlock:
    template_id = AcquisitionSlotId("result")
    slot = AcquisitionSlot(
        id=template_id,
        contract=contract,
        signal=AcquireSignal(Q0),
    )
    duration = Quantity(8, "ns")
    return PulseBlock(
        id=CircuitOperationId(operation_id),
        pulse_template=PulseProgram(
            id=PulseProgramId(f"{operation_id}-template"),
            body=PulseParallel(
                (
                    Play(
                        id=PulseEventId("readout"),
                        signal=ReadoutSignal(Q0),
                        envelope=Constant(
                            duration=duration,
                            amplitude=Quantity(0.25, "arb"),
                        ),
                    ),
                    Acquire(
                        id=PulseEventId("capture"),
                        signal=slot.signal,
                        slot_id=slot.id,
                        duration=duration,
                    ),
                )
            ),
            acquisition_slots=(slot,),
        ),
        acquisition_slot_bindings=((template_id, output_id),),
    )


def _drive(operation_id: str) -> PulseBlock:
    return PulseBlock(
        id=CircuitOperationId(operation_id),
        pulse_template=PulseProgram(
            id=PulseProgramId(f"{operation_id}-template"),
            body=Delay(
                id=PulseEventId("drive"),
                signal=DriveSignal(Q0),
                duration=Quantity(4, "ns"),
            ),
        ),
    )


def _plan(body: object):
    assert isinstance(body, PulseBlock | Sequence | Parallel | Repeat | Conditional)
    verified = verify_quantum_program(
        QuantumProgramIR(QuantumProgramId("feedback"), body),
        (),
    )
    return plan_quantum_pulse_lowering(
        verified,
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("feedback-pulses"),
    )


def _issue_codes(body: object) -> set[str]:
    assert isinstance(body, PulseBlock | Sequence | Parallel | Repeat | Conditional)
    with pytest.raises(QuantumProgramVerificationError) as caught:
        verify_quantum_program(
            QuantumProgramIR(QuantumProgramId("invalid-feedback"), body),
            (),
        )
    return {issue.code for issue in caught.value.issues}


def test_active_reset_lowers_static_runs_around_one_conditional() -> None:
    state_id = AcquisitionSlotId("state")
    final_id = AcquisitionSlotId("final-iq")
    plan = _plan(
        Sequence(
            (
                _acquire("classify", state_id, CLASSIFIED_STATE_RESULT),
                Conditional(
                    predicate=state_id,
                    cases=((1, _drive("reset-x")),),
                    default=None,
                ),
                _acquire("final", final_id, INTEGRATED_IQ_RESULT),
            )
        )
    )

    target = prepare_quantum_target_entry(
        TargetCompileEntryId("active-reset"),
        plan,
    ).program

    assert isinstance(target.body, RealtimeSequence)
    before, decision, after = target.body.instructions
    assert isinstance(before, ScheduledBlock)
    assert isinstance(decision, RealtimeConditional)
    assert isinstance(after, ScheduledBlock)
    assert isinstance(decision.default, RealtimeNoOp)
    [reset_case] = decision.cases
    assert isinstance(reset_case.body, ScheduledBlock)
    assert decision.predicate.slot_id == state_id
    assert target.id == PulseProgramId("feedback-pulses")
    assert (
        before.program.id,
        reset_case.body.program.id,
        after.program.id,
    ) == (
        PulseProgramId("feedback-pulses/blocks/0"),
        PulseProgramId("feedback-pulses/blocks/1"),
        PulseProgramId("feedback-pulses/blocks/2"),
    )
    assert tuple(slot.id for slot in target.acquisition_slots) == (state_id, final_id)
    assert tuple(slot.contract for slot in target.acquisition_slots) == (
        CLASSIFIED_STATE_RESULT,
        INTEGRATED_IQ_RESULT,
    )

    with pytest.raises(ValueError, match="TargetProgram"):
        materialize_quantum_pulse_program(plan)


def test_result_repeat_retains_one_dimensioned_slot_and_one_event_union() -> None:
    rounds = QuantumResultDimension("round", "round", 3)
    contract = CLASSIFIED_STATE_RESULT.with_dimensions(rounds)
    state_id = AcquisitionSlotId("syndrome")
    plan = _plan(
        Repeat(
            Sequence(
                (
                    _acquire("syndrome", state_id, contract),
                    Conditional(
                        predicate=state_id,
                        cases=((1, _drive("correct")),),
                    ),
                )
            ),
            count=3,
            result_dimension_id="round",
        )
    )

    target = materialize_quantum_target_program(plan)

    assert isinstance(target.body, RealtimeRepeat)
    assert target.body.count == 3
    assert target.body.result_dimension_id == "round"
    assert isinstance(target.body.instruction, RealtimeSequence)
    [slot] = target.acquisition_slots
    assert slot.id == state_id
    assert slot.contract == contract
    assert "repeat[" not in slot.id.qualified_name
    assert target.envelope.worst_case_acquisition_count == 3
    assert len(target.envelope.events) == 3
    assert target.envelope.worst_case_operation_count == 12


def test_zero_count_realtime_repeat_materializes_as_noop() -> None:
    plan = _plan(
        Repeat(
            Conditional(
                predicate=AcquisitionSlotId("never-read"),
                cases=((1, _drive("never-run")),),
            ),
            count=0,
        )
    )

    target = materialize_quantum_target_program(plan)

    assert isinstance(target.body, RealtimeNoOp)
    assert target.acquisition_slots == ()
    assert target.envelope.worst_case_operation_count == 0


def test_source_conditional_validates_case_table() -> None:
    predicate = AcquisitionSlotId("state")
    body = _drive("x")

    with pytest.raises(ValueError, match="at least one"):
        Conditional(predicate, ())
    with pytest.raises(ValueError, match="integers"):
        Conditional(predicate, ((True, body),))
    with pytest.raises(ValueError, match="unique"):
        Conditional(predicate, ((1, body), (1, body)))


def test_conditional_rejects_unavailable_or_nonclassified_predicates() -> None:
    state_id = AcquisitionSlotId("state")
    body = Sequence(
        (
            Conditional(state_id, ((1, _drive("too-early")),)),
            _acquire("integrate", state_id, INTEGRATED_IQ_RESULT),
        )
    )

    assert _issue_codes(body) == {
        "quantum_conditional_predicate_not_classified",
        "quantum_conditional_predicate_unavailable",
    }


def test_conditional_branches_cannot_acquire() -> None:
    state_id = AcquisitionSlotId("state")
    branch_id = AcquisitionSlotId("branch-result")
    body = Sequence(
        (
            _acquire("classify", state_id, CLASSIFIED_STATE_RESULT),
            Conditional(
                state_id,
                ((1, _acquire("branch-readout", branch_id, INTEGRATED_IQ_RESULT)),),
            ),
        )
    )

    assert _issue_codes(body) == {"quantum_conditional_branch_acquisition"}


@pytest.mark.parametrize(
    ("repeat", "expected_code"),
    (
        (
            Repeat(
                _acquire(
                    "missing-axis",
                    AcquisitionSlotId("missing-axis"),
                    CLASSIFIED_STATE_RESULT,
                ),
                3,
            ),
            "quantum_repeat_result_dimension_missing",
        ),
        (
            Repeat(
                _acquire(
                    "wrong-axis",
                    AcquisitionSlotId("wrong-axis"),
                    CLASSIFIED_STATE_RESULT.with_dimensions(
                        QuantumResultDimension("round", "round", 2)
                    ),
                ),
                3,
                "round",
            ),
            "quantum_repeat_result_dimension_mismatch",
        ),
        (
            Repeat(_drive("unused-axis"), 3, "round"),
            "quantum_repeat_result_dimension_unused",
        ),
    ),
)
def test_result_repeat_requires_an_exact_body_dimension(
    repeat: Repeat,
    expected_code: str,
) -> None:
    assert expected_code in _issue_codes(repeat)


def test_nested_result_repeats_cannot_reenter_one_dimension() -> None:
    contract = CLASSIFIED_STATE_RESULT.with_dimensions(
        QuantumResultDimension("round", "round", 2)
    )
    body = Repeat(
        Repeat(
            _acquire("nested", AcquisitionSlotId("nested"), contract),
            2,
            "round",
        ),
        2,
        "round",
    )

    assert "quantum_repeat_result_dimension_reentered" in _issue_codes(body)


def test_nested_result_repeats_can_use_distinct_dimensions() -> None:
    contract = CLASSIFIED_STATE_RESULT.with_dimensions(
        QuantumResultDimension("round", "round", 2),
        QuantumResultDimension("capture", "capture", 3),
    )
    plan = _plan(
        Repeat(
            Repeat(
                _acquire("nested", AcquisitionSlotId("nested"), contract),
                3,
                "capture",
            ),
            2,
            "round",
        )
    )

    target = materialize_quantum_target_program(plan)

    assert isinstance(target.body, RealtimeRepeat)
    assert isinstance(target.body.instruction, RealtimeRepeat)
    assert target.body.result_dimension_id == "round"
    assert target.body.instruction.result_dimension_id == "capture"
    assert len(target.acquisition_slots) == 1
    assert target.envelope.worst_case_acquisition_count == 6


def test_parallel_regions_reject_realtime_control() -> None:
    state_id = AcquisitionSlotId("state")
    body = Sequence(
        (
            _acquire("classify", state_id, CLASSIFIED_STATE_RESULT),
            Parallel(
                (
                    Conditional(state_id, ((1, _drive("conditional-drive")),)),
                    _drive("parallel-drive"),
                )
            ),
        )
    )

    assert _issue_codes(body) == {"quantum_realtime_parallel_unsupported"}
