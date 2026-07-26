from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.sdk.domain import DomainBatchInputs
from scopecat_quantum import authoring as quantum
from scopecat_quantum.programs import (
    AuthoredPulseAcquisitionProvenance,
    ImplementedGatePulseEventProvenance,
)
from scopecat_quantum.pulses import DRAG, Play

from quantum_lab_demo import quantum_lab_compiler
from quantum_lab_demo.compiler import QuantumLabCompiler, _ListQuantumLabArtifact
from quantum_lab_demo.virtual_lab.parameters import q0_drag_beta_lookup
from quantum_lab_demo.workflows.drag_beta_calibration import (
    NEGATIVE_CANDIDATE_ID,
    POSITIVE_CANDIDATE_ID,
)
from quantum_lab_demo.workflows.drag_beta_experiment import (
    AMPLIFICATION,
    BETA,
    drag_beta_program,
    drag_beta_template,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab


def test_drag_beta_golden_point_reaches_complex_target_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = quantum_lab_compiler()
    artifacts = _capture_artifacts(compiler, monkeypatch)
    lab = in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
    scan = sc.cartesian(
        sc.param_axis(
            BETA,
            q0_drag_beta_lookup(),
            (Quantity(0.75, "ns"),),
        ),
        sc.axis(AMPLIFICATION, (3,)),
    )

    lab.prepare(drag_beta_template).scan(scan).run()

    [compiled] = artifacts
    [prepared] = compiled.entries
    assert compiled.program.id == drag_beta_program.id
    assert prepared.scheduled.duration_seconds == Decimal("136e-9")

    candidate_origins = tuple(
        provenance
        for provenance in prepared.lowered.event_provenance
        if isinstance(provenance, ImplementedGatePulseEventProvenance)
    )
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
    candidate_plays = tuple(
        scheduled_by_id[provenance.event_id].instruction
        for provenance in candidate_origins
    )
    assert all(isinstance(instruction, Play) for instruction in candidate_plays)
    envelopes = tuple(
        instruction.envelope
        for instruction in candidate_plays
        if isinstance(instruction, Play)
    )
    assert all(isinstance(envelope, DRAG) for envelope in envelopes)
    assert tuple(
        float(envelope.phase.value)
        for envelope in envelopes
        if isinstance(envelope, DRAG)
    ) == pytest.approx((0.0, math.pi) * 3)
    assert all(
        envelope.beta == Quantity(0.75e-9, "s")
        for envelope in envelopes
        if isinstance(envelope, DRAG)
    )

    [acquisition] = prepared.lowered.acquisition_provenance
    assert isinstance(acquisition, AuthoredPulseAcquisitionProvenance)
    assert acquisition.acquisition_slot_id.value == "iq_shots"

    [entry] = compiled.target_artifact.entries
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


def _capture_artifacts(
    compiler: QuantumLabCompiler,
    monkeypatch: pytest.MonkeyPatch,
) -> list[_ListQuantumLabArtifact]:
    artifacts: list[_ListQuantumLabArtifact] = []
    compile_artifact = compiler._compile_target_artifact

    def compile_and_capture(
        program: quantum.Program,
        inputs: DomainBatchInputs,
        *,
        shots: int,
    ) -> _ListQuantumLabArtifact:
        artifact = compile_artifact(program, inputs, shots=shots)
        artifacts.append(artifact)
        return artifact

    monkeypatch.setattr(compiler, "_compile_target_artifact", compile_and_capture)
    return artifacts
