"""Accept a high-confidence DRAG fit with an automatic policy."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.virtual_lab import (
    q0_drag_beta_lookup,
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
lab = sc.open_project(EXAMPLE_ROOT).connect()
parameter_scan = sc.param_axis(
    BETA,
    q0_drag_beta_lookup(),
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
# Analysis proposes a candidate only after the fit clears its local quality
# checks. No separate verification run is required by the config lifecycle.
result = analyze_drag_beta_run(completed_run)
if result.proposal_id is None:
    msg = "the DRAG fit did not produce an eligible proposal"
    raise RuntimeError(msg)

# %%
policy = sc.AutomaticPolicyDecisionAuthority(
    actor="nightly-calibration",
    policy_id="quantum_lab_demo.drag_beta.fit_quality",
    policy_version="1",
)
accepted = lab.config.accept(
    result.analysis,
    authority=policy,
    note="fit passed the versioned DRAG quality policy",
)

# A later production experiment naturally exercises the accepted parameter,
# but it is downstream evidence rather than a prerequisite for acceptance.
production_run = lab.prepare(production_drag_template()).run(
    name="Production X90 with accepted DRAG beta",
    tags=("calibration", "production-gate", "active-config"),
)

# %%
# Undo restores the previous default while retaining the fit, policy decision,
# immutable revision, production run, and activation history.
restored = lab.config.undo(
    note="restore the previous default after the calibration example",
)
production_source = production_run.manifest.config_source

drag_beta_summary = {
    "status": completed_run.manifest.status,
    "point_count": preview.point_count,
    "beta_hat": result.fit.beta_hat,
    "fit_rmse": result.fit.rmse,
    "quality_score": result.assessment.quality_score,
    "proposal_id": result.proposal_id,
    "acceptance_authority": policy.kind,
    "policy": f"{policy.policy_id}@{policy.policy_version}",
    "production_run": production_run.id,
    "accepted_as_default": (
        production_source is not None
        and production_source.content_hash == accepted.entry.content_hash
    ),
    "default_restored": (
        restored.active_state.active_entry_content_hash
        == accepted.activation.previous_entry_content_hash
    ),
}
print(drag_beta_summary)
