from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.sdk.domain import DomainCompilation, DomainCompileRequest
from scopecat_quantum._ids import QubitId
from scopecat_quantum.programs import (
    AuthoredPulseEventProvenance,
    CircuitPulseEventProvenance,
)

from quantum_lab_demo import quantum_lab_compiler
from quantum_lab_demo.compiler import QuantumLabCompiler, _ListQuantumLabArtifact
from quantum_lab_demo.virtual_lab.pulse_profile import (
    y90_pulse_recipe,
    ym90_pulse_recipe,
)
from quantum_lab_demo.workflows.interaction_tomography import (
    ANALYSIS_BASIS,
    INTERACTION_AMPLITUDE,
    PREPARATION,
    interaction_pulse_layout,
    interaction_tomography_program,
    interaction_tomography_template,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab


def _compile_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    preparation: str,
    analysis_basis: str,
):
    compiler = quantum_lab_compiler()
    compilations = _capture_compilations(compiler, monkeypatch)
    run = (
        in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
        .prepare(interaction_tomography_template.bind(shots=2))
        .scan(PREPARATION, (preparation,))
        .scan(ANALYSIS_BASIS, (analysis_basis,))
        .scan(INTERACTION_AMPLITUDE, (Quantity(0.03, "arb"),))
        .run()
    )
    [compilation] = compilations
    [job] = compilation.jobs
    artifact = job.artifact
    assert isinstance(artifact, _ListQuantumLabArtifact)
    assert artifact.program.id == interaction_tomography_program.id
    [prepared] = artifact.entries
    [artifact_entry] = artifact.compiled.artifact.entries
    return run, prepared, artifact_entry


def test_direct_layout_preserves_offsets_and_complex_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, prepared, artifact = _compile_point(
        tmp_path,
        monkeypatch,
        preparation="00",
        analysis_basis="z",
    )
    waveforms = {
        waveform.channel_id.value: waveform.samples for waveform in artifact.waveforms
    }
    control = waveforms["drive-stack:drive.awg0.ch1:q0"]
    target = waveforms["drive-stack:drive.awg0.ch2:q1"]
    coupler = waveforms["coupler-stack:coupler.bias0:coupler-q0-q1"]

    assert run.manifest.status == "completed"
    assert prepared.scheduled.duration_seconds == Decimal("56e-9")
    assert artifact.sample_count == 56
    assert control[:8] == (0j,) * 8
    assert control[8:40] == pytest.approx((0.05 + 0j,) * 32)
    assert control[40:] == (0j,) * 16
    assert target[:12] == (0j,) * 12
    assert any(abs(sample.real) > 0 for sample in target[12:36])
    assert any(abs(sample.imag) > 0 for sample in target[12:36])
    assert target[36:] == (0j,) * 20
    assert coupler[:48] == pytest.approx((0.03 + 0j,) * 48)
    assert coupler[48:] == (0j,) * 8
    assert {acquisition.slot_id.local_id for acquisition in artifact.acquisitions} == {
        "control_iq_shots",
        "target_iq_shots",
    }
    assert all(acquisition.start_sample == 48 for acquisition in artifact.acquisitions)


def test_standard_gates_and_direct_pulses_keep_distinct_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run, prepared, _artifact = _compile_point(
        tmp_path,
        monkeypatch,
        preparation="0+",
        analysis_basis="x",
    )
    circuit = tuple(
        origin.provenance
        for origin in prepared.event_origins
        if isinstance(origin.provenance, CircuitPulseEventProvenance)
    )
    authored = tuple(
        origin.provenance
        for origin in prepared.event_origins
        if isinstance(origin.provenance, AuthoredPulseEventProvenance)
    )

    assert {
        y90_pulse_recipe.implementation_id((QubitId("q1"),)),
        ym90_pulse_recipe.implementation_id((QubitId("q1"),)),
    } <= {provenance.implementation_id for provenance in circuit}
    assert authored
    assert {provenance.template_program_id.value for provenance in authored} == {
        interaction_pulse_layout.id
    }


def _capture_compilations(
    compiler: QuantumLabCompiler,
    monkeypatch: pytest.MonkeyPatch,
) -> list[DomainCompilation]:
    compilations: list[DomainCompilation] = []
    compile_domain = compiler.compile

    def compile_and_capture(request: DomainCompileRequest) -> DomainCompilation:
        compilation = compile_domain(request)
        compilations.append(compilation)
        return compilation

    monkeypatch.setattr(compiler, "compile", compile_and_capture)
    return compilations
