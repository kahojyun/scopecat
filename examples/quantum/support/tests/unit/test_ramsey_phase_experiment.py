from __future__ import annotations

import math
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat_quantum import (
    AuthoredPulseAcquisitionProvenance,
    AuthoredPulseEventProvenance,
    CircuitPulseEventProvenance,
    ImplementedGatePulseEventProvenance,
    MeasurementResult,
    QubitId,
)

from quantum_lab_demo import quantum_lab, quantum_lab_compiler
from quantum_lab_demo.virtual_lab.pulse_profile import x90_pulse_recipe
from quantum_lab_demo.workflows.ramsey_phase_experiment import (
    PHASE,
    X90_CANDIDATE_ID,
    ramsey_phase_program,
    ramsey_phase_template,
    ramsey_x90_candidate,
)


def test_ramsey_program_runs_through_the_shared_compiler(tmp_path: Path) -> None:
    compiler = quantum_lab_compiler()
    lab = quantum_lab(workspace=tmp_path, compiler=compiler)

    run = (
        lab.prepare(ramsey_phase_template)
        .scan(
            PHASE,
            (Quantity(0, "rad"),),
        )
        .run()
    )
    [preparation] = compiler.trace.preparations(ramsey_phase_program.id)
    [prepared] = preparation.entries

    assert run.manifest.status == "completed"
    assert [port.id for port in ramsey_phase_program.ports] == ["qubit", "phase"]
    [result] = ramsey_phase_program.results
    assert isinstance(result, MeasurementResult)
    assert result.id == "iq_shots"
    assert prepared.source_program_id.value == ramsey_phase_program.id
    assert prepared.acquisition_origins[0].address.slot_id == (
        result.acquisition_slot_id
    )
    assert isinstance(
        prepared.acquisition_origins[0].provenance,
        AuthoredPulseAcquisitionProvenance,
    )

    provenance = tuple(origin.provenance for origin in prepared.event_origins)
    [accepted_x90] = tuple(
        item for item in provenance if isinstance(item, CircuitPulseEventProvenance)
    )
    assert accepted_x90.implementation_id == x90_pulse_recipe.implementation_id(
        (QubitId("q0"),)
    )
    assert any(
        isinstance(item, ImplementedGatePulseEventProvenance)
        and item.candidate_id == X90_CANDIDATE_ID
        and item.template_program_id.value == ramsey_x90_candidate.id
        for item in provenance
    )
    assert any(isinstance(item, AuthoredPulseEventProvenance) for item in provenance)


def test_ramsey_phase_rotates_only_the_candidate_and_resets_between_points(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler()
    lab = quantum_lab(workspace=tmp_path, compiler=compiler)
    lab.prepare(ramsey_phase_template).scan(
        PHASE,
        (Quantity(0, "rad"), Quantity(math.pi / 2, "rad")),
    ).run()
    [preparation] = compiler.trace.preparations(ramsey_phase_program.id)

    artifact = preparation.artifact
    drive_waveforms = tuple(
        next(
            waveform
            for waveform in entry.waveforms
            if waveform.channel_id.value == "drive-stack:drive.awg0.ch1:q0"
        )
        for entry in artifact.entries
    )

    assert [entry.sample_count for entry in artifact.entries] == [72, 72]
    assert drive_waveforms[0].samples[:16] == pytest.approx(
        drive_waveforms[1].samples[:16]
    )
    assert any(abs(sample.imag) > 0.0 for sample in drive_waveforms[0].samples[:16])
    assert drive_waveforms[0].samples[16:32] == (0j,) * 16
    assert drive_waveforms[1].samples[16:32] == (0j,) * 16
    assert drive_waveforms[0].samples[32:48] == pytest.approx((0.2 + 0j,) * 16)
    assert drive_waveforms[1].samples[32:48] == pytest.approx((0.2j,) * 16)
    assert [entry.acquisitions[0].slot_id.value for entry in artifact.entries] == [
        "iq_shots",
        "iq_shots",
    ]
