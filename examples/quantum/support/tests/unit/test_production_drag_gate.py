from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.authoring._value_refs import internal_lower_scalar_value_ref
from scopecat.graph.relations.model import LiteralScalarExpr
from scopecat.kernel.entity import EntityRef
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import TableParameterValue
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat.sdk.domain import DomainBatchInputs
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import GateId, PulseEventId, QubitId
from scopecat_quantum.program_targets import PreparedQuantumTargetEntry
from scopecat_quantum.programs import (
    CircuitPulseEventProvenance,
    ImplementedGatePulseEventProvenance,
)
from scopecat_quantum.pulses import Play

from quantum_lab_demo import quantum_lab_compiler
from quantum_lab_demo.compiler import QuantumLabCompiler, _ListQuantumLabArtifact
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListArtifact,
    FakeListTarget,
    configured_fake_list_target,
)
from quantum_lab_demo.virtual_lab.parameters import q0_drag_beta_lookup
from quantum_lab_demo.virtual_lab.pulse_profile import xm90_pulse_recipe
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile
from quantum_lab_demo.workflows.production_drag_gate import (
    accepted_xm90_event_id,
    production_drag_capture,
    production_drag_program,
    production_drag_template,
    production_x90,
    production_x90_event_id,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab


def _entity_id(value: object) -> str:
    assert isinstance(value, EntityRef)
    return value.id


def test_production_drag_gate_authors_config_lookup_into_program_input() -> None:
    declaration = production_drag_program
    [call] = production_drag_capture.ir.body.child_instances
    [execution] = call.module.body.domain_executions
    program = execution.program

    assert tuple(element.id for element in declaration.elements) == ("qubit",)
    assert tuple(port.id for port in declaration.inputs) == ("drag_beta",)
    assert isinstance(program.body, quantum.Program)
    assert tuple(port.id for port in program.body.ports) == ("qubit", "drag_beta")
    assert tuple(port.id for port in program.input_ports) == ("qubit", "drag_beta")
    call_inputs = {binding.import_id: binding.source for binding in call.input_bindings}
    assert internal_lower_scalar_value_ref(call_inputs["qubit"]) == LiteralScalarExpr(
        value=EntityRef(id="q0", kind="logical_qubit")
    )
    assert internal_lower_scalar_value_ref(
        call_inputs["drag_beta"]
    ) == internal_lower_scalar_value_ref(q0_drag_beta_lookup())


def test_active_drag_beta_changes_program_and_compiler_segments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_config = quantum_wiring_config_profile()
    active_beta = Quantity(0.8, "ns")
    active_config = _with_q0_drag_beta(baseline_config, active_beta)
    target = configured_fake_list_target(baseline_config)
    compiler = quantum_lab_compiler(config_profile=baseline_config, target=target)
    artifacts = _capture_artifacts(compiler, monkeypatch)
    lab = in_process_quantum_lab(
        project_root=tmp_path,
        config_profile=baseline_config,
        compiler=compiler,
    )

    baseline_activation = lab.activate_config(
        baseline_config,
        entry_id="production-drag-baseline",
        expected_generation=0,
    )
    baseline_run = lab.prepare(
        production_drag_template,
        config="active",
    ).run()

    active_activation = lab.activate_config(
        active_config,
        entry_id="production-drag-active",
        expected_generation=baseline_activation.active_state.generation,
    )
    active_run = lab.prepare(
        production_drag_template,
        config="active",
    ).run()
    rollback = lab.rollback(
        expected_generation=active_activation.active_state.generation,
        note="restore production DRAG baseline",
    )
    restored_run = lab.prepare(
        production_drag_template,
        config="active",
    ).run()

    baseline, active, restored = artifacts
    assert all(
        artifact.program.id == production_drag_program.id
        for artifact in (baseline, active, restored)
    )
    [baseline_entry] = baseline.entries
    [active_entry] = active.entries
    [restored_entry] = restored.entries
    baseline_production = _event_samples(
        baseline_entry,
        baseline.target_artifact,
        target,
        production_x90_event_id(baseline_entry),
    )
    active_production = _event_samples(
        active_entry,
        active.target_artifact,
        target,
        production_x90_event_id(active_entry),
    )
    restored_production = _event_samples(
        restored_entry,
        restored.target_artifact,
        target,
        production_x90_event_id(restored_entry),
    )
    baseline_reference = _event_samples(
        baseline_entry,
        baseline.target_artifact,
        target,
        accepted_xm90_event_id(baseline_entry),
    )
    active_reference = _event_samples(
        active_entry,
        active.target_artifact,
        target,
        accepted_xm90_event_id(active_entry),
    )
    restored_reference = _event_samples(
        restored_entry,
        restored.target_artifact,
        target,
        accepted_xm90_event_id(restored_entry),
    )
    assert baseline.points[0].value("drag_beta") == Quantity(0.5, "ns")
    assert active.points[0].value("drag_beta") == active_beta
    assert baseline_production != active_production
    assert baseline_reference != active_reference
    assert baseline_reference == restored_reference
    assert restored.points[0].value("drag_beta") == baseline.points[0].value(
        "drag_beta"
    )
    assert restored_production == baseline_production
    assert (
        restored.target_artifact.artifact_fingerprint
        == baseline.target_artifact.artifact_fingerprint
    )
    assert len(baseline_production) == 16
    assert len(baseline_reference) == 16
    assert tuple(sample.real for sample in baseline_production) == tuple(
        sample.real for sample in active_production
    )
    assert tuple(sample.imag for sample in baseline_production) != tuple(
        sample.imag for sample in active_production
    )

    [production] = tuple(
        origin.provenance
        for origin in active_entry.event_origins
        if isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
    )
    assert production.gate_id == GateId("x90")
    assert production.candidate_id is None
    assert production.template_program_id.value == production_x90.id

    [accepted] = tuple(
        origin.provenance
        for origin in active_entry.event_origins
        if isinstance(origin.provenance, CircuitPulseEventProvenance)
    )
    assert accepted.implementation_id == xm90_pulse_recipe.implementation_id(
        (QubitId("q0"),)
    )

    assert baseline_run.manifest.status == active_run.manifest.status == "completed"
    baseline_records = baseline_run.data().measurements().dataset.records
    active_records = active_run.data().measurements().dataset.records
    assert [point.coordinates for point in baseline_records] == [{}]
    assert [point.coordinates for point in active_records] == [{}]
    baseline_source = baseline_run.manifest.config_source
    active_source = active_run.manifest.config_source
    assert isinstance(baseline_source, ConfigRegistryRunConfigSource)
    assert isinstance(active_source, ConfigRegistryRunConfigSource)
    assert baseline_source.entry_id == baseline_activation.entry.id
    assert active_source.entry_id == active_activation.entry.id
    assert active_source.registry_generation == (
        active_activation.active_state.generation
    )
    assert active_source.content_hash == active_activation.entry.content_hash
    assert baseline_run.manifest.config_content_hash == (baseline_source.content_hash)
    assert active_run.manifest.config_content_hash == active_source.content_hash
    assert rollback.active_state.active_entry_id == baseline_activation.entry.id
    restored_source = restored_run.manifest.config_source
    assert isinstance(restored_source, ConfigRegistryRunConfigSource)
    assert restored_source.entry_id == baseline_activation.entry.id
    assert restored_source.registry_generation == 3
    assert restored_run.manifest.config_content_hash == (restored_source.content_hash)
    assert (
        baseline.target_artifact.artifact_fingerprint
        != active.target_artifact.artifact_fingerprint
    )


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


def _event_samples(
    entry: PreparedQuantumTargetEntry,
    artifact: FakeListArtifact,
    target: FakeListTarget,
    event_id: PulseEventId,
) -> tuple[complex, ...]:
    [event] = tuple(item for item in entry.scheduled.events if item.id == event_id)
    assert isinstance(event.instruction, Play)
    channel = target.output_channel(event.instruction.signal)
    assert channel is not None
    [artifact_entry] = tuple(
        item for item in artifact.entries if item.entry_id == entry.id
    )
    [waveform] = tuple(
        item for item in artifact_entry.waveforms if item.channel_id == channel
    )
    rate = Decimal(artifact.sample_rate_hz)
    start = event.start_seconds * rate
    count = event.duration_seconds * rate
    assert start == start.to_integral_value()
    assert count == count.to_integral_value()
    first = int(start)
    return waveform.samples[first : first + int(count)]


def _with_q0_drag_beta(
    config: ConfigProfileSnapshot,
    beta: Quantity,
) -> ConfigProfileSnapshot:
    qubits = config.parameter_snapshot.get("qubits")
    assert isinstance(qubits, TableParameterValue)
    updated_qubits = TableParameterValue(
        id=qubits.id,
        rows=tuple(
            {
                **dict(row),
                "drag_beta": (
                    beta if _entity_id(row["qubit"]) == "q0" else row["drag_beta"]
                ),
            }
            for row in qubits.rows
        ),
    )
    values = tuple(
        updated_qubits if value.id == qubits.id else value
        for value in config.parameter_snapshot.values
    )
    snapshot = config.parameter_snapshot.model_copy(
        update={"id": "production-drag-active-parameters", "values": values}
    )
    return config.model_copy(
        update={
            "id": "production-drag-active-config",
            "parameter_snapshot": snapshot,
        }
    )
