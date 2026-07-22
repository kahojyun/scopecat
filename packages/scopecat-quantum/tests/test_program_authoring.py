from __future__ import annotations

from decimal import Decimal

import pytest
import scopecat as sc
from scopecat import Quantity

from scopecat_quantum import authoring
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CouplerId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.calibrations import (
    CalibrationCatalog,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
)
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import GateCall, GateParameterKind
from scopecat_quantum.programs import (
    AuthoredPulseAcquisitionProvenance,
    AuthoredPulseEventProvenance,
    ImplementedGate,
    ImplementedGatePulseEventProvenance,
    PulseBlock,
    lower_quantum_program_to_pulses,
)
from scopecat_quantum.programs import (
    Parallel as QuantumParallel,
)
from scopecat_quantum.programs import (
    Sequence as QuantumSequence,
)
from scopecat_quantum.pulses import (
    DRAG,
    Acquire,
    AcquireSignal,
    Constant,
    DriveSignal,
    FluxSignal,
    Play,
    PulseProgram,
    PulseValidationError,
    ReadoutSignal,
    ShiftPhase,
    iter_pulse_leaves,
    schedule,
)


def _beta_input() -> authoring.QuantumInput:
    return authoring.input(
        "beta",
        sc.ScalarType(sc.QuantityType(unit="ns")),
    )


def _drag_play(
    qubit: authoring.Qubit,
    beta: authoring.QuantumInput,
) -> authoring.PulseFragment:
    return authoring.play(
        authoring.drive(qubit),
        authoring.drag(
            duration=Quantity(16, "ns"),
            amplitude=Quantity(0.2, "arb"),
            sigma=Quantity(4, "ns"),
            beta=beta,
        ),
    )


def test_sequence_composes_baseline_gate_candidate_pulse_and_measurement() -> None:
    q0 = authoring.qubit("q0")
    beta = _beta_input()
    x90 = authoring.single_qubit_gate("x90")
    readout = authoring.measure(q0, result="raw_iq")
    declaration = authoring._close_program(
        "drag-calibration-point",
        authoring.sequence(
            x90(q0),
            authoring.implements(
                x90(q0),
                _drag_play(q0, beta),
                candidate="x90.drag",
            ),
            readout,
        ),
    )

    bound = authoring.bind(declaration, {"beta": Quantity(0.75, "ns")})

    assert declaration.inputs == (beta,)
    assert tuple(declaration.results) == (readout.result,)
    assert isinstance(bound.program.body, QuantumSequence)
    assert [type(operation) for operation in bound.verified.operations] == [
        GateCall,
        ImplementedGate,
        Measure,
    ]
    unresolved_types = [
        type(operation) for operation in bound.verified.unresolved_circuit.operations
    ]
    assert unresolved_types == [
        GateCall,
        Measure,
    ]


def test_repeated_candidate_materializes_unique_calls_with_bound_drag_beta() -> None:
    q0 = authoring.qubit("q0")
    beta = _beta_input()
    repetitions = authoring.input(
        "repetitions",
        sc.ScalarType(sc.IntType()),
    )
    x90 = authoring.single_qubit_gate("x90")
    candidate = authoring.implements(
        x90(q0),
        _drag_play(q0, beta),
        candidate="x90.drag",
    )
    declaration = authoring._close_program(
        "repeated-drag-candidate",
        authoring.repeat(candidate, repetitions),
    )

    bound = authoring.bind(
        declaration,
        {"beta": Quantity(0.75, "ns"), "repetitions": 3},
    )
    implementations = tuple(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, ImplementedGate)
    )

    assert len(implementations) == 3
    assert len({implementation.call.id for implementation in implementations}) == 3
    template_ids = {
        implementation.pulse_template.id for implementation in implementations
    }
    assert len(template_ids) == 3
    assert {implementation.candidate_id for implementation in implementations} == {
        "x90.drag"
    }
    for implementation in implementations:
        [pulse] = tuple(iter_pulse_leaves(implementation.pulse_template.body))
        assert isinstance(pulse, Play)
        assert isinstance(pulse.envelope, DRAG)
        assert pulse.envelope.beta == Quantity(0.75, "ns")


def test_gate_and_pulse_can_bind_in_parallel_before_final_signal_check() -> None:
    q0 = authoring.qubit("q0")
    x90 = authoring.single_qubit_gate("x90")
    declaration = authoring._close_program(
        "parallel-drive-conflict",
        authoring.parallel(
            x90(q0),
            authoring.play(
                authoring.drive(q0),
                authoring.constant(
                    duration=Quantity(16, "ns"),
                    amplitude=Quantity(0.1, "arb"),
                ),
            ),
        ),
    )

    bound = authoring.bind(declaration)
    assert isinstance(bound.program.body, QuantumParallel)
    gate_call = next(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, GateCall)
    )
    calibration_template = PulseProgram(
        id=PulseProgramId("x90-q0-template"),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(gate_call.qubits[0]),
            envelope=Constant(
                duration=Quantity(16, "ns"),
                amplitude=Quantity(0.2, "arb"),
            ),
        ),
    )
    catalog = CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=CalibrationId("x90-q0"),
                    key=GateCalibrationKey.from_call(gate_call),
                    pulse_template=calibration_template,
                ),
            )
        )
    )

    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        catalog,
        output_id=PulseProgramId("parallel-drive-conflict-pulses"),
    )

    with pytest.raises(PulseValidationError) as caught:
        schedule(lowered.program)

    assert {issue.code for issue in caught.value.issues} == {"pulse_signal_overlap"}


def test_gate_implementation_rejects_a_foreign_pulse_qubit() -> None:
    q0 = authoring.qubit("q0")
    q1 = authoring.qubit("q1")
    x90 = authoring.single_qubit_gate("x90")

    with pytest.raises(ValueError, match="unauthorized signal owners: 'q1'"):
        authoring.implements(
            x90(q0),
            authoring.play(
                authoring.drive(q1),
                authoring.constant(
                    duration=Quantity(16, "ns"),
                    amplitude=Quantity(0.2, "arb"),
                ),
            ),
        )


def test_two_qubit_gate_implementation_authorizes_and_lowers_coupler_pulse() -> None:
    formal_coupler = authoring.coupler("formal-coupler")
    amplitude = authoring.input(
        "amplitude",
        sc.ScalarType(sc.QuantityType(unit="arb")),
    )
    template = authoring.pulse_template(
        "cz.flux",
        authoring.play(
            authoring.flux(formal_coupler),
            authoring.constant(
                duration=Quantity(32, "ns"),
                amplitude=amplitude,
            ),
        ),
        elements=(formal_coupler,),
    )
    q0 = authoring.qubit("q0")
    q1 = authoring.qubit("q1")
    c01 = authoring.coupler("coupler-q0-q1")
    cz = authoring.two_qubit_gate("cz")
    with pytest.raises(TypeError, match="element 0 requires Coupler, got Qubit"):
        template(q0, amplitude=amplitude)
    declaration = authoring._close_program(
        "cz-candidate",
        authoring.implements(
            cz(q0, q1),
            template(c01, amplitude=amplitude),
            resources=(c01,),
            candidate="cz.conditional-phase",
        ),
    )

    bound = authoring.bind(declaration, {"amplitude": Quantity(0.24, "arb")})
    [logical_call] = bound.verified.logical_circuit.operations
    [implementation] = bound.verified.operations
    assert isinstance(logical_call, GateCall)
    assert logical_call.qubits == (QubitId("q0"), QubitId("q1"))
    assert isinstance(implementation, ImplementedGate)
    assert implementation.call == logical_call

    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        CalibrationCatalog(),
        output_id=PulseProgramId("cz-candidate-pulses"),
    )
    [leaf] = iter_pulse_leaves(lowered.program.body)
    assert isinstance(leaf, Play)
    assert leaf.signal == FluxSignal(CouplerId("coupler-q0-q1"))
    [provenance] = lowered.event_provenance
    assert isinstance(provenance, ImplementedGatePulseEventProvenance)
    assert provenance.gate_id.value == "cz"
    assert provenance.candidate_id == "cz.conditional-phase"
    assert provenance.template_program_id == PulseProgramId("cz.flux")


def test_gate_implementation_requires_exact_coupler_resource_authorization() -> None:
    q0 = authoring.qubit("q0")
    q1 = authoring.qubit("q1")
    c01 = authoring.coupler("coupler-q0-q1")
    c23 = authoring.coupler("coupler-q2-q3")
    cz = authoring.two_qubit_gate("cz")
    pulse = authoring.play(
        authoring.flux(c01),
        authoring.constant(
            duration=Quantity(32, "ns"),
            amplitude=Quantity(0.24, "arb"),
        ),
    )

    with pytest.raises(
        ValueError,
        match="unauthorized signal owners: 'coupler-q0-q1'",
    ):
        authoring.implements(cz(q0, q1), pulse)
    with pytest.raises(ValueError, match="unused coupler resources: 'coupler-q2-q3'"):
        authoring.implements(cz(q0, q1), pulse, resources=(c01, c23))
    with pytest.raises(ValueError, match="resources must be unique"):
        authoring.implements(cz(q0, q1), pulse, resources=(c01, c01))


def test_drag_beta_requires_a_time_typed_input() -> None:
    frequency = authoring.input(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )

    with pytest.raises(TypeError, match="must declare 'time' quantity units"):
        authoring.drag(
            duration=Quantity(16, "ns"),
            amplitude=Quantity(0.2, "arb"),
            sigma=Quantity(4, "ns"),
            beta=frequency,
        )


def test_program_binding_requires_exact_typed_inputs() -> None:
    q0 = authoring.qubit("q0")
    beta = _beta_input()
    declaration = authoring._close_program("drag", _drag_play(q0, beta))

    with pytest.raises(authoring.ProgramBindingError, match="missing 'beta'"):
        authoring.bind(declaration)
    with pytest.raises(authoring.ProgramBindingError, match="unknown 'other'"):
        authoring.bind(
            declaration,
            {"beta": Quantity(0.75, "ns"), "other": 1},
        )
    with pytest.raises(
        authoring.ProgramBindingError,
        match="expected quantity",
    ):
        authoring.bind(declaration, {"beta": "not-a-quantity"})


def test_domain_program_and_execution_expose_typed_ports() -> None:
    q0 = authoring.qubit("q0")
    beta_type = sc.ScalarType(sc.QuantityType(unit="ns"))
    beta = authoring.input("beta", beta_type)
    repetitions = authoring.input(
        "repetitions",
        sc.ScalarType(sc.IntType()),
    )
    readout = authoring.measure(q0, result="raw_iq")
    declaration = authoring._close_program(
        "typed-drag-program",
        authoring.sequence(
            authoring.repeat(_drag_play(q0, beta), repetitions),
            readout,
        ),
    )
    repetitions_type = sc.ScalarType(sc.IntType(minimum=0))
    repetitions_point = sc.point("repetitions", repetitions_type)
    beta_point = sc.point("beta", beta_type)
    products = (
        sc.module_body(id="test.quantum.typed-drag")
        .product("integrated_iq_shots")
        .build()
    )

    domain_program = authoring._domain_program(declaration)
    execution = authoring._domain_execution(
        domain_program,
        inputs={beta: beta_point, repetitions: repetitions_point},
        results={readout.result: products.products["integrated_iq_shots"]},
    )

    assert domain_program.dialect_id == authoring.QUANTUM_PROGRAM_DIALECT_ID
    assert domain_program.body is declaration
    assert [(port.id, port.value_type) for port in domain_program.input_ports] == [
        ("repetitions", repetitions_type),
        ("beta", beta_type),
    ]
    assert domain_program.result_ports[0].id == "raw_iq"
    assert domain_program.result_ports[0].contract is readout.result
    assert execution.input_bindings == (
        ("repetitions", repetitions_point),
        ("beta", beta_point),
    )
    assert execution.result_bindings[0][0] == "raw_iq"
    assert execution.result_bindings[0][1].local_id == "integrated_iq_shots"


def test_explicit_acquire_composes_with_readout_play_and_keeps_public_slot() -> None:
    q0 = authoring.qubit("q0")
    capture = authoring.acquire(
        q0,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    declaration = authoring._close_program(
        "explicit-readout",
        authoring.parallel(
            authoring.play(
                authoring.readout(q0),
                authoring.constant(
                    duration=Quantity(12, "ns"),
                    amplitude=Quantity(0.1, "arb"),
                ),
            ),
            capture,
        ),
    )

    bound = authoring.bind(declaration)
    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        CalibrationCatalog(),
        output_id=PulseProgramId("explicit-readout-pulses"),
    )
    scheduled = schedule(lowered.program)

    assert tuple(declaration.results) == (capture.result,)
    assert capture.result.qubit is q0
    assert capture.result.acquisition_slot_id == AcquisitionSlotId("iq_shots")
    assert lowered.program.acquisition_slots[0].id == capture.result.acquisition_slot_id
    assert scheduled.duration_seconds == Decimal("1.2e-8")
    assert {type(event.instruction) for event in scheduled.events} == {Play, Acquire}
    assert {event.start_seconds for event in scheduled.events} == {0}
    [provenance] = lowered.acquisition_provenance
    assert isinstance(provenance, AuthoredPulseAcquisitionProvenance)
    assert provenance.acquisition_slot_id == capture.result.acquisition_slot_id


def test_domain_execution_requires_the_exact_measurement_result_handle() -> None:
    q0 = authoring.qubit("q0")
    capture = authoring.acquire(
        q0,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    foreign = authoring.acquire(
        q0,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    declaration = authoring._close_program("explicit-acquire", capture)
    domain_program = authoring._domain_program(declaration)
    products = (
        sc.module_body(id="test.quantum.explicit-acquire").product("iq_shots").build()
    )

    with pytest.raises(ValueError, match="bind every declared result"):
        authoring._domain_execution(
            domain_program,
            results={foreign.result: products.products["iq_shots"]},
        )


def test_explicit_acquire_results_require_an_axis_or_a_unique_id() -> None:
    q0 = authoring.qubit("q0")
    first = authoring.acquire(
        q0,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    second = authoring.acquire(
        q0,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )

    with pytest.raises(ValueError, match="require an axis"):
        authoring.repeat(first, 2)
    with pytest.raises(ValueError, match="duplicate result ids"):
        authoring._close_program(
            "duplicate-acquisitions",
            authoring.sequence(first, second),
        )


def test_pulse_template_substitutes_qubit_and_outer_input_hygienically() -> None:
    formal_q = authoring.qubit("formal")
    formal_phase = authoring.input(
        "phase",
        sc.ScalarType(sc.QuantityType(unit="rad")),
    )
    template = authoring.pulse_template(
        "x90-with-frame",
        authoring.sequence(
            authoring.shift_phase(authoring.drive(formal_q), formal_phase),
            authoring.play(
                authoring.drive(formal_q),
                authoring.constant(
                    duration=Quantity(8, "ns"),
                    amplitude=Quantity(0.2, "arb"),
                ),
            ),
        ),
        elements=(formal_q,),
    )
    q0 = authoring.qubit("q0")
    outer_phase = authoring.input(
        "ramsey_phase",
        sc.ScalarType(sc.QuantityType(unit="rad")),
    )
    declaration = authoring._close_program(
        "two-template-calls",
        authoring.sequence(
            template(q0, phase=outer_phase),
            template(q0, phase=outer_phase),
        ),
    )

    assert template.id == "x90-with-frame"
    assert template.elements == (formal_q,)
    assert template.inputs == (formal_phase,)
    assert declaration.inputs == (outer_phase,)
    bound = authoring.bind(
        declaration,
        {"ramsey_phase": Quantity(90, "deg")},
    )
    blocks = tuple(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, PulseBlock)
    )
    assert len(blocks) == 2
    assert {block.pulse_template.id for block in blocks} == {
        PulseProgramId("x90-with-frame")
    }
    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        CalibrationCatalog(),
        output_id=PulseProgramId("two-template-calls-pulses"),
    )
    assert len({leaf.id for leaf in iter_pulse_leaves(lowered.program.body)}) == 4
    assert {
        provenance.template_program_id for provenance in lowered.event_provenance
    } == {PulseProgramId("x90-with-frame")}
    assert all(
        isinstance(provenance, AuthoredPulseEventProvenance)
        for provenance in lowered.event_provenance
    )
    scheduled = schedule(lowered.program)
    shifts = tuple(
        event.instruction
        for event in scheduled.events
        if isinstance(event.instruction, ShiftPhase)
    )
    assert [shift.signal for shift in shifts] == [
        DriveSignal(QubitId("q0")),
        DriveSignal(QubitId("q0")),
    ]
    assert all(shift.phase == Quantity(90, "deg").to("rad") for shift in shifts)


def test_pulse_template_rejects_results_and_requires_exact_call_ports() -> None:
    formal_q = authoring.qubit("formal")
    duration = authoring.input(
        "duration",
        sc.ScalarType(sc.QuantityType(unit="ns")),
    )
    with pytest.raises(ValueError, match="cannot capture acquisition results"):
        authoring.pulse_template(
            "invalid-readout",
            authoring.acquire(
                formal_q,
                duration=Quantity(8, "ns"),
                result="iq",
            ),
            elements=(formal_q,),
        )

    template = authoring.pulse_template(
        "delay",
        authoring.delay(authoring.drive(formal_q), duration),
        elements=(formal_q,),
    )
    with pytest.raises(ValueError, match="missing 'duration'"):
        template(formal_q)
    with pytest.raises(ValueError, match="unknown 'other'"):
        template(formal_q, duration=Quantity(8, "ns"), other=1)
    with pytest.raises(TypeError, match="invalid pulse template input 'duration'"):
        template(formal_q, duration=Quantity(1, "rad"))


def test_shift_phase_accepts_symbolic_phase() -> None:
    q0 = authoring.qubit("q0")
    phase = authoring.input(
        "phase",
        sc.ScalarType(sc.QuantityType(unit="rad")),
    )
    declaration = authoring._close_program(
        "virtual-z",
        authoring.sequence(
            authoring.shift_phase(authoring.drive(q0), phase),
            authoring.play(
                authoring.drive(q0),
                authoring.constant(
                    duration=Quantity(4, "ns"),
                    amplitude=Quantity(0.1, "arb"),
                ),
            ),
        ),
    )
    bound = authoring.bind(declaration, {"phase": Quantity(180, "deg")})
    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        CalibrationCatalog(),
        output_id=PulseProgramId("virtual-z-pulses"),
    )
    [shift, _play] = schedule(lowered.program).events
    assert isinstance(shift.instruction, ShiftPhase)
    assert shift.duration_seconds == 0
    assert shift.instruction.phase == Quantity(180, "deg").to("rad")


def test_program_element_ports_bind_every_logical_owner() -> None:
    formal_q0 = authoring.qubit("control")
    formal_q1 = authoring.qubit("target")
    formal_coupler = authoring.coupler("coupler")
    fixed = authoring.qubit("fixed")
    x = authoring.single_qubit_gate("x")
    cz = authoring.two_qubit_gate("cz")
    measure = authoring.measure(formal_q0, result="measure_iq")
    capture = authoring.acquire(
        formal_q1,
        duration=Quantity(8, "ns"),
        result="capture_iq",
    )
    envelope = authoring.constant(
        duration=Quantity(8, "ns"),
        amplitude=Quantity(0.1, "arb"),
    )
    declaration = authoring._close_program(
        "formal-elements",
        authoring.sequence(
            x(formal_q0),
            x(fixed),
            measure,
            authoring.play(authoring.drive(formal_q0), envelope),
            authoring.play(authoring.readout(formal_q1), envelope),
            capture,
            authoring.implements(
                cz(formal_q0, formal_q1),
                authoring.play(authoring.flux(formal_coupler), envelope),
                resources=(formal_coupler,),
            ),
        ),
        elements=(formal_q0, formal_q1, formal_coupler),
    )

    bound = authoring.bind(
        declaration,
        {
            "control": "q2",
            "target": sc.entity_ref("q3", kind="logical_qubit"),
            "coupler": "coupler-q2-q3",
        },
    )
    gate, fixed_gate, measurement, drive, readout, acquisition, implemented = (
        bound.verified.operations
    )
    assert isinstance(gate, GateCall)
    assert gate.qubits == (QubitId("q2"),)
    assert isinstance(fixed_gate, GateCall)
    assert fixed_gate.qubits == (QubitId("fixed"),)
    assert isinstance(measurement, Measure)
    assert measurement.qubit == QubitId("q2")
    assert isinstance(drive, PulseBlock)
    [drive_leaf] = iter_pulse_leaves(drive.pulse_template.body)
    assert isinstance(drive_leaf, Play)
    assert drive_leaf.signal == DriveSignal(QubitId("q2"))
    assert isinstance(readout, PulseBlock)
    [readout_leaf] = iter_pulse_leaves(readout.pulse_template.body)
    assert isinstance(readout_leaf, Play)
    assert readout_leaf.signal == ReadoutSignal(QubitId("q3"))
    assert isinstance(acquisition, PulseBlock)
    [acquire_leaf] = iter_pulse_leaves(acquisition.pulse_template.body)
    assert isinstance(acquire_leaf, Acquire)
    assert acquire_leaf.signal == AcquireSignal(QubitId("q3"))
    assert isinstance(implemented, ImplementedGate)
    assert implemented.call.qubits == (QubitId("q2"), QubitId("q3"))
    [flux_leaf] = iter_pulse_leaves(implemented.pulse_template.body)
    assert isinstance(flux_leaf, Play)
    assert flux_leaf.signal == FluxSignal(CouplerId("coupler-q2-q3"))

    with pytest.raises(authoring.ProgramBindingError, match="logical_qubit"):
        authoring.bind(
            declaration,
            {
                "control": sc.entity_ref("c0", kind="logical_coupler"),
                "target": "q3",
                "coupler": "coupler-q2-q3",
            },
        )


def test_program_rejects_unused_or_conflicting_formal_ports() -> None:
    q0 = authoring.qubit("q0")
    unused = authoring.qubit("unused")
    measurement = authoring.measure(q0, result="iq")

    with pytest.raises(ValueError, match="unused formal elements: 'unused'"):
        authoring._close_program("unused", measurement, elements=(unused,))

    count = authoring.scalar_input("q0", GateParameterKind.INTEGER)
    with pytest.raises(ValueError, match="conflicting port ids: 'q0'"):
        authoring._close_program(
            "conflict",
            authoring.sequence(
                authoring.repeat(authoring.single_qubit_gate("x")(q0), count),
                measurement,
            ),
            elements=(q0,),
        )
