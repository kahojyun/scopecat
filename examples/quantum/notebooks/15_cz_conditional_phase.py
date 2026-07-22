"""Run and analyze a two-qubit gate/coupler-pulse program in one DSL."""

from __future__ import annotations

# %%
import math

import scopecat as sc
from quantum_lab_demo import (
    QuantumLabCompiler,
    notebook_workspace,
    quantum_lab,
)
from quantum_lab_demo.reference_experiments import (
    CZ_AMPLITUDE,
    CZ_AMPLITUDE_POINTS,
    CZ_AMPLITUDE_SPAN,
    CZ_CANDIDATE_ID,
    CZ_FLUX_PULSE_TEMPLATE,
    analyze_cz_phase_run,
    cz_conditional_phase,
    cz_phase_template,
)
from quantum_lab_demo.virtual_lab import (
    CZ_AMPLITUDE_PARAMETER_COLUMN,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
    q0_q1_cz_row,
)
from scopecat.records.parameter import TableParameterValue
from scopecat_quantum import ImplementedGatePulseEventProvenance


def _entity_id(value: object) -> str:
    assert isinstance(value, sc.EntityRef)
    return value.id


def _quantity_in_unit(value: object, unit: str) -> float:
    assert isinstance(value, sc.Quantity)
    return float(value.to(unit).value)


# %%
# One Program contains all of these first-class statements:
#
# prepare control state with an accepted X gate
# -> accepted X90(target)
# -> explicit CZ(control, target) implemented by a coupler PulseTemplate
# -> shift_phase(target drive, analyzer phase)
# -> accepted X90(target)
# -> parallel readout pulses and acquisitions for both qubits.
program = cz_conditional_phase
authoring_summary = {
    "program": program.id,
    "inputs": tuple(value.id for value in program.inputs),
    "results": tuple(value.id for value in program.results),
    "gate_arities": {
        definition.id.value: definition.qubit_arity
        for definition in program.gate_definitions
    },
    "cz_template": CZ_FLUX_PULSE_TEMPLATE.id,
}
print(authoring_summary)

# %%
# Workspace preview and execution use the same public path as every other
# experiment. No payload compute or direct target compiler call appears here.
workspace = notebook_workspace("15-cz-conditional-phase")
lab = quantum_lab(workspace=workspace)
system = lab.system
assert system is not None
compiler = system.domain_compiler
assert isinstance(compiler, QuantumLabCompiler)
cz_parameter_scan = sc.param_axis(
    CZ_AMPLITUDE,
    q0_q1_cz_row(),
    CZ_AMPLITUDE_PARAMETER_COLUMN,
    span=CZ_AMPLITUDE_SPAN,
    points=CZ_AMPLITUDE_POINTS,
)
prepared = lab.prepare(cz_phase_template).scan(cz_parameter_scan)
preview = prepared.preview()
run = prepared.run(
    name="CZ conditional-phase Ramsey",
    tags=("reference", "calibration", "two-qubit", "coupler-pulse"),
)

# %%
measurements = run.data().measurements()
records = tuple(measurements.dataset.records)
measurement_summary = {
    "run_id": run.id,
    "status": run.manifest.status,
    "points": preview.point_count,
    "coordinates": preview.coordinate_ids,
    "records": len(records),
    "observables": tuple(sorted(records[0].observables)),
    "physical_executions": compiler.trace.physical_execution_count,
}
print(measurement_summary)

# %%
# The prepared proof retains the semantic CZ call and its physical coupler
# event. The target artifact maps that event onto the fake coupler AWG channel.
reference = compiler.trace.preparations(cz_conditional_phase.id)[-1]
candidate_origins = tuple(
    origin.provenance
    for entry in reference.entries
    for origin in entry.event_origins
    if isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
)
artifact = reference.artifact
flux_channels = tuple(
    sorted(
        {
            waveform.channel_id.value
            for entry in artifact.entries
            for waveform in entry.waveforms
            if waveform.channel_id.value.startswith("awg.flux.")
        }
    )
)
physical_summary = {
    "candidate_events": len(candidate_origins),
    "candidate_ids": tuple(
        sorted(
            {
                value.candidate_id
                for value in candidate_origins
                if value.candidate_id is not None
            }
        )
    ),
    "candidate_gate_ids": tuple(
        sorted({value.gate_id.value for value in candidate_origins})
    ),
    "template_ids": tuple(
        sorted({value.template_program_id.value for value in candidate_origins})
    ),
    "flux_channels": flux_channels,
    "artifact_fingerprint": reference.artifact_fingerprint,
}
print(physical_summary)

# %%
# Fit both control-state Ramsey fringes. Their phase difference is the
# conditional phase; the best amplitude is proposed only after phase,
# contrast, RMSE, and control-state guardrails pass.
result = analyze_cz_phase_run(run)
saved = result.analysis.save()
candidate = result.analysis.candidate_config()
[proposal] = result.analysis.parameter_proposals
[delta] = proposal.deltas
assert isinstance(delta.after, TableParameterValue)
q0_q1 = next(
    row
    for row in delta.after.rows
    if _entity_id(row["control_qubit"]) == "q0"
    and _entity_id(row["partner_qubit"]) == "q1"
    and row["gate"] == "cz"
)
parameter_table = run.config.parameter_snapshot.get(TWO_QUBIT_GATE_PARAMETER_TABLE)
assert isinstance(parameter_table, TableParameterValue)
accepted_q0_q1 = next(
    row
    for row in parameter_table.rows
    if _entity_id(row["control_qubit"]) == "q0"
    and _entity_id(row["partner_qubit"]) == "q1"
    and row["gate"] == "cz"
)
scanned_amplitudes = tuple(
    sorted(
        {
            _quantity_in_unit(point.coordinates["coupler_amplitude"], "arb")
            for point in preview.points
        }
    )
)
parameter_scan_summary = {
    "snapshot_id": run.config.parameter_snapshot.id,
    "table": TWO_QUBIT_GATE_PARAMETER_TABLE,
    "row": {"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},
    "column": CZ_AMPLITUDE_PARAMETER_COLUMN,
    "accepted_center": _quantity_in_unit(
        accepted_q0_q1[CZ_AMPLITUDE_PARAMETER_COLUMN],
        "arb",
    ),
    "scanned_values": scanned_amplitudes,
}
fit_summary = {
    "selected_amplitude": float(result.fit.selected.amplitude.to("arb").value),
    "conditional_phase": result.fit.selected.conditional_phase,
    "phase_error": result.fit.selected.phase_error,
    "minimum_contrast": result.fit.selected.minimum_contrast,
    "maximum_rmse": result.fit.selected.maximum_rmse,
    "maximum_control_error": result.fit.selected.maximum_control_error,
    "quality_score": result.fit.quality_score,
    "failed_checks": result.fit.failed_checks,
    "proposal_id": result.proposal_id,
    "candidate_amplitude": _quantity_in_unit(
        q0_q1[CZ_AMPLITUDE_PARAMETER_COLUMN], "arb"
    ),
    "candidate_proposal_ids": candidate.proposal_ids,
    "analysis_record_id": saved.record.id,
}
assert math.isclose(result.fit.selected.conditional_phase, math.pi)
assert fit_summary["failed_checks"] == ()
assert physical_summary["candidate_ids"] == (CZ_CANDIDATE_ID,)
print(fit_summary)

# %%
summary = {
    "program": authoring_summary,
    "parameter_scan": parameter_scan_summary,
    "measurement": measurement_summary,
    "physical": physical_summary,
    "fit": fit_summary,
}
print(summary)
