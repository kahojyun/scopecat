from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat import Quantity
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import TableParameterValue
from scopecat_quantum import (
    CircuitPulseEventProvenance,
    GateId,
    ImplementedGatePulseEventProvenance,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo import quantum_lab
from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    DRAG_GATE_PULSE_TEMPLATE,
    XM90_CALIBRATION_ID,
)
from quantum_lab_demo.reference_experiments.production_drag_gate import (
    ACTIVE_DRAG_BETA,
    PRODUCTION_DRAG_BETA_INPUT,
    PRODUCTION_DRAG_GATE_TEMPLATE,
    TRUSTED_REFERENCE_BETA,
    ProductionDragGateCompiler,
    production_drag_gate_program,
    trusted_xm90_calibration_catalog,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile


def _entity_id(value: object) -> str:
    assert isinstance(value, EntityRef)
    return value.id


def test_production_drag_gate_authors_config_lookup_into_program_input() -> None:
    declaration = production_drag_gate_program()
    execution = PRODUCTION_DRAG_GATE_TEMPLATE.build().domain_executions[0]
    assert execution is not None
    program = execution.program

    assert declaration.inputs == (PRODUCTION_DRAG_BETA_INPUT,)
    assert isinstance(program.body, quantum.Program)
    assert program.body.inputs == (PRODUCTION_DRAG_BETA_INPUT,)
    assert tuple(port.id for port in program.input_ports) == ("drag_beta",)
    assert execution.input_bindings == (("drag_beta", ACTIVE_DRAG_BETA),)

    [reference] = trusted_xm90_calibration_catalog().gates.entries
    assert reference.id == XM90_CALIBRATION_ID


def test_active_drag_beta_changes_only_production_compiled_segment(
    tmp_path: Path,
) -> None:
    baseline_config = quantum_wiring_config_profile()
    active_beta = Quantity(0.8, "ns")
    active_config = _with_q0_drag_beta(baseline_config, active_beta)
    lab = quantum_lab(workspace=tmp_path, config_profile=baseline_config)

    baseline_activation = lab.activate_config(
        baseline_config,
        entry_id="production-drag-baseline",
        expected_generation=0,
    )
    baseline_compiler = ProductionDragGateCompiler()
    baseline_run = lab.prepare(
        PRODUCTION_DRAG_GATE_TEMPLATE,
        config="active",
        system=sc.ExperimentSystem(
            domain_compiler=baseline_compiler,
        ),
    ).run()

    active_activation = lab.activate_config(
        active_config,
        entry_id="production-drag-active",
        expected_generation=baseline_activation.active_state.generation,
    )
    active_compiler = ProductionDragGateCompiler()
    active_run = lab.prepare(
        PRODUCTION_DRAG_GATE_TEMPLATE,
        config="active",
        system=sc.ExperimentSystem(
            domain_compiler=active_compiler,
        ),
    ).run()
    rollback = lab.rollback(
        expected_generation=active_activation.active_state.generation,
        note="restore production DRAG baseline",
    )
    restored_compiler = ProductionDragGateCompiler()
    restored_run = lab.prepare(
        PRODUCTION_DRAG_GATE_TEMPLATE,
        config="active",
        system=sc.ExperimentSystem(
            domain_compiler=restored_compiler,
        ),
    ).run()

    [baseline] = baseline_compiler.preparations
    [active] = active_compiler.preparations
    [restored] = restored_compiler.preparations
    assert isinstance(baseline_compiler.preparations, tuple)
    assert baseline.resolved_drag_beta == TRUSTED_REFERENCE_BETA
    assert active.resolved_drag_beta == active_beta
    assert baseline.production_samples != active.production_samples
    assert baseline.trusted_reference_samples == active.trusted_reference_samples
    assert active.trusted_reference_samples == restored.trusted_reference_samples
    assert restored.resolved_drag_beta == baseline.resolved_drag_beta
    assert restored.production_samples == baseline.production_samples
    assert restored.artifact_fingerprint == baseline.artifact_fingerprint
    assert len(baseline.production_samples) == 16
    assert len(baseline.trusted_reference_samples) == 16
    assert tuple(sample.real for sample in baseline.production_samples) == tuple(
        sample.real for sample in active.production_samples
    )
    assert tuple(sample.imag for sample in baseline.production_samples) != tuple(
        sample.imag for sample in active.production_samples
    )

    [production] = tuple(
        origin.provenance
        for origin in active.entry.event_origins
        if isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
    )
    assert production.gate_id == GateId("x90")
    assert production.candidate_id is None
    assert production.template_program_id.value == DRAG_GATE_PULSE_TEMPLATE.id

    [trusted] = tuple(
        origin.provenance
        for origin in active.entry.event_origins
        if isinstance(origin.provenance, CircuitPulseEventProvenance)
    )
    assert trusted.calibration_id == XM90_CALIBRATION_ID

    assert baseline_run.manifest.status == active_run.manifest.status == "completed"
    baseline_records = baseline_run.data().measurements().dataset.records
    active_records = active_run.data().measurements().dataset.records
    assert [point.coordinates for point in baseline_records] == [{}]
    assert [point.coordinates for point in active_records] == [{}]
    assert baseline_compiler.physical_execution_count == 1
    assert active_compiler.physical_execution_count == 1
    assert baseline_run.manifest.config_source is not None
    assert active_run.manifest.config_source is not None
    assert baseline_run.manifest.config_source.entry_id == baseline_activation.entry.id
    assert active_run.manifest.config_source.entry_id == active_activation.entry.id
    assert active_run.manifest.config_source.registry_generation == (
        active_activation.active_state.generation
    )
    assert active_run.manifest.config_source.content_hash == (
        active_activation.entry.content_hash
    )
    assert baseline_run.manifest.config_content_hash == (
        baseline_run.manifest.config_source.content_hash
    )
    assert active_run.manifest.config_content_hash == (
        active_run.manifest.config_source.content_hash
    )
    assert rollback.active_state.active_entry_id == baseline_activation.entry.id
    assert restored_run.manifest.config_source is not None
    assert restored_run.manifest.config_source.entry_id == baseline_activation.entry.id
    assert restored_run.manifest.config_source.registry_generation == 3
    assert restored_run.manifest.config_content_hash == (
        restored_run.manifest.config_source.content_hash
    )
    assert baseline.artifact_fingerprint != active.artifact_fingerprint


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
        row_locations=qubits.row_locations,
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
