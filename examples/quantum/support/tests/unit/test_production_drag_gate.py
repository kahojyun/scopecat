from __future__ import annotations

from pathlib import Path

from scopecat import Quantity
from scopecat.authoring._value_refs import internal_lower_scalar_value_ref
from scopecat.compiler.relations.model import LiteralScalarExpr
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import TableParameterValue
from scopecat_quantum import (
    CircuitPulseEventProvenance,
    GateId,
    ImplementedGatePulseEventProvenance,
    QubitId,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo import quantum_lab_compiler
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

from .demo_lab_experiment_testkit import embedded_quantum_lab


def _entity_id(value: object) -> str:
    assert isinstance(value, EntityRef)
    return value.id


def test_production_drag_gate_authors_config_lookup_into_program_input() -> None:
    declaration = production_drag_program
    [call] = production_drag_capture.ir.body.instances
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
) -> None:
    baseline_config = quantum_wiring_config_profile()
    active_beta = Quantity(0.8, "ns")
    active_config = _with_q0_drag_beta(baseline_config, active_beta)
    compiler = quantum_lab_compiler()
    lab = embedded_quantum_lab(
        workspace=tmp_path,
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

    baseline, active, restored = compiler.trace.preparations(production_drag_program.id)
    assert isinstance(
        compiler.trace.preparations(production_drag_program.id),
        tuple,
    )
    [baseline_entry] = baseline.entries
    [active_entry] = active.entries
    [restored_entry] = restored.entries
    baseline_production = baseline.event_samples(
        baseline_entry,
        production_x90_event_id(baseline_entry),
    )
    active_production = active.event_samples(
        active_entry,
        production_x90_event_id(active_entry),
    )
    restored_production = restored.event_samples(
        restored_entry,
        production_x90_event_id(restored_entry),
    )
    baseline_reference = baseline.event_samples(
        baseline_entry,
        accepted_xm90_event_id(baseline_entry),
    )
    active_reference = active.event_samples(
        active_entry,
        accepted_xm90_event_id(active_entry),
    )
    restored_reference = restored.event_samples(
        restored_entry,
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
    assert restored.artifact_fingerprint == baseline.artifact_fingerprint
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
    assert compiler.trace.physical_execution_count == 3
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
