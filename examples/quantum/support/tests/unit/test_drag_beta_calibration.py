from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path

import pytest
import scopecat as sc
from scopecat import IntType, Quantity, QuantityType, ScalarType
from scopecat_quantum import (
    DRAG,
    AuthoredPulseAcquisitionProvenance,
    AuthoredPulseEventProvenance,
    CircuitPulseEventProvenance,
    ImplementedGatePulseEventProvenance,
    Play,
    QubitId,
    program_port_type,
)

from quantum_lab_demo import quantum_lab_compiler
from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    q0_drag_beta_lookup,
    q0_drag_beta_row,
)
from quantum_lab_demo.virtual_lab.pulse_profile import (
    x90_pulse_recipe,
    xm90_pulse_recipe,
)
from quantum_lab_demo.workflows.drag_beta_calibration import (
    NEGATIVE_CANDIDATE_ID,
    POSITIVE_CANDIDATE_ID,
    candidate_x90,
    candidate_xm90,
)
from quantum_lab_demo.workflows.drag_beta_experiment import (
    AMPLIFICATION,
    BETA,
    drag_beta_capture,
    drag_beta_program,
    drag_beta_template,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab


def _golden_point(tmp_path: Path):
    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
    scan = sc.cartesian(
        sc.param_axis(
            BETA,
            q0_drag_beta_row(),
            DRAG_BETA_PARAMETER_COLUMN,
            (Quantity(0.75, "ns"),),
        ),
        sc.axis(AMPLIFICATION, (3,)),
    )
    lab.prepare(drag_beta_template).scan(scan).run()
    [preparation] = compiler.trace.preparations(drag_beta_program.id)
    [prepared] = preparation.entries
    return drag_beta_program, prepared, preparation.artifact


def _nanoseconds(seconds: Decimal) -> Decimal:
    return seconds * Decimal(1_000_000_000)


_X90_IMPLEMENTATION_ID = x90_pulse_recipe.implementation_id((QubitId("q0"),))
_XM90_IMPLEMENTATION_ID = xm90_pulse_recipe.implementation_id((QubitId("q0"),))


def test_drag_beta_capture_binds_the_accepted_parameter_cell() -> None:
    capture = drag_beta_capture(
        amplification=AMPLIFICATION,
        beta=q0_drag_beta_lookup(),
    )
    assert capture.inputs["beta"] == q0_drag_beta_lookup()


def test_n3_golden_schedule_and_implementation_bindings(tmp_path: Path) -> None:
    declaration, prepared, _artifact = _golden_point(tmp_path)

    assert [port.id for port in declaration.inputs] == ["amplification", "beta"]
    assert program_port_type(declaration.inputs[0]) == ScalarType(IntType(minimum=1))
    assert program_port_type(declaration.inputs[1]) == ScalarType(
        QuantityType(unit="ns")
    )
    assert len(prepared.scheduled.events) == 10
    assert prepared.scheduled.duration_seconds == Decimal("136e-9")

    candidate_origins = tuple(
        provenance
        for provenance in prepared.lowered.event_provenance
        if isinstance(provenance, ImplementedGatePulseEventProvenance)
    )
    assert len(candidate_origins) == 6
    assert (
        tuple(provenance.candidate_id for provenance in candidate_origins)
        == (
            POSITIVE_CANDIDATE_ID,
            NEGATIVE_CANDIDATE_ID,
        )
        * 3
    )
    assert (
        tuple(provenance.gate_id.value for provenance in candidate_origins)
        == (
            "x90",
            "xm90",
        )
        * 3
    )

    scheduled_by_id = {event.id: event for event in prepared.scheduled.events}
    candidate_events = tuple(
        scheduled_by_id[provenance.event_id] for provenance in candidate_origins
    )
    assert tuple(_nanoseconds(event.start_seconds) for event in candidate_events) == (
        Decimal(16),
        Decimal(32),
        Decimal(48),
        Decimal(64),
        Decimal(80),
        Decimal(96),
    )
    assert all(isinstance(event.instruction, Play) for event in candidate_events)
    candidate_envelopes = tuple(
        event.instruction.envelope
        for event in candidate_events
        if isinstance(event.instruction, Play)
    )
    assert all(isinstance(envelope, DRAG) for envelope in candidate_envelopes)
    drag_envelopes = tuple(
        envelope for envelope in candidate_envelopes if isinstance(envelope, DRAG)
    )
    assert tuple(
        float(envelope.phase.value) for envelope in drag_envelopes
    ) == pytest.approx((0.0, math.pi) * 3)
    assert all(envelope.beta == Quantity(0.75e-9, "s") for envelope in drag_envelopes)

    selected = prepared.lowered.implementation_bindings
    assert len(selected.operation_ids) == 2
    assert tuple(binding.implementation_id for binding in selected.gates.bindings) == (
        _X90_IMPLEMENTATION_ID,
        _XM90_IMPLEMENTATION_ID,
    )
    assert selected.measurements.bindings == ()
    assert all(
        provenance.operation_id not in selected.operation_ids
        for provenance in candidate_origins
    )

    calibrated_origins = tuple(
        provenance
        for provenance in prepared.lowered.event_provenance
        if isinstance(provenance, CircuitPulseEventProvenance)
    )
    starts_by_implementation = {
        implementation_id: tuple(
            _nanoseconds(scheduled_by_id[provenance.event_id].start_seconds)
            for provenance in calibrated_origins
            if provenance.implementation_id == implementation_id
        )
        for implementation_id in (_X90_IMPLEMENTATION_ID, _XM90_IMPLEMENTATION_ID)
    }
    assert starts_by_implementation[_X90_IMPLEMENTATION_ID] == (Decimal(0),)
    assert starts_by_implementation[_XM90_IMPLEMENTATION_ID] == (Decimal(112),)
    calibrated_plays = tuple(
        scheduled_by_id[provenance.event_id].instruction
        for provenance in calibrated_origins
    )
    assert all(isinstance(instruction, Play) for instruction in calibrated_plays)
    calibrated_envelopes = tuple(
        instruction.envelope
        for instruction in calibrated_plays
        if isinstance(instruction, Play)
    )
    assert all(isinstance(envelope, DRAG) for envelope in calibrated_envelopes)
    assert all(
        envelope.beta == Quantity(0.75e-9, "s")
        for envelope in calibrated_envelopes
        if isinstance(envelope, DRAG)
    )
    authored_origins = tuple(
        provenance
        for provenance in prepared.lowered.event_provenance
        if isinstance(provenance, AuthoredPulseEventProvenance)
    )
    assert tuple(
        _nanoseconds(scheduled_by_id[provenance.event_id].start_seconds)
        for provenance in authored_origins
    ) == (Decimal(128), Decimal(128))
    [acquisition_origin] = prepared.lowered.acquisition_provenance
    assert isinstance(acquisition_origin, AuthoredPulseAcquisitionProvenance)
    assert acquisition_origin.acquisition_slot_id.value == "iq_shots"
    assert {
        provenance.template_program_id.value for provenance in candidate_origins
    } == {candidate_x90.id, candidate_xm90.id}


def test_n3_point_compiles_to_complex_drag_samples(tmp_path: Path) -> None:
    _declaration, _prepared, artifact = _golden_point(tmp_path)
    [entry] = artifact.entries
    drive_waveform = next(
        waveform
        for waveform in entry.waveforms
        if waveform.channel_id.value == "drive-stack:drive.awg0.ch1:q0"
    )
    positive = drive_waveform.samples[16:32]
    negative = drive_waveform.samples[32:48]

    assert entry.sample_count == 136
    assert any(abs(sample.imag) > 0.0 for sample in positive)
    assert positive == pytest.approx(tuple(-sample for sample in negative))
    assert positive[0].real == pytest.approx(positive[-1].real)
    assert positive[0].imag == pytest.approx(-positive[-1].imag)
