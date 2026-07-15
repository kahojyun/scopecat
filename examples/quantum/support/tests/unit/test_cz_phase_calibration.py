from __future__ import annotations

import math
from pathlib import Path

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.records.parameter import TableParameterValue
from scopecat_quantum import (
    CircuitPulseEventProvenance,
    FluxSignal,
    ImplementedGatePulseEventProvenance,
    Play,
    TargetCompileEntryId,
    TargetCompilerId,
    compile_target,
    prepare_quantum_target_batch,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo import quantum_lab
from quantum_lab_demo.reference_experiments.cz_phase_analysis import (
    CZ_AMPLITUDE_COLUMN,
    CZ_PARAMETER_TABLE,
    CZ_PHASE_PROPOSAL_ID,
    analyze_cz_phase_run,
)
from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    ANALYZER_PHASE_INPUT,
    CONTROL_STATE_INPUT,
    CZ_AMPLITUDE_INPUT,
    CZ_CANDIDATE_ID,
    CZ_FLUX_PULSE_TEMPLATE,
    cz_conditional_phase_program,
    prepare_cz_phase_entry,
)
from quantum_lab_demo.reference_experiments.cz_phase_experiment import (
    CZ_PHASE_CAPTURE_MODULE,
    CZ_PHASE_TEMPLATE,
    CzPhaseDomainExecutionAdapter,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListTargetCompiler,
    default_fake_list_target,
)


def _entity_id(value: object) -> str:
    assert isinstance(value, sc.EntityRef)
    return value.id


def test_cz_phase_program_keeps_two_qubit_gate_and_coupler_pulse_provenance() -> None:
    declaration = cz_conditional_phase_program()
    prepared = prepare_cz_phase_entry(
        declaration,
        amplitude=Quantity(0.24, "arb"),
        control_state=1,
        analyzer_phase=Quantity(math.pi / 2.0, "rad"),
        entry_id=TargetCompileEntryId("cz-phase-golden"),
    )

    assert set(declaration.inputs) == {
        CZ_AMPLITUDE_INPUT,
        CONTROL_STATE_INPUT,
        ANALYZER_PHASE_INPUT,
    }
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
    assert candidate.template_program_id.value == CZ_FLUX_PULSE_TEMPLATE.id
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
    assert tuple(value.calibration_id.value for value in calibrated) == (
        "cz-phase.baseline.x.q0",
        "cz-phase.baseline.x90.q1",
        "cz-phase.baseline.x90.q1",
    )


def test_cz_phase_point_compiles_coupler_flux_on_the_target_channel() -> None:
    prepared = prepare_cz_phase_entry(
        cz_conditional_phase_program(),
        amplitude=Quantity(0.24, "arb"),
        control_state=0,
        analyzer_phase=Quantity(0, "rad"),
        entry_id=TargetCompileEntryId("cz-phase-waveform"),
    )
    target = default_fake_list_target()
    compiler = FakeListTargetCompiler(TargetCompilerId("cz-phase-test.v1"), target)
    batch = prepare_quantum_target_batch(
        (prepared,),
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=1,
    )

    [entry] = compile_target(compiler, batch.request).artifact.entries
    flux = next(
        waveform
        for waveform in entry.waveforms
        if waveform.channel_id.value == "awg.flux.0"
    )
    assert flux.samples[16:48] == pytest.approx((0.24 + 0j,) * 32)
    assert all(sample == 0j for index, sample in enumerate(flux.samples) if index < 16)
    assert {window.slot_id.value for window in entry.acquisitions} == {
        "control_iq_shots",
        "target_iq_shots",
    }


def test_cz_phase_workspace_run_fits_pi_and_authors_candidate_proposal(
    tmp_path: Path,
) -> None:
    adapter = CzPhaseDomainExecutionAdapter()
    lab = quantum_lab(workspace=tmp_path)
    prepared = lab.prepare(
        CZ_PHASE_TEMPLATE,
        execution_backend=sc.ExecutionBackend(domain_adapters=(adapter,)),
    )

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
    assert adapter.physical_execution_count == 1
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
    assert delta.parameter_id == CZ_PARAMETER_TABLE
    assert isinstance(delta.after, TableParameterValue)
    q0_q1 = next(
        row
        for row in delta.after.rows
        if _entity_id(row["control_qubit"]) == "q0"
        and _entity_id(row["partner_qubit"]) == "q1"
        and row["gate"] == "cz"
    )
    assert q0_q1[CZ_AMPLITUDE_COLUMN] == result.fit.selected.amplitude
    saved = result.analysis.save()
    assert saved.record.id == "analysis-cz-conditional-phase"


def test_cz_phase_capture_uses_one_quantum_program_without_payload_compute() -> None:
    body = CZ_PHASE_CAPTURE_MODULE.ir.body
    [program] = body.domain_programs
    [call] = body.domain_calls

    assert program.dialect_id == quantum.QUANTUM_PROGRAM_DIALECT_ID
    assert isinstance(program.body, quantum.Program)
    assert tuple(name for name, _value in call.input_bindings) == (
        "control_state",
        "coupler_amplitude",
        "analyzer_phase",
    )
    assert body.operations == ()
