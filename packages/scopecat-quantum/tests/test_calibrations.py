from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, dataclass, fields
from typing import cast

import pytest
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.calibrations import (
    CalibrationCatalog,
    CalibrationSelection,
    CalibrationSelectionError,
    CalibrationSelectionIssue,
    CalibrationSelectionIssueCode,
    GateCalibration,
    GateCalibrationArgument,
    GateCalibrationBinding,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateCalibrationSelection,
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
    select_calibrations,
)
from scopecat_quantum.circuits import (
    CircuitProgram,
    Measure,
    Sequence,
    VerifiedCircuitProgram,
    verify_circuit_program,
)
from scopecat_quantum.gates import (
    GateArgument,
    GateArgumentValue,
    GateCall,
    GateDefinition,
    GateParameterDefinition,
    GateParameterKind,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Delay,
    DriveSignal,
    Play,
    PulseInstruction,
    PulseProgram,
    ReadoutSignal,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.pulses import (
    Sequence as PulseSequence,
)

X = GateDefinition(
    id=GateId("x"),
    qubit_arity=1,
    parameters=(GateParameterDefinition(id="angle", kind=GateParameterKind.ANGLE),),
)
Y = GateDefinition(
    id=GateId("y"),
    qubit_arity=1,
    parameters=(GateParameterDefinition(id="angle", kind=GateParameterKind.ANGLE),),
)
ROTATE = GateDefinition(
    id=GateId("rotate"),
    qubit_arity=1,
    parameters=(
        GateParameterDefinition(id="angle", kind=GateParameterKind.ANGLE),
        GateParameterDefinition(id="phase", kind=GateParameterKind.ANGLE),
    ),
)
Q0 = QubitId("q0")
Q1 = QubitId("q1")


def _pulse_template() -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId("calibrated-pulse"),
        body=Delay(
            id=PulseEventId("delay"),
            signal=DriveSignal(Q0),
            duration=Quantity(20, "ns"),
        ),
    )


def _measurement_template() -> PulseProgram:
    acquire_signal = AcquireSignal(Q0)
    slot = AcquisitionSlot(
        AcquisitionSlotId("template-result"),
        AcquisitionKind.INTEGRATED_IQ,
        acquire_signal,
    )
    return PulseProgram(
        id=PulseProgramId("readout-template"),
        body=PulseParallel(
            (
                Play(
                    PulseEventId("readout"),
                    ReadoutSignal(Q0),
                    Constant(Quantity(200, "ns"), Quantity(0.2, "ratio")),
                ),
                Acquire(
                    PulseEventId("acquire"),
                    acquire_signal,
                    slot.id,
                    Quantity(200, "ns"),
                ),
            )
        ),
        acquisition_slots=(slot,),
    )


def _call(
    operation_id: str,
    *,
    gate_id: GateId = X.id,
    qubit: QubitId = Q0,
    angle: float = 0.5,
) -> GateCall:
    return GateCall(
        id=CircuitOperationId(operation_id),
        gate_id=gate_id,
        qubits=(qubit,),
        arguments=(GateArgument(id="angle", value=Quantity(angle, "rad")),),
    )


def _verified(*calls: GateCall) -> VerifiedCircuitProgram:
    return verify_circuit_program(
        CircuitProgram(
            id=CircuitId("circuit"),
            body=Sequence(operations=calls),
        ),
        gate_definitions=(X, Y, ROTATE),
    )


def _calibration(
    calibration_id: str,
    call: GateCall,
    *,
    pulse_template: PulseProgram | None = None,
) -> GateCalibration:
    return GateCalibration(
        id=CalibrationId(calibration_id),
        key=GateCalibrationKey.from_call(call),
        pulse_template=pulse_template or _pulse_template(),
    )


def _catalog(*calibrations: GateCalibration) -> CalibrationCatalog:
    return CalibrationCatalog(gates=GateCalibrationCatalog(calibrations))


def test_exact_calibration_key_contains_call_data_not_gate_definition() -> None:
    call = _call("x-q0")

    key = GateCalibrationKey.from_call(call)

    assert {item.name for item in fields(GateCalibrationKey)} == {
        "gate_id",
        "operands",
        "arguments",
    }
    assert key == GateCalibrationKey(
        gate_id=GateId("x"),
        operands=(Q0,),
        arguments=(GateCalibrationArgument(id="angle", value=Quantity(0.5, "rad")),),
    )


def test_selection_seals_exact_gate_call_coverage() -> None:
    first = _call("first")
    second = _call("second")
    pulse = _pulse_template()

    selection = select_calibrations(
        _verified(first, second),
        _catalog(_calibration("x-q0", first, pulse_template=pulse)),
    )

    assert selection.operation_ids == (first.id, second.id)
    assert selection.gates.gate_call_ids == (first.id, second.id)
    assert tuple(binding.call_id for binding in selection.gates.bindings) == (
        first.id,
        second.id,
    )
    assert selection.gates.binding_for(first.id).pulse_template is pulse
    assert selection.binding_for(first.id).pulse_template is pulse
    with pytest.raises(TypeError, match="only be created by select_calibrations"):
        CalibrationSelection(
            CircuitId("forged"),
            (),
            selection.gates,
            selection.measurements,
        )
    with pytest.raises(TypeError, match="only be created by select_calibrations"):
        GateCalibrationSelection(CircuitId("forged"), (), ())
    attribute = "_circuit_id"
    with pytest.raises(FrozenInstanceError):
        setattr(cast("object", selection), attribute, CircuitId("forged"))


def test_named_argument_order_does_not_change_calibration_selection() -> None:
    catalog_call = GateCall(
        id=CircuitOperationId("catalog-call"),
        gate_id=ROTATE.id,
        qubits=(Q0,),
        arguments=(
            GateArgument(id="phase", value=Quantity(0.25, "rad")),
            GateArgument(id="angle", value=Quantity(0.5, "rad")),
        ),
    )
    program_call = GateCall(
        id=CircuitOperationId("program-call"),
        gate_id=ROTATE.id,
        qubits=(Q0,),
        arguments=(
            GateArgument(id="angle", value=Quantity(0.5, "rad")),
            GateArgument(id="phase", value=Quantity(0.25, "rad")),
        ),
    )

    selection = select_calibrations(
        _verified(program_call),
        _catalog(_calibration("rotate", catalog_call)),
    )

    assert selection.gates.gate_call_ids == (program_call.id,)
    assert selection.gates.bindings[0].key.arguments == (
        GateCalibrationArgument(id="angle", value=Quantity(0.5, "rad")),
        GateCalibrationArgument(id="phase", value=Quantity(0.25, "rad")),
    )


def test_equivalent_angle_units_have_one_exact_calibration_key() -> None:
    catalog_call = GateCall(
        id=CircuitOperationId("catalog-call"),
        gate_id=X.id,
        qubits=(Q0,),
        arguments=(GateArgument(id="angle", value=Quantity(180, "deg")),),
    )
    program_call = GateCall(
        id=CircuitOperationId("program-call"),
        gate_id=X.id,
        qubits=(Q0,),
        arguments=(GateArgument(id="angle", value=Quantity(math.pi, "rad")),),
    )
    calibration = _calibration("x-180", catalog_call)

    selection = select_calibrations(
        _verified(program_call),
        _catalog(calibration),
    )

    assert selection.gates.bindings[0].key == calibration.key
    assert calibration.key.arguments[0].value == Quantity(
        3.14159265359,
        "rad",
    )


def test_calibration_key_rejects_duplicate_named_arguments() -> None:
    with pytest.raises(ValueError, match="argument ids must be unique"):
        GateCalibrationKey(
            gate_id=ROTATE.id,
            operands=(Q0,),
            arguments=(
                GateCalibrationArgument(id="angle", value=Quantity(0.5, "rad")),
                GateCalibrationArgument(id="angle", value=Quantity(0.25, "rad")),
            ),
        )


def test_measurement_without_calibration_prevents_aggregate_selection() -> None:
    call = _call("gate")
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=Q0,
        acquisition_slot_id=AcquisitionSlotId("readout"),
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    program = verify_circuit_program(
        CircuitProgram(
            id=CircuitId("measured-circuit"),
            body=Sequence(operations=(call, measurement)),
        ),
        gate_definitions=(X,),
    )

    with pytest.raises(CalibrationSelectionError) as raised:
        select_calibrations(program, _catalog(_calibration("gate", call)))

    assert len(raised.value.issues) == 1
    issue = raised.value.issues[0]
    assert issue.code is CalibrationSelectionIssueCode.MISSING
    assert issue.operation_id == measurement.id
    assert issue.matching_calibration_ids == ()
    assert issue.message == "operation 'measure' has no exact calibration"
    assert issue.key == MeasurementCalibrationKey(
        qubit=Q0,
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )


def test_ambiguous_measurement_calibrations_are_order_independent() -> None:
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=Q0,
        acquisition_slot_id=AcquisitionSlotId("result"),
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    program = verify_circuit_program(
        CircuitProgram(CircuitId("measurement"), measurement),
        gate_definitions=(),
    )
    key = MeasurementCalibrationKey.from_measurement(measurement)
    template = _measurement_template()
    entries = (
        MeasurementCalibration(CalibrationId("readout-z"), key, template),
        MeasurementCalibration(CalibrationId("readout-a"), key, template),
    )

    errors: list[CalibrationSelectionError] = []
    for ordered_entries in (entries, tuple(reversed(entries))):
        with pytest.raises(CalibrationSelectionError) as raised:
            select_calibrations(
                program,
                CalibrationCatalog(
                    measurements=MeasurementCalibrationCatalog(ordered_entries)
                ),
            )
        errors.append(raised.value)

    assert errors[0].issues == errors[1].issues
    assert errors[0].issues[0].code is CalibrationSelectionIssueCode.AMBIGUOUS
    assert errors[0].issues[0].operation_id == measurement.id
    assert errors[0].issues[0].matching_calibration_ids == (
        CalibrationId("readout-a"),
        CalibrationId("readout-z"),
    )


def test_missing_and_ambiguous_calibrations_are_aggregated_order_independently() -> (
    None
):
    missing = _call("missing", gate_id=X.id)
    ambiguous = _call("ambiguous", gate_id=Y.id)
    first_match = _calibration("y-a", ambiguous)
    second_match = _calibration("y-b", ambiguous)
    program = _verified(missing, ambiguous)

    with pytest.raises(CalibrationSelectionError) as forward:
        select_calibrations(
            program,
            _catalog(first_match, second_match),
        )
    with pytest.raises(CalibrationSelectionError) as reversed_order:
        select_calibrations(
            program,
            _catalog(second_match, first_match),
        )

    assert forward.value.issues == reversed_order.value.issues
    issues_by_operation = {issue.operation_id: issue for issue in forward.value.issues}
    assert issues_by_operation[missing.id].code is CalibrationSelectionIssueCode.MISSING
    assert (
        issues_by_operation[ambiguous.id].code
        is CalibrationSelectionIssueCode.AMBIGUOUS
    )
    assert issues_by_operation[ambiguous.id].matching_calibration_ids == (
        CalibrationId("y-a"),
        CalibrationId("y-b"),
    )


@pytest.mark.parametrize(
    "other_call",
    [
        _call("different-operand", qubit=Q1),
        _call("different-argument", angle=0.25),
        _call("different-gate", gate_id=Y.id),
    ],
)
def test_selection_never_falls_back_from_an_exact_key(other_call: GateCall) -> None:
    catalog_call = _call("catalog-call")

    with pytest.raises(CalibrationSelectionError) as raised:
        select_calibrations(
            _verified(other_call),
            _catalog(_calibration("catalog", catalog_call)),
        )

    assert raised.value.issues[0].code is CalibrationSelectionIssueCode.MISSING


def test_catalog_identity_is_unique_even_when_keys_differ() -> None:
    with pytest.raises(ValueError, match="calibration ids must be unique"):
        GateCalibrationCatalog(
            (
                _calibration("duplicate", _call("first")),
                _calibration("duplicate", _call("second", gate_id=Y.id)),
            )
        )


@pytest.mark.parametrize(
    "value",
    [
        True,
        float("nan"),
        float("inf"),
        Quantity(float("nan"), "rad"),
        Quantity(1, "V"),
        "not-a-gate-value",
    ],
)
def test_calibration_argument_rejects_invalid_runtime_values(value: object) -> None:
    with pytest.raises(ValueError, match="finite gate argument value"):
        GateCalibrationArgument(
            id="angle",
            value=cast("GateArgumentValue", value),
        )


def test_calibration_argument_rejects_malformed_quantity_shape() -> None:
    malformed = Quantity.model_construct(
        value=cast("float", "not-a-number"),
        unit="rad",
    )

    with pytest.raises(ValueError, match="finite gate argument value"):
        GateCalibrationArgument(id="angle", value=malformed)


def test_calibration_argument_accepts_arbitrarily_large_integers() -> None:
    argument = GateCalibrationArgument(id="count", value=10**1000)

    assert argument.value == 10**1000


def test_calibration_key_closes_nominal_runtime_shapes() -> None:
    argument = GateCalibrationArgument(id="angle", value=Quantity(0.5, "rad"))
    with pytest.raises(ValueError, match="gate_id must be a GateId"):
        GateCalibrationKey(
            gate_id=cast("GateId", Q0),
            operands=(Q0,),
            arguments=(argument,),
        )
    with pytest.raises(ValueError, match="tuple of QubitId"):
        GateCalibrationKey(
            gate_id=X.id,
            operands=cast("tuple[QubitId, ...]", (X.id,)),
            arguments=(argument,),
        )
    with pytest.raises(ValueError, match="tuple of GateCalibrationArgument"):
        GateCalibrationKey(
            gate_id=X.id,
            operands=(Q0,),
            arguments=cast("tuple[GateCalibrationArgument, ...]", (Q0,)),
        )


@pytest.mark.parametrize("operands", [(), (Q0, Q0)])
def test_calibration_key_requires_nonempty_unique_operands(
    operands: tuple[QubitId, ...],
) -> None:
    with pytest.raises(ValueError, match="operand"):
        GateCalibrationKey(gate_id=X.id, operands=operands)


def test_gate_calibration_and_catalog_close_runtime_shapes() -> None:
    key = GateCalibrationKey.from_call(_call("call"))
    pulse = _pulse_template()
    with pytest.raises(ValueError, match="id must be a CalibrationId"):
        GateCalibration(
            id=cast("CalibrationId", CircuitOperationId("wrong-space")),
            key=key,
            pulse_template=pulse,
        )
    with pytest.raises(ValueError, match="key must be a GateCalibrationKey"):
        GateCalibration(
            id=CalibrationId("calibration"),
            key=cast("GateCalibrationKey", _call("not-a-key")),
            pulse_template=pulse,
        )
    with pytest.raises(ValueError, match="require a pulse template"):
        GateCalibration(
            id=CalibrationId("calibration"),
            key=key,
            pulse_template=cast("PulseProgram", object()),
        )
    invalid_template_id = PulseProgram(
        id=cast("PulseProgramId", CalibrationId("wrong-space")),
        body=pulse.body,
    )
    with pytest.raises(ValueError, match="template id must be a PulseProgramId"):
        GateCalibration(
            id=CalibrationId("calibration"),
            key=key,
            pulse_template=invalid_template_id,
        )
    with pytest.raises(ValueError, match="template id must be a PulseProgramId"):
        GateCalibrationBinding(
            call_id=CircuitOperationId("call"),
            key=key,
            calibration_id=CalibrationId("calibration"),
            pulse_template=invalid_template_id,
        )
    with pytest.raises(ValueError, match="tuple of GateCalibration"):
        GateCalibrationCatalog(
            entries=cast(
                "tuple[GateCalibration, ...]",
                [_calibration("calibration", _call("catalog-call"))],
            )
        )
    with pytest.raises(ValueError, match="tuple of GateCalibration"):
        GateCalibrationCatalog(entries=cast("tuple[GateCalibration, ...]", (key,)))
    with pytest.raises(ValueError, match="gates must be a GateCalibrationCatalog"):
        CalibrationCatalog(gates=cast("GateCalibrationCatalog", ()))


def test_issue_and_binding_close_nominal_runtime_shapes() -> None:
    call = _call("call")
    key = GateCalibrationKey.from_call(call)
    pulse = _pulse_template()
    with pytest.raises(ValueError, match="operation_id must be a CircuitOperationId"):
        CalibrationSelectionIssue(
            code=CalibrationSelectionIssueCode.MISSING,
            operation_id=cast("CircuitOperationId", CalibrationId("wrong-space")),
            key=key,
            matching_calibration_ids=(),
            message="missing",
        )
    with pytest.raises(ValueError, match="issue code is invalid"):
        CalibrationSelectionIssue(
            code=cast("CalibrationSelectionIssueCode", "missing"),
            operation_id=call.id,
            key=key,
            matching_calibration_ids=(),
            message="missing",
        )
    with pytest.raises(ValueError, match="issue key is invalid"):
        CalibrationSelectionIssue(
            code=CalibrationSelectionIssueCode.MISSING,
            operation_id=call.id,
            key=cast("GateCalibrationKey", call),
            matching_calibration_ids=(),
            message="missing",
        )
    with pytest.raises(ValueError, match="tuple of CalibrationId"):
        CalibrationSelectionIssue(
            code=CalibrationSelectionIssueCode.MISSING,
            operation_id=call.id,
            key=key,
            matching_calibration_ids=cast("tuple[CalibrationId, ...]", (call.id,)),
            message="missing",
        )
    with pytest.raises(ValueError, match="message must be non-empty"):
        CalibrationSelectionIssue(
            code=CalibrationSelectionIssueCode.MISSING,
            operation_id=call.id,
            key=key,
            matching_calibration_ids=(),
            message=" ",
        )
    with pytest.raises(ValueError, match="cannot contain matching ids"):
        CalibrationSelectionIssue(
            code=CalibrationSelectionIssueCode.MISSING,
            operation_id=call.id,
            key=key,
            matching_calibration_ids=(CalibrationId("unexpected"),),
            message="missing",
        )
    with pytest.raises(ValueError, match="at least two matching ids"):
        CalibrationSelectionIssue(
            code=CalibrationSelectionIssueCode.AMBIGUOUS,
            operation_id=call.id,
            key=key,
            matching_calibration_ids=(CalibrationId("only-one"),),
            message="ambiguous",
        )
    with pytest.raises(ValueError, match="calibration_id must be a CalibrationId"):
        GateCalibrationBinding(
            call_id=call.id,
            key=key,
            calibration_id=cast("CalibrationId", call.id),
            pulse_template=pulse,
        )
    with pytest.raises(ValueError, match="binding call_id"):
        GateCalibrationBinding(
            call_id=cast("CircuitOperationId", CalibrationId("wrong-space")),
            key=key,
            calibration_id=CalibrationId("calibration"),
            pulse_template=pulse,
        )
    with pytest.raises(ValueError, match="binding key"):
        GateCalibrationBinding(
            call_id=call.id,
            key=cast("GateCalibrationKey", call),
            calibration_id=CalibrationId("calibration"),
            pulse_template=pulse,
        )
    with pytest.raises(ValueError, match="requires a PulseProgram"):
        GateCalibrationBinding(
            call_id=call.id,
            key=key,
            calibration_id=CalibrationId("calibration"),
            pulse_template=cast("PulseProgram", object()),
        )
    issue = CalibrationSelectionIssue(
        code=CalibrationSelectionIssueCode.MISSING,
        operation_id=call.id,
        key=key,
        matching_calibration_ids=(),
        message="missing",
    )
    with pytest.raises(ValueError, match="tuple of CalibrationSelectionIssue"):
        CalibrationSelectionError(
            cast("tuple[CalibrationSelectionIssue, ...]", [issue])
        )


def test_gate_calibrations_cannot_produce_acquisition_results() -> None:
    call = _call("call")
    key = GateCalibrationKey.from_call(call)
    acquire_signal = AcquireSignal(Q0)
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("readout"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=acquire_signal,
    )
    declared_slot_program = PulseProgram(
        id=PulseProgramId("declares-acquisition"),
        body=Delay(
            id=PulseEventId("delay"),
            signal=DriveSignal(Q0),
            duration=Quantity(20, "ns"),
        ),
        acquisition_slots=(slot,),
    )
    acquire_program = PulseProgram(
        id=PulseProgramId("contains-acquire"),
        body=PulseSequence(
            instructions=(
                Acquire(
                    id=PulseEventId("acquire"),
                    signal=acquire_signal,
                    slot_id=slot.id,
                    duration=Quantity(20, "ns"),
                ),
            )
        ),
    )

    for pulse_template in (declared_slot_program, acquire_program):
        with pytest.raises(ValueError, match="cannot declare acquisition slots"):
            GateCalibration(
                id=CalibrationId("calibration"),
                key=key,
                pulse_template=pulse_template,
            )
        with pytest.raises(ValueError, match="cannot reference pulse templates"):
            GateCalibrationBinding(
                call_id=call.id,
                key=key,
                calibration_id=CalibrationId("calibration"),
                pulse_template=pulse_template,
            )


def test_gate_calibration_rejects_duplicate_template_event_identities_early() -> None:
    call = _call("call")
    duplicate = PulseEventId("delay", scope=("relative",))
    pulse_template = PulseProgram(
        id=PulseProgramId("duplicate-events"),
        body=PulseSequence(
            (
                Delay(duplicate, DriveSignal(Q0), Quantity(10, "ns")),
                Delay(duplicate, DriveSignal(Q0), Quantity(10, "ns")),
            )
        ),
    )

    with pytest.raises(ValueError, match="template event ids must be unique"):
        GateCalibration(
            id=CalibrationId("calibration"),
            key=GateCalibrationKey.from_call(call),
            pulse_template=pulse_template,
        )


@dataclass(frozen=True, slots=True)
class _AlienPulseNode:
    branches: tuple[PulseInstruction, ...]


def test_gate_calibration_rejects_unknown_template_nodes_early() -> None:
    call = _call("call")
    pulse_template = PulseProgram(
        id=PulseProgramId("alien"),
        body=cast(
            "PulseInstruction",
            _AlienPulseNode((_pulse_template().body,)),
        ),
    )

    with pytest.raises(ValueError, match="must contain pulse instructions"):
        GateCalibration(
            id=CalibrationId("calibration"),
            key=GateCalibrationKey.from_call(call),
            pulse_template=pulse_template,
        )


def test_selection_never_seals_a_cross_identity_calibration_id() -> None:
    call = _call("call")
    calibration = _calibration("calibration", call)
    catalog = _catalog(calibration)
    object.__setattr__(
        calibration,
        "id",
        CircuitOperationId("cross-identity-space"),
    )

    with pytest.raises(ValueError, match="calibration_id must be a CalibrationId"):
        select_calibrations(_verified(call), catalog)
