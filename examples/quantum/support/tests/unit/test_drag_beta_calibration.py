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
)

from quantum_lab_demo import quantum_lab, quantum_lab_compiler
from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    AMPLIFICATION_INPUT,
    BETA_INPUT,
    DRAG_GATE_PULSE_TEMPLATE,
    NEGATIVE_CANDIDATE_ID,
    POSITIVE_CANDIDATE_ID,
    X90_CALIBRATION_ID,
    XM90_CALIBRATION_ID,
    baseline_calibration_catalog,
    drag_beta_calibration_program,
)
from quantum_lab_demo.reference_experiments.drag_beta_experiment import (
    AMPLIFICATION,
    BETA,
    DRAG_BETA_PROGRAM,
    DRAG_BETA_TEMPLATE,
)
from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    q0_drag_beta_lookup,
    q0_drag_beta_row,
)

_GOLDEN_BASELINE_BETA = Quantity(0.625, "ns")


def _golden_point(tmp_path: Path):
    compiler = quantum_lab_compiler(
        calibration_catalog=baseline_calibration_catalog(_GOLDEN_BASELINE_BETA)
    )
    lab = quantum_lab(workspace=tmp_path, compiler=compiler)
    scan = sc.cartesian(
        sc.param_axis(
            BETA,
            q0_drag_beta_row(),
            DRAG_BETA_PARAMETER_COLUMN,
            (Quantity(0.75, "ns"),),
        ),
        sc.axis(AMPLIFICATION, (3,)),
    )
    lab.prepare(DRAG_BETA_TEMPLATE).scan(scan).run()
    [preparation] = compiler.trace.preparations(DRAG_BETA_PROGRAM.id)
    [prepared] = preparation.entries
    return drag_beta_calibration_program(), prepared, preparation.artifact


def _nanoseconds(seconds: Decimal) -> Decimal:
    return seconds * Decimal(1_000_000_000)


def test_drag_beta_template_binds_the_accepted_parameter_cell() -> None:
    execution = DRAG_BETA_TEMPLATE.build().module.domain_executions[0]

    assert execution is not None
    assert dict(execution.input_bindings)["beta"] == q0_drag_beta_lookup()


def test_n3_golden_schedule_and_calibration_selection(tmp_path: Path) -> None:
    declaration, prepared, _artifact = _golden_point(tmp_path)

    assert declaration.inputs == (AMPLIFICATION_INPUT, BETA_INPUT)
    assert BETA_INPUT.value_type == ScalarType(QuantityType(unit="ns"))
    assert AMPLIFICATION_INPUT.value_type == ScalarType(IntType(minimum=1))
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

    selected = prepared.lowered.calibration_selection
    assert len(selected.operation_ids) == 2
    assert tuple(binding.calibration_id for binding in selected.gates.bindings) == (
        X90_CALIBRATION_ID,
        XM90_CALIBRATION_ID,
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
    starts_by_calibration = {
        calibration_id: tuple(
            _nanoseconds(scheduled_by_id[provenance.event_id].start_seconds)
            for provenance in calibrated_origins
            if provenance.calibration_id == calibration_id
        )
        for calibration_id in (X90_CALIBRATION_ID, XM90_CALIBRATION_ID)
    }
    assert starts_by_calibration[X90_CALIBRATION_ID] == (Decimal(0),)
    assert starts_by_calibration[XM90_CALIBRATION_ID] == (Decimal(112),)
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
        envelope.beta == Quantity(0.625e-9, "s")
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
    } == {DRAG_GATE_PULSE_TEMPLATE.id}


def test_n3_point_compiles_to_complex_drag_samples(tmp_path: Path) -> None:
    _declaration, _prepared, artifact = _golden_point(tmp_path)
    [entry] = artifact.entries
    drive_waveform = next(
        waveform
        for waveform in entry.waveforms
        if waveform.channel_id.value == "awg.drive.0"
    )
    positive = drive_waveform.samples[16:32]
    negative = drive_waveform.samples[32:48]

    assert entry.sample_count == 136
    assert any(abs(sample.imag) > 0.0 for sample in positive)
    assert positive == pytest.approx(tuple(-sample for sample in negative))
    assert positive[0].real == pytest.approx(positive[-1].real)
    assert positive[0].imag == pytest.approx(-positive[-1].imag)
