from __future__ import annotations

import math

import pytest
from scopecat import Quantity
from scopecat_quantum import (
    AuthoredPulseAcquisitionProvenance,
    AuthoredPulseEventProvenance,
    CircuitPulseEventProvenance,
    ImplementedGatePulseEventProvenance,
    MeasurementResult,
    TargetCompilerId,
    compile_target,
    prepare_quantum_target_batch,
)

from quantum_lab_demo.reference_experiments.ramsey_phase_calibration import (
    PHASE_INPUT,
    RAMSEY_X90_PULSE_TEMPLATE,
    X90_CANDIDATE_ID,
    prepare_ramsey_phase_scan,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListTargetCompiler,
    default_fake_list_target,
)


def test_ramsey_program_exposes_one_phase_input_and_one_physical_result() -> None:
    declaration, [prepared] = prepare_ramsey_phase_scan((Quantity(0, "rad"),))

    assert declaration.inputs == (PHASE_INPUT,)
    [result] = declaration.results
    assert isinstance(result, MeasurementResult)
    assert result.id == "iq_shots"
    assert prepared.source_program_id.value == declaration.id
    assert prepared.acquisition_origins[0].address.slot_id == (
        result.acquisition_slot_id
    )
    assert isinstance(
        prepared.acquisition_origins[0].provenance,
        AuthoredPulseAcquisitionProvenance,
    )

    provenance = tuple(origin.provenance for origin in prepared.event_origins)
    assert any(isinstance(item, CircuitPulseEventProvenance) for item in provenance)
    assert any(
        isinstance(item, ImplementedGatePulseEventProvenance)
        and item.candidate_id == X90_CANDIDATE_ID
        and item.template_program_id.value == RAMSEY_X90_PULSE_TEMPLATE.id
        for item in provenance
    )
    assert any(isinstance(item, AuthoredPulseEventProvenance) for item in provenance)


def test_ramsey_phase_rotates_only_the_candidate_and_resets_between_entries() -> None:
    _declaration, entries = prepare_ramsey_phase_scan(
        (Quantity(0, "rad"), Quantity(math.pi / 2, "rad"))
    )
    target = default_fake_list_target()
    compiler = FakeListTargetCompiler(
        TargetCompilerId("ramsey-phase-reference.v1"),
        target,
    )
    batch = prepare_quantum_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=1,
    )

    artifact = compile_target(compiler, batch.request).artifact
    drive_waveforms = tuple(
        next(
            waveform
            for waveform in entry.waveforms
            if waveform.channel_id.value == "awg.drive.0"
        )
        for entry in artifact.entries
    )

    assert [entry.sample_count for entry in artifact.entries] == [72, 72]
    assert drive_waveforms[0].samples[:16] == pytest.approx((0.2 + 0j,) * 16)
    assert drive_waveforms[1].samples[:16] == pytest.approx((0.2 + 0j,) * 16)
    assert drive_waveforms[0].samples[16:32] == (0j,) * 16
    assert drive_waveforms[1].samples[16:32] == (0j,) * 16
    assert drive_waveforms[0].samples[32:48] == pytest.approx((0.2 + 0j,) * 16)
    assert drive_waveforms[1].samples[32:48] == pytest.approx((0.2j,) * 16)
    assert [entry.acquisitions[0].slot_id.value for entry in artifact.entries] == [
        "iq_shots",
        "iq_shots",
    ]
