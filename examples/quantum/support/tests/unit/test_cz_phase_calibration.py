from __future__ import annotations

import math
from pathlib import Path

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.authoring._value_refs import internal_lower_scalar_value_ref
from scopecat.records.parameter import TableParameterValue
from scopecat.sdk.domain import DomainCompilation, DomainCompileRequest
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import QubitId
from scopecat_quantum.programs import (
    CircuitPulseEventProvenance,
    ImplementedGatePulseEventProvenance,
)
from scopecat_quantum.pulses import FluxSignal, Play

from quantum_lab_demo import quantum_lab_compiler
from quantum_lab_demo.compiler import QuantumLabCompiler, _ListQuantumLabArtifact
from quantum_lab_demo.virtual_lab.parameters import (
    CZ_AMPLITUDE_PARAMETER_COLUMN,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
    q0_q1_cz_amplitude_lookup,
)
from quantum_lab_demo.virtual_lab.pulse_profile import (
    x90_pulse_recipe,
    x_pulse_recipe,
)
from quantum_lab_demo.workflows.cz_phase_analysis import (
    CZ_PHASE_PROPOSAL_ID,
    analyze_cz_phase_run,
)
from quantum_lab_demo.workflows.cz_phase_calibration import (
    CZ_CANDIDATE_ID,
    cz_conditional_phase,
    cz_flux_candidate,
)
from quantum_lab_demo.workflows.cz_phase_experiment import (
    ANALYZER_PHASE,
    CONTROL_STATE,
    CZ_AMPLITUDE,
    cz_phase_capture,
    cz_phase_template,
)

from .demo_lab_experiment_testkit import (
    in_process_quantum_lab,
)


def _entity_id(value: object) -> str:
    assert isinstance(value, sc.EntityRef)
    return value.id


def _compiled_cz_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    control_state: int,
    analyzer_phase: Quantity,
):
    compiler = quantum_lab_compiler()
    compilations = _capture_compilations(compiler, monkeypatch)
    lab = in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
    scan = sc.cartesian(
        sc.param_axis(
            CZ_AMPLITUDE,
            q0_q1_cz_amplitude_lookup(),
            (Quantity(0.24, "arb"),),
        ),
        sc.axis(CONTROL_STATE, (control_state,)),
        sc.axis(ANALYZER_PHASE, (analyzer_phase,)),
    )
    lab.prepare(cz_phase_template).scan(scan).run()
    [compilation] = compilations
    [job] = compilation.jobs
    artifact = job.artifact
    assert isinstance(artifact, _ListQuantumLabArtifact)
    assert artifact.program.id == cz_conditional_phase.id
    [prepared] = artifact.entries
    [artifact_entry] = artifact.compiled.artifact.entries
    return prepared, artifact_entry


def test_cz_phase_program_keeps_two_qubit_gate_and_coupler_pulse_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = cz_conditional_phase
    prepared, _artifact_entry = _compiled_cz_point(
        tmp_path,
        monkeypatch,
        control_state=1,
        analyzer_phase=Quantity(math.pi / 2.0, "rad"),
    )

    assert tuple(element.id for element in declaration.elements) == (
        "control",
        "target",
        "coupler",
    )
    assert tuple(port.id for port in declaration.inputs) == (
        "control_state",
        "coupler_amplitude",
        "analyzer_phase",
    )
    assert tuple(result.id for result in declaration.results) == (
        "control_iq_shots",
        "target_iq_shots",
    )
    [candidate] = tuple(
        provenance
        for provenance in prepared.lowered.event_provenance
        if isinstance(provenance, ImplementedGatePulseEventProvenance)
    )
    assert candidate.gate_id.value == "cz"
    assert candidate.candidate_id == CZ_CANDIDATE_ID
    assert candidate.template_program_id.value == cz_flux_candidate.id
    candidate_event = next(
        event for event in prepared.scheduled.events if event.id == candidate.event_id
    )
    assert isinstance(candidate_event.instruction, Play)
    assert candidate_event.instruction.signal == FluxSignal(
        quantum.flux(quantum.coupler("coupler-q0-q1")).owner
    )
    calibrated = tuple(
        provenance
        for provenance in prepared.lowered.event_provenance
        if isinstance(provenance, CircuitPulseEventProvenance)
    )
    assert tuple(value.implementation_id.value for value in calibrated) == (
        x_pulse_recipe.implementation_id((QubitId("q0"),)).value,
        x90_pulse_recipe.implementation_id((QubitId("q1"),)).value,
        x90_pulse_recipe.implementation_id((QubitId("q1"),)).value,
    )


def test_cz_phase_point_compiles_coupler_flux_on_the_target_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepared, entry = _compiled_cz_point(
        tmp_path,
        monkeypatch,
        control_state=0,
        analyzer_phase=Quantity(0, "rad"),
    )
    flux = next(
        waveform
        for waveform in entry.waveforms
        if waveform.channel_id.value == ("coupler-stack:coupler.bias0:coupler-q0-q1")
    )
    assert flux.samples[16:48] == pytest.approx((0.24 + 0j,) * 32)
    assert all(sample == 0j for index, sample in enumerate(flux.samples) if index < 16)
    assert {window.slot_id.value for window in entry.acquisitions} == {
        "control_iq_shots",
        "target_iq_shots",
    }


def test_cz_phase_in_process_run_fits_pi_and_authors_candidate_proposal(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
    prepared = lab.prepare(cz_phase_template)

    preview = prepared.preview()
    run = prepared.run()
    records = run.data().measurements().dataset.records
    result = analyze_cz_phase_run(run)

    assert preview.point_count == 24
    assert preview.coordinate_ids == (
        "coupler_amplitude",
        "control_state",
        "analyzer_phase",
    )
    assert run.manifest.status == "completed"
    assert len(records) == 24
    assert len(result.observations) == 24
    assert float(result.fit.selected.amplitude.to("arb").value) == pytest.approx(0.24)
    assert result.fit.selected.conditional_phase == pytest.approx(math.pi)
    assert result.fit.selected.phase_error < 1e-12
    assert result.fit.selected.minimum_contrast > 0.85
    assert result.fit.selected.maximum_rmse < 1e-12
    assert result.fit.failed_checks == ()
    assert result.proposal_id == CZ_PHASE_PROPOSAL_ID

    [proposal] = result.analysis.parameter_proposals
    [delta] = proposal.deltas
    assert delta.parameter_id == TWO_QUBIT_GATE_PARAMETER_TABLE
    assert isinstance(delta.after, TableParameterValue)
    q0_q1 = next(
        row
        for row in delta.after.rows
        if _entity_id(row["control_qubit"]) == "q0"
        and _entity_id(row["partner_qubit"]) == "q1"
        and row["gate"] == "cz"
    )
    assert q0_q1[CZ_AMPLITUDE_PARAMETER_COLUMN] == result.fit.selected.amplitude
    saved = result.analysis.save()
    assert saved.record.id == "analysis-cz-conditional-phase"


def test_cz_phase_capture_uses_one_quantum_program_without_payload_compute() -> None:
    body = cz_phase_capture.ir.body
    [call] = body.child_instances
    [execution] = call.module.body.domain_executions
    program = execution.program

    assert program.dialect_id == quantum.QUANTUM_PROGRAM_DIALECT_ID
    assert isinstance(program.body, quantum.Program)
    assert tuple(name for name, _value in execution.input_bindings) == (
        "control",
        "target",
        "coupler",
        "control_state",
        "coupler_amplitude",
        "analyzer_phase",
    )
    call_inputs = {binding.import_id: binding.source for binding in call.input_bindings}
    assert internal_lower_scalar_value_ref(
        call_inputs["coupler_amplitude"]
    ) == internal_lower_scalar_value_ref(q0_q1_cz_amplitude_lookup())
    assert body.operations == ()


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
