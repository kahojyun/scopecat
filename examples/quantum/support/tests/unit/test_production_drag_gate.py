from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.kernel.entity import EntityRef
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import TableParameterValue
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat.sdk.domain import DomainBatchInputs
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import PulseEventId
from scopecat_quantum.program_targets import PreparedQuantumTargetEntry
from scopecat_quantum.pulses import DriveSignal, Play

from quantum_lab_demo import quantum_lab_compiler
from quantum_lab_demo.compiler import QuantumLabCompiler, _ListQuantumLabArtifact
from quantum_lab_demo.configuration import quantum_lab_bootstrap_config
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListArtifact,
    FakeListTarget,
    configured_fake_list_target,
)
from quantum_lab_demo.workflows.production_drag_gate import (
    production_drag_template,
    production_x90_event_id,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab


def test_active_drag_beta_changes_the_production_gate_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_config = quantum_lab_bootstrap_config()
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
    baseline_run = lab.prepare(production_drag_template, config="active").run()
    active_activation = lab.activate_config(
        active_config,
        entry_id="production-drag-active",
        expected_generation=baseline_activation.active_state.generation,
    )
    active_run = lab.prepare(production_drag_template, config="active").run()
    lab.rollback(
        expected_generation=active_activation.active_state.generation,
        note="restore production DRAG baseline",
    )
    restored_run = lab.prepare(production_drag_template, config="active").run()

    baseline, active, restored = artifacts
    [baseline_entry] = baseline.entries
    [active_entry] = active.entries
    [restored_entry] = restored.entries
    baseline_samples = _event_samples(
        baseline_entry,
        baseline.target_artifact,
        target,
        production_x90_event_id(baseline_entry),
    )
    active_samples = _event_samples(
        active_entry,
        active.target_artifact,
        target,
        production_x90_event_id(active_entry),
    )
    restored_samples = _event_samples(
        restored_entry,
        restored.target_artifact,
        target,
        production_x90_event_id(restored_entry),
    )

    assert baseline.points[0].value("drag_beta") == Quantity(0.5, "ns")
    assert active.points[0].value("drag_beta") == active_beta
    assert restored.points[0].value("drag_beta") == Quantity(0.5, "ns")
    assert tuple(sample.real for sample in baseline_samples) == tuple(
        sample.real for sample in active_samples
    )
    assert tuple(sample.imag for sample in baseline_samples) != tuple(
        sample.imag for sample in active_samples
    )
    assert restored_samples == baseline_samples
    assert (
        active.target_artifact.artifact_fingerprint
        != baseline.target_artifact.artifact_fingerprint
    )
    assert (
        restored.target_artifact.artifact_fingerprint
        == baseline.target_artifact.artifact_fingerprint
    )

    assert baseline_run.manifest.status == "completed"
    assert active_run.manifest.status == "completed"
    assert restored_run.manifest.status == "completed"
    active_source = active_run.manifest.config_source
    assert isinstance(active_source, ConfigRegistryRunConfigSource)
    assert active_source.entry_id == active_activation.entry.id


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
    assert isinstance(event.instruction.signal, DriveSignal)
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
                    beta
                    if row["qubit"] == EntityRef(id="q0", kind="logical_qubit")
                    else row["drag_beta"]
                ),
            }
            for row in qubits.rows
        ),
    )
    snapshot = config.parameter_snapshot.model_copy(
        update={
            "id": "production-drag-active-parameters",
            "values": tuple(
                updated_qubits if value.id == qubits.id else value
                for value in config.parameter_snapshot.values
            ),
        }
    )
    return config.model_copy(
        update={
            "id": "production-drag-active-config",
            "parameter_snapshot": snapshot,
        }
    )
