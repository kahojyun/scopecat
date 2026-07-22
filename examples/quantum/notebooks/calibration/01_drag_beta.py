"""Run, review, activate, and roll back a DRAG beta calibration."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.virtual_lab import (
    DRAG_BETA_PARAMETER_COLUMN,
    q0_drag_beta_row,
)
from quantum_lab_demo.workflows.drag_beta_analysis import analyze_drag_beta_run
from quantum_lab_demo.workflows.drag_beta_experiment import (
    BETA,
    DRAG_BETA_POINTS,
    DRAG_BETA_SPAN,
    drag_beta_template,
)
from quantum_lab_demo.workflows.production_drag_gate import production_drag_template

# %%
# The active DRAG beta centers this parameter-table scan. Each point binds the
# same Program input used later by the production X90 gate.
lab = quantum_lab(workspace=notebook_workspace("calibration-drag-beta"))
parameter_scan = sc.param_axis(
    BETA,
    q0_drag_beta_row(),
    DRAG_BETA_PARAMETER_COLUMN,
    span=DRAG_BETA_SPAN,
    points=DRAG_BETA_POINTS,
)
experiment = lab.prepare(drag_beta_template()).scan(parameter_scan)
preview = experiment.preview()
completed_run = experiment.run(
    name="DRAG beta rough calibration",
    tags=("calibration", "gate-pulse"),
)

# %%
# Analysis saves fit evidence and proposes a candidate without changing the
# active configuration. The candidate can be previewed before review.
result = analyze_drag_beta_run(completed_run)
saved_analysis = result.analysis.save()
if result.proposal_id is None:
    msg = "the DRAG fit did not produce an eligible proposal"
    raise RuntimeError(msg)
candidate = result.analysis.candidate_config()
candidate_preview = (
    lab.prepare(drag_beta_template(), config=candidate).scan(parameter_scan).preview()
)

# %%
# Install the source config as this isolated demo workspace's rollback point,
# then review and activate the candidate atomically.
baseline = lab.activate_config(
    completed_run.config,
    entry_id=f"drag-beta-baseline-{completed_run.id}",
)
baseline_production_run = lab.prepare(
    production_drag_template(),
    config="active",
).run(
    name="Production X90 with baseline DRAG beta",
    tags=("calibration", "production-gate", "baseline"),
)
review = lab.review_parameter_proposal(
    completed_run,
    result.proposal_id,
    decision="approved",
    note="fit evidence and scan coverage reviewed",
)
activation = lab.activate(
    candidate,
    entry_id=f"drag-beta-candidate-{completed_run.id}",
    expected_generation=baseline.active_state.generation,
    activation_note="select reviewed q0 DRAG beta",
)
active_production_run = lab.prepare(
    production_drag_template(),
    config="active",
).run(
    name="Production X90 with accepted DRAG beta",
    tags=("calibration", "production-gate", "active-config"),
)

# %%
# Rollback keeps the proposal, review, and activation as durable evidence while
# restoring the previous active entry.
rollback = lab.rollback(
    expected_generation=activation.active_state.generation,
    note="restore baseline after production-gate verification",
)

drag_beta_summary = {
    "status": completed_run.manifest.status,
    "point_count": preview.point_count,
    "beta_hat": result.fit.beta_hat,
    "fit_rmse": result.fit.rmse,
    "quality_score": result.assessment.quality_score,
    "analysis_record_id": saved_analysis.record.id,
    "proposal_id": result.proposal_id,
    "candidate_points": candidate_preview.point_count,
    "review": review.decision,
    "production_runs": (
        baseline_production_run.id,
        active_production_run.id,
    ),
    "active_entry": activation.entry.id,
    "restored_entry": rollback.active_state.active_entry_id,
}
print(drag_beta_summary)
