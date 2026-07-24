"""Run and analyze a two-qubit gate calibration with a coupler pulse."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.virtual_lab import (
    CZ_AMPLITUDE_PARAMETER_COLUMN,
    q0_q1_cz_row,
)
from quantum_lab_demo.workflows.cz_phase_analysis import analyze_cz_phase_run
from quantum_lab_demo.workflows.cz_phase_calibration import (
    cz_conditional_phase,
    cz_flux_candidate,
)
from quantum_lab_demo.workflows.cz_phase_experiment import (
    CZ_AMPLITUDE,
    CZ_AMPLITUDE_POINTS,
    CZ_AMPLITUDE_SPAN,
    cz_phase_template,
)

# %%
# One recursive Program composes the logical CZ gate, its accepted coupler-pulse
# implementation, analyzer frame shift, parallel readout, and acquisition.
authoring_summary = {
    "program": cz_conditional_phase.id,
    "inputs": tuple(value.id for value in cz_conditional_phase.inputs),
    "results": tuple(value.id for value in cz_conditional_phase.results),
    "cz_implementation": cz_flux_candidate.id,
}
print(authoring_summary)

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()
cz_parameter_scan = sc.param_axis(
    CZ_AMPLITUDE,
    q0_q1_cz_row(),
    CZ_AMPLITUDE_PARAMETER_COLUMN,
    span=CZ_AMPLITUDE_SPAN,
    points=CZ_AMPLITUDE_POINTS,
)
experiment = lab.prepare(cz_phase_template()).scan(cz_parameter_scan)
preview = experiment.preview()
run = experiment.run(
    name="CZ conditional-phase Ramsey",
    tags=("calibration", "two-qubit", "coupler-pulse"),
)

# %%
# The fit compares the two control-state Ramsey fringes and creates a standard
# candidate config only after phase, contrast, and residual checks pass.
result = analyze_cz_phase_run(run)
saved_analysis = result.analysis.save()
candidate = result.analysis.candidate_config()
candidate_preview = (
    lab.prepare(cz_phase_template(), config=candidate).scan(cz_parameter_scan).preview()
)

# %%
records = tuple(run.data().measurements().dataset.records)
summary = {
    "program": authoring_summary,
    "run_id": run.id,
    "status": run.manifest.status,
    "points": preview.point_count,
    "coordinates": preview.coordinate_ids,
    "records": len(records),
    "observables": tuple(sorted(records[0].observables)),
    "selected_amplitude": result.fit.selected.amplitude,
    "conditional_phase": result.fit.selected.conditional_phase,
    "quality_score": result.fit.quality_score,
    "failed_checks": result.fit.failed_checks,
    "proposal_id": result.proposal_id,
    "analysis_record_id": saved_analysis.record.id,
    "candidate_points": candidate_preview.point_count,
}
print(summary)
