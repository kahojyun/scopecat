from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
from decimal import Decimal
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from scopecat import Quantity

from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    Barrier,
    CalibrationCatalog,
    CalibrationId,
    CircuitId,
    CircuitNode,
    CircuitOperationId,
    CircuitParallel,
    CircuitProgram,
    CircuitPulseLoweringError,
    CircuitPulseLoweringIssueCode,
    CircuitSequence,
    Constant,
    Delay,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateCall,
    GateDefinition,
    GateId,
    GatePulseInstantiation,
    LoweredCircuitPulseProgram,
    Measure,
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
    MeasurementPulseInstantiation,
    Play,
    PulseEventId,
    PulseInstruction,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    PulseSequence,
    PulseValidationError,
    QubitId,
    ReadoutSignal,
    VerifiedCircuitProgram,
    lower_circuit_to_pulses,
    schedule,
    select_calibrations,
    verify_circuit_program,
)

X = GateDefinition(GateId("x"), qubit_arity=1)
Q0 = QubitId("q0")
Q1 = QubitId("q1")
Q2 = QubitId("q2")
Q3 = QubitId("q3")


@dataclass(frozen=True, slots=True)
class _LeafShape:
    kind: str


@dataclass(frozen=True, slots=True)
class _SequenceShape:
    children: tuple[_TreeShape, ...]


@dataclass(frozen=True, slots=True)
class _ParallelShape:
    children: tuple[_TreeShape, ...]


type _TreeShape = _LeafShape | _SequenceShape | _ParallelShape


_TREE_SHAPES = st.recursive(
    st.sampled_from(
        (
            _LeafShape("play"),
            _LeafShape("delay"),
            _LeafShape("barrier"),
        )
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=3).map(lambda items: _SequenceShape(tuple(items))),
        st.lists(children, max_size=3).map(lambda items: _ParallelShape(tuple(items))),
    ),
    max_leaves=6,
)


def _shape_leaf_count(shape: _TreeShape) -> int:
    if isinstance(shape, _LeafShape):
        return 1
    return sum(_shape_leaf_count(child) for child in shape.children)


def _call(operation_id: str, qubit: QubitId = Q0) -> GateCall:
    return GateCall(
        id=CircuitOperationId(operation_id),
        gate_id=X.id,
        qubits=(qubit,),
    )


def _verified(
    body: GateCall | Measure | CircuitSequence | CircuitParallel,
    *,
    circuit_id: str = "circuit",
) -> VerifiedCircuitProgram:
    return verify_circuit_program(
        CircuitProgram(CircuitId(circuit_id), body),
        (X,),
    )


def _template(
    qubit: QubitId,
    *durations_ns: int,
    program_id: str = "template",
    local_id: str = "pulse",
    relative_scope: tuple[str, ...] = (),
) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=PulseSequence(
            tuple(
                Delay(
                    id=PulseEventId(
                        f"{local_id}-{index}",
                        scope=relative_scope,
                    ),
                    signal=DriveSignal(qubit),
                    duration=Quantity(duration_ns, "ns"),
                )
                for index, duration_ns in enumerate(durations_ns)
            )
        ),
    )


def _build_circuit_shape(
    shape: _TreeShape,
    calls: list[GateCall],
) -> CircuitNode:
    if isinstance(shape, _LeafShape):
        index = len(calls)
        call = _call(f"generated-call-{index}", QubitId(f"generated-q-{index}"))
        calls.append(call)
        return call
    children = tuple(_build_circuit_shape(child, calls) for child in shape.children)
    if isinstance(shape, _SequenceShape):
        return CircuitSequence(children)
    return CircuitParallel(children)


def _build_pulse_shape(
    shape: _TreeShape,
    *,
    qubit: QubitId,
    leaf_count: list[int],
) -> PulseInstruction:
    if isinstance(shape, _LeafShape):
        index = leaf_count[0]
        leaf_count[0] += 1
        event_id = PulseEventId(
            f"{shape.kind}-{index}",
            scope=("template/relative",),
        )
        signal = DriveSignal(qubit)
        if shape.kind == "play":
            return Play(
                event_id,
                signal,
                Constant(Quantity(1, "ns"), Quantity(0.25, "arb")),
            )
        if shape.kind == "delay":
            return Delay(event_id, signal, Quantity(1, "ns"))
        return Barrier(event_id, (signal,))
    children = tuple(
        _build_pulse_shape(child, qubit=qubit, leaf_count=leaf_count)
        for child in shape.children
    )
    if isinstance(shape, _SequenceShape):
        return PulseSequence(children)
    return PulseParallel(children)


def _calibration(
    calibration_id: str,
    call: GateCall,
    template: PulseProgram,
) -> GateCalibration:
    return GateCalibration(
        id=CalibrationId(calibration_id),
        key=GateCalibrationKey.from_call(call),
        pulse_template=template,
    )


def _measurement_template(
    qubit: QubitId,
    *,
    template_slot_id: AcquisitionSlotId | None = None,
    duration_ns: int = 8,
    program_id: str = "measurement-template",
) -> PulseProgram:
    acquire_signal = AcquireSignal(qubit)
    slot = AcquisitionSlot(
        id=template_slot_id or AcquisitionSlotId("template-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=acquire_signal,
    )
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=PulseParallel(
            (
                Play(
                    PulseEventId("stimulus", scope=("readout",)),
                    ReadoutSignal(qubit),
                    Constant(
                        Quantity(duration_ns, "ns"),
                        Quantity(0.4, "arb"),
                    ),
                ),
                Acquire(
                    PulseEventId("capture", scope=("readout",)),
                    acquire_signal,
                    slot.id,
                    Quantity(duration_ns, "ns"),
                ),
            )
        ),
        acquisition_slots=(slot,),
    )


def _measurement_calibration(
    calibration_id: str,
    measurement: Measure,
    template: PulseProgram,
) -> MeasurementCalibration:
    return MeasurementCalibration(
        id=CalibrationId(calibration_id),
        key=MeasurementCalibrationKey.from_measurement(measurement),
        pulse_template=template,
    )


def _lower(
    program: VerifiedCircuitProgram,
    calibrations: tuple[GateCalibration, ...],
    *,
    output_id: str = "lowered",
) -> LoweredCircuitPulseProgram:
    return lower_circuit_to_pulses(
        program,
        select_calibrations(
            program,
            CalibrationCatalog(gates=GateCalibrationCatalog(calibrations)),
        ),
        output_id=PulseProgramId(output_id),
    )


@given(
    call_count=st.integers(min_value=1, max_value=6),
    template_event_count=st.integers(min_value=1, max_value=5),
)
def test_reused_template_is_hygienic_and_provenance_is_a_bijection(
    call_count: int,
    template_event_count: int,
) -> None:
    calls = tuple(_call(f"call-{index}") for index in range(call_count))
    template = _template(
        Q0,
        *(1 for _ in range(template_event_count)),
        relative_scope=("template/relative",),
    )
    calibration = _calibration("x-q0", calls[0], template)
    verified = _verified(CircuitSequence(calls))

    first = _lower(verified, (calibration,))
    second = _lower(verified, (calibration,))

    expected_event_count = call_count * template_event_count
    event_ids = tuple(item.event_id for item in first.event_provenance)
    assert first == second
    assert calibration.pulse_template is template
    assert len(event_ids) == expected_event_count
    assert len(set(event_ids)) == expected_event_count
    assert (
        tuple(
            event_id
            for instantiation in first.instantiations
            for event_id in instantiation.event_ids
        )
        == event_ids
    )
    assert tuple(
        cast("GatePulseInstantiation", item).call_id for item in first.instantiations
    ) == tuple(call.id for call in calls)
    assert all(
        provenance.template_event_id.scope == ("template/relative",)
        for provenance in first.event_provenance
    )
    assert all(
        provenance.event_id.scope[:4]
        == (
            "circuits",
            verified.program.id.value,
            "operations",
            provenance.operation_id.value,
        )
        for provenance in first.event_provenance
    )
    assert all(
        first.provenance_for(provenance.event_id) is provenance
        for provenance in first.event_provenance
    )
    assert schedule(first.program).duration_seconds == (
        Decimal(call_count * template_event_count) * Decimal("1e-9")
    )


def test_structural_scope_prevents_delimiter_collisions_across_circuits() -> None:
    template = _template(
        Q0,
        1,
        relative_scope=("relative/path",),
    )
    first_call = _call("c")
    second_call = _call("b/c")
    first = _lower(
        _verified(first_call, circuit_id="a/b"),
        (_calibration("first", first_call, template),),
    )
    second = _lower(
        _verified(second_call, circuit_id="a"),
        (_calibration("second", second_call, template),),
    )

    first_id = first.event_provenance[0].event_id
    second_id = second.event_provenance[0].event_id
    assert first_id != second_id
    assert first_id.value != second_id.value
    assert first_id.scope == (
        "circuits",
        "a/b",
        "operations",
        "c",
        "relative/path",
    )
    assert second_id.scope == (
        "circuits",
        "a",
        "operations",
        "b/c",
        "relative/path",
    )


@given(
    first_duration=st.integers(min_value=1, max_value=10_000),
    second_duration=st.integers(min_value=1, max_value=10_000),
    third_duration=st.integers(min_value=1, max_value=10_000),
)
def test_circuit_composition_maps_homomorphically_to_pulse_composition(
    first_duration: int,
    second_duration: int,
    third_duration: int,
) -> None:
    first = _call("first", Q0)
    second = _call("second", Q1)
    third = _call("third", Q2)
    calibrations = (
        _calibration("q0", first, _template(Q0, first_duration, program_id="q0")),
        _calibration(
            "q1",
            second,
            _template(Q1, second_duration, program_id="q1"),
        ),
        _calibration(
            "q2",
            third,
            _template(Q2, third_duration, program_id="q2"),
        ),
    )
    left_associated = _verified(
        CircuitSequence((CircuitSequence((first, second)), third))
    )
    right_associated = _verified(
        CircuitSequence((first, CircuitSequence((second, third))))
    )

    left = _lower(left_associated, calibrations, output_id="sequence")
    right = _lower(right_associated, calibrations, output_id="sequence")

    assert isinstance(left.program.body, PulseSequence)
    assert isinstance(left.program.body.instructions[0], PulseSequence)
    assert schedule(left.program) == schedule(right.program)

    forward = _lower(
        _verified(CircuitParallel((first, second))),
        calibrations,
        output_id="parallel",
    )
    reversed_order = _lower(
        _verified(CircuitParallel((second, first))),
        calibrations,
        output_id="parallel",
    )
    assert isinstance(forward.program.body, PulseParallel)
    assert schedule(forward.program) == schedule(reversed_order.program)
    assert {event.start_seconds for event in schedule(forward.program).events} == {
        Decimal(0)
    }


@given(
    circuit_shape=_TREE_SHAPES.filter(lambda shape: _shape_leaf_count(shape) > 0),
    template_shape=_TREE_SHAPES.filter(lambda shape: _shape_leaf_count(shape) > 0),
)
def test_generated_lowering_preserves_every_composition_node_and_origin(
    circuit_shape: _TreeShape,
    template_shape: _TreeShape,
) -> None:
    calls: list[GateCall] = []
    circuit_body = _build_circuit_shape(circuit_shape, calls)
    verified = verify_circuit_program(
        CircuitProgram(CircuitId("generated-structure"), circuit_body),
        (X,),
    )
    calibrations: list[GateCalibration] = []
    templates_by_call: dict[
        CircuitOperationId,
        tuple[GateCalibration, PulseProgram],
    ] = {}
    for index, call in enumerate(calls):
        template = PulseProgram(
            id=PulseProgramId(f"generated-template-{index}"),
            body=_build_pulse_shape(
                template_shape,
                qubit=call.qubits[0],
                leaf_count=[0],
            ),
        )
        calibration = _calibration(f"generated-calibration-{index}", call, template)
        calibrations.append(calibration)
        templates_by_call[call.id] = (calibration, template)
    lowered = _lower(
        verified,
        tuple(calibrations),
        output_id="generated-output",
    )

    expected_provenance: list[
        tuple[
            PulseEventId,
            CircuitOperationId,
            CalibrationId,
            PulseProgramId,
            PulseEventId,
            tuple[int, ...],
        ]
    ] = []
    expected_instantiations: list[
        tuple[
            CircuitOperationId,
            GateCalibrationKey,
            CalibrationId,
            PulseProgramId,
            tuple[PulseEventId, ...],
        ]
    ] = []

    def assert_pulse_instantiation(
        template_instruction: PulseInstruction,
        lowered_instruction: PulseInstruction,
        *,
        call: GateCall,
        calibration: GateCalibration,
        template: PulseProgram,
        path: tuple[int, ...],
        event_ids: list[PulseEventId],
    ) -> None:
        if isinstance(template_instruction, PulseSequence):
            assert isinstance(lowered_instruction, PulseSequence)
            assert len(lowered_instruction.instructions) == len(
                template_instruction.instructions
            )
            for index, (template_child, lowered_child) in enumerate(
                zip(
                    template_instruction.instructions,
                    lowered_instruction.instructions,
                    strict=True,
                )
            ):
                assert_pulse_instantiation(
                    template_child,
                    lowered_child,
                    call=call,
                    calibration=calibration,
                    template=template,
                    path=(*path, index),
                    event_ids=event_ids,
                )
            return
        if isinstance(template_instruction, PulseParallel):
            assert isinstance(lowered_instruction, PulseParallel)
            assert len(lowered_instruction.branches) == len(
                template_instruction.branches
            )
            for index, (template_child, lowered_child) in enumerate(
                zip(
                    template_instruction.branches,
                    lowered_instruction.branches,
                    strict=True,
                )
            ):
                assert_pulse_instantiation(
                    template_child,
                    lowered_child,
                    call=call,
                    calibration=calibration,
                    template=template,
                    path=(*path, index),
                    event_ids=event_ids,
                )
            return

        assert isinstance(template_instruction, Play | Delay | Barrier)
        assert isinstance(lowered_instruction, Play | Delay | Barrier)
        expected_event_id = template_instruction.id.prefixed(
            "circuits",
            verified.program.id.value,
            "operations",
            call.id.value,
        )
        assert lowered_instruction == replace(
            template_instruction,
            id=expected_event_id,
        )
        event_ids.append(expected_event_id)
        expected_provenance.append(
            (
                expected_event_id,
                call.id,
                calibration.id,
                template.id,
                template_instruction.id,
                path,
            )
        )

    def assert_circuit_instantiation(
        circuit_node: CircuitNode,
        pulse_instruction: PulseInstruction,
    ) -> None:
        if isinstance(circuit_node, GateCall):
            calibration, template = templates_by_call[circuit_node.id]
            event_ids: list[PulseEventId] = []
            assert_pulse_instantiation(
                template.body,
                pulse_instruction,
                call=circuit_node,
                calibration=calibration,
                template=template,
                path=(),
                event_ids=event_ids,
            )
            expected_instantiations.append(
                (
                    circuit_node.id,
                    calibration.key,
                    calibration.id,
                    template.id,
                    tuple(event_ids),
                )
            )
            return
        if isinstance(circuit_node, CircuitSequence):
            assert isinstance(pulse_instruction, PulseSequence)
            circuit_children = circuit_node.operations
            pulse_children = pulse_instruction.instructions
        else:
            assert isinstance(circuit_node, CircuitParallel)
            assert isinstance(pulse_instruction, PulseParallel)
            circuit_children = circuit_node.branches
            pulse_children = pulse_instruction.branches
        assert len(circuit_children) == len(pulse_children)
        for circuit_child, pulse_child in zip(
            circuit_children,
            pulse_children,
            strict=True,
        ):
            assert_circuit_instantiation(circuit_child, pulse_child)

    assert_circuit_instantiation(verified.program.body, lowered.program.body)
    assert tuple(
        (
            item.event_id,
            item.operation_id,
            item.calibration_id,
            item.template_program_id,
            item.template_event_id,
            item.template_path,
        )
        for item in lowered.event_provenance
    ) == tuple(expected_provenance)
    assert tuple(
        (
            cast("GatePulseInstantiation", item).call_id,
            item.key,
            item.calibration_id,
            item.template_program_id,
            item.event_ids,
        )
        for item in lowered.instantiations
    ) == tuple(expected_instantiations)


@given(measurement_count=st.integers(min_value=1, max_value=8))
def test_reused_measurement_template_rewrites_every_declared_result_slot(
    measurement_count: int,
) -> None:
    measurements = tuple(
        Measure(
            id=CircuitOperationId(f"measure-{index}"),
            qubit=Q0,
            acquisition_slot_id=AcquisitionSlotId(
                "result",
                scope=(f"measurement-{index}",),
            ),
            acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
        )
        for index in range(measurement_count)
    )
    verified = _verified(CircuitSequence(measurements))
    template = _measurement_template(Q0)
    measurement_calibration = _measurement_calibration(
        "readout-q0",
        measurements[0],
        template,
    )
    selection = select_calibrations(
        verified,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog((measurement_calibration,))
        ),
    )

    lowered = lower_circuit_to_pulses(
        verified,
        selection,
        output_id=PulseProgramId("measured"),
    )

    expected_slot_ids = tuple(
        measurement.acquisition_slot_id for measurement in measurements
    )
    assert measurement_calibration.pulse_template is template
    assert tuple(slot.id for slot in lowered.program.acquisition_slots) == (
        expected_slot_ids
    )
    assert (
        tuple(
            provenance.acquisition_slot_id
            for provenance in lowered.acquisition_provenance
        )
        == expected_slot_ids
    )
    assert (
        tuple(
            provenance.template_acquisition_slot_id
            for provenance in lowered.acquisition_provenance
        )
        == (template.acquisition_slots[0].id,) * measurement_count
    )
    assert all(
        lowered.acquisition_provenance_for(provenance.acquisition_slot_id) is provenance
        for provenance in lowered.acquisition_provenance
    )
    measurement_instantiations = tuple(
        cast("MeasurementPulseInstantiation", instantiation)
        for instantiation in lowered.instantiations
    )
    assert tuple(
        instantiation.measurement_id for instantiation in measurement_instantiations
    ) == tuple(measurement.id for measurement in measurements)
    assert (
        tuple(
            instantiation.acquisition_slot_id
            for instantiation in measurement_instantiations
        )
        == expected_slot_ids
    )
    assert len({item.event_id for item in lowered.event_provenance}) == (
        2 * measurement_count
    )
    assert tuple(item.operation_id for item in lowered.event_provenance) == tuple(
        measurement.id for measurement in measurements for _ in range(2)
    )
    scheduled = schedule(lowered.program)
    assert scheduled.duration_seconds == Decimal(measurement_count * 8) * Decimal(
        "1e-9"
    )
    scheduled_acquires = tuple(
        event.instruction
        for event in scheduled.events
        if isinstance(event.instruction, Acquire)
    )
    assert tuple(acquire.slot_id for acquire in scheduled_acquires) == expected_slot_ids


def test_parallel_measurements_preserve_structure_and_independent_slots() -> None:
    first = Measure(
        CircuitOperationId("measure-q0"),
        Q0,
        AcquisitionSlotId("q0-result"),
        AcquisitionKind.INTEGRATED_IQ,
    )
    second = Measure(
        CircuitOperationId("measure-q1"),
        Q1,
        AcquisitionSlotId("q1-result"),
        AcquisitionKind.INTEGRATED_IQ,
    )
    verified = _verified(CircuitParallel((first, second)))
    calibrations = (
        _measurement_calibration(
            "readout-q0",
            first,
            _measurement_template(Q0, program_id="readout-q0"),
        ),
        _measurement_calibration(
            "readout-q1",
            second,
            _measurement_template(Q1, program_id="readout-q1"),
        ),
    )
    selection = select_calibrations(
        verified,
        CalibrationCatalog(measurements=MeasurementCalibrationCatalog(calibrations)),
    )

    lowered = lower_circuit_to_pulses(
        verified,
        selection,
        output_id=PulseProgramId("parallel-readout"),
    )
    scheduled = schedule(lowered.program)

    assert isinstance(lowered.program.body, PulseParallel)
    assert len(lowered.program.body.branches) == 2
    assert {event.start_seconds for event in scheduled.events} == {Decimal(0)}
    assert scheduled.duration_seconds == Decimal("8e-9")
    assert tuple(slot.id for slot in scheduled.acquisition_slots) == (
        first.acquisition_slot_id,
        second.acquisition_slot_id,
    )


def test_template_slot_rename_changes_provenance_but_not_lowered_program() -> None:
    measurement = Measure(
        CircuitOperationId("measure"),
        Q0,
        AcquisitionSlotId("circuit-result"),
        AcquisitionKind.INTEGRATED_IQ,
    )
    verified = _verified(measurement)

    def lower_with_template_slot(template_slot_id: AcquisitionSlotId):
        template = _measurement_template(
            Q0,
            template_slot_id=template_slot_id,
        )
        calibration = _measurement_calibration("readout", measurement, template)
        selection = select_calibrations(
            verified,
            CalibrationCatalog(
                measurements=MeasurementCalibrationCatalog((calibration,))
            ),
        )
        return lower_circuit_to_pulses(
            verified,
            selection,
            output_id=PulseProgramId("lowered-readout"),
        )

    first = lower_with_template_slot(AcquisitionSlotId("first-local"))
    second = lower_with_template_slot(AcquisitionSlotId("local", scope=("second",)))

    assert first.program == second.program
    assert schedule(first.program) == schedule(second.program)
    assert (
        first.acquisition_provenance[0].template_acquisition_slot_id
        != second.acquisition_provenance[0].template_acquisition_slot_id
    )


def test_selection_mismatches_and_measurement_are_aggregated() -> None:
    selected_call = _call("first", Q0)
    selected_program = _verified(selected_call, circuit_id="selection-source")
    template = _template(Q0, 10)
    selection = select_calibrations(
        selected_program,
        CalibrationCatalog(
            gates=GateCalibrationCatalog(
                (_calibration("selected", selected_call, template),)
            )
        ),
    )
    target = _verified(
        CircuitSequence(
            (
                _call("first", Q1),
                _call("second", Q2),
                Measure(
                    CircuitOperationId("measure"),
                    Q3,
                    AcquisitionSlotId("readout"),
                    AcquisitionKind.INTEGRATED_IQ,
                ),
            )
        ),
        circuit_id="target",
    )

    errors: list[CircuitPulseLoweringError] = []
    for _ in range(2):
        with pytest.raises(CircuitPulseLoweringError) as raised:
            lower_circuit_to_pulses(
                target,
                selection,
                output_id=PulseProgramId("mismatched"),
            )
        errors.append(raised.value)

    assert errors[0].issues == errors[1].issues
    assert tuple(
        (
            issue.code,
            issue.path,
            issue.operation_id,
            issue.calibration_id,
            issue.template_event_id,
        )
        for issue in errors[0].issues
    ) == (
        (
            CircuitPulseLoweringIssueCode.BINDING_KEY_MISMATCH,
            ("body", "operations", 0),
            CircuitOperationId("first"),
            CalibrationId("selected"),
            None,
        ),
        (
            CircuitPulseLoweringIssueCode.SELECTION_CIRCUIT_MISMATCH,
            ("selection", "circuit_id"),
            None,
            None,
            None,
        ),
        (
            CircuitPulseLoweringIssueCode.SELECTION_COVERAGE_MISMATCH,
            ("selection", "operation_ids"),
            None,
            None,
            None,
        ),
    )


def test_final_scheduler_still_owns_cross_template_signal_conflicts() -> None:
    left = _call("left", Q0)
    right = _call("right", Q1)
    verified = _verified(CircuitParallel((left, right)))
    shared_signal_template = _template(Q0, 10)
    lowered = _lower(
        verified,
        (
            _calibration("left", left, shared_signal_template),
            _calibration("right", right, shared_signal_template),
        ),
    )

    with pytest.raises(PulseValidationError) as raised:
        schedule(lowered.program)

    assert {issue.code for issue in raised.value.issues} == {"pulse_signal_overlap"}


def test_zero_event_gate_still_exports_an_immutable_instantiation() -> None:
    call = _call("empty")
    verified = _verified(call)
    empty_template = _template(Q0, program_id="empty")
    lowered = _lower(
        verified,
        (_calibration("empty", call, empty_template),),
    )

    assert lowered.event_provenance == ()
    assert lowered.instantiation_for(call.id).event_ids == ()
    attribute = "program"
    with pytest.raises(FrozenInstanceError):
        setattr(cast("object", lowered), attribute, empty_template)
